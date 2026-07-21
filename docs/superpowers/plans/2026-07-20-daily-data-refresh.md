# Daily Data Refresh Implementation Plan

**Status:** Superseded on 2026-07-21

> **Historical plan — do not execute its unchecked steps or rollout commands.** The GitHub-hosted production refresh was removed after `stats.nba.com` blocked hosted-runner traffic. CI/CD must not receive production write credentials. The supported trusted-machine workflow is documented in README and uses the guarded season build, local-load, and promote commands. Production credentials must be supplied through the documented environment mechanism, never in command-line arguments or GitHub Actions.

**Historical goal:** Add a GitHub Actions daily cron that refreshes the current NBA season's data into the Railway Postgres, plus the ETL/CLI support it needs, and use its manual trigger to load the missing 2025-26 season.

**Historical architecture:** Three small additions to the existing ETL: a `--force` flag on `etl/extract.py` (re-download instead of skip), a pure-function season calculator (`scripts/current_season.py`), and a legacy `make refresh` target chaining extract-force → transform → load. The first two remain useful building blocks. The direct-load target is not the supported production entry point, and the proposed GitHub-hosted loader was removed.

**Tech Stack:** Python 3.11, uv, nba_api, GitHub Actions, PostgreSQL on Railway.

**Spec:** `docs/superpowers/specs/2026-07-20-daily-data-refresh-design.md`

## Global Constraints

- Work on branch `data-refresh` (main auto-deploys to Railway with "Wait for CI" — never commit this work directly to main).
- Package manager is `uv`; run everything as `uv run ...`.
- No new dependencies (runtime or dev). No third-party GitHub Actions beyond the four already in use (`actions/checkout@v4`, `astral-sh/setup-uv@v5`, `actions/setup-python@v5`) — the extract retry is a shell loop, not a marketplace action.
- `make check` (ruff + mypy) and the full pytest suite must pass at the end of every task.
- Local pytest quirk on this machine: prefix with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. Local Docker Postgres (`make db-start`, idempotent) is required for the existing suite; the new season tests themselves need no DB.
- Do not modify `etl/transform.py`, `etl/load.py`, `db/schema/*.sql`, or `app/`.
- Season string format is exactly `YYYY-YY` (e.g. `2026-27`). The historical cron time was `0 10 * * *`; no repository refresh cron remains.
- Historical constraint (no longer valid): the proposal used a GitHub Actions `DATABASE_URL` secret. Do not create or use such a production-writing CI secret.

---

### Task 1: Season calculator (`scripts/current_season.py`)

**Files:**
- Create: `scripts/current_season.py`
- Test: `tests/test_current_season.py` (create)

