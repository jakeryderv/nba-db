# NBA Stats Explorer

A read-only web app and REST API for exploring NBA statistics — standings, stat leaders, box scores, and player search — backed by PostgreSQL and an ETL pipeline over the official NBA API.

**Live:** https://nba-api-production-0cd7.up.railway.app · **API docs:** https://nba-api-production-0cd7.up.railway.app/docs

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

All endpoints are read-only. Interactive docs at `/docs`.

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /ready` | Verified default-season readiness and critical row counts |
| `GET /api/seasons` | Loaded seasons |
| `GET /api/dataset-status` | Dataset freshness, verification, manifest, and row counts |
| `GET /api/teams` | All teams |
| `GET /api/teams/{id}` | Team by ID |
| `GET /api/teams/{id}/stats` | Team record, splits, and season averages |
| `GET /api/teams/{id}/players` | Team player averages, ranked by scoring |
| `GET /api/players` | Players (case-insensitive `?search=`, `?active=`, pagination) |
| `GET /api/players/{id}` | Player by ID |
| `GET /api/players/{id}/stats` | Player season averages |
| `GET /api/players/{id}/games` | Paginated player game log |
| `GET /api/shot-chart/players` | Players with shot attempts in a season |
| `GET /api/shot-chart/games` | Games with attempts for one player or team |
| `GET /api/shot-chart/action-types` | Available action types in the loaded season |
| `GET /api/shot-chart` | Player or team locations, efficiency, frequency, and league-relative zone analytics |
| `GET /api/shot-profile` | Five-zone profile plus venue, month, opponent, and All-Star-break splits |
| `GET /api/shot-chart.csv` | Complete filtered player or team shot-attempt export |
| `GET /api/comparisons/players` | Compare exactly two players for a season |
| `GET /api/comparisons/teams` | Compare two teams, including head-to-head results |
| `GET /api/games` | Games (filter by `?season=`, `?team_id=`) |
| `GET /api/games/{id}` | Game by ID |
| `GET /api/games/{id}/boxscore` | Full box score |
| `GET /api/team-game-stats` | Team box-score lines (by season) |
| `GET /api/player-game-stats` | Player box-score lines (by season) |
| `GET /api/leaders/{stat}` | Qualified stat leaders (points, rebounds, assists, steals, blocks) |
| `GET /api/standings` | League standings (`?season=` required) |

```bash
curl "https://nba-api-production-0cd7.up.railway.app/api/players?search=lebron"
curl "https://nba-api-production-0cd7.up.railway.app/api/leaders/points?season=2025-26"
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

## Safe season lifecycle

The guarded lifecycle handles exactly one NBA **Regular Season** dataset at a time. Preseason, All-Star, Play-In, and playoff datasets are outside this workflow's scope. Run extraction and official verification from a trusted machine that can reach `stats.nba.com`; GitHub Actions uses deterministic fixtures and its ephemeral PostgreSQL service, never calls NBA endpoints, and never loads production.

### 1. Build and validate one season

Choose the season deliberately. This force-downloads fresh source data, including bounded `ShotChartDetail` responses for all 30 teams, transforms it, validates file relationships and official Regular Season game IDs in the `002.......` format, then compares calculated team and player counting-stat totals with the NBA's `LeagueDashTeamStats` and `LeagueDashPlayerStats` totals. Per-team requests are deliberate because the NBA endpoint silently caps an all-league shot response at 102,400 rows. Shot makes, player/team identity, and 3PT makes must match each player-game box score exactly. FGA and 3PA may differ by one for a documented NBA source correction; every accepted difference is recorded in `manifest.json`, while anything larger fails closed. Games played, records, and points must match exactly. Other counting stats use the same documented one-count correction policy because NBA game-log and aggregate feeds can diverge after stat corrections; every difference remains visible in the report. Only a passing `data/clean/<season>/verification.json` can be bound into the manifest with source scope, row counts, and SHA-256 checksums for all six transformed files.

```bash
make season-build SEASON=2025-26
uv run python -m json.tool data/clean/2025-26/manifest.json
uv run python -m json.tool data/clean/2025-26/verification.json
```

The equivalent trusted-machine Dagger build requires an explicit freshness key so a changing external NBA response cannot be confused with a deterministic cached input. It returns a typed directory that must be deliberately exported to the host:

```bash
dagger call season-build \
  --season=2025-26 \
  --refresh-key=2026-07-22T010000Z \
  export --path=data
```

To build, load, and serve the season entirely in disposable Dagger services, use a unique operation ID and leave the command running:

```bash
dagger up local-refresh \
  --season=2025-26 \
  --refresh-key=2026-07-22T010000Z \
  --operation-id=local-refresh-2026-07-22T010000Z
```

To rerun only the network-backed cross-check after transformation, use `make verify-official SEASON=2025-26`. Do not edit transformed files after verification or manifest creation. The report records every transformed-file checksum, and local load and production promotion fail closed if the dataset, report, or manifest changed. This check validates season totals; the existing relational and API tests still cover per-game calculations and application behavior.

