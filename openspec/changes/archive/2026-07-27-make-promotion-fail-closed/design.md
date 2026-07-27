## Context

`etl/season_lifecycle.py` has three write paths. `load-local` and `stage` each call
`apply_schema` before replacing data; `promote` does not. All three then call
`replace_season`, which does its work inside `with conn.transaction():` — so the commit
happens when that block exits, and `verify_live_api` runs after it.

Two consequences. A pending migration breaks promotion specifically, after the backup is
taken and partway through the replacement. And a live-verification failure finds
production already serving data that failed its checks, with recovery being a manual
restore from a backup that nothing has ever exercised.

Since #47, promotion already refuses a dataset staging is not serving, and since #29 the
data-quality checks are real pytest functions taking a connection and a season. Both
change what the right fix looks like.

## Goals / Non-Goals

**Goals:**

- Make promotion apply migrations like every other write path.
- Move data verification before the commit, so bad data never becomes visible.
- Have the promote path and the restore drill run the same checks.
- Turn the post-commit recovery path from a named artifact into an exercised procedure.

**Non-Goals:**

- Automatic restore on a post-commit failure. Argued against below.
- Changing the TRUNCATE-and-load replacement strategy. That is #31's rename-swap work,
  and it shortens the failure window rather than changing what fails.
- Any change to who may run these commands. They remain operator-only with typed
  confirmations.

## Decisions

### Verification hooks into `replace_season`'s transaction, not around it

`replace_season` owns the transaction, so a caller cannot verify inside it from outside.
It gains an optional verification callback invoked after the rows are written and before
the transaction block exits. Raising from that callback rolls the whole replacement back.

The alternative — having the caller open the transaction and pass the connection down —
spreads transaction ownership across two functions, and the advisory-lock handling
already lives inside `replace_season`. Keeping the boundary where it is and passing
behaviour in is the smaller change.

### What "verify" can mean before a commit, and what it cannot

This is the correction to the issue's framing, and it is the crux of the change.

The issue proposes running the smoke checks before the commit, verifying "against the
open transaction's session." That is not possible for `verify_live_api`. It checks the
*deployed API*, which reads through the application's own connection pool; an
uncommitted transaction is invisible to every connection but the one that opened it. Live
verification inherently requires a committed write. No amount of restructuring changes
that.

What can move is verification of the data itself: counts reconciled against the manifest,
and the data-quality checks. Those run on the writing connection, inside the transaction,
and see exactly the rows about to be committed.

So the split is: **data correctness moves before the commit; deployment correctness
necessarily stays after it.** That is not a compromise, it is the actual shape of the
problem, and it removes the failure that matters — production serving data that failed
its own checks.

### The data-quality checks move out of the test module

They currently live in `db/tests/test_data_quality.py` and are called two ways: by pytest
via a session-scoped fixture, and by the restore drill running that pytest suite. The
fixture opens its own connection, which by definition cannot see the promotion's open
transaction, so the promote path cannot reuse them as they stand.

They move to an importable module. The pytest file becomes a thin caller, the restore
drill keeps running pytest, and the promote path calls the functions directly on its own
connection. One implementation, three callers.

Importing a test module into the production write path would be the alternative and is
worse: it makes a correctness check depend on test-collection layout, and it inverts
which of the two is the real definition.

### Recovery stays manual, and that is a decision rather than a default

The issue offers automatically running `pg_restore` on a post-commit smoke failure. This
change argues against it.

Once data is verified before the commit, the remaining post-commit failures are
overwhelmingly *not* data failures. What is left is the deployment being wedged, the
application being down, the edge misbehaving, or verification itself being unreachable.
Restoring the database fixes none of those, and a restore is destructive and slow. An
automatic restore would therefore fire mostly in cases where it cannot help, while being
the single most dangerous action in the system.

The honest fix is the issue's own third option: make the procedure explicit, documented,
and exercised. The restore drill already proves a backup restores into a servable
database every month, so the mechanism is tested; what is missing is the operator-facing
procedure that connects a failed promotion to that mechanism.

### Migrations apply on the promote path before the backup or the lock

`apply_schema` runs against production before the replacement. Placing it before the
backup would mean backing up a schema that just changed; placing it after the write is
too late. It goes where the other two paths put it — immediately before the replacement,
inside the operation lock, so a concurrent operation cannot interleave.

## Risks / Trade-offs

- **Pre-commit verification lengthens the transaction**, and `replace_season` holds
  `ACCESS EXCLUSIVE` through a TRUNCATE-and-load. → The checks are aggregate reads over
  the rows just written, adding seconds to an operation already measured in minutes.
  #31's rename-swap work is what actually shortens this window.
- **The extracted check module becomes production code**, so a slow or wrong check now
  blocks a promotion rather than failing a test. → That is the intent; the negative
  controls added in #29 exist precisely so the checks are known to fail when they should.
- **Verification inside a transaction sees uncommitted data**, which is the point, but it
  means the checks must not open their own connections. → The extracted functions take a
  connection; the fixture that opens one stays in the test layer.
- **A migration applied during promotion is not covered by the backup taken after it.**
  → Ordering puts `apply_schema` after the backup, so the backup reflects the pre-change
  schema; document that recovery restores to the prior schema and re-applies.

## Migration Plan

Additive to a path that cannot run in CI: no schema change, no application change, no
deploy-path change. The extracted check module is a move plus a thin re-export, covered
by the existing negative-control tests.

Rollback is a revert. The change cannot be exercised end to end by automation, since
promotion is operator-only; verification is by unit tests over the new seams plus the
existing drill.

## Open Questions

None blocking. Whether pre-commit verification should also run on the `stage` path is
worth deciding during implementation: staging is where a bad dataset should be caught
first, and the same callback is already in place — but staging failing loudly is less
costly than production doing so, and #47 already makes staging a precondition rather than
a formality.
