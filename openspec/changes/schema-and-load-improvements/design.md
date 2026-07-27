## Context

`replace_season` runs `TRUNCATE ... RESTART IDENTITY` and then copies every row, all
inside one transaction. That is atomic and correct, and it holds `ACCESS EXCLUSIVE` on
the product tables from the truncate until the commit — so every reader blocks for the
whole load.

Migration `10` is the first migration that can land safely: until #28, the promote path
never applied migrations, so adding one would have aborted promotion partway through.

Two things constrain the load-path rewrite. The advisory lock and the transaction are
owned by `replace_season` itself. And #28 added a pre-commit verification hook that runs
`db.quality_checks` against the writing connection — those checks query tables by name,
so they must run after any rename.

## Goals / Non-Goals

**Goals:**

- Keep the database readable while a season loads.
- Land the accumulated schema defects as one append-only migration.
- Remove the retired loader, which is unreachable but still holds unguarded deletes.
- Harden statement splitting before a migration needs it.

**Non-Goals:**

- Aligning the `minutes` column types. Argued below.
- Changing the advisory-lock or transaction boundaries.
- Any API response-shape change.
- Applying the migration to staging or production. That is an operator step through the
  existing guarded commands.

## Decisions

### Load into new tables, swap by rename

Build `<table>__incoming` alongside the live tables, copy into those, then rename inside
the same transaction: live to `__previous`, incoming to live, and drop `__previous`.
PostgreSQL takes `ACCESS EXCLUSIVE` for the rename, but holds it for a catalog update
rather than for the copy.

This keeps every property the current approach has. The rename is transactional, so a
failure anywhere rolls back to the original tables. The advisory lock still serializes
concurrent replacements. And atomicity is unchanged — a reader sees either the old
contents or the new, never a mixture.

*Alternative considered:* `DELETE` instead of `TRUNCATE`, which takes only `ROW
EXCLUSIVE`. It avoids the outage but leaves the table bloated by a full season of dead
tuples and is far slower. Rejected.

### Verification runs after the swap

The pre-commit verifier added in #28 calls `db.quality_checks`, which queries `games`,
`player_game_stats`, and the rest by name. Run before the rename it would verify the
*old* contents and pass while the incoming data was never checked — a silent false pass,
which is worse than the problem being solved.

So the ordering inside the transaction is: copy into incoming, rename, verify, commit.
This is why the spec change says verification observes the data as it will be served
rather than merely "before commit".

### Migration 10 contents, and one thing left out

Included: `game_date` NOT NULL, indexes on both game foreign keys, the standings view
rewritten as `UNION ALL` over home and away legs, the unreferenced `SERIAL` surrogate
keys dropped so the existing unique constraints become the primary keys, and the
discarded `ORDER BY` clauses removed from four views.

The surrogate keys were verified unreferenced — no SQL, Python, or frontend code reads
`player_game_stats.id` or `team_game_stats.id`. Dropping them makes the natural key the
primary key, which the data-quality check for natural keys already accepts, since it
matches on primary *or* unique constraints.

Left out: aligning `minutes` types. `team_game_stats.minutes` is `INTEGER`,
`player_game_stats.minutes` is `DECIMAL(5,1)`, and `app/models.py` mirrors both. Team
minutes are integral by construction — five players times forty-eight minutes — so the
difference is correct modelling rather than drift. Changing it would rewrite a column and
break the public type of a response field, bought for nothing but symmetry.

### `split_sql` is hardened before, not after

It flips a boolean on any `$$`, so a tagged dollar quote (`$func$`), a `$$` inside a
string literal, or a semicolon inside a quoted literal mis-splits the file. Nothing in
`01`-`09` trips it. Hardening it is a prerequisite rather than a cleanup: the failure
mode is a migration silently applied in fragments, and discovering that during a
promotion is the worst case.

### `etl/load.py` is deleted rather than left retired

It is unreachable — the only reference is its own test. It nevertheless contains four
unguarded `DELETE` statements and a `load_season` that silently skips shot attempts.
Retired code that can still destroy data is a hazard whose only defence is that nobody
calls it yet.

## Risks / Trade-offs

- **The migration rewrites two tables' primary keys on production data.** → ~26k and
  ~2.5k rows; small, but it is a rewrite under the promotion lock. The restore drill
  exercises `init_db` against a real backup monthly, so the migration is proven against
  production-shaped data before an operator applies it.
- **Rename-swap changes the most dangerous function in the codebase**, immediately after
  #28 added verification to it. → Every existing replacement test still applies
  unchanged; the new behaviour is additive. The tests assert the swap is transactional by
  forcing a failure and checking the original contents survive.
- **Incoming tables leak if a transaction dies outside the normal path.** → They are
  created and dropped inside the same transaction, so a rollback removes them; a crashed
  backend rolls back too. Names are fixed rather than random so a leaked table is
  obvious rather than accumulating silently.
- **Indexes on both game foreign keys cost write time on load.** → Two indexes over
  1,230 rows; irrelevant next to the copy itself.
- **Dropping the surrogate keys is irreversible in the forward direction.** → Verified
  unreferenced across SQL, Python, and frontend before proposing it.

## Migration Plan

Sequenced so the risky part lands last and separately verifiable:

1. Harden `split_sql`, delete the retired loader, fix `transform_games`. Independent.
2. Add migration `10`. Applied automatically by `init_db` on every boot and by every
   write path since #28.
3. Rewrite the replacement to load-and-swap, with verification after the rename.

Rollback for 1 and 3 is a revert. Migration `10` is append-only and cannot be un-applied
by reverting; reversing it would require migration `11`, which is the intended mechanism.

## Open Questions

None blocking. Whether the incoming tables should carry the indexes during the copy or
gain them after is worth measuring during implementation — building indexes after the
copy is usually faster, but it lengthens the window before the swap.
