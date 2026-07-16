# Public Read-Only Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all unauthenticated write/admin capability (data entry, ETL trigger, SQL query demo) from the deployed app, fix Postgres-migration regressions, add a read-only DB role, add an API test suite wired into CI, and rewrite the README.

**Architecture:** FastAPI app (`app/main.py`) serving a single-page UI (`app/templates/index.html`) over PostgreSQL via a psycopg connection pool (`app/db.py`, `db/config.py`). Schema is applied idempotently at deploy by `scripts/init_db.py` (Railway `startCommand`). Tests run against a dedicated `nba_db_test` database created by `tests/conftest.py`.

**Tech Stack:** Python 3.11, FastAPI, psycopg 3 + psycopg-pool, PostgreSQL 16 (Docker locally, Railway in prod), uv, pytest + httpx (new, dev-only), ruff, mypy, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-07-15-public-readonly-cleanup-design.md`

## Global Constraints

- Python `>=3.11`; package manager is `uv` (run everything as `uv run ...`).
- New dependencies allowed only in the `dev` group: `pytest`, `httpx`. No new runtime dependencies.
- All SQL uses psycopg parameter binding (`%s`); never interpolate user input.
- Ruff config: line-length 100, double quotes. `make check` (ruff + mypy) must pass at the end of every task.
- Running tests locally requires the Docker Postgres: `make db-start` first. Tests use a separate database `nba_db_test` — they never touch `nba_db`.
- Do not modify `db/schema/*.sql`, the ETL scripts, or `db/tests/test_data_quality.py`.
- Read-only role name is exactly `nba_readonly`; env var name is exactly `READONLY_DB_PASSWORD`.
- Live deployment URL (for README): `https://nba-api-production-0cd7.up.railway.app`

---

### Task 1: Test infrastructure (pytest + test database + seed data)

**Files:**
- Modify: `pyproject.toml` (dev deps via `uv add`, ruff per-file ignore)
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`
- Create: `tests/test_api.py` (health test only in this task)

**Interfaces:**
- Produces: session-scoped pytest fixture `client` (a `fastapi.testclient.TestClient` bound to the app, pointed at seeded `nba_db_test`), and seed constants importable as `from tests.conftest import LAKERS, CELTICS, LEBRON, TATUM, JORDAN, SEED_SEASON`. Seed contents: 2 teams (Lakers `1610612747`, Celtics `1610612738`), 3 players (LeBron `2544` active, Tatum `1628369` active, Jordan `893` inactive), season `2024-25`, 10 games (`0022400001`…`0022400010`, Lakers home, all 110–100 Lakers wins), team stats for both teams in every game, LeBron with 30 points in all 10 games, Tatum with 25 points in games 1–5 only.
- Consumes: `scripts/init_db.py` `main()` (existing), `db.config.get_db_config()` (existing).

- [ ] **Step 1: Add dev dependencies**

Run:
```bash
uv add --dev pytest httpx
```
Expected: `pyproject.toml` dev group gains `pytest` and `httpx`; `uv.lock` updated.

- [ ] **Step 2: Allow late imports in conftest**

In `pyproject.toml`, under `[tool.ruff.lint.per-file-ignores]`, add:

```toml
"tests/conftest.py" = ["E402"]
```

- [ ] **Step 3: Create the test package and conftest**

Create empty `tests/__init__.py`, then create `tests/conftest.py`:

```python
"""Shared fixtures: dedicated test database (nba_db_test) with seed data."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Point the app at the test database BEFORE any app/db imports.
# load_dotenv() does not override already-set environment variables.
os.environ.pop("DATABASE_URL", None)
os.environ["DB_NAME"] = "nba_db_test"

import psycopg
import pytest
from fastapi.testclient import TestClient

import init_db  # scripts/init_db.py (via sys.path above)
from db.config import get_db_config

SEED_SEASON = "2024-25"
LAKERS = 1610612747
CELTICS = 1610612738
LEBRON = 2544
TATUM = 1628369
JORDAN = 893


def _connect_admin() -> psycopg.Connection:
    """Connect to the maintenance database to create/drop the test DB."""
    config = get_db_config() | {"dbname": "postgres"}
    return psycopg.connect(**config, autocommit=True)


def _seed(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO teams (id, full_name, abbreviation, nickname, city, state, year_founded)"
            " VALUES (%s, 'Los Angeles Lakers', 'LAL', 'Lakers', 'Los Angeles', 'California', 1948),"
            " (%s, 'Boston Celtics', 'BOS', 'Celtics', 'Boston', 'Massachusetts', 1946)",
            (LAKERS, CELTICS),
        )
        cur.execute(
            "INSERT INTO players (id, full_name, first_name, last_name, is_active)"
            " VALUES (%s, 'LeBron James', 'LeBron', 'James', TRUE),"
            " (%s, 'Jayson Tatum', 'Jayson', 'Tatum', TRUE),"
            " (%s, 'Michael Jordan', 'Michael', 'Jordan', FALSE)",
            (LEBRON, TATUM, JORDAN),
        )
        cur.execute(
            "INSERT INTO seasons (id, start_year, end_year, games_count, players_count)"
            " VALUES (%s, 2024, 2025, 10, 3)",
            (SEED_SEASON,),
        )
        for i in range(1, 11):
            game_id = f"00224000{i:02d}"
            cur.execute(
                "INSERT INTO games (id, game_date, season, home_team_id, away_team_id,"
                " home_score, away_score) VALUES (%s, %s, %s, %s, %s, 110, 100)",
                (game_id, f"2024-11-{i:02d}", SEED_SEASON, LAKERS, CELTICS),
            )
            for team_id, is_home, points in ((LAKERS, True, 110), (CELTICS, False, 100)):
                cur.execute(
                    "INSERT INTO team_game_stats (game_id, team_id, season, is_home, points,"
                    " rebounds, assists, fgm, fga, fg3m, fg3a, ftm, fta)"
                    " VALUES (%s, %s, %s, %s, %s, 45, 25, 40, 90, 12, 35, 18, 22)",
                    (game_id, team_id, SEED_SEASON, is_home, points),
                )
            # LeBron plays all 10 games: qualifies for leaders (HAVING COUNT(*) >= 10).
            cur.execute(
                "INSERT INTO player_game_stats (game_id, player_id, team_id, season, minutes,"
                " points, rebounds, assists, fgm, fga, fg3m, fg3a, ftm, fta)"
                " VALUES (%s, %s, %s, %s, 36.5, 30, 8, 9, 12, 20, 2, 6, 4, 5)",
                (game_id, LEBRON, LAKERS, SEED_SEASON),
            )
            # Tatum plays only games 1-5: below the leaders threshold.
            if i <= 5:
                cur.execute(
                    "INSERT INTO player_game_stats (game_id, player_id, team_id, season, minutes,"
                    " points, rebounds, assists, fgm, fga, fg3m, fg3a, ftm, fta)"
                    " VALUES (%s, %s, %s, %s, 34.0, 25, 7, 4, 9, 19, 3, 8, 4, 4)",
                    (game_id, TATUM, CELTICS, SEED_SEASON),
                )
    conn.commit()


@pytest.fixture(scope="session")
def client():
    with _connect_admin() as admin:
        admin.execute("DROP DATABASE IF EXISTS nba_db_test")
        admin.execute("CREATE DATABASE nba_db_test")

    init_db.main()  # applies db/schema/*.sql to nba_db_test

    with psycopg.connect(**get_db_config()) as conn:
        _seed(conn)

    from app.db import close_pool
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client

    close_pool()
```

- [ ] **Step 4: Write the first test (health check)**

Create `tests/test_api.py`:

```python
"""API tests against the seeded nba_db_test database."""


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy", "database": "connected"}
```

- [ ] **Step 5: Run the test**

Run (Postgres must be up: `make db-start`):
```bash
uv run pytest tests/ -v
```
Expected: `test_health PASSED` (1 passed).

- [ ] **Step 6: Run checks**

Run: `make check`
Expected: ruff and mypy pass (note: lint/typecheck currently scan `etl/ app/ db/` only; Task 6 adds `tests/` to lint).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock tests/
git commit -m "test: add pytest infrastructure with dedicated test database"
```

---

### Task 2: Remove admin endpoints, dead files, and unused models

**Files:**
- Modify: `app/main.py` (delete lines 150-165 POST /api/players, 263-297 POST /api/games, 433-484 POST /api/player-game-stats, 577-758 ETL + Query sections; trim imports)
- Modify: `app/models.py` (delete lines 183-227: `PlayerCreate`, `GameCreate`, `PlayerGameStatsCreate` and the "Input Models for Data Entry" header)
- Delete: `app/routes.py`, `db-project-rubric.pdf`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `client` fixture from Task 1.
- Produces: `app/main.py` exposes ONLY these routes afterward: `GET /`, `GET /health`, `GET /api/seasons`, `GET /api/teams`, `GET /api/teams/{team_id}`, `GET /api/players`, `GET /api/players/{player_id}`, `GET /api/players/{player_id}/stats`, `GET /api/games`, `GET /api/games/{game_id}`, `GET /api/games/{game_id}/boxscore`, `GET /api/team-game-stats`, `GET /api/player-game-stats`, `GET /api/leaders/{stat}`, `GET /api/standings`. Later tasks (UI, README) rely on exactly this list.

- [ ] **Step 1: Write failing guard tests**

Append to `tests/test_api.py`:

```python
class TestAdminEndpointsRemoved:
    """The public app must expose no write or SQL-execution capability."""

    def test_query_endpoint_removed(self, client):
        r = client.post("/api/query", json={"query": "SELECT 1"})
        assert r.status_code == 404

    def test_etl_endpoint_removed(self, client):
        r = client.post("/api/etl", json={"seasons": ["2024-25"]})
        assert r.status_code == 404

    def test_create_player_removed(self, client):
        r = client.post("/api/players", json={"id": 999999, "full_name": "Nobody"})
        assert r.status_code == 405  # GET /api/players still exists

    def test_create_game_removed(self, client):
        r = client.post("/api/games", json={})
        assert r.status_code == 405  # GET /api/games still exists

    def test_create_player_game_stats_removed(self, client):
        r = client.post("/api/player-game-stats", json={})
        assert r.status_code == 405  # GET /api/player-game-stats still exists
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py -v -k Removed`
Expected: all 5 FAIL (endpoints currently return 200/400/422, not 404/405).

- [ ] **Step 3: Delete the endpoints and helpers from `app/main.py`**

Delete these blocks (identified by their current content, not line numbers, since earlier deletions shift lines):
1. The whole `@app.post("/api/players", ...)` endpoint (`create_player`).
2. The whole `@app.post("/api/games", ...)` endpoint (`create_game`).
3. The whole `@app.post("/api/player-game-stats", ...)` endpoint (`create_player_game_stats`).
4. Everything from the `# === ETL Pipeline ===` comment through the end of the file: `ETLRequest`, `ETLSeasonResult`, `ETLResponse`, `PROJECT_ROOT`, `run_etl_step`, `run_etl_pipeline`, the `# === Query Demo ===` section, `QueryRequest`, `QueryResponse`, `execute_query`.

Then fix imports at the top of the file:
- Remove `import subprocess` and `import sys`.
- Remove `from pydantic import BaseModel` (only the deleted request models used it).
- From the `app.models` import block remove: `GameCreate`, `PlayerCreate`, `PlayerGameStatsCreate`.
- Keep `Path` (used by `TEMPLATES_DIR`) and `Literal` (used by `StatCategory`).

- [ ] **Step 4: Delete the unused input models from `app/models.py`**

Delete everything from the `# === Input Models for Data Entry ===` comment to the end of the file (`PlayerCreate`, `GameCreate`, `PlayerGameStatsCreate`).

- [ ] **Step 5: Delete dead files**

```bash
git rm app/routes.py db-project-rubric.pdf
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: all tests PASS (health + 5 guard tests).

- [ ] **Step 7: Run checks**

Run: `make check`
Expected: PASS (this also proves no dangling imports/references).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: remove unauthenticated write/ETL/SQL endpoints and dead files"
```

---

### Task 3: Case-insensitive player search (ILIKE)

**Files:**
- Modify: `app/main.py` (the `list_players` endpoint, search condition)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `client` fixture; seed player "LeBron James" from Task 1.
- Produces: `GET /api/players?search=` matches case-insensitively.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api.py`:

```python
def test_player_search_is_case_insensitive(client):
    r = client.get("/api/players", params={"search": "lebron"})
    assert r.status_code == 200
    names = [p["full_name"] for p in r.json()["data"]]
    assert names == ["LeBron James"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py::test_player_search_is_case_insensitive -v`
Expected: FAIL — Postgres `LIKE` is case-sensitive, so `names == []`.

- [ ] **Step 3: Fix the query**

In `app/main.py` `list_players`, change:

```python
            conditions.append("full_name LIKE %s")
```
to:
```python
            conditions.append("full_name ILIKE %s")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_api.py
git commit -m "fix: use ILIKE for case-insensitive player search on Postgres"
```

---

### Task 4: Read-endpoint test coverage

**Files:**
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `client` fixture and seed constants (`from tests.conftest import LAKERS, CELTICS, LEBRON, TATUM, JORDAN, SEED_SEASON`). Seed facts used below: Boston Celtics sorts before Los Angeles Lakers; LeBron averages exactly 30.0 ppg over 10 games; Tatum has 5 games (under the 10-game leaders threshold); Lakers are 10-0.
- Produces: regression coverage for every public GET endpoint; no new app code.

- [ ] **Step 1: Write the coverage tests**

Append to `tests/test_api.py`:

```python
from tests.conftest import CELTICS, JORDAN, LAKERS, LEBRON, SEED_SEASON, TATUM


def test_home_page_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<html" in r.text.lower()


def test_list_seasons(client):
    r = client.get("/api/seasons")
    assert r.status_code == 200
    assert [s["id"] for s in r.json()] == [SEED_SEASON]


def test_list_teams_sorted_by_name(client):
    r = client.get("/api/teams")
    assert r.status_code == 200
    assert [t["id"] for t in r.json()] == [CELTICS, LAKERS]


def test_get_team(client):
    r = client.get(f"/api/teams/{LAKERS}")
    assert r.status_code == 200
    assert r.json()["abbreviation"] == "LAL"


def test_get_team_not_found(client):
    assert client.get("/api/teams/1").status_code == 404


def test_list_players_active_filter(client):
    r = client.get("/api/players", params={"active": "false"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["data"][0]["id"] == JORDAN


def test_list_players_pagination(client):
    r = client.get("/api/players", params={"limit": 2, "offset": 0})
    body = r.json()
    assert body["total"] == 3
    assert len(body["data"]) == 2


def test_get_player_not_found(client):
    assert client.get("/api/players/1").status_code == 404


def test_player_season_averages(client):
    r = client.get(f"/api/players/{LEBRON}/stats")
    assert r.status_code == 200
    (row,) = r.json()
    assert row["season"] == SEED_SEASON
    assert row["games_played"] == 10
    assert row["ppg"] == 30.0


def test_player_stats_not_found(client):
    assert client.get("/api/players/1/stats").status_code == 404


def test_list_games_filtered_by_season_and_team(client):
    r = client.get("/api/games", params={"season": SEED_SEASON, "team_id": LAKERS})
    body = r.json()
    assert body["total"] == 10
    assert all(g["home_team"] == "Los Angeles Lakers" for g in body["data"])


def test_get_game(client):
    r = client.get("/api/games/0022400001")
    assert r.status_code == 200
    body = r.json()
    assert body["home_score"] == 110
    assert body["away_team"] == "Boston Celtics"


def test_get_game_not_found(client):
    assert client.get("/api/games/nope").status_code == 404


def test_boxscore(client):
    r = client.get("/api/games/0022400001/boxscore")
    assert r.status_code == 200
    body = r.json()
    assert [p["player_id"] for p in body["home_players"]] == [LEBRON]
    assert [p["player_id"] for p in body["away_players"]] == [TATUM]
    assert body["home_team_stats"]["points"] == 110
    assert body["away_team_stats"]["points"] == 100


def test_list_team_game_stats(client):
    r = client.get(
        "/api/team-game-stats", params={"season": SEED_SEASON, "team_id": CELTICS}
    )
    body = r.json()
    assert body["total"] == 10
    assert all(s["team_abbr"] == "BOS" for s in body["data"])


def test_list_player_game_stats(client):
    r = client.get(
        "/api/player-game-stats", params={"season": SEED_SEASON, "player_id": TATUM}
    )
    body = r.json()
    assert body["total"] == 5


def test_leaders_respects_min_games_threshold(client):
    r = client.get("/api/leaders/points", params={"season": SEED_SEASON})
    assert r.status_code == 200
    leaders = r.json()["data"]
    assert [(leader["player_id"], leader["value"]) for leader in leaders] == [(LEBRON, 30.0)]


def test_leaders_rejects_unknown_stat(client):
    r = client.get("/api/leaders/dunks", params={"season": SEED_SEASON})
    assert r.status_code == 422


def test_standings(client):
    r = client.get("/api/standings", params={"season": SEED_SEASON})
    assert r.status_code == 200
    rows = r.json()
    assert [(t["team_id"], t["wins"], t["losses"]) for t in rows] == [
        (LAKERS, 10, 0),
        (CELTICS, 0, 10),
    ]
    assert rows[0]["win_pct"] == 1.0
```

- [ ] **Step 2: Run the suite**

Run: `uv run pytest tests/ -v`
Expected: all PASS. If any coverage test fails, the endpoint has a real bug — investigate before changing the test's expectation.

- [ ] **Step 3: Commit**

```bash
git add tests/test_api.py
git commit -m "test: cover all public read endpoints"
```

---

### Task 5: Remove Data Entry and SQL Demo from the UI

**Files:**
- Modify: `app/templates/index.html`

**Interfaces:**
- Consumes: route list from Task 2 (the UI may only call GET endpoints).
- Produces: UI with exactly four nav sections: Standings, Leaders, Games, Players.

No unit test covers the template's internals; verification is grep + manual smoke test (Step 5).

- [ ] **Step 1: Remove HTML**

In `app/templates/index.html` delete:
1. In `<nav>`: the two `<li>`/`<a>` blocks with `data-section="entry"` and `data-section="demo"` (currently around lines 1146–1157).
2. The entire `<section id="entry" class="section">…</section>` (the "Data Entry" section with the Add Player / Add Game / Add Player Stats / Load Season forms, currently around lines 1229–1487).
3. The entire `<section id="demo" class="section">…</section>` (the "SQL Query Demo" section, currently around lines 1490–1538).

- [ ] **Step 2: Remove JavaScript**

In the `<script>` block:
1. In `loadSection`, change the dispatch map from
   `({standings:loadStandings, leaders:loadLeaders, games:loadGames, players:loadPlayers, entry:loadEntry, demo:loadDemo})[s]();`
   to
   `({standings:loadStandings, leaders:loadLeaders, games:loadGames, players:loadPlayers})[s]();`
2. Delete everything from the `// === Entry Form Functions ===` comment through the end of `setSeasons` (functions: `loadEntry`, the four form `onsubmit` handlers inside it, `setSeasons`).
3. Delete the `// === Demo Tab Functions ===` block (functions: `loadDemo`, `runQuery`).
4. Delete `escapeHtml` ONLY if unused elsewhere — verify first with `grep -n 'escapeHtml' app/templates/index.html`; if the only remaining hits are its own definition, delete it.

- [ ] **Step 3: Remove CSS**

Delete the style rule blocks whose selectors match only removed markup. Before deleting each, confirm the class/id no longer appears in the HTML body (`grep -n '<selector-name>' app/templates/index.html` shows only the CSS definition):
`.entry-tabs`, `.entry-tab` (incl. `:hover`, `.active`), `.entry-form` (incl. `.active`), `.data-form` and its descendant rules, `.form-description`, `.form-message` (if only used by removed forms), `.btn-submit`, `.btn-reset` (if only used by removed forms), `.query-container`, `.query-input-area`, `#sql-query` (all three rules), `.query-actions`, `.query-hint`, `.query-examples`, `.example-btn` (incl. `:hover`), `.query-results` and all `.query-results *` rules, `.query-placeholder`, `.query-results-header`, `.query-results-info`, `.query-results-time`, and the `.entry-tabs` rule inside the responsive `@media` block.

- [ ] **Step 4: Grep for leftovers**

Run:
```bash
grep -n 'loadEntry\|loadDemo\|runQuery\|setSeasons\|entry-\|data-form\|sql-query\|example-btn\|api/query\|api/etl\|form-message' app/templates/index.html
```
Expected: no output. Any hit is an incomplete deletion — fix it.

- [ ] **Step 5: Smoke test in the browser**

Run: `make api`, open `http://localhost:8000`.
Expected: nav shows only Standings / Leaders / Games / Players; all four sections load data; player and game modals open; no console errors. Stop the server.

- [ ] **Step 6: Run the API suite (guards against accidental route changes)**

Run: `uv run pytest tests/ -v` and `make check`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add app/templates/index.html
git commit -m "feat: remove Data Entry and SQL Demo sections from the UI"
```

---

### Task 6: Read-only database role

**Files:**
- Modify: `scripts/init_db.py`
- Modify: `db/config.py`
- Modify: `app/db.py`
- Modify: `.env.example`
- Test: `tests/test_readonly_role.py` (create)

**Interfaces:**
- Consumes: `client` fixture (guarantees `nba_db_test` exists and is seeded).
- Produces:
  - `init_db.ensure_readonly_role(conn: psycopg.Connection) -> None` — idempotent; no-op when `READONLY_DB_PASSWORD` is unset.
  - `db.config.get_db_config(readonly: bool = False) -> dict[str, Any]` — with `readonly=True` and `READONLY_DB_PASSWORD` set, returns the same host/port/dbname but `user="nba_readonly"` and that password; otherwise identical to today.
  - `db.config.get_conninfo(readonly: bool = False) -> str` — same rule, string form.
  - `app/db.py` pool connects with `get_conninfo(readonly=True)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_readonly_role.py`:

```python
"""The nba_readonly role can SELECT but cannot write."""

import psycopg
import pytest
from psycopg.errors import InsufficientPrivilege

import init_db
from db.config import get_db_config


def test_readonly_role_can_select_but_not_insert(client, monkeypatch):
    monkeypatch.setenv("READONLY_DB_PASSWORD", "test-readonly-pw")

    conn = psycopg.connect(**get_db_config())
    try:
        init_db.ensure_readonly_role(conn)
        init_db.ensure_readonly_role(conn)  # idempotent: safe to run twice
    finally:
        conn.close()

    ro_config = get_db_config(readonly=True)
    assert ro_config["user"] == "nba_readonly"
    assert ro_config["dbname"] == "nba_db_test"

    with psycopg.connect(**ro_config) as ro_conn, ro_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM teams")
        assert cur.fetchone()[0] == 2
        with pytest.raises(InsufficientPrivilege):
            cur.execute("INSERT INTO players (id, full_name) VALUES (999, 'Nope')")


def test_config_ignores_readonly_flag_when_password_unset(client, monkeypatch):
    monkeypatch.delenv("READONLY_DB_PASSWORD", raising=False)
    config = get_db_config(readonly=True)
    assert config["user"] != "nba_readonly"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_readonly_role.py -v`
Expected: FAIL with `AttributeError: module 'init_db' has no attribute 'ensure_readonly_role'` (first test) and `TypeError: get_db_config() got an unexpected keyword argument 'readonly'` (second test).

- [ ] **Step 3: Implement `ensure_readonly_role` and restructure `init_db` main**

In `scripts/init_db.py`:

Add `import os` at the top and `from psycopg import sql` below the `import psycopg` line.

Change `apply_schema()` to accept the connection instead of creating one, and always run the role setup from `main()`:

```python
def apply_schema(conn: psycopg.Connection) -> None:
    sql_files = sorted(SCHEMA_DIR.glob("*.sql"))
    if not sql_files:
        raise FileNotFoundError(f"No SQL files found in {SCHEMA_DIR}")

    with conn.cursor() as cur:
        for sql_file in sql_files:
            print(f"Applying {sql_file.name}...")
            for statement in split_sql(sql_file.read_text()):
                cur.execute(statement)
    conn.commit()
    print("Schema initialized successfully.")


def ensure_readonly_role(conn: psycopg.Connection) -> None:
    """Create/refresh the SELECT-only role the web app connects as."""
    password = os.getenv("READONLY_DB_PASSWORD")
    if not password:
        print("READONLY_DB_PASSWORD not set, skipping read-only role setup.")
        return

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'nba_readonly'")
        action = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(
            sql.SQL("{} ROLE nba_readonly LOGIN PASSWORD {}").format(
                sql.SQL(action), sql.Literal(password)
            )
        )
        cur.execute("GRANT USAGE ON SCHEMA public TO nba_readonly")
        cur.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO nba_readonly")
        cur.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO nba_readonly"
        )
    conn.commit()
    print("Read-only role nba_readonly is configured.")


def main() -> None:
    conn = psycopg.connect(**get_db_config())
    try:
        if schema_is_initialized(conn):
            print("Schema already initialized, skipping.")
        else:
            apply_schema(conn)
        ensure_readonly_role(conn)
    finally:
        conn.close()
```

Delete the old `apply_schema` body that created its own connection and early-returned. `split_sql` and `schema_is_initialized` are unchanged.

- [ ] **Step 4: Implement the readonly config path**

In `db/config.py`, replace the two functions' signatures and add the override at the end of `get_db_config` (both the `DATABASE_URL` and `DB_*` branches must flow through it, so compute the base config first):

```python
def get_db_config(readonly: bool = False) -> dict[str, Any]:
    """Return PostgreSQL connection parameters.

    With readonly=True and READONLY_DB_PASSWORD set, connect as the
    SELECT-only nba_readonly role instead of the owner.
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        parsed = urlparse(database_url)
        config: dict[str, Any] = {
            "dbname": parsed.path.lstrip("/"),
            "user": parsed.username or "",
            "password": parsed.password or "",
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 5432,
        }
    else:
        config = {
            "dbname": os.getenv("DB_NAME", "nba_db"),
            "user": os.getenv("DB_USER", "nba_user"),
            "password": os.getenv("DB_PASSWORD", "nba_password"),
            "host": os.getenv("DB_HOST", "localhost"),
            "port": int(os.getenv("DB_PORT", "5432")),
        }

    if readonly:
        ro_password = os.getenv("READONLY_DB_PASSWORD")
        if ro_password:
            config["user"] = "nba_readonly"
            config["password"] = ro_password

    return config


def get_conninfo(readonly: bool = False) -> str:
    """Return a PostgreSQL connection string."""
    config = get_db_config(readonly=readonly)
    return (
        f"dbname={config['dbname']} "
        f"user={config['user']} "
        f"password={config['password']} "
        f"host={config['host']} "
        f"port={config['port']}"
    )
```

In `app/db.py` `get_pool`, change `conninfo=get_conninfo(),` to `conninfo=get_conninfo(readonly=True),`.

- [ ] **Step 5: Document the variable**

Append to `.env.example`:

```bash

# Optional: when set, scripts/init_db.py creates a SELECT-only role `nba_readonly`
# with this password, and the web app connects as that role instead of the owner.
# READONLY_DB_PASSWORD=change-me
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: all PASS (including the full API suite — the app pool falls back to owner creds because `READONLY_DB_PASSWORD` is unset in the test session's app fixture).

- [ ] **Step 7: Run checks**

Run: `make check`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/init_db.py db/config.py app/db.py .env.example tests/test_readonly_role.py
git commit -m "feat: add SELECT-only nba_readonly role for the web app"
```

---

### Task 7: Wire tests into CI and the Makefile

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `Makefile` (`test` target, new `test-data` target, help text, lint targets)

**Interfaces:**
- Consumes: test suite from Tasks 1–6 (needs a Postgres reachable at `localhost:5432` with user `nba_user`/`nba_password`).
- Produces: `make test` = pytest suite; `make test-data` = existing data-quality script; CI runs lint, typecheck, pytest.

- [ ] **Step 1: Update the Makefile**

Replace the `test` target and add `test-data`:

```makefile
test:
	PYTHONPATH=. uv run pytest tests/ -v

test-data:
	PYTHONPATH=. uv run python db/tests/test_data_quality.py
```

Add `tests/` to the lint/format targets (leave `typecheck` scope unchanged):

```makefile
lint:
	uv run ruff check etl/ app/ db/ tests/

format:
	uv run ruff format etl/ app/ db/ tests/
	uv run ruff check --fix etl/ app/ db/ tests/
```

In the `help` target, change the testing lines to:

```makefile
	@echo "  make test        - Run API test suite (requires make db-start)"
	@echo "  make test-data   - Run data quality tests (requires loaded data)"
```

Add `test-data` to the `.PHONY` line.

- [ ] **Step 2: Update CI**

Replace `.github/workflows/ci.yml` with:

```yaml
name: CI

on:
  push:
    branches: [main, master]
  pull_request:

jobs:
  quality:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: nba_user
          POSTGRES_PASSWORD: nba_password
          POSTGRES_DB: nba_db
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: uv sync

      - name: Lint
        run: uv run ruff check etl/ app/ db/ tests/

      - name: Typecheck
        run: uv run mypy etl/ app/ db/

      - name: Test
        env:
          DB_HOST: localhost
          DB_PORT: "5432"
          DB_USER: nba_user
          DB_PASSWORD: nba_password
        run: uv run pytest tests/ -v
```

- [ ] **Step 3: Verify locally**

Run: `make test` and `make check`
Expected: all PASS.

- [ ] **Step 4: Commit and verify CI**

```bash
git add Makefile .github/workflows/ci.yml
git commit -m "ci: run API test suite against a Postgres service container"
git push
gh run watch --exit-status $(gh run list --branch main --limit 1 --json databaseId --jq '.[0].databaseId')
```
Expected: CI run completes green. If the test job fails in CI but passed locally, read the job log (`gh run view --log-failed`) before changing anything.

---

### Task 8: README rewrite

**Files:**
- Modify: `README.md` (full replacement)

**Interfaces:**
- Consumes: route list from Task 2; role/env behavior from Task 6; Make targets from Task 7; live URL `https://nba-api-production-0cd7.up.railway.app`.
- Produces: README describing the deployed read-only app. Note: the old README documented audit triggers, a `shots` table, and shot-chart endpoints that do not exist in the Postgres schema — they must NOT reappear.

- [ ] **Step 1: Replace README.md with:**

````markdown
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

The deployed app is read-only; data is loaded by pointing the ETL at the production database from a trusted machine:

```bash
DATABASE_URL="postgresql://user:pass@host:port/dbname" make load SEASON=2024-25
```

(`extract` and `transform` only touch local files; only `load` needs the production `DATABASE_URL`.)

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

- [ ] Scheduled data refresh (Railway cron)
- [ ] Shot chart data and visualizations
- [ ] Historical season backfill

## License

MIT
````

- [ ] **Step 2: Verify claims against the code**

Run:
```bash
grep -n '@app.get\|@app.post' app/main.py
```
Expected: only `@app.get` decorators, matching the README endpoint table exactly (15 routes including `/` and `/health`).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for the deployed read-only app"
```

---

### Post-plan operator steps (not code — do interactively with the user)

1. Push to `main`; confirm CI green and Railway redeploys successfully (`/health` returns healthy).
2. Set `READONLY_DB_PASSWORD` on the Railway service (generate a strong password); redeploy; confirm the app still serves data and `POST`-based endpoints are gone in production.
3. Optional follow-up (out of scope): Railway cron for scheduled ETL refresh.
