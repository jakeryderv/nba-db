# Daily Data Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GitHub Actions daily cron that refreshes the current NBA season's data into the Railway Postgres, plus the ETL/CLI support it needs, and use its manual trigger to load the missing 2025-26 season.

**Architecture:** Three small additions to the existing ETL: a `--force` flag on `etl/extract.py` (re-download instead of skip), a pure-function season calculator (`scripts/current_season.py`), and a `make refresh` target chaining extract-force → transform → load. A scheduled workflow (`.github/workflows/refresh-data.yml`) runs that chain daily against the Railway DB via a `DATABASE_URL` repo secret; `workflow_dispatch` with a `season` input doubles as the one-time 2025-26 loader.

**Tech Stack:** Python 3.11, uv, nba_api, GitHub Actions, PostgreSQL on Railway.

**Spec:** `docs/superpowers/specs/2026-07-20-daily-data-refresh-design.md`

## Global Constraints

- Work on branch `data-refresh` (main auto-deploys to Railway with "Wait for CI" — never commit this work directly to main).
- Package manager is `uv`; run everything as `uv run ...`.
- No new dependencies (runtime or dev). No third-party GitHub Actions beyond the four already in use (`actions/checkout@v4`, `astral-sh/setup-uv@v5`, `actions/setup-python@v5`) — the extract retry is a shell loop, not a marketplace action.
- `make check` (ruff + mypy) and the full pytest suite must pass at the end of every task.
- Local pytest quirk on this machine: prefix with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. Local Docker Postgres (`make db-start`, idempotent) is required for the existing suite; the new season tests themselves need no DB.
- Do not modify `etl/transform.py`, `etl/load.py`, `db/schema/*.sql`, or `app/`.
- Season string format is exactly `YYYY-YY` (e.g. `2026-27`). Cron time is exactly `0 10 * * *` (10:00 UTC).
- Secret name is exactly `DATABASE_URL` (GitHub Actions repo secret; value set by the operator in the rollout phase, not by any task).

---

### Task 1: Season calculator (`scripts/current_season.py`)

**Files:**
- Create: `scripts/current_season.py`
- Test: `tests/test_current_season.py` (create)

**Interfaces:**
- Produces: `current_season(today: datetime.date) -> str` returning `YYYY-YY`; module runnable as a script printing the season for today. Task 3's workflow calls `uv run python scripts/current_season.py`.
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
- Produces: `uv run python etl/extract.py --season X --force` re-downloads all files even when present; `make refresh SEASON=X` runs extract-force → transform → load. Task 3's workflow shells out to the three underlying commands directly (not via make), but must match these semantics.
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

- [ ] **Step 2: Add the `refresh` target to `Makefile`**

Add `refresh` to the `.PHONY` line, then add after the `etl` target:

```makefile
refresh:
	uv run python etl/extract.py --season $(SEASON) --force
	uv run python etl/transform.py --season $(SEASON)
	PYTHONPATH=. uv run python etl/load.py --season $(SEASON)
	@echo "Refresh complete for season $(SEASON)!"
```

In the `help` target's ETL section, add:

```makefile
	@echo "  make refresh     - Force re-download + reload one season (for data refresh)"
```

- [ ] **Step 3: Verify skip vs force behavior without hitting the network**

The 2024-25 raw files exist locally, so the default path must skip (no network), and `--help` must show the flag:

Run: `uv run python etl/extract.py --season 2024-25 2>&1 | grep -c Skip`
Expected: `3` (teams, players, both game logs skip — game logs print one skip line each, so accept `3` or `4`; any non-zero count with no "Fetching" lines proves the guard still works).

Run: `uv run python etl/extract.py --help | grep force`
Expected: the `--force` help line.

Do NOT run with `--force` here — that would hit the NBA API for no reason; the flag's logic is the one-line guard change verified by reading, and the workflow dispatch in the rollout phase exercises it for real.

- [ ] **Step 4: Full suite + checks**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest tests/ -q` then `make check`
Expected: 35 passed; all checks pass.

- [ ] **Step 5: Commit**

```bash
git add etl/extract.py Makefile
git commit -m "feat: add extract --force flag and make refresh target"
```

---

### Task 3: Scheduled refresh workflow + README note

**Files:**
- Create: `.github/workflows/refresh-data.yml`
- Modify: `README.md` (the "Loading data into production" section)

**Interfaces:**
- Consumes: `scripts/current_season.py` (Task 1, run as a script) and `etl/extract.py --force` (Task 2). Secret `DATABASE_URL` (set by the operator later; the workflow only references it).
- Produces: workflow `Refresh Data` with `schedule` (`0 10 * * *`) and `workflow_dispatch` (optional `season` string input).

- [ ] **Step 1: Create `.github/workflows/refresh-data.yml`**

```yaml
name: Refresh Data

