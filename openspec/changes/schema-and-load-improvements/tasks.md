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

- [ ] 3.1 Add a failing test asserting a replacement does not hold a lock that blocks readers for the duration of the copy.
- [ ] 3.2 Add a failing test asserting a mid-load failure leaves the original contents intact and no incoming tables behind.
- [ ] 3.3 Rewrite `replace_season` to copy into `<table>__incoming` and swap by rename inside the same transaction.
- [ ] 3.4 Move the pre-commit verification to run after the rename, so it reads the tables under the names callers use rather than passing against the old contents.
- [ ] 3.5 Add a test that verification observes the incoming data, by failing verification on the new rows and asserting rollback.
- [ ] 3.6 Confirm the advisory lock and transaction boundaries are unchanged.

## 4. Verification

- [ ] 4.1 Run `make check` and `make test` and show the output.
- [ ] 4.2 Run `make dagger-check`.
- [ ] 4.3 Run `make test-data` against a loaded database and confirm all checks still pass on the new schema.
- [ ] 4.4 Run `openspec validate`.
- [ ] 4.5 Confirm no lifecycle command was executed and no production credential handled.
- [ ] 4.6 Close #31 in the implementing commit.
