# Public Read-Only Cleanup — Design

**Date:** 2026-07-15
**Status:** Approved

## Goal

Turn the deployed Railway site into a proper public, read-only NBA stats explorer. Remove the class-project admin features (data entry, ETL trigger, SQL query demo) from the public surface, fix Postgres-migration regressions, add defense-in-depth via a read-only DB role, add an API test suite, and rewrite the README to match reality.

## Background

The project began as a database course project (rubric PDF is in the repo). The web UI and API expose unauthenticated write/admin capabilities that are inappropriate for a public deployment:

- `POST /api/query` — arbitrary SQL with a bypassable keyword blocklist (e.g. `pg_sleep`, `SELECT ... INTO`), no row limit or statement timeout, running as the full-privilege DB user.
- `POST /api/etl` — unauthenticated trigger for 10-minute synchronous subprocess runs that scrape the NBA API.
- `POST /api/players`, `POST /api/games`, `POST /api/player-game-stats` — unauthenticated inserts.
- UI "Data Entry" tabs and "SQL Query Demo" section backed by the above.

Decision (approved): **remove these entirely** rather than gate them behind auth. Data loading remains an operator task: `make etl` locally, or `DATABASE_URL=<railway-url> make etl` against production. Scheduled refresh stays a roadmap item.

## Changes

### 1. Remove the admin surface

`app/main.py`:
- Delete endpoints: `POST /api/players`, `POST /api/games`, `POST /api/player-game-stats`, `POST /api/etl`, `POST /api/query`.
- Delete helpers and models used only by them: `run_etl_step`, `ETLRequest`, `ETLSeasonResult`, `ETLResponse`, `QueryRequest`, `QueryResponse`, and the `subprocess` / `sys` imports.

`app/models.py`:
- Delete `PlayerCreate`, `GameCreate`, `PlayerGameStatsCreate`.

`app/templates/index.html`:
- Delete the Data Entry section (Add Player / Add Game / Add Player Stats / Load Season tabs) and the SQL Query Demo section, including their CSS and JS (forms, tab switching, query runner, example-query buttons).
- Remove any nav links pointing at the deleted sections.

Out of scope (deliberately kept): audit-log triggers, views, stored procedures — harmless, and ETL/loading may rely on triggers.

### 2. Bug fixes + dead files

- `LIKE` → `ILIKE` in the player search condition in `app/main.py` (Postgres `LIKE` is case-sensitive; SQLite's wasn't — `?search=lebron` currently misses "LeBron").
- Delete empty `app/routes.py`.
- Delete `db-project-rubric.pdf`.

### 3. Read-only DB role

- `scripts/init_db.py`: after schema init, if env var `READONLY_DB_PASSWORD` is set, idempotently ensure role `nba_readonly` exists (LOGIN, that password) with `USAGE` on schema `public` and `SELECT` on all tables and views (plus `ALTER DEFAULT PRIVILEGES` so future tables are covered). Runs on every deploy; must be safe to re-run.
- `app/db.py` / `db/config.py`: when `READONLY_DB_PASSWORD` is set, the FastAPI connection pool connects as `nba_readonly` (same host/port/dbname); otherwise behavior is unchanged (local dev needs nothing new).
- ETL and `init_db.py` continue to use the owner credentials (`DATABASE_URL` / `DB_*`).
- `.env.example`: document `READONLY_DB_PASSWORD` as optional.
- Operator action: set `READONLY_DB_PASSWORD` on the Railway service.

### 4. API test suite

- New `tests/test_api.py` using FastAPI `TestClient` against a real Postgres.
- Seed fixture: minimal dataset (2 teams, a few players, 1–2 games with player/team game stats) inserted by the test setup.
- Coverage: health check; list/get for teams, players (including case-insensitive search), games; boxscore; leaders; standings; 404 cases; and a guard test asserting the removed write endpoints return 404/405.
- CI (`.github/workflows/ci.yml`): add a `postgres:16` service container; job runs `init_db.py`, then `pytest`.
- `Makefile`: `make test` runs the full pytest suite (existing data-quality tests remain; they require a loaded DB and may be marked/skipped when tables are empty).

### 5. README rewrite

- Reframe as a deployed read-only NBA stats explorer (include the live Railway URL).
- Endpoint table: GET endpoints only.
- Data loading documented as an operator task (local ETL, or pointed at production via `DATABASE_URL`).
- Keep local development setup (Docker Postgres, uv, Makefile).
- Drop documentation of removed features; trim rubric-oriented sales pitch where it no longer matches.

## Error handling

No changes to read-path error handling — existing 404/503 behavior stays. `init_db.py` role setup failures should fail loudly at deploy (same as schema failures).

## Testing

- `make check` (ruff + mypy) passes.
- New API tests pass locally against Docker Postgres and in CI against the service container.
- Manual verification: UI loads with only read-only sections; removed endpoints 404/405; player search is case-insensitive; app works connected as `nba_readonly`.

## Success criteria

- No unauthenticated write or SQL-execution capability remains in the deployed app.
- App serves all read traffic via a SELECT-only role when `READONLY_DB_PASSWORD` is set.
- CI runs lint, typecheck, and API tests.
- README describes the app as deployed.
