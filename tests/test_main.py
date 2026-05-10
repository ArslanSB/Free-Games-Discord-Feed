from dataclasses import dataclass, field

import httpx
import respx

from bot import Entry, RunStats, run_once

WEBHOOK = "https://discord.com/api/webhooks/test/abc"
FEED_URL = "https://feed.example.com/test.xml"

SAMPLE_FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>x</id><title>t</title><updated>2026-05-10T00:00:00Z</updated>
  <entry>
    <id>id-1</id>
    <title>Epic Games (Game) - Game One</title>
    <updated>2026-05-10T10:00:00Z</updated>
    <published>2026-05-10T10:00:00Z</published>
    <link href="https://example.com/1"/>
    <content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml"><p>desc one</p></div></content>
  </entry>
  <entry>
    <id>id-2</id>
    <title>Steam (Game) - Game Two</title>
    <updated>2026-05-09T10:00:00Z</updated>
    <published>2026-05-09T10:00:00Z</published>
    <link href="https://example.com/2"/>
    <content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml"><p>desc two</p></div></content>
  </entry>
  <entry>
    <id>id-3</id>
    <title>Amazon Prime (Loot) - Skin</title>
    <updated>2026-05-08T10:00:00Z</updated>
    <published>2026-05-08T10:00:00Z</published>
    <link href="https://example.com/3"/>
    <content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml"><p>desc three</p></div></content>
  </entry>
