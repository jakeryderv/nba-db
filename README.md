# NBA Stats Explorer

A read-only web app and REST API for exploring NBA statistics — standings, stat leaders, box scores, and player search — backed by PostgreSQL and an ETL pipeline over the official NBA API.

**Live:** https://nba-api-production-0cd7.up.railway.app · **API docs:** https://nba-api-production-0cd7.up.railway.app/docs

## How it works

- **ETL pipeline** (`etl/`) downloads season data from the NBA API, transforms it to CSVs, and loads it into PostgreSQL. Loading is an operator task — the public app has no write capability.
- **FastAPI app** (`app/`) serves a single-page dashboard and a read-only JSON API. In production it connects with a SELECT-only database role (`nba_readonly`).
- **Schema** (`db/schema/`) is applied idempotently at deploy time by `scripts/init_db.py` (Railway `startCommand`), with CHECK constraints, indexes, and views.

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
curl "https://nba-api-production-0cd7.up.railway.app/api/leaders/points?season=2024-25"
```

## Local development

Prerequisites: Docker, Python 3.11+, [uv](https://github.com/astral-sh/uv).

```bash
make install       # uv sync
cp .env.example .env
make db-start      # PostgreSQL in Docker
make etl           # extract + transform + load (default SEASON=2024-25)
make api           # http://localhost:8000
```

Other useful targets (`make help` for all): `make etl SEASON=2023-24`, `make etl-multi`, `make db-shell`, `make status`, `make seasons`.

## Loading data into production

The **Refresh Data** GitHub Actions workflow (daily at 10:00 UTC, or on demand via `workflow_dispatch` with an optional `season` input) re-downloads the current season from the NBA API and loads it into the production database (idempotent inserts — only new games land).

**Current status: the schedule is disabled.** stats.nba.com blocks requests from GitHub's datacenter IPs (requests hang until timeout), so scheduled runs cannot reach the API. Until the 2026-27 season starts, refreshes are run manually from a trusted machine (see below). Options for re-enabling automation at season start: a local cron job, a self-hosted GitHub runner, or a residential proxy for the hosted runner. Also note: GitHub automatically disables scheduled workflows after 60 days without repository activity — re-enable from the Actions tab.

Manual loading from a trusted machine still works:

```bash
DATABASE_URL="postgresql://user:pass@host:port/dbname" make refresh SEASON=2025-26
```

(`extract`/`transform` only touch local files; only the `load` step needs the production `DATABASE_URL` — Railway's public TCP-proxy address, not the internal one.)

## Testing

```bash
make test        # API test suite (pytest; needs make db-start, uses a separate nba_db_test database)
make test-data   # data quality checks against loaded data
make check       # ruff + mypy
```

## Configuration

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Full connection string (takes precedence; used on Railway) |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | Individual settings for local development |
| `READONLY_DB_PASSWORD` | Optional. When set, `init_db.py` provisions a SELECT-only `nba_readonly` role and the web app connects as it |

## Deployment

Deployed on [Railway](https://railway.com) (`railway.toml`): on each deploy, `scripts/init_db.py` applies the schema if missing and refreshes the read-only role, then uvicorn serves the app. Set `DATABASE_URL` (provided by the Railway Postgres plugin) and `READONLY_DB_PASSWORD` on the service.

## Roadmap

- [x] Scheduled data refresh (built; schedule disabled until 2026-27 — see Loading data into production)
- [ ] Shot chart data and visualizations
- [ ] Historical season backfill

## License

MIT
