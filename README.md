# NBA Database

A PostgreSQL database system for NBA statistics with ETL pipeline powered by the NBA API.

## Features

- **ETL Pipeline**: Automated data extraction from NBA API, transformation, and database loading
- **REST API**: FastAPI application with 18 endpoints for querying stats
- **Web Interface**: Interactive dashboard for browsing stats (http://localhost:8000)
- **Comprehensive Stats**: Player box scores, team stats, game data, shot charts
- **Multi-Season Support**: Load data for any NBA season
- **Database Features**: CHECK constraints, triggers, views, stored procedures
- **Data Quality Tests**: Automated validation of data integrity and consistency
- **Docker Support**: One-command PostgreSQL setup

## Tech Stack

| Component | Technology |
|-----------|------------|
| Database | PostgreSQL 16 |
| Language | Python 3.11 |
| Web Framework | FastAPI |
| Package Manager | uv |
| Data Processing | pandas, numpy |
| NBA Data | nba_api |
| Containerization | Docker, Docker Compose |
| Code Quality | ruff, mypy |

## Database Schema

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│     teams       │     │     players     │     │     games       │
├─────────────────┤     ├─────────────────┤     ├─────────────────┤
│ id (PK)         │     │ id (PK)         │     │ id (PK)         │
│ full_name       │     │ full_name       │     │ home_team_id(FK)│
│ abbreviation    │     │ first_name      │     │ away_team_id(FK)│
│ nickname        │     │ last_name       │     │ home_score      │
│ city            │     │ is_active       │     │ away_score      │
│ state           │     └─────────────────┘     │ season          │
│ year_founded    │                             │ game_date       │
└─────────────────┘                             └─────────────────┘
         │                      │                        │
         │                      │                        │
         ▼                      ▼                        ▼
┌───────────────────────────────────────────────────────────────────┐
│                      player_game_stats                             │
├───────────────────────────────────────────────────────────────────┤
│ id (PK), game_id (FK), player_id (FK), team_id (FK)               │
│ position, starter, minutes                                         │
│ points, rebounds, assists, steals, blocks, turnovers              │
│ fgm, fga, fg_pct, fg3m, fg3a, fg3_pct, ftm, fta, ft_pct           │
│ offensive_rating, defensive_rating, net_rating, pace, pie         │
└───────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────┐
│                       team_game_stats                              │
├───────────────────────────────────────────────────────────────────┤
│ id (PK), game_id (FK), team_id (FK), is_home                      │
│ points, rebounds, assists, steals, blocks, turnovers              │
│ fgm, fga, fg_pct, fg3m, fg3a, fg3_pct, ftm, fta, ft_pct           │
│ offensive_rating, defensive_rating, net_rating, pace              │
└───────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────┐
│                           shots                                    │
├───────────────────────────────────────────────────────────────────┤
│ id (PK), game_id (FK), player_id (FK), team_id (FK)               │
│ period, minutes_remaining, seconds_remaining                       │
│ event_type, action_type, shot_type                                │
│ shot_zone_basic, shot_zone_area, shot_zone_range, shot_distance   │
│ loc_x, loc_y, shot_made                                           │
└───────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
nba-db/
├── app/                    # FastAPI web application
│   ├── main.py             # API endpoints (18 routes)
│   ├── models.py           # Pydantic response models
│   ├── db.py               # Database connection pool
│   └── templates/
│       └── index.html      # Web interface dashboard
│
├── data/
│   ├── raw/               # Raw JSON from NBA API
│   └── clean/             # Transformed CSVs
│
├── db/
│   ├── schema/
│   │   ├── 01_tables.sql      # Table definitions
│   │   ├── 02_constraints.sql # CHECK constraints
│   │   ├── 03_indexes.sql     # Query optimization
│   │   ├── 04_triggers.sql    # Audit logging triggers
│   │   ├── 05_views.sql       # Pre-built query views
│   │   └── 06_procedures.sql  # Stored procedures
│   ├── tests/
│   │   └── test_data_quality.py
│
├── etl/
│   ├── extract.py         # Download from NBA API
│   ├── transform.py       # JSON → CSV transformation
│   └── load.py            # CSV → PostgreSQL loading
│
├── docker-compose.yml     # PostgreSQL container
├── Makefile              # Automation commands
├── pyproject.toml        # Python dependencies
└── README.md
```

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager

### Installation

```bash
# Clone the repository
git clone <repo>
cd nba-db

# Install dependencies
make install

# Copy environment file
cp .env.example .env

# Start PostgreSQL
make db-start

# Run full ETL pipeline
make etl
```

### Verify Installation

```bash
# Check database status and row counts
make status

# Run data quality tests
make test
```

## Usage

### Make Commands

```bash
make help          # Show all available commands

# Database
make db-start      # Start PostgreSQL container
make db-stop       # Stop PostgreSQL container
make db-reset      # Reset database (destroy and recreate)
make db-shell      # Open psql shell

# ETL Pipeline (default: 2024-25 season)
make extract       # Download data from NBA API
make transform     # Transform raw data to CSVs
make load          # Load CSVs into database
make etl           # Run full ETL pipeline

# Load different seasons
make etl SEASON=2023-24
make etl SEASON=2022-23

# API
make api           # Start FastAPI server (http://localhost:8000)

# Testing & Quality
make test          # Run data quality tests
make lint          # Run ruff linter
make format        # Format code with ruff
make typecheck     # Run mypy type checker
make check         # Run all checks (lint + typecheck)

# Maintenance
make clean         # Remove generated files
make status        # Show database status and row counts
make seasons       # List loaded seasons
```

## Web Interface

The project includes an interactive web dashboard at http://localhost:8000 with:

- **Dashboard**: Overview stats and quick links
- **Players**: Search and browse player statistics
- **Teams**: View all 30 NBA teams
- **Games**: Browse game results with box scores
- **Standings**: League standings by season
- **Leaders**: Stat leaders (points, rebounds, assists, etc.)

Start the server with `make api` and open http://localhost:8000 in your browser.

## REST API

Start the API server:
```bash
make api
# Server runs at http://localhost:8000
# Interactive docs at http://localhost:8000/docs
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/seasons` | GET | List loaded seasons |
| `/api/teams` | GET | List all teams |
| `/api/teams/{id}` | GET | Get team by ID |
| `/api/teams/{id}/standings` | GET | Team win/loss record |
| `/api/players` | GET | List players (search, pagination) |
| `/api/players/{id}` | GET | Get player by ID |
| `/api/players/{id}/stats` | GET | Player season averages |
| `/api/players/{id}/games` | GET | Player game logs |
| `/api/players/{id}/shots` | GET | Player shot chart data |
| `/api/players/{id}/shooting-zones` | GET | Player FG% by zone |
| `/api/games` | GET | List games (filter by season/team) |
| `/api/games/{id}` | GET | Get game by ID |
| `/api/games/{id}/boxscore` | GET | Full box score |
| `/api/games/{id}/shots` | GET | All shots from game |
| `/api/leaders/{stat}` | GET | Stat leaders (points, rebounds, etc.) |
| `/api/standings` | GET | League standings |

### Example API Requests

```bash
# Get all teams
curl http://localhost:8000/api/teams

# Search players
curl "http://localhost:8000/api/players?search=lebron"

# Get player season averages
curl http://localhost:8000/api/players/2544/stats

# Get game box score
curl http://localhost:8000/api/games/22401220/boxscore

# Get scoring leaders
curl "http://localhost:8000/api/leaders/points?season=2024-25"

# Get player shooting zones
curl http://localhost:8000/api/players/2544/shooting-zones
```

## Data Quality Tests

The test suite validates:

| Category | Tests |
|----------|-------|
| **Row Counts** | Tables are not empty, teams = 30 |
| **Referential Integrity** | All FKs reference valid records |
| **Data Consistency** | Game scores match team stats, 2 teams per game |
| **Value Ranges** | No negative stats, percentages between 0-1 |
| **Completeness** | Active players have stats, all teams have games |

Run tests:
```bash
make test
```

## Database Features

### CHECK Constraints

Data validation at the database level:

| Table | Constraints |
|-------|-------------|
| `games` | Scores non-negative, home/away teams different |
| `player_game_stats` | Stats non-negative, makes <= attempts, percentages 0-1 |
| `team_game_stats` | Stats non-negative, makes <= attempts, percentages 0-1 |
| `shots` | Valid period (1-10), time (0-12min), court coordinates |
| `teams` | Year founded 1946-2025 |
| `seasons` | Valid year range, non-negative counts |

### Triggers

Automated database operations:

| Trigger | Purpose |
|---------|---------|
| `trg_audit_*` | Log all changes to `audit_log` table |
| `trg_update_season_counts` | Auto-update season statistics |
| `trg_validate_game_stats` | Ensure 2 teams per game |
| `trg_set_game_date` | Auto-populate game dates |

### Views

Pre-built queries for common operations:

| View | Description |
|------|-------------|
| `vw_team_standings` | Win/loss records by season |
| `vw_player_season_averages` | PPG, RPG, APG, etc. |
| `vw_scoring_leaders` | Top scorers by season |
| `vw_recent_games` | Games with team names |
| `vw_player_shooting_stats` | FG%, 3P%, eFG% |
| `vw_team_offensive_stats` | Team scoring averages |

### Stored Procedures

Reusable database functions:

| Procedure | Description |
|-----------|-------------|
| `fn_get_player_averages(player_id, season)` | Calculate player stats |
| `fn_get_team_record(team_id, season)` | Get win/loss record |
| `fn_get_stat_leaders(stat, season, limit)` | Get league leaders |
| `fn_search_players(search_term, limit)` | Search players by name |
| `fn_get_head_to_head(team1, team2, season)` | Head-to-head results |
| `sp_refresh_season_stats(season)` | Update season metadata |

## NBA API Endpoints Used

| Endpoint | Data |
|----------|------|
| `CommonAllPlayers` | Player roster |
| `teams.get_teams()` | Team information |
| `LeagueGameLog` | Season game schedule |
| `BoxScoreTraditionalV3` | Player/team traditional stats |
| `BoxScoreAdvancedV3` | Player/team advanced stats |
| `ShotChartDetail` | Shot location data |

## Current Data

| Table | Records | Description |
|-------|---------|-------------|
| teams | 30 | All NBA teams |
| players | ~5,100 | All-time players |
| games | ~1,200 | Season games |
| player_game_stats | ~32,000 | Player box scores |
| team_game_stats | ~2,400 | Team box scores |
| shots | ~170,000 | Shot chart data |

## Configuration

Environment variables (`.env`):

```bash
DB_NAME=nba_db
DB_USER=nba_user
DB_PASSWORD=nba_password
DB_HOST=localhost
DB_PORT=5432
```

## Roadmap

- [x] ETL pipeline with multi-season support
- [x] FastAPI REST application
- [x] Shot chart data and endpoints
- [x] Code quality tools (ruff, mypy)
- [x] Database views for common queries
- [x] CHECK constraints and triggers
- [x] Stored procedures and functions
- [x] Web interface dashboard
- [ ] Scheduled data refresh (cron/GitHub Actions)
- [ ] Shot chart visualizations
- [ ] Historical season backfill

## License

MIT