</feed>"""


@dataclass
class FakeDB:
    seen_ids: set[str] = field(default_factory=set)
    marked: list[Entry] = field(default_factory=list)
    runs: list[RunStats] = field(default_factory=list)
    find_unseen_calls: int = 0

    def find_unseen(self, ids: list[str]) -> list[str]:
        self.find_unseen_calls += 1
        return [i for i in ids if i not in self.seen_ids]

    def mark_seen(self, entry: Entry) -> None:
        self.seen_ids.add(entry.id)
        self.marked.append(entry)

    def record_run(self, stats: RunStats) -> None:
        self.runs.append(stats)


@respx.mock
def test_posts_new_games_only_skipping_loot_and_seen():
    respx.get(FEED_URL).mock(return_value=httpx.Response(200, text=SAMPLE_FEED))
    discord_route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))
    db = FakeDB(seen_ids={"id-2"})  # Game Two already seen
    with httpx.Client() as client:
        rc = run_once(
            client=client,
            feed_url=FEED_URL,
            webhook_url=WEBHOOK,
            db=db,
            exclude_stores=[],
            dry_run=False,
            bootstrap=False,
        )
    assert rc == 0
    # Only id-1 (Game One) should be posted: id-2 is seen, id-3 is loot.
    assert discord_route.call_count == 1
    assert [e.id for e in db.marked] == ["id-1"]
    assert len(db.runs) == 1
    # items_seen counts post-filter Game entries (id-1, id-2) — Loot dropped.
    assert db.runs[0].items_seen == 2  # noqa: PLR2004
    assert db.runs[0].items_new == 1
    assert db.runs[0].items_posted == 1


@respx.mock
def test_dry_run_does_not_post_or_mark():
    respx.get(FEED_URL).mock(return_value=httpx.Response(200, text=SAMPLE_FEED))
    discord_route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))
    db = FakeDB()
    with httpx.Client() as client:
        rc = run_once(
            client=client,
            feed_url=FEED_URL,
            webhook_url=WEBHOOK,
            db=db,
            exclude_stores=[],
            dry_run=True,
            bootstrap=False,
        )
    assert rc == 0
    assert discord_route.call_count == 0
    assert db.marked == []
    assert db.runs == []  # dry-run also skips bot_runs write
    # In dry-run mode, run_once must not touch the DB at all.
    assert db.find_unseen_calls == 0


@respx.mock
def test_bootstrap_marks_all_without_posting():
    respx.get(FEED_URL).mock(return_value=httpx.Response(200, text=SAMPLE_FEED))
    discord_route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))
    db = FakeDB()
    with httpx.Client() as client:
        rc = run_once(
            client=client,
            feed_url=FEED_URL,
            webhook_url=WEBHOOK,
            db=db,
            exclude_stores=[],
            dry_run=False,
            bootstrap=True,
        )
    assert rc == 0
    assert discord_route.call_count == 0
    # Both Game entries marked seen, Loot ignored.
    assert sorted(e.id for e in db.marked) == ["id-1", "id-2"]
    assert len(db.runs) == 1
    assert db.runs[0].errors == "bootstrap"


@respx.mock
def test_feed_fetch_failure_returns_nonzero_and_records_error():
    respx.get(FEED_URL).mock(return_value=httpx.Response(503))
    db = FakeDB()
    with httpx.Client() as client:
        rc = run_once(
            client=client,
            feed_url=FEED_URL,
            webhook_url=WEBHOOK,
            db=db,
            exclude_stores=[],
            dry_run=False,
            bootstrap=False,
        )
    assert rc == 1
    # bot_runs row written with error, since DB itself is reachable.
    assert len(db.runs) == 1
    assert db.runs[0].errors and "feed" in db.runs[0].errors.lower()


@respx.mock
def test_max_posts_caps_normal_mode_and_leaves_rest_unseen():
    """With MAX_POSTS=1 and 2 unseen games, only the oldest is posted and marked."""
    respx.get(FEED_URL).mock(return_value=httpx.Response(200, text=SAMPLE_FEED))
    discord_route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))
    db = FakeDB()
    with httpx.Client() as client:
        rc = run_once(
            client=client,
            feed_url=FEED_URL,
            webhook_url=WEBHOOK,
            db=db,
            exclude_stores=[],
            dry_run=False,
            bootstrap=False,
            max_posts=1,
        )
    assert rc == 0
    # Only the oldest unseen game (id-2 published 2026-05-09) is posted.
    assert discord_route.call_count == 1
    assert [e.id for e in db.marked] == ["id-2"]
    # items_new reflects FULL backlog (2), not the capped slice.
    assert db.runs[0].items_new == 2  # noqa: PLR2004
    assert db.runs[0].items_posted == 1


@respx.mock
def test_max_posts_zero_means_unlimited():
    respx.get(FEED_URL).mock(return_value=httpx.Response(200, text=SAMPLE_FEED))
    discord_route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))
    db = FakeDB()
    with httpx.Client() as client:
        rc = run_once(
            client=client,
            feed_url=FEED_URL,
            webhook_url=WEBHOOK,
            db=db,
            exclude_stores=[],
            dry_run=False,
            bootstrap=False,
            max_posts=0,
        )
    assert rc == 0
    assert discord_route.call_count == 2  # noqa: PLR2004 - both games posted
    assert sorted(e.id for e in db.marked) == ["id-1", "id-2"]


@respx.mock
def test_max_posts_caps_bootstrap_mode():
    """Bootstrap with MAX_POSTS=1 marks only the oldest game as seen, leaves the other for next run."""
    respx.get(FEED_URL).mock(return_value=httpx.Response(200, text=SAMPLE_FEED))
    db = FakeDB()
    with httpx.Client() as client:
        rc = run_once(
            client=client,
            feed_url=FEED_URL,
            webhook_url=WEBHOOK,
            db=db,
            exclude_stores=[],
            dry_run=False,
            bootstrap=True,
            max_posts=1,
        )
    assert rc == 0
    assert [e.id for e in db.marked] == ["id-2"]  # oldest only
    assert db.runs[0].items_new == 2  # noqa: PLR2004


@respx.mock
def test_discord_failure_does_not_mark_seen_but_continues():
    respx.get(FEED_URL).mock(return_value=httpx.Response(200, text=SAMPLE_FEED))
    # First post fails (non-429), second succeeds.
    respx.post(WEBHOOK).mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(204),
        ]
    )
    db = FakeDB()
    with httpx.Client() as client:
        rc = run_once(
            client=client,
            feed_url=FEED_URL,
            webhook_url=WEBHOOK,
            db=db,
            exclude_stores=[],
            dry_run=False,
            bootstrap=False,
        )
    # Run still returns 0 (per-item failures are not fatal); errors field is set.
    assert rc == 0
    # Entries are processed oldest-first by published_at.
    # id-2 (2026-05-09) is processed first → 500 fail (not marked).
    # id-1 (2026-05-10) is processed second → 204 success (marked).
    assert [e.id for e in db.marked] == ["id-1"]
    assert db.runs[0].items_posted == 1
    assert db.runs[0].errors and "id-2" in db.runs[0].errors