**Interfaces:**
- Produces: `current_season(today: datetime.date) -> str` returning `YYYY-YY`; module runnable as a script printing the season for today. Operators can use it to identify a season before running an explicit local refresh.
- Consumes: nothing from other tasks. `tests/conftest.py` already puts `scripts/` on `sys.path` (that's how `import current_season` resolves under pytest).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_current_season.py`:

```python
"""Season-string date math for the scheduled refresh."""

import datetime

from current_season import current_season


def test_october_starts_new_season():
    assert current_season(datetime.date(2026, 10, 1)) == "2026-27"


def test_december_is_same_season():
    assert current_season(datetime.date(2026, 12, 31)) == "2026-27"


def test_january_belongs_to_prior_year_season():
    assert current_season(datetime.date(2027, 1, 1)) == "2026-27"


def test_june_finals_still_prior_year_season():
    assert current_season(datetime.date(2027, 6, 15)) == "2026-27"


def test_offseason_maps_to_completed_season():
    assert current_season(datetime.date(2026, 7, 20)) == "2025-26"


def test_september_is_still_prior_season():
    assert current_season(datetime.date(2026, 9, 30)) == "2025-26"


def test_century_boundary_formatting():
    assert current_season(datetime.date(1999, 11, 1)) == "1999-00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest tests/test_current_season.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'current_season'`.

- [ ] **Step 3: Write the implementation**

Create `scripts/current_season.py`:

```python
#!/usr/bin/env python3
"""Print the current NBA season string (e.g. 2026-27).

October-December belong to the season starting that year;
January-September belong to the season that started the prior year.
"""

import datetime


def current_season(today: datetime.date) -> str:
    start_year = today.year if today.month >= 10 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


if __name__ == "__main__":
    print(current_season(datetime.date.today()))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest tests/test_current_season.py -v`
Expected: 7 passed.

- [ ] **Step 5: Verify the script entrypoint**

Run: `uv run python scripts/current_season.py`
Expected: `2025-26` (today is 2026-07-20 — off-season maps to the completed season).

- [ ] **Step 6: Full suite + checks**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest tests/ -q` then `make check`
Expected: 35 passed (28 existing + 7 new); all checks pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/current_season.py tests/test_current_season.py
git commit -m "feat: add current-season calculator for scheduled refresh"
```

---

### Task 2: `--force` flag on extract + `make refresh` target

**Files:**
- Modify: `etl/extract.py`
- Modify: `Makefile`

**Interfaces:**
- Historical output: `--force` re-downloads files even when present, and the legacy Make target chained extract, transform, and load. Production operation now uses README's guarded workflow.
- Consumes: nothing from Task 1.

No pytest coverage for extract (it is network-bound and deliberately untested); Step 3 verifies the flag by observing skip behavior on local files.

- [ ] **Step 1: Add the flag and thread it through `etl/extract.py`**

Change the three download functions to accept and honor `force` (each currently has an `if os.path.exists(filepath): ... skip` guard; `download_league_game_log` uses `continue` inside its loop):

```python
def download_teams(force=False):
    """Download static team data."""
    print("\n=== Teams ===")
    shared_dir = get_shared_dir()
    ensure_dir(shared_dir)

    filepath = os.path.join(shared_dir, "teams.json")
    if os.path.exists(filepath) and not force:
        print("  Skipping (exists)")
        return

    data = teams.get_teams()
    save_json(data, filepath)
    print(f"  Found {len(data)} teams")
```

```python
def download_players(season, force=False):
```
with its guard changed to:
```python
    if os.path.exists(filepath) and not force:
        print("  Skipping (exists)")
        return
```

```python
def download_league_game_log(season, force=False):
```
with its per-file guard changed to:
```python
        if os.path.exists(filepath) and not force:
            print(f"  Skipping {label} (exists)")
            continue
```

In `main()`, add the argument and pass it through:

```python
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download files even if they already exist",
    )
```
```python
    download_teams(force=args.force)
    download_players(season, force=args.force)
    download_league_game_log(season, force=args.force)
```

- [ ] **Step 2: Add the legacy `refresh` target to `Makefile` (historical)**

The implementation directly chained extraction, transformation, and database loading, and advertised that target in Make help. The executable recipe is intentionally omitted here because it bypasses the guarded production workflow. It is retained only as implementation history; use README's build, local-load, and promote procedure instead.

- [ ] **Step 3: Verify skip vs force behavior without hitting the network**

The 2024-25 raw files exist locally, so the default path must skip (no network), and `--help` must show the flag:

Run: `uv run python etl/extract.py --season 2024-25 2>&1 | grep -c Skip`
Expected: `3` (teams, players, both game logs skip — game logs print one skip line each, so accept `3` or `4`; any non-zero count with no "Fetching" lines proves the guard still works).

Run: `uv run python etl/extract.py --help | grep force`
Expected: the `--force` help line.

Do NOT run with `--force` just to test it — that would hit the NBA API for no reason. It is exercised when a trusted operator intentionally refreshes one selected season.

- [ ] **Step 4: Full suite + checks**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest tests/ -q` then `make check`
Expected: 35 passed; all checks pass.

- [ ] **Step 5: Commit**

```bash
git add etl/extract.py Makefile
git commit -m "feat: add extract --force flag and make refresh target"
```

---

### Task 3: GitHub-hosted production refresh (superseded)

The original plan called for `.github/workflows/refresh-data.yml` to receive a production `DATABASE_URL`, fetch NBA data on a hosted runner, and write it to Railway. Hosted-runner access to `stats.nba.com` proved unreliable, and coupling CI/CD to production write credentials was unnecessary risk. That workflow has been removed.

Do not recreate the workflow, configure a production database secret in GitHub Actions, or follow historical dispatch or cron instructions from repository history.

### Supported replacement

README is the source of truth for the trusted-machine production workflow. It requires the guarded season build, local-load, and promote commands. Production credentials must be provided through README's documented environment mechanism—not command-line arguments or GitHub Actions. The legacy direct-load target and commands in repository history are not supported production procedures.

GitHub Actions runs validation only against its ephemeral PostgreSQL service and has no production write path.