on:
  schedule:
    - cron: "0 10 * * *"
  workflow_dispatch:
    inputs:
      season:
        description: "Season to refresh (e.g. 2025-26). Defaults to the current season."
        required: false
        type: string

jobs:
  refresh:
    runs-on: ubuntu-latest
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

      - name: Determine season
        id: season
        run: |
          if [ -n "${{ inputs.season }}" ]; then
            echo "season=${{ inputs.season }}" >> "$GITHUB_OUTPUT"
          else
            echo "season=$(uv run python scripts/current_season.py)" >> "$GITHUB_OUTPUT"
          fi

      - name: Extract (with retries)
        run: |
          for attempt in 1 2 3; do
            if uv run python etl/extract.py --season "${{ steps.season.outputs.season }}" --force; then
              exit 0
            fi
            echo "Extract attempt $attempt failed; retrying in 30s..."
            sleep 30
          done
          echo "Extract failed after 3 attempts (NBA API may be blocking this runner's IP)."
          exit 1

      - name: Transform
        run: uv run python etl/transform.py --season "${{ steps.season.outputs.season }}"

      - name: Load
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: PYTHONPATH=. uv run python etl/load.py --season "${{ steps.season.outputs.season }}"
```

- [ ] **Step 2: Validate the YAML**

Run: `uv run python -c "import yaml, sys; yaml.safe_load(open('.github/workflows/refresh-data.yml')); print('valid')"`
(pyyaml is available transitively; if the import fails, use `python3 -c` with the system Python instead.)
Expected: `valid`.

- [ ] **Step 3: Update README**

In `README.md`, replace the "Loading data into production" section body (keep the heading) with:

```markdown
Data refreshes automatically: the **Refresh Data** GitHub Actions workflow runs daily at 10:00 UTC, re-downloading the current season from the NBA API and loading it into the production database (idempotent inserts — only new games land). It can also be run on demand from the Actions tab (`workflow_dispatch`), optionally with an explicit `season` input for backfills.

Manual loading from a trusted machine still works:

```bash
DATABASE_URL="postgresql://user:pass@host:port/dbname" make refresh SEASON=2025-26
```

(`extract`/`transform` only touch local files; only the `load` step needs the production `DATABASE_URL` — Railway's public TCP-proxy address, not the internal one.)
```

Also update the Roadmap: change `- [ ] Scheduled data refresh (Railway cron)` to `- [x] Scheduled data refresh (GitHub Actions, daily)`.

- [ ] **Step 4: Full suite + checks**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest tests/ -q` then `make check`
Expected: 35 passed; all checks pass.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/refresh-data.yml README.md
git commit -m "feat: add daily data-refresh workflow"
```

---

### Rollout (operator + controller, after tasks merge)

Not subagent work — done interactively with the user:

1. Push `data-refresh`, open a PR, confirm CI green, merge (Railway auto-deploys main; the deploy is a no-op for the app code, which is fine).
2. Fetch the Railway Postgres **public** connection string (TCP proxy host/port — `mcp__railway__list_tcp_proxies` or the Railway dashboard's Postgres "Connect" tab; the `postgres.railway.internal` URL will NOT work from GitHub runners) and set it: `gh secret set DATABASE_URL --body "<public-url>"`.
3. Trigger the loader/IP-block test: `gh workflow run refresh-data.yml -f season=2025-26`, then `gh run watch`. Success loads 2025-26 into production AND proves GitHub runners can reach the NBA API.
4. Verify live: `curl "https://nba-api-production-0cd7.up.railway.app/api/standings?season=2025-26"` returns 30 teams; seasons dropdown on the site shows 2025-26.
5. **Fallback if step 3's extract fails all retries (IP block):** run locally — `make etl SEASON=2025-26`, then `DATABASE_URL="<public-url>" make load SEASON=2025-26`; install a local cron for `make refresh` (`crontab -e`: `0 5 * * * cd /home/jake/dev/projects/nba-db && DATABASE_URL="<public-url>" make refresh SEASON=$(uv run python scripts/current_season.py)`); disable the workflow's schedule trigger and note the local-cron reality in the README.
