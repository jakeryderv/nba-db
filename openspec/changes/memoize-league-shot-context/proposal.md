## Why

The shot chart recomputes the same league-wide baseline for every caller on every
load. Whenever `made is None` — the default dashboard case — two aggregates run over
the full five-table join using a predicate that, with no filters applied, reduces to
`sa.season = %s`. Both produce an identical league FG% scalar and an identical set of
~30 league zone rows regardless of which team or player is being viewed.

Measured against production, those two queries are roughly **85-100ms of ~180ms** —
about half the server time on the slowest public endpoint — and roughly double how
long each request holds a pooled connection. The dataset behind them changes only when
an operator promotes a season, so this is pure repeated work.

Caching it introduces a second instance of a hazard this repo has already specced once.
The natural cache key includes caller-supplied filters, so a caller can mint unbounded
distinct keys — exactly the failure the rate limiter's bounded-state requirement exists
to prevent. Rather than write that rule a second time, this change generalizes it.

## What Changes

- Memoize the league FG% scalar and the league zone map, keyed on the context predicate
  and its parameters rather than on the season alone. Filters change the context, so a
  season-only key would serve one filtered baseline in place of another.
- Bound the memo with a hard cap and LRU eviction from the outset, following the
  `SlidingWindowLimiter` pattern already in `app/middleware.py`.
- Invalidate on the season's `loaded_at`. Promotion replaces data **without restarting
  the process**, so a memo scoped to the process lifetime would serve pre-promotion
  league context indefinitely.
- **Generalize** the existing `Limiter state is bounded` requirement so it governs any
  process-local state keyed on values a caller can vary. The hard cap is the shared
  rule; how each mechanism degrades at the cap is not, and the requirement says so.

Not in scope: a materialized view of league zone aggregates. It is the more durable
answer, but it needs a migration, and #31 already proposes migration 10 while #28 must
land first — taking that route would entangle a self-contained performance fix with the
promotion cluster. Also not in scope: caching anything subject-specific, or any edge
caching over `/api/`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `public-api-surface`: the bounded-state requirement is widened from the rate limiter
  to any process-local state keyed on request input, and gains a rule that values
  derived from the dataset stop being served once that dataset is replaced.

## Impact

- **Code**: a new memo module; `app/main.py` shot-chart handler at both league-context
  call sites; no change to `app/shot_filters.py`, which already returns the context
  predicate and parameters separately.
- **Behavior**: response shapes are unchanged. `made=true` and `made=false` already skip
  both queries, so only the default path is affected.
- **Queries**: this trades two full-season aggregates for one cheap single-row read of
  `loaded_at`. It reduces work rather than eliminating queries, and the numbers should be
  stated that way.
- **Expected result**: roughly halves shot-chart latency and roughly doubles that
  endpoint's throughput ceiling. Note the correction on record — the original review
  claimed ~70% of server time and a tripling of connection-hold time; the verified
  figures are ~50-55% and a doubling.
- **No conflict** with `release-readiness`'s requirement that release verification read
  the origin rather than a cache: this memo is origin-side and per-process.
  `scripts/check_live.py` requests the shot chart under a response-time budget but
  asserts no league values, so it is helped rather than affected.
- **Dependencies**: none added.

Closes #48.
