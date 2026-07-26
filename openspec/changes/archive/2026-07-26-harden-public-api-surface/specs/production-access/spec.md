## MODIFIED Requirements

### Requirement: Pooled connections are bounded

Application connections SHALL carry a statement timeout and an
idle-in-transaction timeout, and the pool SHALL bound its size and its wait
queue, so that a slow or pathological query cannot exhaust the database on
behalf of anonymous callers.

The pool SHALL be created once during application startup and closed during
shutdown. It SHALL NOT be constructed lazily from request handling: handlers
run concurrently on a threadpool, and an unsynchronized check-then-create there
allows two cold requests to build two pools, leaking one and doubling the
connection budget the bound is meant to enforce.

#### Scenario: A long query is cut off

- **WHEN** a query exceeds the configured statement timeout
- **THEN** the database terminates it rather than holding the connection indefinitely

#### Scenario: Concurrent cold requests share one pool

- **WHEN** several requests arrive simultaneously against a freshly started instance
- **THEN** they use the single pool opened at startup and no additional pool is constructed

## ADDED Requirements

### Requirement: A request does not serially reacquire connections

A single request SHALL NOT take multiple sequential pool checkouts to assemble
one response. Endpoints that need several queries SHALL share one cursor
through extracted query functions rather than invoking other route handlers as
functions.

Serial checkouts multiply a request's occupancy of a bounded pool, so a
handful of concurrent callers to such an endpoint can starve the pool while
each individually appears well-behaved.

#### Scenario: A composite endpoint uses one checkout

- **WHEN** an endpoint composes data that other endpoints also return
- **THEN** it calls shared query functions on one cursor rather than calling those route handlers

#### Scenario: Only the needed season is fetched

- **WHEN** a comparison needs one season's stats
- **THEN** the query filters to that season rather than fetching every season and discarding the rest
