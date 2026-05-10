"""Free-games Discord bot — see docs/superpowers/specs/ for design."""

import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Protocol

import httpx

TITLE_RE = re.compile(r"^(?P<store>.+?) \((?P<kind>Game|Loot)\) - (?P<game_name>.+)$")


def parse_title(title: str) -> tuple[str, str, str] | None:
    """Parse a LootScraper entry title into (store, kind, game_name).

    Returns None if the title doesn't match the expected pattern.
    """
    match = TITLE_RE.match(title)
    if not match:
        return None
    return match.group("store"), match.group("kind"), match.group("game_name")


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    store: str
    kind: str
    game_name: str
    link: str
    image_url: str | None
    description: str
    published_at: datetime


class _ContentExtractor(HTMLParser):
    """Extract first <img src> and visible text from an Atom <content> XHTML body."""

    def __init__(self) -> None:
        super().__init__()
        self.image_url: str | None = None
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "img" and self.image_url is None:
            for k, v in attrs:
                if k == "src" and v:
                    self.image_url = v
                    return

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    @property
    def text(self) -> str:
        return " ".join(c.strip() for c in self._chunks if c.strip())


def _extract_content(xhtml: str) -> tuple[str | None, str]:
    parser = _ContentExtractor()
    parser.feed(xhtml)
    return parser.image_url, parser.text


def parse_entries(xml: str) -> list[Entry]:
    """Parse an Atom feed string into normalized Entry objects.

    Entries with malformed titles are silently skipped.
    """
    import feedparser  # local import keeps top-level fast

    feed = feedparser.parse(xml)
    out: list[Entry] = []
    for raw in feed.entries:
        parsed = parse_title(raw.get("title", ""))
        if parsed is None:
            continue
        store, kind, game_name = parsed

        content_html = ""
        if raw.get("content"):
            content_html = raw["content"][0].get("value", "")
        image_url, description = _extract_content(content_html)

        published_struct = raw.get("published_parsed") or raw.get("updated_parsed")
        if published_struct is None:
            published_at = datetime.now(tz=UTC)
        else:
            published_at = datetime(*published_struct[:6], tzinfo=UTC)

        out.append(
            Entry(
                id=raw.get("id", ""),
                title=raw.get("title", ""),
                store=store,
                kind=kind,
                game_name=game_name,
                link=raw.get("link", ""),
                image_url=image_url,
                description=description,
                published_at=published_at,
            )
        )
    return out


def filter_games(entries: list[Entry], exclude_stores: list[str] | None = None) -> list[Entry]:
    """Keep only Game entries, dropping Loot.

    Optionally exclude listed stores (case-insensitive).
    """
    excluded = {s.lower() for s in (exclude_stores or [])}
    return [e for e in entries if e.kind == "Game" and e.store.lower() not in excluded]


EMBED_COLOR_GREEN = 0x00B94C  # decimal 47436
DESCRIPTION_LIMIT = 300


def build_embed_payload(entry: Entry) -> dict:
    """Build the JSON body for a Discord webhook POST."""
    description = entry.description
    if len(description) > DESCRIPTION_LIMIT:
        description = description[: DESCRIPTION_LIMIT - 1].rstrip() + "…"

    embed: dict = {
        "title": entry.game_name,
        "url": entry.link,
        "footer": {"text": f"{entry.store} · Free for a limited time"},
        "color": EMBED_COLOR_GREEN,
        "timestamp": entry.published_at.isoformat(),
    }
    if description:
        embed["description"] = description
    if entry.image_url:
        embed["image"] = {"url": entry.image_url}

    return {"username": "Free Games", "embeds": [embed]}


log = logging.getLogger("bot")


