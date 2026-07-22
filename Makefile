.PHONY: help install hooks-install hooks-run pre-push db-start db-stop db-reset db-shell db-logs extract transform verify-official refresh season-build season-load-local season-stage season-promote require-season require-staging require-promotion live-check restore-drill artifact-archive artifact-upload backup-upload test test-data clean seasons status lint format format-check docs typecheck check dagger-check api

# Configuration
SEASON ?= 2025-26
TARGET ?=
CONFIRM_SEASON ?=
CONFIRM_SINGLE_SEASON ?=
BACKUP_FILE ?=
API_URL ?=
STAGING_API_URL ?=
RESTORE_CONFIRM ?=
ARTIFACT_DIR ?=

# Default target
help:
	@echo "NBA Database - Available Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install     - Install Python dependencies"
	@echo "  make hooks-install - Install selective pre-commit and pre-push hooks"
	@echo "  make hooks-run   - Run every lightweight pre-commit hook"
	@echo ""
	@echo "Database:"
	@echo "  make db-start    - Start PostgreSQL container"
	@echo "  make db-stop     - Stop PostgreSQL container"
	@echo "  make db-reset    - Reset database (destroy and recreate)"
	@echo "  make db-shell    - Open psql shell"
	@echo "  make db-logs     - View database logs"
	@echo ""
	@echo "Season Lifecycle (default: SEASON=2025-26):"
	@echo "  make season-build       - Extract, transform, cross-check, and write manifest"
	@echo "  make season-load-local  - Replace local DB with exactly the manifested season"
	@echo "  make season-stage       - Replace and smoke-test an isolated staging environment"
	@echo "  make season-promote     - Back up and replace production with typed confirmations"
	@echo "  make live-check         - Verify deployed health, provenance, and core reads"
	@echo "  make restore-drill      - Restore and verify a backup in a disposable database"
	@echo "  make artifact-archive  - Package verified raw/clean data outside the repository"
	@echo "  make artifact-upload   - Package and upload verified data to S3-compatible storage"
	@echo "  make backup-upload     - Upload and checksum-verify a production backup"
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
	@echo "  make format-check - Verify ruff formatting"
	@echo "  make docs        - Validate Markdown and local links"
	@echo "  make typecheck   - Run mypy type checker"
	@echo "  make check       - Run native formatting, lint, docs, and type checks"
	@echo "  make dagger-check - Run the complete portable Dagger pipeline"
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

hooks-install:
	uv run pre-commit install --hook-type pre-commit --hook-type pre-push

hooks-run:
	uv run pre-commit run --all-files

pre-push:
	uv run python scripts/ci_impact.py pre-push

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
	@uv run python -m etl.season_lifecycle validate-season --season "$(SEASON)"

require-staging: require-season
	@test "$(TARGET)" = "staging" || (echo "ERROR: set TARGET=staging" && exit 2)
	@test "$(CONFIRM_SEASON)" = "$(SEASON)" || (echo "ERROR: type CONFIRM_SEASON=$(SEASON)" && exit 2)
	@test -n "$(strip $(STAGING_API_URL))" || (echo "ERROR: set STAGING_API_URL to the staging HTTPS URL" && exit 2)
	@test "$(origin STAGING_DATABASE_URL)" != "command line" || (echo "ERROR: export STAGING_DATABASE_URL; do not pass it as a make argument" && exit 2)
	@test -n "$$STAGING_DATABASE_URL" || (echo "ERROR: export STAGING_DATABASE_URL in the environment" && exit 2)

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

season-stage: require-staging
	uv run python -m etl.season_lifecycle stage \
		--season "$(SEASON)" \
		--target "$(TARGET)" \
		--confirm-season "$(CONFIRM_SEASON)" \
		--api-url "$(STAGING_API_URL)"

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

live-check: require-season
	uv run python scripts/check_live.py --season "$(SEASON)" --api-url "$(API_URL)"

restore-drill: require-season
	@test -n "$(strip $(BACKUP_FILE))" || (echo "ERROR: set BACKUP_FILE to the archive to test" && exit 2)
	@test -n "$(strip $(RESTORE_CONFIRM))" || (echo "ERROR: type RESTORE_CONFIRM='RESTORE <name>_recovery'" && exit 2)
	@test "$(origin RECOVERY_DATABASE_URL)" != "command line" || (echo "ERROR: export RECOVERY_DATABASE_URL; do not pass it as a make argument" && exit 2)
	@test -n "$$RECOVERY_DATABASE_URL" || (echo "ERROR: export RECOVERY_DATABASE_URL" && exit 2)
	uv run python scripts/restore_drill.py --season "$(SEASON)" --backup-file "$(BACKUP_FILE)" --confirm "$(RESTORE_CONFIRM)"

artifact-archive: require-season
	@test -n "$(strip $(ARTIFACT_DIR))" || (echo "ERROR: set ARTIFACT_DIR outside the repository" && exit 2)
	uv run python scripts/archive_dataset.py --season "$(SEASON)" --output-dir "$(ARTIFACT_DIR)"

artifact-upload: require-season
	@test -n "$(strip $(ARTIFACT_DIR))" || (echo "ERROR: set ARTIFACT_DIR outside the repository" && exit 2)
	uv run --extra ops python scripts/archive_dataset.py --season "$(SEASON)" --output-dir "$(ARTIFACT_DIR)" --upload

backup-upload: require-season
	@test -n "$(strip $(BACKUP_FILE))" || (echo "ERROR: set BACKUP_FILE to a protected .dump path" && exit 2)
	uv run --extra ops python scripts/upload_backup.py --season "$(SEASON)" --backup-file "$(BACKUP_FILE)"

# Info commands
seasons:
	@docker compose exec db psql -U nba_user -d nba_db -c "SELECT id AS season, games_count, players_count, loaded_at FROM seasons ORDER BY id DESC;" 2>/dev/null || echo "Database not running"

# Testing & Quality
test:
	PYTHONPATH=. uv run pytest tests/ -v

test-data:
	PYTHONPATH=. uv run python db/tests/test_data_quality.py

lint:
	uv run ruff check etl/ app/ db/ scripts/ tests/ .dagger/src/ nba_config.py

format:
	uv run ruff format etl/ app/ db/ scripts/ tests/ .dagger/src/ nba_config.py
	uv run ruff check --fix etl/ app/ db/ scripts/ tests/ .dagger/src/ nba_config.py

format-check:
	uv run ruff format --check etl/ app/ db/ scripts/ tests/ .dagger/src/ nba_config.py

docs:
	uv run python scripts/check_docs.py

typecheck:
	uv run mypy etl/ app/ db/ scripts/ nba_config.py

# API
api:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

check: format-check lint docs typecheck
	@echo "All checks passed!"

dagger-check:
	dagger call full --source=.

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
	@docker compose exec db psql -U nba_user -d nba_db -c "SELECT 'teams' AS table_name, COUNT(*) AS count FROM teams UNION ALL SELECT 'players', COUNT(*) FROM players UNION ALL SELECT 'games', COUNT(*) FROM games UNION ALL SELECT 'player_game_stats', COUNT(*) FROM player_game_stats UNION ALL SELECT 'team_game_stats', COUNT(*) FROM team_game_stats UNION ALL SELECT 'shot_attempts', COUNT(*) FROM shot_attempts;" 2>/dev/null || echo "Database not running"
