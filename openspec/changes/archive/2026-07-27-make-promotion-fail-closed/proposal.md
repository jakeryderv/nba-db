## Why

Every check in the season lifecycle fails closed except in the one path where the
stakes are highest. Promotion replaces production data, and two gaps sit in it.

**Promotion never applies migrations.** `load-local` and `stage` both call
`apply_schema` before writing; the promote branch does not. Adding a migration
`10_*.sql` therefore means promotion takes a backup and then aborts mid-transaction
on the first insert or verification query. It fails closed, so nothing corrupts — but
it fails for a reason nobody would guess, in the path with the least room to
improvise. #31 proposes exactly that migration, so this has to land first.

Nothing in the specs says *when* migrations are applied, only that they are
append-only, checksum-tracked, and atomic on failure. That a write path applies them
first is a missing invariant, not merely a missing line.

**Verification runs after the commit.** The replacement transaction commits when its
block exits, and only then does live verification run. On failure the command raises
and production is already serving data that failed verification, with recovery being
a manual restore from a backup nothing has ever exercised.

## What Changes

- Promotion applies pending migrations before writing, matching every other write path.
- Promotion verifies the replacement data **inside the transaction, before it commits**.
  A dataset that fails verification is rolled back and never becomes visible.
- The data-quality checks move out of the test module into importable functions, so the
  promote path and the restore drill call the same code rather than two copies of it.
- The recovery path for a post-commit live-verification failure becomes documented and
  exercised rather than merely named.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `schema-migrations`: gains a requirement that a path writing season data applies
  pending migrations before it writes. Currently unstated, which is why promotion could
  diverge from the other two paths without contradicting anything.
- `season-lifecycle`: gains a requirement that replacement data is verified before the
  transaction commits. The existing live-verification requirement is amended: naming the
  backup as the recovery path is no longer sufficient on its own, because a recovery path
  that has never been exercised is not a recovery path.

## Impact

- **Code**: `etl/season_lifecycle.py` promote branch and `replace_season`; the
  data-quality checks extracted from `db/tests/test_data_quality.py` into an importable
  module, with the test file becoming one caller rather than the only home.
- **Behavior**: a promotion whose data fails verification now leaves production
  untouched instead of serving it. A promotion against a database with pending
  migrations now succeeds instead of aborting.
- **Docs**: the operator runbook gains the recovery procedure.
- **Dependencies**: none added.
- **Not in scope**: automatically restoring the backup on a post-commit failure. The
  design argues against it rather than assuming it — see the design document.
- **Rails**: this strengthens operator-only guards. Nothing here runs a lifecycle
  command or handles production credentials.

Closes #28.
