# Daily Data Refresh + 2025-26 Load — Design

**Date:** 2026-07-20
**Status:** Superseded on 2026-07-21

> **Historical document — do not implement the GitHub Actions rollout below.** GitHub-hosted runners could not reliably reach `stats.nba.com`, and a repository workflow should not hold credentials capable of writing to production. The production-writing workflow has been removed. The supported trusted-machine procedure is documented in README and uses the guarded season build, local-load, and promote commands. Production credentials must be supplied through the documented environment mechanism, never in command-line arguments or GitHub Actions. CI uses only an ephemeral PostgreSQL service.

## Historical goal

Bring the deployed site's data up to date (load the 2025-26 season) and keep it current automatically: a daily scheduled job refreshes the current season's data during the season. Backfill beyond 2025-26 is explicitly out of scope for now.

## Background

At the time of this proposal, the production database had only 2024-25 and extraction used cached raw files. The original loader behavior described here was later superseded by guarded replacement and promotion tooling; do not rely on this historical document for current load semantics. Extract used 4 NBA API calls per season via `LeagueGameLog`/`CommonAllPlayers`.

The original platform decision was **GitHub Actions cron**. The known datacenter-IP risk materialized, so this part of the design was retired in favor of the guarded trusted-machine procedure documented in README. The ETL `--force` option and season calculator remain useful building blocks; the legacy `make refresh` target is not the supported production entry point.

## Changes

### 1. `etl/extract.py`: `--force` flag

- `--force` re-downloads all files for the run even when they exist: the season's `league_game_log_*.json` AND the shared `players.json` (so mid-season signings/rookies appear). `teams.json` may also be refreshed under `--force` (harmless; teams are static).
- Default behavior without the flag is unchanged (skip existing).
- Historical workflow-level retries were removed with the workflow. A trusted operator can diagnose extraction failures and rerun the same explicit season locally.

### 2. `scripts/current_season.py`

- Prints the current NBA season string (e.g. `2026-27`) to stdout.
- Rule: months October–December → `YYYY-(YY+1)`; January–September → `(YYYY-1)-YY`.
- Off-season behavior: the helper identifies the most recent completed season. The operator still verifies and supplies the season explicitly.
- Unit-tested (pure date math; function takes a `date` argument for testability).

### 3. `Makefile`: `refresh` target

- Historical implementation: the target directly chained extract, transform, and load for one season.
- It is not the supported production workflow; README's guarded build, local-load, and promote sequence supersedes it.

### 4. `.github/workflows/refresh-data.yml` (removed)

- Historical proposal: a scheduled or manually dispatched GitHub-hosted job would extract, transform, and load production data.
- Superseding decision: the workflow was removed because extraction is unreliable from GitHub-hosted IPs and CI/CD must remain isolated from production write credentials.

### 5. Superseding operator policy

- Follow the supported trusted-machine workflow in README.
- Use its guarded season build, local-load, and promote commands; do not invoke the legacy direct-load path for production.
- Supply production credentials only through README's documented environment mechanism, never as command-line arguments or GitHub Actions secrets.
- Do not restore the removed workflow or follow rollout commands from repository history.

## Error handling

- Extract failures (network, IP block): diagnose the guarded build failure before restarting the documented procedure.
- Load or promotion failures: stop and diagnose them before resuming at the documented safe stage.
- Season rollover: the helper provides a candidate, but the operator confirms the season before each guarded build.

## Testing

- Unit tests for `current_season(date)` covering both month ranges and year boundaries (added to the existing pytest suite; no DB needed).
- Extract `--force` behavior verified by a focused test or manual verification (file mtimes change) — no NBA API mocking in the suite.
- CI configuration is validated independently and has no production write path.
- `make check` and the full suite stay green.

## Historical success criteria

- 2025-26 season visible on the live site (standings, leaders, games).
- Refreshes are run from a trusted machine for one explicit season at a time.
- CI remains read-only with respect to production.
