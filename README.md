# Free-Games Discord Bot

Posts new free PC games to a Discord channel by polling the [LootScraper](https://github.com/eikowagenknecht/lootscraper) Atom feed every 30 minutes via GitHub Actions. Dedupes via Supabase so the same game is never announced twice.

## What it watches

`https://feed.eikowagenknecht.com/lootscraper.xml` — covers Epic Games Store, Steam, GOG, Amazon Prime Gaming, Humble, and itch.io. Loot/cosmetic items are filtered out; only full free games are posted.

## One-time setup

### 1. Discord webhook

In your Discord channel: Edit channel → Integrations → Webhooks → New Webhook → Copy URL. This is `DISCORD_WEBHOOK_URL`.

### 2. Supabase project

1. Create a project at [supabase.com](https://supabase.com) (free tier).
2. In the SQL editor, paste and run the contents of [`supabase/schema.sql`](supabase/schema.sql).
3. Project Settings → API: copy the **Project URL** and the **service_role** key. These are `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`. The service key bypasses RLS — keep it private.

### 3. GitHub repo secrets

Repo → Settings → Secrets and variables → Actions → New repository secret. Add:

- `DISCORD_WEBHOOK_URL`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`

### 4. Bootstrap

To avoid an avalanche of historical posts on the first run, do an initial bootstrap:

1. Actions tab → **Poll** workflow → **Run workflow**
2. Set `bootstrap` to `1`, leave `dry_run` empty.
3. Run. The bot will seed `seen_posts` with every current `(Game)` entry without posting.

After bootstrap completes, the cron (`*/30 * * * *`) takes over automatically. New entries on the feed will be announced within ~30 minutes.

## Local development

```bash
# One-time: install uv (https://docs.astral.sh/uv/)
# macOS / Linux:
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync the venv (creates .venv and installs deps from uv.lock)
uv sync

# Run tests
uv run pytest

# Lint
uv run ruff check . && uv run ruff format --check .

# Smoke-test against the live feed without posting or writing to Supabase
DRY_RUN=1 \
DISCORD_WEBHOOK_URL=unused \
SUPABASE_URL=unused \
SUPABASE_SERVICE_KEY=unused \
uv run python bot.py
```

Note: `DRY_RUN=1` short-circuits before any Supabase or Discord call, so the secrets above can be placeholder strings.

## Operational notes

- **Audit log:** every run inserts a row in `bot_runs` with counts and any errors. Query in the Supabase SQL editor:
  ```sql
  select * from bot_runs order by ran_at desc limit 50;
  ```
- **Keep-alive:** Supabase pauses free-tier projects after ~7 days of zero activity. The `bot_runs` insert every 30 min keeps the project warm.
- **Failure modes:** see the design spec (kept locally in `docs/superpowers/specs/`).
- **Duplicate posts (at-least-once delivery):** If Supabase is unreachable *after* a Discord post succeeds, the entry is not marked seen and will be re-posted on the next run. This is by design — we'd rather risk a rare duplicate than silently drop an announcement. The `bot_runs.errors` column records this as `"... mark_seen <id> after post: ..."`. If you see unexpected duplicates, query:
  ```sql
  select ran_at, errors from bot_runs where errors like '%mark_seen%' order by ran_at desc;
  ```

- **Throttling / staged rollout (`MAX_POSTS`):** Set the optional `MAX_POSTS` env var (or repo variable) to a positive integer to cap how many posts the bot publishes per run. Only the oldest N unseen entries are posted and marked seen; the rest stay unseen and surface on the next scheduled run. Useful for: smoke-testing a new channel one game at a time, draining a large backlog gradually, or applying a soft rate limit on busy weeks. Manual workflow_dispatch runs also accept a `max_posts` input that overrides the repo variable for that one run. Default `0` = no cap.

## Excluding stores

Set the `EXCLUDE_STORES` env var (or repo variable) to a comma-separated list, case-insensitive:

```
EXCLUDE_STORES=Amazon Prime,itch.io
```

Items from those stores will be ignored.
