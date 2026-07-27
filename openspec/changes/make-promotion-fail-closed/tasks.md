## 1. Extract the data-quality checks

- [ ] 1.1 Move the check functions out of `db/tests/test_data_quality.py` into an importable module that takes a connection and a season, with no pytest dependency.
- [ ] 1.2 Reduce `db/tests/test_data_quality.py` to a thin pytest caller over that module, keeping the session-scoped `conn` fixture in the test layer where it belongs.
- [ ] 1.3 Confirm the existing negative-control tests in `tests/test_data_quality_checks.py` still pass unchanged, since they import these by name.
- [ ] 1.4 Confirm the restore drill still runs them via pytest and still fails on corrupt data.

## 2. Migrations on the promote path

- [ ] 2.1 Add a failing test asserting the promote path applies pending migrations before replacing data.
- [ ] 2.2 Call `apply_schema` in the promote branch, inside the operation lock and after the backup, matching where `load-local` and `stage` place it.
- [ ] 2.3 Add a test that all three write paths apply migrations, so a fourth path cannot be added without one.

## 3. Verify before commit

- [ ] 3.1 Add a failing test asserting `replace_season` rolls back when its verification callback raises, leaving prior data in place.
- [ ] 3.2 Add the optional verification callback to `replace_season`, invoked after the rows are written and before the transaction block exits.
- [ ] 3.3 Implement the promotion verifier: manifest count reconciliation plus the extracted data-quality checks, on the writing connection.
- [ ] 3.4 Add a failing test asserting a promotion whose data fails verification leaves the previous season intact and takes no recovery action.
- [ ] 3.5 Decide whether `stage` also runs the pre-commit verifier, and record the reasoning either way.

## 4. Recovery procedure

- [ ] 4.1 Make the post-commit live-verification failure message name the backup file for this promotion and point at the documented procedure.
- [ ] 4.2 Write the recovery procedure in `docs/operations/season-lifecycle.md` as executable steps, not prose.
- [ ] 4.3 State plainly that the backup precedes any migration applied during the promotion, so recovery restores the prior schema and re-applies.
- [ ] 4.4 Add a test asserting the failure message carries the backup path, so the message cannot silently lose the one thing an operator needs.

## 5. Verification

- [ ] 5.1 Run `make check` and `make test` and show the output.
- [ ] 5.2 Run `make dagger-check`.
- [ ] 5.3 Run `openspec validate`.
- [ ] 5.4 Confirm no lifecycle command was executed and no production credential handled while implementing this.
- [ ] 5.5 Close #28 in the implementing commit.
