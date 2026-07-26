# production-access

## Purpose

The deployed application is publicly reachable and the database behind it holds
a dataset that is expensive to rebuild — a full extract, transform, official
verification, and guarded promotion. The product is read-only by design, so the
web tier has no legitimate reason to hold credentials that can write, and the
cheapest durable protection is to make writes impossible at the database rather
than absent from the request handlers.

Enforcement lives in connection configuration, not in the route layer. A route
that forgets to be read-only is a plausible mistake; a role without write
grants makes that mistake inert.
## Requirements
### Requirement: The application connects through a SELECT-only role

The deployed application SHALL connect as a dedicated role granted schema usage
and SELECT only, including as the default privilege for future tables. Owner
credentials SHALL be a local-development fallback only, and the application
SHALL log when it takes that fallback so the posture is visible rather than
assumed.

#### Scenario: Production serves through the restricted role

- **WHEN** the read-only role password is configured
- **THEN** the connection pool authenticates as that role and cannot write

#### Scenario: The owner fallback is announced

- **WHEN** the application starts without a configured read-only password
- **THEN** it logs that it is connecting with owner credentials

### Requirement: Requesting a read-only connection fails closed

Resolving connection configuration with read-only requested SHALL raise when
the read-only password is unset, rather than falling back to owner credentials.
A caller that asked for restricted access and silently received privileged
access is the failure mode this forbids.

#### Scenario: Missing read-only password raises

- **WHEN** read-only connection configuration is requested and no read-only password is set
- **THEN** configuration raises instead of returning owner credentials

### Requirement: The public API exposes no write path

Every public endpoint SHALL be read-only. No change SHALL add an endpoint that
inserts, updates, or deletes data, or that triggers an ETL, lifecycle, or
maintenance operation. Data enters the database only through operator-run
lifecycle commands.

#### Scenario: Data changes require an operator

- **WHEN** the loaded dataset needs to change
- **THEN** an operator runs the lifecycle commands; no HTTP request can cause it

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
