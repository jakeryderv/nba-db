# NBA Stats Explorer

A read-only web app and REST API for exploring NBA statistics — standings, stat leaders, box scores, and player search — backed by PostgreSQL and an ETL pipeline over the official NBA API.

**Live:** https://nba.jvs.sh · **API docs:** https://nba.jvs.sh/docs

## How it works

- **ETL pipeline** (`etl/`) downloads season box scores and league-wide shot locations from the NBA API, transforms them to CSVs, and loads them into PostgreSQL. Loading is an operator task — the public app has no write capability.
- **FastAPI app** (`app/`) serves a single-page dashboard and a read-only JSON API. In production it connects with a SELECT-only database role (`nba_readonly`).
- **Schema** (`db/schema/`) is managed as numbered, checksum-tracked migrations by `scripts/init_db.py` (Railway `startCommand`), with CHECK constraints, indexes, and views.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Database | PostgreSQL 16 locally; PostgreSQL 18 in Dagger, staging, and production |
| Language | Python 3.11 |
| Web framework | FastAPI + psycopg 3 |
| Package manager | uv |
| Data source | [nba_api](https://github.com/swar/nba_api) |
| Automation | Dagger (local and CI), pre-commit, GitHub Actions |

## API

All endpoints are read-only. **[Interactive documentation](https://nba.jvs.sh/docs)** is generated
from the running application, so it is the authoritative endpoint reference and cannot drift from
the code.

```bash
curl "https://nba.jvs.sh/api/players?search=lebron"
curl "https://nba.jvs.sh/api/leaders/points?season=2025-26"
```

Shot-chart filters are shareable in the dashboard URL and can be opened directly from player,
team, and game details. Filters include opponent, game, date range, home/away venue, period,
result, shot type, and action type. Zone results include shot frequency, points per shot, and the
field-goal percentage difference from the league under the same context. League comparisons are
omitted when filtering to makes or misses because that filter makes an efficiency baseline
meaningless. Complete filtered attempts can be downloaded as CSV; browser plotting is capped while
all aggregates remain complete.

The shot profile normalizes official shot zones into rim, paint, midrange, corner-three, and
above-the-break-three areas. It reports frequency, FG%, eFG%, and points per shot, highlights the
highest and lowest-efficiency areas with a minimum-sample guard, and keeps every split within the
loaded season. The 2025-26 phase boundary uses the first day after the official February 13-15,
2026 All-Star weekend.

## Local development

Prerequisites: Docker, Python 3.11+, [uv](https://github.com/astral-sh/uv), and [Dagger](https://docs.dagger.io/getting-started/installation/) 0.21.7.

```bash
make install       # uv sync
make hooks-install # selective pre-commit and pre-push hooks
cp .env.example .env
make db-start      # PostgreSQL in Docker
make season-build      # defaults to the verified product season, 2025-26
make season-load-local
make api           # http://localhost:8000
```

The verified product default is centralized as `2025-26`. Read-only API filters, standalone
extract/transform commands, and Make targets use that default. A different season can still be
selected explicitly with `SEASON=YYYY-YY`. Database loads always replace the target with exactly one
manifested Regular Season dataset; production still requires its typed season and deletion
confirmations. Run `make help` for the complete target list.

For a disposable environment with an empty schema, run `dagger up dev`. Dagger starts both PostgreSQL and the API, and exposes the API on port 8000 without using the host database.

## Local-first automation

Dagger defines the authoritative portable checks and isolated services. The same pipeline runs locally and in GitHub Actions:

```bash
dagger check                 # all functions marked as Dagger checks
dagger call full --source=.  # the explicit complete merge gate
make dagger-check            # convenience alias for the complete gate
```

The local hooks are intentionally tiered:

- Pre-commit runs generic file hygiene, Ruff on staged Python files, and Markdown checks only when those file types are staged.
- Pre-push compares committed changes with `origin/main`. Documentation-only, frontend-only, and ETL/lifecycle-only changes get focused Dagger checks; mixed, unknown, backend, schema, dependency, Dagger, and CI changes get the full pipeline.
- GitHub pull requests use the same conservative classifier inside one stable required job. Pushes to `main`, nightly runs, and manual runs always execute the full pipeline. Nightly/manual runs also audit dependencies.

Hooks are fast developer feedback and can be bypassed with `--no-verify`; GitHub Actions remains the trusted merge gate. If a pre-push comparison cannot be calculated, it fails safe to the full pipeline. Install both hooks with `make hooks-install`, run lightweight hooks manually with `make hooks-run`, or invoke the affected pre-push gate with `make pre-push`.

## Operating the data

Loading a season replaces the entire contents of a database, so every command that touches staging
or production is operator-only and requires typed confirmations. The full runbook — building and
verifying a season, replacing the local database, promoting with a backup, and restoring from one —
is in **[docs/operations/season-lifecycle.md](docs/operations/season-lifecycle.md)**.

## Testing

```bash
make test        # API test suite (pytest; needs make db-start, uses a separate nba_db_test database)
make test-data   # data quality checks against loaded data
make check       # native formatting + ruff + docs + mypy
make dagger-check # full portable merge gate, including PostgreSQL/browser tests
```

`make test` also runs the primary dashboard journeys in a headless Chromium browser. Install the browser once on a new workstation with `uv run playwright install chromium`; the test suite falls back to a locally installed Chrome when available.

## Configuration

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Application/development connection string (takes precedence; used on Railway) |
| `PRODUCTION_DATABASE_URL` | Promotion and scheduled-backup connection string; keep only in operator shells or the encrypted GitHub Actions secret |
| `STAGING_DATABASE_URL` | Staging-only connection string for the guarded staging load |
| `STAGING_API_URL` | Staging's public HTTPS URL. Required for promotion: production refuses a dataset staging is not already serving |
| `RECOVERY_DATABASE_URL` | Drill-only connection string whose database name ends in `_recovery` |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | Individual settings for local development |
| `READONLY_DB_PASSWORD` | Optional. When set, `init_db.py` provisions a SELECT-only `nba_readonly` role and the web app connects as it |
| `RATE_LIMIT_ENABLED` | Enable public rate limiting (default `true`). Limiting covers the whole surface except `/health` and `/static/` |
| `RATE_LIMIT_REQUESTS` | Per-client ordinary requests per window (default `600`) |
| `RATE_LIMIT_EXPENSIVE_REQUESTS` | Per-client shot analytics/export requests per window (default `120`) |
| `RATE_LIMIT_READY_REQUESTS` | Per-client `/ready` requests per window (default `600`), budgeted separately so public traffic cannot throttle the platform healthcheck |
| `RATE_LIMIT_WINDOW_SECONDS` | Sliding rate-limit window (default `60`) |
| `RATE_LIMIT_MAX_CLIENTS` | Cap on tracked client/group entries before least-recently-used eviction (default `10000`) |
| `TRUSTED_EDGE` | Names the edge proxy this deployment sits behind (`cloudflare`, or unset). Unset means no edge client-address header is trusted, so an environment without a proxy in front cannot have its rate limiting bypassed by a forged header |
| `TRUSTED_PROXY_HOPS` | Hops appended by trusted proxies, counted from the right of `X-Forwarded-For` (default `1`, Railway's edge). Only consulted when `CF-Connecting-IP` is absent: a proxy-set header the edge overwrites on every request is preferred, because it stays correct when a proxy layer is added and a counted position does not |

## Deployment and monitoring

Merging to `main` deploys to production on Railway, gated by the `/ready` healthcheck and verified
afterward by the release observer. Deployment, artifact retention, scheduled maintenance, product
signals, and monitoring are documented in
**[docs/operations/deployment.md](docs/operations/deployment.md)**.

What changed in production and when is recorded in
[docs/operations/changelog.md](docs/operations/changelog.md); the current verified state is in
[docs/operations/production-status.md](docs/operations/production-status.md).

## Contributing

Setup, the checks to run, and the safety rails are in [CONTRIBUTING.md](CONTRIBUTING.md).
Behavior is governed by the specs in `openspec/specs/` — where a spec exists, it wins over the
code and this README.

## Roadmap

- [x] Stage and promote the verified complete 2025-26 dataset
- [x] Dataset freshness/provenance endpoint and visible verification status
- [x] Shot charts, contextual filters, five-zone profiles, in-season splits, exports, and comparisons
- [x] Browser acceptance coverage for primary, mobile, empty, error, sharing, and export flows
- [x] Readiness, request telemetry, scheduled live checks, rate protection, and gzip responses
- [x] Durable verified-dataset archive packaging and Railway object storage
- [x] Production backup restore-tested on PostgreSQL 18 and retained with checksum metadata
- [x] Daily retained backups and monthly isolated restore drills with visible failure incidents
- [x] Exact-revision Railway release observation and automatic GitHub incident tracking
- [x] Runtime-only production dependency installation with no startup environment mutation
- [x] Anonymous usage signals and one-click sharing for evidence-driven product work
- [x] Separate HTTP policy, shot-filter, and frontend core modules from the main application files
- [ ] Complete the seven-day production burn-in, then tune only from HTTP metrics, usage signals,
  and query plans
- [ ] Deferred by product scope: historical backfill, multi-season promotion, and cross-season analysis

## License

MIT