def post_to_discord(client: httpx.Client, webhook_url: str, payload: dict) -> bool:
    """POST the embed payload. Returns True on 2xx, False otherwise.

    Retries once on 429 after sleeping Retry-After seconds.
    """
    for attempt in (1, 2):
        resp = client.post(webhook_url, json=payload, timeout=10.0)
        if resp.is_success:
            return True
        if resp.status_code == 429 and attempt == 1:  # noqa: PLR2004
            retry_after = resp.headers.get("Retry-After", "1")
            try:
                wait = float(retry_after)
            except ValueError:
                log.warning(
                    "Discord 429 with non-numeric Retry-After=%r; defaulting to 1s",
                    retry_after,
                )
                wait = 1.0
            log.warning("Discord 429; sleeping %.1fs before retry", wait)
            time.sleep(wait)
            continue
        log.error("Discord POST failed: %d %s", resp.status_code, resp.text[:200])
        return False
    return False


@dataclass
class RunStats:
    items_seen: int = 0
    items_new: int = 0
    items_posted: int = 0
    errors: str | None = None


class Database(Protocol):
    def find_unseen(self, ids: list[str]) -> list[str]:
        """Return the subset of `ids` that are NOT yet in seen_posts."""

    def mark_seen(self, entry: Entry) -> None:
        """Insert entry into seen_posts."""

    def record_run(self, stats: RunStats) -> None:
        """Insert one row into bot_runs (keep-alive heartbeat + audit)."""


class SupabaseDB:
    """Thin adapter over supabase-py for our two tables."""

    def __init__(self, url: str, service_key: str) -> None:
        from supabase import create_client

        self._client = create_client(url, service_key)

    def find_unseen(self, ids: list[str]) -> list[str]:
        if not ids:
            return []
        resp = self._client.table("seen_posts").select("id").in_("id", ids).execute()
        seen = {row["id"] for row in resp.data}
        return [i for i in ids if i not in seen]

    def mark_seen(self, entry: Entry) -> None:
        self._client.table("seen_posts").insert(
            {
                "id": entry.id,
                "title": entry.title,
                "store": entry.store,
                "link": entry.link,
            }
        ).execute()

    def record_run(self, stats: RunStats) -> None:
        self._client.table("bot_runs").insert(
            {
                "items_seen": stats.items_seen,
                "items_new": stats.items_new,
                "items_posted": stats.items_posted,
                "errors": stats.errors,
            }
        ).execute()


class _NullDB:
    """No-op database used in dry-run mode; never actually called by run_once."""

    def find_unseen(self, ids: list[str]) -> list[str]:
        return []

    def mark_seen(self, entry: Entry) -> None:
        pass

    def record_run(self, stats: RunStats) -> None:
        pass


POST_PACING_SECONDS = 1  # rate-limit pacing between Discord posts


