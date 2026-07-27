## Context

`app/shot_filters.py` returns two predicates: one scoped to the subject being viewed,
and `context_where_clause`, which omits the subject and describes the league-wide slice
the subject is compared against. The shot-chart handler runs the context predicate twice
whenever `made is None` — once for a league FG% scalar, once for a league zone map —
each over the full five-table join.

With no optional filters the context predicate reduces to `sa.season = %s`. So the
default dashboard load computes a whole-season aggregate that is byte-identical for
every caller, twice, on every request. Measured at ~85-100ms of ~180ms, and roughly
double the connection-hold time.

The data behind it changes only when an operator promotes a season, and promotion
replaces rows **without restarting the process**.

Two constraints come from the surrounding code rather than from this feature. Sync
FastAPI handlers run on a threadpool, so any shared structure is touched concurrently —
`SlidingWindowLimiter` carries a `threading.Lock` for exactly this reason. And the cache
key includes caller-supplied filter values, which is the same unbounded-key hazard the
limiter's bounded-state requirement was written for.

## Goals / Non-Goals

**Goals:**

- Stop recomputing an identical league baseline per request.
- Keep the memo bounded and thread-safe from the first commit, not as a follow-up.
- Ensure a promotion cannot leave stale league figures being served.
- Keep the change independently shippable.

**Non-Goals:**

- A materialized view. More durable, but it needs a migration, and #31 proposes
  migration 10 with #28 required first. Taking that route couples a self-contained
  performance fix to the promotion cluster.
- Caching subject-specific results. Those vary per caller and would not hit.
- Any edge or HTTP caching over `/api/`. `release-readiness` constrains that separately.
- Changing response shapes or the `made=true/false` paths, which already skip both
  queries.

## Decisions

### Key on the context predicate and its parameters, not the season

`(context_where_clause, tuple(context_params), loaded_at)`.

Filters — opponent, period, shot type, action type, date range, home/away — all alter
`context_where_clause` and `context_params`. Keying on season alone would serve one
filtered league baseline in place of another, which is a correctness bug that looks like
plausible data. Including the rendered clause means a future filter cannot silently
collide: a new predicate changes the key by construction.

`loaded_at` is part of the key rather than a separate validity check. That makes a stale
read impossible to express instead of merely unlikely, and it means eviction handles
retirement — old entries age out through the LRU rather than needing a purge step.

### Bound it, lock it, follow the limiter

An `OrderedDict` LRU with a hard cap and a `threading.Lock`, mirroring
`SlidingWindowLimiter`. Two properties, for two different reasons:

- **The cap** because `context_params` is caller-controlled. A caller varying filters
  can mint unlimited distinct keys, and on a single replica that is unbounded process
  memory. This is the generalized requirement, not a new concern.
- **The lock** because sync handlers run on a threadpool. `move_to_end` followed by an
  insert and a `popitem` is not atomic; concurrent shot-chart requests are the normal
  case, not an edge case.

At the cap the memo evicts the least-recently-used entry and recomputes on the next
miss. That is the correct degradation *for a cache* — unlike the limiter, failing toward
"do the work" costs latency and nothing else.

### Read `loaded_at` on the cursor the handler already holds

One indexed single-row read against `seasons`, issued inside the existing cursor block.
It adds a query but requires no additional pool checkout, and it replaces two
full-season aggregates.

This is a reduction in work, not an elimination of queries, and the change should be
described that way. Folding `loaded_at` into the existing summary query as a subselect
would save the round trip, but it entangles a provenance read with a statistics query
for a sub-millisecond gain; not worth the coupling.

*Alternative considered:* a short TTL. It bounds staleness without any read, but it
cannot state that a value is current — after a promotion it serves wrong figures for the
length of the TTL, silently. The promotion path already records `loaded_at`; using it
makes correctness structural.

### Cached values are treated as immutable

The zone map is a `dict` the handler reads while assembling its response. Handing out
the cached object invites a future edit that mutates it in place and corrupts every
subsequent response. The memo returns values that callers must not mutate, and the
handler builds its response from them rather than into them.

## Risks / Trade-offs

- **`RENAMED` + `MODIFIED` in one delta is unused elsewhere in this repo.** `openspec
  validate` passes, but validation is not the archiver. → Verify at archive time that
  `openspec/specs/public-api-surface/spec.md` ends up with the renamed header, the full
  generalized text, and all four scenarios. If the archiver mishandles it, fix the spec
  file in the same PR rather than leaving a half-applied rename.
- **A wrong key is worse than no cache**, because it returns plausible numbers rather
  than an error. → The key includes the rendered predicate, so an added filter changes
  it automatically; a test asserts two different filter sets do not collide.
- **The memo hides regressions in the underlying query.** A slow league aggregate now
  shows up once per key instead of once per request. → Acceptable; the live check still
  exercises the endpoint under a response-time budget.
- **Multi-replica futures dilute the hit rate** — each process keeps its own memo. →
  Still correct, just recomputed per process. Not a concern at one replica.
- **Measurement claims are easy to overstate.** The original review said ~70% of server
  time and a tripled hold time; verification put it at ~50-55% and doubled. → Report
  measured before/after numbers from this change rather than repeating either figure.

## Migration Plan

Additive and self-contained: one new module, two call sites, no schema change, no
deploy-path change, no response-shape change. Rollback is a revert.

## Open Questions

None blocking. The cap value should follow the limiter's precedent of an explicit
constant with an environment override, sized so that ordinary filter combinations fit
comfortably while a caller enumerating filters cannot grow memory.