### 2. Replace the local database

Start PostgreSQL, ensure no production URL is present, then load the manifested season locally:

```bash
make db-start
unset DATABASE_URL PRODUCTION_DATABASE_URL
make season-load-local SEASON=2025-26
```

After exporting a Dagger season build, the persistent Docker Compose database can instead be loaded through an explicitly granted host-service tunnel:

```bash
dagger call local-load \
  --database=tcp://localhost:5432 \
  --season=2025-26 \
  --confirm-local-target='LOCAL DOCKER DATABASE' \
  --operation-id=local-load-2026-07-22T010000Z
```

`local-load` has no network extraction step. It verifies the exported manifest again and uses the same exact one-season replacement logic as the Make workflow. The required operation ID prevents a mutating execution layer from being reused accidentally.

This is an exact one-season replacement: all other local season rows are removed inside the replacement transaction, including shot attempts. Verify the local API, shot totals, and visualizations before considering production promotion. There is no raw load or multi-season Make target. `refresh` exists only as a compatibility alias for the same guarded build and localhost replacement; it is not a production promotion path.

### 3. Promote with backup and typed confirmations

Promotion requires the dedicated `PRODUCTION_DATABASE_URL` environment variable. It is never accepted as a CLI argument and is intentionally distinct from the app's ordinary `DATABASE_URL`. Read the secret without echoing it or storing it in shell history:

```bash
read -rsp "Production database URL: " PRODUCTION_DATABASE_URL
printf '\n'
export PRODUCTION_DATABASE_URL
```

Create a protected backup directory outside the repository, then run promotion. The backup file must be a new path; the command refuses to overwrite an existing file.

```bash
install -d -m 700 "$HOME/.local/share/nba-db/backups"
make season-promote \
  SEASON=2025-26 \
  TARGET=production \
  CONFIRM_SEASON=2025-26 \
  CONFIRM_SINGLE_SEASON='DELETE OTHER SEASONS' \
  BACKUP_FILE="$HOME/.local/share/nba-db/backups/nba-db-before-2025-26-20260721T180000Z.dump" \
  API_URL=https://nba-api-production-0cd7.up.railway.app
unset PRODUCTION_DATABASE_URL
```

Dagger also exposes the same guarded promotion and returns the backup as a typed file. The database URL is introduced as a Dagger secret, while the data directory and backup destination remain explicit host grants:

```bash
dagger call promote \
  --season=2025-26 \
  --confirm-season=2025-26 \
  --confirm-single-season='DELETE OTHER SEASONS' \
  --api-url=https://nba-api-production-0cd7.up.railway.app \
  --backup-name=nba-db-before-2025-26-20260722T010000Z.dump \
  --operation-id=production-2025-26-20260722T010000Z \
  --production-database-url=env:PRODUCTION_DATABASE_URL \
  export --path="$HOME/.local/share/nba-db/backups/nba-db-before-2025-26-20260722T010000Z.dump"
unset PRODUCTION_DATABASE_URL
```

The typed confirmations remain enforced inside the lifecycle command. Neither GitHub Actions nor Railway receives `PRODUCTION_DATABASE_URL`, calls `stats.nba.com`, or invokes these mutating functions.

Promotion verifies the manifest again, rejects local database targets, and takes a database advisory lock held from the protected custom-format `pg_dump` through the final live smoke check. It atomically replaces production so it contains exactly the confirmed season, then checks live health, season metadata, game identity/count, a sampled box score, standings, and points leaders against the manifest and promoted season. The API smoke check retries briefly; if it ultimately fails, the database replacement has already committed, so investigate immediately and restore the backup if the promoted data is not acceptable.

Before production promotion, load the same manifested data into an isolated staging database and
smoke-test the staging app. Keep staging and production in separate Railway environments with
separate PostgreSQL services and variables. Export the staging secret rather than passing it on the
command line:

```bash
export STAGING_DATABASE_URL
make season-stage \
  TARGET=staging \
  CONFIRM_SEASON=2025-26 \
  STAGING_API_URL=https://your-staging-app.example
unset STAGING_DATABASE_URL
```

The staging command refuses local routes and refuses to run when staging and production URLs are
the same. It applies migrations, replaces staging with the manifested season, and runs the same live
API smoke suite. Smoke requests force cache revalidation.

### Backup restore guidance

Keep the reported backup path and restrict access to it. Run the executable restore drill against a
database name ending in `_recovery`; the command refuses an existing database, inspects the archive,
restores it, verifies the one-season provenance counts, and removes the disposable database even
when verification fails:

```bash
export RECOVERY_DATABASE_URL='postgresql://.../nba_recovery'
make restore-drill \
  BACKUP_FILE="$HOME/.local/share/nba-db/backups/<backup>.dump" \
  RESTORE_CONFIRM='RESTORE nba_recovery'
unset RECOVERY_DATABASE_URL
```

Only after this drill passes should an operator schedule a controlled production restore. A real
production restore remains a manual incident operation because it replaces the entire database
state, including seasons that promotion removed.

