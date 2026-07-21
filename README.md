# NBA Stats Explorer

A read-only web app and REST API for exploring NBA statistics — standings, stat leaders, box scores, and player search — backed by PostgreSQL and an ETL pipeline over the official NBA API.

**Live:** https://nba-api-production-0cd7.up.railway.app · **API docs:** https://nba-api-production-0cd7.up.railway.app/docs

## How it works

- **ETL pipeline** (`etl/`) downloads season data from the NBA API, transforms it to CSVs, and loads it into PostgreSQL. Loading is an operator task — the public app has no write capability.
- **FastAPI app** (`app/`) serves a single-page dashboard and a read-only JSON API. In production it connects with a SELECT-only database role (`nba_readonly`).
- **Schema** (`db/schema/`) is managed as numbered, checksum-tracked migrations by `scripts/init_db.py` (Railway `startCommand`), with CHECK constraints, indexes, and views.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Database | PostgreSQL 16 (Docker locally, Railway in production) |
| Language | Python 3.11 |
| Web framework | FastAPI + psycopg 3 |
| Package manager | uv |
| Data source | [nba_api](https://github.com/swar/nba_api) |
| CI | GitHub Actions (ruff, mypy, pytest) |

## API

All endpoints are read-only. Interactive docs at `/docs`.

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /api/seasons` | Loaded seasons |
| `GET /api/teams` | All teams |
| `GET /api/teams/{id}` | Team by ID |
| `GET /api/players` | Players (case-insensitive `?search=`, `?active=`, pagination) |
| `GET /api/players/{id}` | Player by ID |
| `GET /api/players/{id}/stats` | Player season averages |
| `GET /api/games` | Games (filter by `?season=`, `?team_id=`) |
| `GET /api/games/{id}` | Game by ID |
| `GET /api/games/{id}/boxscore` | Full box score |
| `GET /api/team-game-stats` | Team box-score lines (by season) |
| `GET /api/player-game-stats` | Player box-score lines (by season) |
| `GET /api/leaders/{stat}` | Stat leaders (points, rebounds, assists, steals, blocks) |
| `GET /api/standings` | League standings (`?season=` required) |

```bash
curl "https://nba-api-production-0cd7.up.railway.app/api/players?search=lebron"
curl "https://nba-api-production-0cd7.up.railway.app/api/leaders/points?season=2025-26"
```

## Local development

Prerequisites: Docker, Python 3.11+, [uv](https://github.com/astral-sh/uv).

```bash
make install       # uv sync
cp .env.example .env
make db-start      # PostgreSQL in Docker
make season-build SEASON=2025-26
make season-load-local SEASON=2025-26
make api           # http://localhost:8000
```

Every data command requires an explicit season. There is no default season or default multi-season backfill. Run `make help` for the complete target list.

## Safe season lifecycle

The guarded lifecycle handles exactly one NBA **Regular Season** dataset at a time. Preseason, All-Star, Play-In, and playoff datasets are outside this workflow's scope. Run extraction from a trusted machine that can reach `stats.nba.com`; GitHub Actions performs validation only against its ephemeral PostgreSQL service and never loads production.

### 1. Build and validate one season

Choose the season deliberately. This force-downloads fresh source data, transforms it, validates file relationships and official Regular Season game IDs in the `002.......` format, and writes `data/clean/<season>/manifest.json` with source scope, row counts, and SHA-256 checksums.

```bash
make season-build SEASON=2025-26
uv run python -m json.tool data/clean/2025-26/manifest.json
```

Do not edit transformed files after the manifest is created. Local load and production promotion recompute the checksums and fail closed if the dataset changed.

### 2. Replace the local database

Start PostgreSQL, ensure no production URL is present, then load the manifested season locally:

```bash
make db-start
unset DATABASE_URL PRODUCTION_DATABASE_URL
make season-load-local SEASON=2025-26
```

This is an exact one-season replacement: all other local season rows are removed inside the replacement transaction. Verify the local API and data before considering production promotion. There is no raw load or multi-season Make target. `refresh` exists only as a compatibility alias for the same guarded build and localhost replacement; it is not a production promotion path.

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

Promotion verifies the manifest again, rejects local database targets, and takes a database advisory lock held from the protected custom-format `pg_dump` through the final live smoke check. It atomically replaces production so it contains exactly the confirmed season, then checks live health, season metadata, game identity/count, a sampled box score, standings, and points leaders against the manifest and promoted season. The API smoke check retries briefly; if it ultimately fails, the database replacement has already committed, so investigate immediately and restore the backup if the promoted data is not acceptable.

### Backup restore guidance

Keep the reported backup path and restrict access to it. First inspect the archive with `pg_restore --list` and restore it into an isolated recovery database using PostgreSQL's `pg_restore --clean --if-exists --no-owner` options. Verify season counts and API behavior there. Only then schedule a controlled production restore using the same archive. Supply connection fields and passwords through PostgreSQL environment variables or a protected service file—not command-line connection strings—and confirm the target database before running any restore. A restore replaces the full pre-promotion database state, including seasons that promotion removed.

## Testing

```bash
make test        # API test suite (pytest; needs make db-start, uses a separate nba_db_test database)
make test-data   # data quality checks against loaded data
make check       # ruff + mypy
```

## Configuration

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Application/development connection string (takes precedence; used on Railway) |
| `PRODUCTION_DATABASE_URL` | Promotion-only connection string; export interactively and never store in CLI arguments or GitHub Actions |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | Individual settings for local development |
| `READONLY_DB_PASSWORD` | Optional. When set, `init_db.py` provisions a SELECT-only `nba_readonly` role and the web app connects as it |

## Deployment

Deployed on [Railway](https://railway.com) (`railway.toml`): on each deploy, `scripts/init_db.py` applies pending checksum-tracked schema migrations and refreshes the read-only role, then uvicorn serves the app. Set `DATABASE_URL` (provided by the Railway Postgres plugin) and `READONLY_DB_PASSWORD` on the service.

Schema migration files are immutable after they have been applied. To change the database, add the next numbered file under `db/schema/`; editing an applied file causes initialization to fail with a checksum error.

## Roadmap

- [ ] Automated data refresh (production loading is currently a guarded operator task)
- [ ] Shot chart data and visualizations
- [ ] Historical season backfill

## License

MIT
