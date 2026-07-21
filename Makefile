.PHONY: help install db-start db-stop db-reset db-shell db-logs extract transform verify-official refresh season-build season-load-local season-promote require-season require-promotion test test-data clean seasons status lint format typecheck check api

# Configuration
SEASON ?=
TARGET ?=
CONFIRM_SEASON ?=
CONFIRM_SINGLE_SEASON ?=
BACKUP_FILE ?=
API_URL ?=

# Default target
help:
	@echo "NBA Database - Available Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install     - Install Python dependencies"
	@echo ""
	@echo "Database:"
	@echo "  make db-start    - Start PostgreSQL container"
	@echo "  make db-stop     - Stop PostgreSQL container"
	@echo "  make db-reset    - Reset database (destroy and recreate)"
	@echo "  make db-shell    - Open psql shell"
	@echo "  make db-logs     - View database logs"
	@echo ""
	@echo "Season Lifecycle (explicit SEASON=YYYY-YY required):"
	@echo "  make season-build       - Extract, transform, cross-check, and write manifest"
	@echo "  make season-load-local  - Replace local DB with exactly the manifested season"
	@echo "  make season-promote     - Back up and replace production with typed confirmations"
	@echo ""
	@echo "Data preparation:"
	@echo "  make extract     - Download data from NBA API"
	@echo "  make transform   - Transform raw data to CSVs"
	@echo "  make verify-official - Compare local totals with official NBA aggregates"
	@echo "  make refresh     - Local-only alias for guarded season build + load"
	@echo ""
	@echo "  Example local build: make season-build SEASON=2025-26"
	@echo ""
	@echo "Testing & Quality:"
	@echo "  make test        - Run API test suite (requires make db-start)"
	@echo "  make test-data   - Run data quality tests (requires loaded data)"
	@echo "  make lint        - Run ruff linter"
	@echo "  make format      - Format code with ruff"
	@echo "  make typecheck   - Run mypy type checker"
	@echo "  make check       - Run all checks (lint + typecheck)"
	@echo ""
	@echo "API:"
	@echo "  make api         - Start FastAPI server (http://localhost:8000)"
	@echo ""
	@echo "Info:"
	@echo "  make seasons     - List loaded seasons"
	@echo "  make status      - Show database status"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean       - Remove generated files"

# Setup
install:
	uv sync

# Database commands
db-start:
	docker compose up -d
	@echo "Waiting for database to be ready..."
	@sleep 5
	@docker compose exec db pg_isready -U nba_user -d nba_db --quiet || (echo "Database not ready" && exit 1)
	@echo "Database is ready!"

db-stop:
	docker compose down

db-reset:
	docker compose down -v
	docker compose up -d
	@echo "Waiting for database to initialize..."
	@sleep 10
	@docker compose exec db pg_isready -U nba_user -d nba_db --quiet || (echo "Database not ready" && exit 1)
	@echo "Database reset complete!"

db-shell:
	docker compose exec db psql -U nba_user -d nba_db

db-logs:
	docker compose logs -f db

# ETL Pipeline
require-season:
	@test -n "$(strip $(SEASON))" || (echo "ERROR: set an explicit SEASON=YYYY-YY" && exit 2)
	@uv run python -m etl.season_lifecycle validate-season --season "$(SEASON)"

require-promotion: require-season
	@test "$(TARGET)" = "production" || (echo "ERROR: set TARGET=production" && exit 2)
	@test "$(CONFIRM_SEASON)" = "$(SEASON)" || (echo "ERROR: type CONFIRM_SEASON=$(SEASON)" && exit 2)
	@test "$(CONFIRM_SINGLE_SEASON)" = "DELETE OTHER SEASONS" || (echo "ERROR: type CONFIRM_SINGLE_SEASON='DELETE OTHER SEASONS'" && exit 2)
	@test -n "$(strip $(BACKUP_FILE))" || (echo "ERROR: set BACKUP_FILE to a new protected backup path" && exit 2)
	@test -n "$(strip $(API_URL))" || (echo "ERROR: set API_URL to the credential-free production HTTPS URL" && exit 2)
	@test "$(origin PRODUCTION_DATABASE_URL)" != "command line" || (echo "ERROR: export PRODUCTION_DATABASE_URL; do not pass it as a make argument" && exit 2)
	@test -n "$$PRODUCTION_DATABASE_URL" || (echo "ERROR: export PRODUCTION_DATABASE_URL in the environment" && exit 2)

extract: require-season
	uv run python etl/extract.py --season "$(SEASON)"

transform: require-season
	uv run python etl/transform.py --season "$(SEASON)"

verify-official: require-season
	uv run python -m etl.official_verification --season "$(SEASON)"

season-build: require-season
	uv run python etl/extract.py --season "$(SEASON)" --force
	uv run python etl/transform.py --season "$(SEASON)"
	uv run python -m etl.official_verification --season "$(SEASON)"
	uv run python -m etl.season_lifecycle manifest --season "$(SEASON)"
	@echo "Season build, official verification, and manifest complete for $(SEASON)."

season-load-local: require-season
	uv run python -m etl.season_lifecycle load-local --season "$(SEASON)"

season-promote: require-promotion
	uv run python -m etl.season_lifecycle promote \
		--season "$(SEASON)" \
		--target "$(TARGET)" \
		--confirm-season "$(CONFIRM_SEASON)" \
		--confirm-single-season "$(CONFIRM_SINGLE_SEASON)" \
		--backup-file "$(BACKUP_FILE)" \
		--api-url "$(API_URL)"

refresh: season-build
	$(MAKE) season-load-local SEASON="$(SEASON)"
	@echo "Local-only refresh completed; production requires season-promote."

# Info commands
seasons:
	@docker compose exec db psql -U nba_user -d nba_db -c "SELECT id AS season, games_count, players_count, loaded_at FROM seasons ORDER BY id DESC;" 2>/dev/null || echo "Database not running"

# Testing & Quality
test:
	PYTHONPATH=. uv run pytest tests/ -v

test-data:
	PYTHONPATH=. uv run python db/tests/test_data_quality.py

lint:
	uv run ruff check etl/ app/ db/ scripts/ tests/

format:
	uv run ruff format etl/ app/ db/ scripts/ tests/
	uv run ruff check --fix etl/ app/ db/ scripts/ tests/

typecheck:
	uv run mypy etl/ app/ db/ scripts/

# API
api:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

check: lint typecheck
	@echo "All checks passed!"

# Maintenance
clean:
	rm -rf data/clean/*/
	rm -rf __pycache__ **/__pycache__
	rm -rf .pytest_cache
	@echo "Cleaned generated files"

# Quick status check
status:
	@echo "=== Docker Status ==="
	@docker compose ps
	@echo ""
	@echo "=== Database Tables ==="
	@docker compose exec db psql -U nba_user -d nba_db -c "\dt" 2>/dev/null || echo "Database not running"
	@echo ""
	@echo "=== Row Counts ==="
	@docker compose exec db psql -U nba_user -d nba_db -c "SELECT 'teams' AS table_name, COUNT(*) AS count FROM teams UNION ALL SELECT 'players', COUNT(*) FROM players UNION ALL SELECT 'games', COUNT(*) FROM games UNION ALL SELECT 'player_game_stats', COUNT(*) FROM player_game_stats UNION ALL SELECT 'team_game_stats', COUNT(*) FROM team_game_stats;" 2>/dev/null || echo "Database not running"