The same drill can run without host PostgreSQL client tools by passing the backup as a typed Dagger
file. Dagger creates and removes an isolated PostgreSQL 18 service for the operation:

```bash
dagger call restore-backup \
  --backup="$HOME/.local/share/nba-db/backups/<backup>.dump" \
  --season=2025-26 \
  --source=.
```

### Production monitoring

`/health` checks database connectivity while `/ready` additionally fails unless the verified default
season and its critical row counts match provenance metadata. Every response carries an
`X-Request-ID`, `Server-Timing`, and `X-Response-Time-Ms`; application logs include the same request
ID and elevate requests over one second.

Run a bounded live contract check at any time:

```bash
make live-check API_URL=https://nba-api-production-0cd7.up.railway.app
```

The scheduled and manually dispatched GitHub workflow runs this check using the configured
`LIVE_API_URL` repository variable. Its expected production totals are 1,230 games, 582
participating players, and 219,160 shots. Count drift, readiness failure, missing telemetry headers,
a response over three seconds, or a broken core/shot exploration endpoint fails the job. Use
Railway's HTTP metrics and logs with the returned request ID to investigate latency or errors.

The public API applies a process-local sliding-window limit per client. Ordinary API reads default
to 600 requests per minute; the aggregate-heavy shot chart, shot profile, and CSV routes default to
120. Large responses use gzip when the client advertises support. Override the limits with the
documented environment variables only after reviewing production traffic.

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
| `PRODUCTION_DATABASE_URL` | Promotion-only connection string; export interactively and never store in CLI arguments or GitHub Actions |
| `STAGING_DATABASE_URL` | Staging-only connection string for the guarded staging load |
| `RECOVERY_DATABASE_URL` | Drill-only connection string whose database name ends in `_recovery` |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | Individual settings for local development |
| `READONLY_DB_PASSWORD` | Optional. When set, `init_db.py` provisions a SELECT-only `nba_readonly` role and the web app connects as it |
| `RATE_LIMIT_ENABLED` | Enable public API rate limiting (default `true`) |
| `RATE_LIMIT_REQUESTS` | Per-client ordinary API requests per window (default `600`) |
| `RATE_LIMIT_EXPENSIVE_REQUESTS` | Per-client shot analytics/export requests per window (default `120`) |
| `RATE_LIMIT_WINDOW_SECONDS` | Sliding rate-limit window (default `60`) |

## Deployment

Deployed on [Railway](https://railway.com) (`railway.toml`) after the required GitHub check succeeds: Railpack builds the application, `scripts/init_db.py` applies pending checksum-tracked schema migrations and refreshes the read-only role, then uvicorn serves the app. Set `DATABASE_URL` (provided by the Railway Postgres plugin) and `READONLY_DB_PASSWORD` on the service. Railway deployment remains separate from Dagger so production credentials stay out of GitHub-hosted runners.

Schema migration files are immutable after they have been applied. To change the database, add the next numbered file under `db/schema/`; editing an applied file causes initialization to fail with a checksum error.

### Verified artifact retention

The production Railway project contains the `nba-db-artifacts` S3-compatible bucket. Archive the
raw NBA responses, clean CSVs, verification report, and manifest only after manifest verification
passes. The command refuses repository-local output and existing filenames, writes a SHA-256
sidecar and JSON receipt, and verifies checksum metadata after upload.

```bash
install -d -m 700 "$HOME/.local/share/nba-db/artifacts"
set -a
eval "$(railway bucket credentials --bucket nba-db-artifacts --environment production)"
set +a
make artifact-upload SEASON=2025-26 ARTIFACT_DIR="$HOME/.local/share/nba-db/artifacts"
make backup-upload SEASON=2025-26 BACKUP_FILE="$HOME/.local/share/nba-db/backups/<backup>.dump"
unset AWS_ENDPOINT_URL AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_S3_BUCKET_NAME AWS_DEFAULT_REGION
```

The uploader is an operator-only optional dependency (`uv run --extra ops`) and is not imported by
the web service. Object keys are versioned beneath `verified-seasons/<season>/` using an archive name
that includes the verified manifest checksum.

## Roadmap

- [x] Stage and promote the verified complete 2025-26 dataset
- [x] Dataset freshness/provenance endpoint and visible verification status
- [x] Shot charts, contextual filters, five-zone profiles, in-season splits, exports, and comparisons
- [x] Browser acceptance coverage for primary, mobile, empty, error, sharing, and export flows
- [x] Readiness, request telemetry, scheduled live checks, rate protection, and gzip responses
- [x] Durable verified-dataset archive packaging and Railway object storage
- [x] Production backup restore-tested on PostgreSQL 18 and retained with checksum metadata
- [x] Separate HTTP policy, shot-filter, and frontend core modules from the main application files
- [ ] Continue tuning only from production HTTP metrics and query plans
- [ ] Deferred by product scope: historical backfill, multi-season promotion, and cross-season analysis

## License

MIT
