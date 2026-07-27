## RENAMED Requirements

- FROM: `### Requirement: Limiter state is bounded`
- TO: `### Requirement: State keyed on request input is bounded`

## MODIFIED Requirements

### Requirement: State keyed on request input is bounded

Process-local state keyed on values a caller can vary SHALL enforce a hard cap on
the number of tracked keys and SHALL evict rather than grow past it. Reaching the
cap SHALL degrade in the direction that preserves whatever the state exists to
provide.

Without a bound, every distinct key ever observed persists for the process
lifetime, so a caller who can vary the key can grow memory without limit on a
single replica. This is not a rate-limiting concern that happens to involve
memory; it is a property of any keyed state on a public, anonymous surface. The
limiter was the first instance and a memo keyed on request filters is the second,
which is why the rule is stated once rather than per mechanism.

The direction of degradation does not generalize and SHALL be decided per
mechanism. A limiter that stops limiting when full has failed open, which is the
outcome it exists to prevent. A cache that recomputes when full has lost an
optimization and nothing else. Stating a single at-cap behavior for both would be
wrong about one of them.

Limiter state SHALL additionally remove a key once its window contains no
remaining requests, rather than retaining an empty entry.

#### Scenario: Expired window is evicted

- **WHEN** a tracked key's window empties as its entries age out
- **THEN** the key is removed from limiter state rather than retained as an empty entry

#### Scenario: Key cap does not disable limiting

- **WHEN** the number of tracked limiter keys reaches the cap
- **THEN** limiting remains in force

#### Scenario: A caller cannot grow cache memory without bound

- **WHEN** a caller issues requests that vary the values a cache is keyed on
- **THEN** the number of retained entries stops at the cap rather than growing with the number of distinct keys

#### Scenario: A full cache recomputes rather than answering from the wrong entry

- **WHEN** a cache is at its cap and a request arrives for an evicted key
- **THEN** the value is recomputed for that key rather than served from another key's entry

## ADDED Requirements

### Requirement: Cached values derived from the dataset stop being served when it is replaced

A cached value derived from season data SHALL be invalidated when that season's
recorded load changes, so that no response mixes values computed from a replaced
dataset with values computed from the current one.

Promotion replaces season data in place without restarting the process. State
scoped to the process lifetime therefore outlives the data it was derived from,
and a cache with no invalidation would keep serving pre-promotion figures
indefinitely — with no error, no log line, and no expiry to eventually correct it.

Invalidation SHALL be driven by data the application reads rather than by elapsed
time. A time-based expiry bounds how long a stale value is served but cannot state
that a value is current, and the promotion path already records when a season was
loaded.

#### Scenario: A promotion retires cached values

- **WHEN** a season's data is replaced and its recorded load time changes
- **THEN** subsequent responses reflect the new data rather than cached values derived from the previous load

#### Scenario: An unchanged dataset does not force recomputation

- **WHEN** a season's recorded load time is unchanged between requests
- **THEN** a cached value for the same key may be served without recomputing it
