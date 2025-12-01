.PHONY: help install db-start db-stop db-reset db-shell db-logs extract transform load etl test clean clean-season seasons status lint format typecheck check api

# Configuration
SEASON ?= 2024-25

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
	@echo "ETL Pipeline (default season: $(SEASON)):"
	@echo "  make extract     - Download data from NBA API"
	@echo "  make transform   - Transform raw data to CSVs"
	@echo "  make load        - Load CSVs into database"
	@echo "  make etl         - Run full ETL pipeline"
	@echo ""
	@echo "  Override season: make etl SEASON=2023-24"
	@echo ""
	@echo "Testing & Quality:"
	@echo "  make test        - Run data quality tests"
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
	@sleep 3
	@docker compose exec db pg_isready -U postgres -d nba_db || (echo "Database not ready" && exit 1)
	@echo "Database is ready!"

db-stop:
	docker compose down

db-reset:
	docker compose down -v
	docker compose up -d
	@echo "Waiting for database to initialize..."
	@sleep 5
	@docker compose exec db pg_isready -U postgres -d nba_db || (echo "Database not ready" && exit 1)
	@echo "Database reset complete!"

db-shell:
	docker compose exec db psql -U postgres -d nba_db

db-logs:
	docker compose logs -f db

# ETL Pipeline
extract:
	uv run python etl/extract.py --season $(SEASON)

transform:
	uv run python etl/transform.py --season $(SEASON)

load:
	uv run python etl/load.py --season $(SEASON)

etl: extract transform load
	@echo "ETL pipeline complete for season $(SEASON)!"

# Info commands
seasons:
	@docker compose exec db psql -U postgres -d nba_db -c "SELECT id as season, games_count, players_count, shots_count, loaded_at FROM seasons ORDER BY id DESC;" 2>/dev/null || echo "Database not running"

# Testing & Quality
test:
	uv run python db/tests/test_data_quality.py

lint:
	uv run ruff check etl/ app/ db/tests/

format:
	uv run ruff format etl/ app/ db/tests/
	uv run ruff check --fix etl/ app/ db/tests/

typecheck:
	uv run mypy etl/ app/ db/tests/

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

clean-season:
	rm -rf data/raw/$(SEASON)/
	rm -rf data/clean/$(SEASON)/
	@echo "Cleaned data for season $(SEASON)"

# Quick status check
status:
	@echo "=== Docker Status ==="
	@docker compose ps
	@echo ""
	@echo "=== Database Tables ==="
	@docker compose exec db psql -U postgres -d nba_db -c "\dt" 2>/dev/null || echo "Database not running"
	@echo ""
	@echo "=== Row Counts ==="
	@docker compose exec db psql -U postgres -d nba_db -c "SELECT 'teams' as table_name, COUNT(*) FROM teams UNION ALL SELECT 'players', COUNT(*) FROM players UNION ALL SELECT 'games', COUNT(*) FROM games UNION ALL SELECT 'player_game_stats', COUNT(*) FROM player_game_stats UNION ALL SELECT 'team_game_stats', COUNT(*) FROM team_game_stats UNION ALL SELECT 'shots', COUNT(*) FROM shots;" 2>/dev/null || echo "Database not running"
