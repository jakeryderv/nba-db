## 1. Prerequisites and deletions

- [x] 1.1 Add failing tests for `split_sql`: a tagged dollar quote (`$func$`), a `$$` inside a string literal, and a semicolon inside a quoted literal must not split a statement.
- [x] 1.2 Harden `split_sql` in `scripts/init_db.py` to satisfy them. This is a prerequisite, not a cleanup: the failure mode is a migration silently applied in fragments.
- [x] 1.3 Confirm migrations `01`-`09` still split identically after the change, statement for statement.
- [x] 1.4 Delete `etl/load.py` and `tests/test_etl_load.py`, and confirm nothing imports either.
- [x] 1.5 Replace the filter-inside-a-loop in `transform_games` with a grouped pass, asserting identical output on the existing fixture before and after.

## 2. Migration 10

- [x] 2.1 Add a failing test asserting `games.game_date` is NOT NULL, both game foreign keys are indexed, and the surrogate `id` columns are gone.
- [x] 2.2 Write `db/schema/10_*.sql` as the next append-only file: `game_date` NOT NULL, indexes on `home_team_id` and `away_team_id`, drop the two `SERIAL` surrogate keys and promote the existing unique constraints to primary keys.
- [x] 2.3 Rewrite `vw_team_standings` as a `UNION ALL` of home and away legs so the join can use an index, and assert it returns the same rows as before for the seeded fixture.
- [x] 2.4 Drop the `ORDER BY` clauses from the four views whose callers discard them.
- [x] 2.5 Confirm the natural-key data-quality check still passes, now that these are primary rather than unique constraints.
- [x] 2.6 Confirm the migration applies cleanly on top of an existing loaded database, not only on a fresh one.

## 3. Load and swap

- [x] 3.1 Add a failing test asserting a replacement does not hold a lock that blocks readers for the duration of the copy.
- [x] 3.2 Add a failing test asserting a mid-load failure leaves the original contents intact and no incoming tables behind.
- [x] 3.3 Replace `TRUNCATE ... RESTART IDENTITY` with ordered unqualified DELETEs, removing rows from referencing tables before their targets. Drop `RESTART IDENTITY`: migration 10 left no sequences for it to reset.
- [x] 3.4 Confirm verification still observes the new rows, since no rename is involved and the tables keep their names throughout.
- [x] 3.5 Add a test that a load leaves no rows from any other season, which TRUNCATE previously guaranteed structurally.
- [x] 3.6 Confirm the advisory lock and transaction boundaries are unchanged.

## 4. Verification

- [x] 4.1 Run `make check` and `make test` and show the output.
- [x] 4.2 Run `make dagger-check`.
- [x] 4.3 Run `make test-data` against a loaded database and confirm all checks still pass on the new schema.
- [x] 4.4 Run `openspec validate`.
- [x] 4.5 Confirm no lifecycle command was executed and no production credential handled.
- [x] 4.6 Close #31 in the implementing commit.
