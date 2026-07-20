# Daily Data Refresh + 2025-26 Load — Design

**Date:** 2026-07-20
**Status:** Approved

## Goal

Bring the deployed site's data up to date (load the 2025-26 season) and keep it current automatically: a daily scheduled job refreshes the current season's data during the season. Backfill beyond 2025-26 is explicitly out of scope for now.

## Background

The production database has only 2024-25. The ETL is operator-run (`make etl`), extract caches raw files and skips re-download, and load is idempotent (`ON CONFLICT DO NOTHING`, plus `sp_update_season_metadata`). Extract is lightweight: 4 NBA API calls per season via `LeagueGameLog`/`CommonAllPlayers` — cheap enough to run daily.

Platform decision: **GitHub Actions cron** (free, no infrastructure, failure emails built in). Known risk: stats.nba.com sometimes blocks datacenter IPs; the first manual dispatch run is the empirical test. Fallback if blocked: run the same Make target from local cron; the repo-side work is identical.

## Changes

### 1. `etl/extract.py`: `--force` flag

- `--force` re-downloads all files for the run even when they exist: the season's `league_game_log_*.json` AND the shared `players.json` (so mid-season signings/rookies appear). `teams.json` may also be refreshed under `--force` (harmless; teams are static).
- Default behavior without the flag is unchanged (skip existing).
- Transient-failure resilience: the scheduled workflow retries the extract step (workflow-level retry, not Python-level).

### 2. `scripts/current_season.py`

- Prints the current NBA season string (e.g. `2026-27`) to stdout.
- Rule: months October–December → `YYYY-(YY+1)`; January–September → `(YYYY-1)-YY`.
- Off-season behavior: the job refreshes the most recent completed season — an idempotent no-op. No special-casing.
- Unit-tested (pure date math; function takes a `date` argument for testability).

### 3. `Makefile`: `refresh` target

- `make refresh SEASON=X`: `extract --force` → `transform` → `load` for one season.
- Documented in `make help`.

### 4. `.github/workflows/refresh-data.yml`

- Triggers: `schedule` daily at 10:00 UTC (~6am ET, after West Coast games), and `workflow_dispatch` with optional `season` input (defaults to computed current season).
- Steps: checkout → setup uv/python → `uv sync` → determine season (input or `scripts/current_season.py`) → extract with `--force` and up to 2 retries (e.g. `nick-fields/retry` or a shell retry loop) → transform → load.
- `DATABASE_URL` comes from a GitHub Actions repo secret pointing at the Railway Postgres **public** TCP-proxy address (the app's internal `postgres.railway.internal` URL is unreachable from runners).
- Failure behavior: a failed extract stops the job before load — the DB stays at the previous day's state, never partial. GitHub's default workflow-failure email is the alert channel.

### 5. Operator steps (with the user)

1. Fetch the Railway Postgres public connection string (TCP proxy) and set it: `gh secret set DATABASE_URL`.
2. Trigger `workflow_dispatch` with `season=2025-26` — this loads the missing season into production AND tests whether GitHub runners can reach the NBA API.
3. If the runner is blocked by the NBA API: run `make etl SEASON=2025-26` locally, then `DATABASE_URL=<public-url> make load SEASON=2025-26`; move the daily job to local cron (same Make target) and note it in the README.
4. Update README: data-freshness section (daily refresh, how to trigger manually).

## Error handling

- Extract failures (network, IP block): job fails before any DB write; retried next day or manually.
- Load failures mid-run: per-table commits with idempotent inserts — a re-run completes the remainder; no duplicate rows possible.
- Season rollover: handled by date math; no annual maintenance.

## Testing

- Unit tests for `current_season(date)` covering both month ranges and year boundaries (added to the existing pytest suite; no DB needed).
- Extract `--force` behavior verified by a focused test or manual verification (file mtimes change) — no NBA API mocking in the suite.
- The workflow is validated by the manual dispatch run (operator step 2).
- `make check` and the full suite stay green.

## Success criteria

- 2025-26 season visible on the live site (standings, leaders, games).
- Scheduled workflow exists, runs green (or the local-cron fallback is documented and installed).
- No annual maintenance required for season rollover.
