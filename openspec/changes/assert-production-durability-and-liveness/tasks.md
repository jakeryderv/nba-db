## 1. Extract alert reconciliation

- [x] 1.1 Create `.github/actions/reconcile-alert/action.yml` as a composite action taking `title`, `passed`, and `run-url`, reproducing the current `reconcile()` behavior: create on first failure, comment on repeat failure, close on recovery.
- [x] 1.2 Repoint `.github/workflows/maintenance.yml` at the composite action, keeping the existing per-operation titles (`Production backup failed`, `Production restore drill failed`) byte-identical so no in-flight alert is orphaned.
- [x] 1.3 Consolidate the label bootstrap into the composite action for every caller that can use it. `release-observer.yml` keeps its inline copy: its alert must file when CI failed, which is exactly when its conditional checkout is skipped, so it cannot depend on a repo-local action. Record that reason in the workflow.
- [x] 1.4 Replace the `--search "<title> in:title"` lookup in `release-observer.yml` with the same exact-title match, so every reconciler resolves alerts identically even though one stays inline.

## 2. Backup freshness

- [x] 2.1 Add a failing test for a freshness function that fails when the newest backup exceeds a maximum age, passes within it, and fails when no backup exists at all.
- [x] 2.2 Implement the check in `scripts/` reusing the existing paginated listing, taking `--max-age-hours` and reporting the newest backup's age either way.
- [x] 2.3 Extend it to assert the last drill is no older than 40 days, reading the pointer object from task 5.1.
- [x] 2.4 Assert the check does not import or depend on the backup job's code path, so it cannot pass by virtue of the backup job having run.

## 3. Liveness workflow

- [x] 3.1 Create `.github/workflows/production-watch.yml` with a `*/10 * * * *` liveness schedule, a `0 14 * * *` freshness schedule, and a mode-select step following `maintenance.yml`'s pattern.
- [x] 3.2 Implement the liveness probe against `/ready` with `Cache-Control: no-cache` and `Pragma: no-cache`, asserting HTTP 200 and a ready status.
- [x] 3.3 Add three spaced in-job retries before declaring failure, so a transient blip does not open an issue.
- [x] 3.4 Wire both modes to the composite action with distinct titles (`Production liveness check failed`, `Production backup freshness check failed`), so neither can close the other's alert or maintenance's.
- [x] 3.5 Add `workflow_dispatch` with a mode input and validate the required configuration (`LIVE_API_URL`) before probing.

## 4. Restore drill proves servability

- [ ] 4.1 Add a failing test asserting the drill fails when the restored `seasons.manifest_sha256` disagrees with the backup object's recorded manifest digest, and when that metadata is absent.
- [ ] 4.2 Thread the backup object's manifest digest from `scripts/download_backup.py` (already read, currently unused downstream) into the drill and compare it.
- [ ] 4.3 Run `scripts/init_db.py` against the restored database inside the drill, proving migrations apply and `nba_readonly` plus grants are recreated.
- [ ] 4.4 Evaluate the application's readiness check against the restored database, asserting the same conditions the deployment healthcheck does from the same code rather than a reimplementation.
- [ ] 4.5 Connect as `nba_readonly` and run a representative read, proving the least-privilege path and not only the superuser path.
- [ ] 4.6 Update `.dagger/src/nba_db_ci/main.py` `restore-backup` for the added steps and keep its reported output naming what was proved.

## 5. Retention preserves the proven copy

- [ ] 5.1 Have a successful drill write `database-backups/<season>/last-proven.json` naming the proved key and the time it was proved.
- [ ] 5.2 Add a failing test asserting `prune_backups` retains the pointed-at key even when it is older than the retention window, and still prunes expired unproven copies.
- [ ] 5.3 Implement the guard in `scripts/upload_backup.py`.
- [ ] 5.4 Add a failing test asserting pruning aborts on an unreadable or malformed pointer, then implement that fail-closed behavior.
- [ ] 5.5 Confirm the pointer object cannot itself be pruned — it does not match the `.dump` suffix filter, but assert it rather than assuming.

## 6. Documentation

- [ ] 6.1 Document the watch workflow, both schedules, and the max-age values in `docs/operations/deployment.md` under production monitoring.
- [ ] 6.2 State the shared-failure-domain limitation plainly in the same section: these checks run on the same platform as the jobs they watch, so platform-wide silence is not covered.
- [ ] 6.3 Replace the `TBD - created by archiving change harden-public-api-surface` placeholder in `openspec/specs/public-api-surface/spec.md` with a real Purpose.

## 7. Verification

- [ ] 7.1 Run `make check` and `make test` and show the output.
- [ ] 7.2 Dispatch `maintenance.yml` after task 1.2 to confirm the extraction is behavior-preserving against a real run.
- [ ] 7.3 Dispatch both `production-watch.yml` modes manually and confirm each passes and files nothing.
- [ ] 7.4 Force one failure path (probe an unreachable URL via dispatch input, or a max age of zero) and confirm an alert opens with the right title, a repeat comments rather than duplicating, and recovery closes it.
- [ ] 7.5 Dispatch a restore drill against a real backup and confirm the new assertions pass and the pointer object is written.
- [ ] 7.6 Confirm `openspec validate` passes and close #46 and #49 in the implementing commit.
