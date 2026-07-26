## Why

Every production invariant in this repo is specced except the two that answer "is
production still there?" — durability and liveness. That is why the gaps below
accumulated without anyone noticing: nothing pinned them, so nothing flagged their
absence.

Both gaps share a shape. Each existing signal is emitted *by the thing it reports on*,
so the signal disappears exactly when the subject fails. `maintenance.yml`'s alert
reconciliation is `if: always()` **inside** the maintenance job, so a schedule that stops
firing produces no alert — only silence, which reads identically to success. The release
observer triggers `on: workflow_run` for CI, so between merges nothing watches production
at all. In both cases a healthy-looking dashboard is compatible with a system that has
stopped working.

## What Changes

- Assert that a recent backup **exists**, from a job independent of the one that creates
  backups. Today `scripts/download_backup.py` takes `max(backups, key=LastModified)` with
  no age bound, so if uploads silently stop the monthly drill keeps downloading an
  ever-older dump and reporting green for up to a month.
- Compare each backup's recorded manifest digest against the restored dataset. The
  uploader already stamps `{"sha256", "manifest"}` on every object and the downloader
  already reads it back, but nothing ever compares it, so the drill proves the dump is
  self-consistent rather than that it matches the dataset production serves.
- Extend the restore drill to prove the restored database is **servable**, not only that
  its counts reconcile against provenance metadata.
- Stop retention from deleting the last copy proven restorable. Retention is 30 days and
  the drill is monthly, so the only backup ever proven good can expire on roughly the
  cadence of the check that proved it.
- Add a continuous liveness probe on a `*/10` schedule that reconciles the same
  `production-alert` issue, cutting worst-case outage detection from ~21 hours to ~10
  minutes.

Not in scope: changing backup frequency, retention length, or the restore drill cadence.
The defect is that their outcomes are unobserved, not that their schedules are wrong.

## Capabilities

### New Capabilities

- `backup-durability`: what must be true of the backup loop for a restore to be a real
  recovery option — that a recent backup exists, that it matches the dataset production
  serves, that restoring it yields a database that can serve, and that the last proven
  copy survives retention.
- `production-liveness`: that production is observed continuously between deploys rather
  than only after them, and that an outage raises a visible signal that later clears.

### Modified Capabilities

None. `release-readiness` already governs deploy gating and release verification, and its
origin-not-a-cache requirement constrains this work without itself changing. A continuous
liveness probe is a separate concern from verifying a release, so it earns its own
capability rather than widening that one.

## Impact

- **Specs**: two new capabilities under `openspec/specs/`.
- **Workflows**: `.github/workflows/maintenance.yml` (drill assertions), plus a new
  scheduled workflow for liveness and backup freshness. Both reuse the `production-alert`
  reconcile pattern established in #45.
- **Scripts**: `scripts/download_backup.py` (freshness bound), `scripts/restore_drill.py`
  (manifest comparison, servability), `scripts/upload_backup.py` (retention floor).
- **Dagger**: `.dagger/src/nba_db_ci/main.py` `restore-backup`, which drives the drill.
- **Tests**: `tests/test_artifact_archive.py` and the restore-drill suite.
- **Operator docs**: `docs/operations/deployment.md` monitoring and maintenance sections.
- **Dependencies**: none added. Single replica, `restartPolicyType: ON_FAILURE` with a
  3-retry cap, is why a crash-loop stays down and why the probe interval matters.
- **Cost**: one additional scheduled GitHub Actions job at `*/10`.

Closes #46 and #49.