def _fetch_feed(client: httpx.Client, url: str) -> str:
    resp = client.get(url, timeout=10.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def run_once(
    *,
    client: httpx.Client,
    feed_url: str,
    webhook_url: str,
    db: Database,
    exclude_stores: list[str],
    dry_run: bool,
    bootstrap: bool,
    max_posts: int = 0,
) -> int:
    """Single end-to-end run. Returns process exit code (0 on success)."""
    stats = RunStats()
    error_parts: list[str] = []

    # 1. Fetch feed.
    try:
        xml = _fetch_feed(client, feed_url)
    except Exception as exc:  # network or 5xx
        log.exception("Feed fetch failed")
        stats.errors = f"feed fetch failed: {exc}"
        if not dry_run:
            try:
                db.record_run(stats)
            except Exception:
                log.exception("Could not record run after feed failure")
        return 1

    # 2. Parse + filter.
    entries = parse_entries(xml)
    games = filter_games(entries, exclude_stores=exclude_stores)
    stats.items_seen = len(games)

    # 3. Dry run: log all filtered games and exit without touching any external service.
    if dry_run:
        games_oldest_first = sorted(games, key=lambda e: e.published_at)
        items_new_total_dry = len(games_oldest_first)
        if max_posts > 0:
            games_oldest_first = games_oldest_first[:max_posts]
        stats.items_new = items_new_total_dry
        for e in games_oldest_first:
            log.info("[DRY RUN] would post: %s — %s", e.store, e.game_name)
        return 0

    # 4. Dedup.
    candidate_ids = [e.id for e in games]
    try:
        unseen_ids = set(db.find_unseen(candidate_ids))
    except Exception as exc:
        log.exception("DB unreachable during dedup query")
        stats.errors = f"db unreachable: {exc}"
        # Cannot record_run either if DB is down; return 1 silently.
        return 1
    new_entries = [e for e in games if e.id in unseen_ids]
    # Process oldest first so chronological order is preserved in the channel.
    new_entries.sort(key=lambda e: e.published_at)
    items_new_total = len(new_entries)
    if max_posts > 0:
        new_entries = new_entries[:max_posts]
    stats.items_new = items_new_total

    # 5. Bootstrap: mark all without posting.
    if bootstrap:
        for e in new_entries:
            try:
                db.mark_seen(e)
            except Exception as exc:
                log.exception("Bootstrap mark_seen failed for %s", e.id)
                error_parts.append(f"bootstrap mark {e.id}: {exc}")
        stats.items_posted = 0
        stats.errors = "bootstrap" if not error_parts else "bootstrap; " + "; ".join(error_parts)
        try:
            db.record_run(stats)
        except Exception:
            log.exception("record_run failed after bootstrap")
        return 0

    # 6. Normal mode: post each new entry, mark seen on success.
    failures = 0
    for e in new_entries:
        try:
            ok = post_to_discord(client, webhook_url, build_embed_payload(e))
        except Exception as exc:
            log.exception("Discord post raised for %s", e.id)
            failures += 1
            error_parts.append(f"post {e.id}: {exc}")
            continue
        if not ok:
            failures += 1
            error_parts.append(f"post {e.id} returned non-2xx")
            continue
        try:
            db.mark_seen(e)
            stats.items_posted += 1
        except Exception as exc:
            log.exception("mark_seen failed for %s after successful post", e.id)
            failures += 1  # ← add this
            error_parts.append(f"mark_seen {e.id} after post: {exc}")
        time.sleep(POST_PACING_SECONDS)

    if error_parts:
        stats.errors = f"{failures} failure(s): " + "; ".join(error_parts)

    # 7. Heartbeat / audit row.
    try:
        db.record_run(stats)
    except Exception:
        log.exception("record_run final write failed")

    return 0


def main() -> int:
    import os

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    feed_url = os.environ.get("FEED_URL", "https://feed.eikowagenknecht.com/lootscraper.xml")
    exclude_stores_raw = os.environ.get("EXCLUDE_STORES", "")
    exclude_stores = [s.strip() for s in exclude_stores_raw.split(",") if s.strip()]
    dry_run = os.environ.get("DRY_RUN") == "1"
    bootstrap = os.environ.get("BOOTSTRAP") == "1"
    max_posts_raw = os.environ.get("MAX_POSTS", "")
    try:
        max_posts = int(max_posts_raw) if max_posts_raw else 0
    except ValueError:
        log.warning("MAX_POSTS=%r is not an integer; treating as 0 (unlimited)", max_posts_raw)
        max_posts = 0
    max_posts = max(max_posts, 0)

    db: Database
    if dry_run:
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
        db = _NullDB()  # type: ignore[assignment]
    else:
        webhook_url = os.environ["DISCORD_WEBHOOK_URL"]
        supabase_url = os.environ["SUPABASE_URL"]
        supabase_key = os.environ["SUPABASE_SERVICE_KEY"]
        db = SupabaseDB(supabase_url, supabase_key)

    with httpx.Client() as client:
        return run_once(
            client=client,
            feed_url=feed_url,
            webhook_url=webhook_url,
            db=db,
            exclude_stores=exclude_stores,
            dry_run=dry_run,
            bootstrap=bootstrap,
            max_posts=max_posts,
        )


if __name__ == "__main__":
    raise SystemExit(main())
