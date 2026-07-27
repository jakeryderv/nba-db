## 1. Measure the baseline

- [x] 1.1 Record current shot-chart timing against production and locally, so the change reports measured before/after numbers rather than repeating either figure from the review.
- [x] 1.2 Confirm the two league-context queries are the dominant cost by timing the handler with them removed, establishing the ceiling this change can reach.

## 2. Bounded memo

- [x] 2.1 Add a failing test that a caller varying the values the memo is keyed on cannot grow it past its cap.
- [x] 2.2 Add a failing test that a full memo recomputes for an evicted key rather than returning another key's value.
- [x] 2.3 Add a failing test that two different filter sets do not collide on one key, using predicates that differ only in their parameters.
- [x] 2.4 Add a failing test that a changed `loaded_at` retires cached values while an unchanged one serves them.
- [x] 2.5 Implement the memo as an `OrderedDict` LRU with a hard cap and a `threading.Lock`, following `SlidingWindowLimiter` in `app/middleware.py`. Handlers run on a threadpool, so the lock is required, not defensive.
- [x] 2.6 Make the cap an explicit constant with an environment override, matching the limiter's precedent.

## 3. Wire into the shot chart

- [x] 3.1 Read the season's `loaded_at` on the cursor the handler already holds, so no additional pool checkout is introduced.
- [x] 3.2 Route the league FG% scalar (`app/main.py` league-context block) through the memo.
- [x] 3.3 Route the league zone map through the memo.
- [x] 3.4 Confirm cached values are not mutated while assembling the response; build the response from them rather than into them.
- [x] 3.5 Confirm `made=true` and `made=false` still skip both queries entirely and never populate the memo.

## 4. Verify behavior is unchanged

- [x] 4.1 Assert the shot-chart response is byte-identical before and after for the same inputs, including league FG% and per-zone league comparison values.
- [x] 4.2 Assert a second identical request issues no league-context queries, by counting executed statements rather than by timing.
- [x] 4.3 Run the browser suite to confirm the dashboard's shot chart renders unchanged.

## 5. Spec

- [x] 5.1 Run `openspec validate`.
- [x] 5.2 At archive time, verify the `RENAMED` plus `MODIFIED` delta actually applied: `openspec/specs/public-api-surface/spec.md` must carry the renamed header, the full generalized text, and all four scenarios. No prior change in this repo has used `RENAMED`, and validation is not the archiver.
- [x] 5.3 Fill in a real Purpose if the archiver stamps a placeholder, rather than leaving a `TBD`.

## 6. Verification

- [x] 6.1 Run `make check` and `make test` and show the output.
- [x] 6.2 Run `make dagger-check`.
- [x] 6.3 Record measured after-numbers against production once deployed, and state the improvement in measured terms.
- [x] 6.4 Close #48 in the implementing commit.
