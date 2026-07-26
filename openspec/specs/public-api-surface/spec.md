# public-api-surface Specification

## Purpose
TBD - created by archiving change harden-public-api-surface. Update Purpose after archive.
## Requirements
### Requirement: Rate limiting keys on an identity the client cannot choose

The rate limiter SHALL derive its client key from the hop attributed by the
trusted edge proxy, not from the first value of a client-supplied forwarding
header. Where a forwarding header carries multiple hops, the limiter SHALL read
the hop appended by the trusted proxy rather than the leftmost value, which is
under the caller's control.

A limiter keyed on attacker-chosen input imposes no limit at all: it converts a
shared budget into a per-request budget for anyone who varies the header.

#### Scenario: Forged forwarding header does not mint a new budget

- **WHEN** a client sends a different fabricated forwarding value on each request
- **THEN** every request is attributed to the same client key and the limit applies across them

#### Scenario: Genuine client addresses are distinguished

- **WHEN** two distinct clients reach the app through the edge proxy
- **THEN** they receive independent budgets

### Requirement: Limiter state is bounded

The limiter SHALL remove a key once its window contains no remaining requests,
and SHALL enforce a hard cap on the number of tracked keys. Reaching the cap
SHALL NOT cause requests to bypass limiting.

Without eviction, every distinct key ever observed persists for the process
lifetime, so an attacker who can vary the key can grow the limiter's memory
without bound on a single replica.

#### Scenario: Expired window is evicted

- **WHEN** a tracked key's window empties as its entries age out
- **THEN** the key is removed from limiter state rather than retained as an empty entry

#### Scenario: Key cap does not disable limiting

- **WHEN** the number of tracked keys reaches the cap
- **THEN** limiting remains in force

### Requirement: Rate limiting is default-on with an explicit exemption list

Rate limiting SHALL apply to the public surface by default. Paths that are not
limited SHALL be named in an explicit exemption list, so that adding an endpoint
brings it under limiting without further action, and exempting one is a
deliberate, visible decision.

This inverts the prior posture, under which only paths beneath a single prefix
were limited and every other route — including a readiness check that performs
a full-season aggregate per request — was unprotected by omission.

#### Scenario: A newly added endpoint is limited by default

- **WHEN** a route is added outside the previously limited prefix
- **THEN** it is rate limited without any change to the limiter configuration

#### Scenario: Readiness is limited

- **WHEN** an unauthenticated client repeatedly requests the readiness endpoint
- **THEN** the requests are rate limited

#### Scenario: Exemptions are enumerated

- **WHEN** a path must not be limited
- **THEN** it appears in the exemption list rather than being excluded by a prefix test

### Requirement: Query parameters are validated at the boundary

Every public query parameter that reaches SQL, a response header, or a response
body SHALL be constrained at the boundary. A season SHALL be accepted only in
the product's season format, through a single shared definition rather than
per-endpoint repetition. Free-text search SHALL carry a maximum length and
SHALL escape `LIKE` metacharacters before use in a pattern match. Identifier
parameters SHALL carry length bounds.

Rejecting a malformed season also removes a silent failure: an unrecognized
season currently returns an empty result set that is indistinguishable from a
season with no data.

#### Scenario: Malformed season is rejected

- **WHEN** a request supplies a season that does not match the season format
- **THEN** the request is rejected with a client error rather than returning empty results

#### Scenario: Search metacharacters are literal

- **WHEN** a search term contains `%` or `_`
- **THEN** those characters match themselves rather than acting as wildcards

#### Scenario: Oversized parameters are rejected

- **WHEN** a search term or identifier exceeds its bound
- **THEN** the request is rejected before reaching the database

### Requirement: Response headers are constructed from sanitized values

No request-supplied value SHALL be interpolated into a response header without
sanitization. Download filenames SHALL be built from a sanitized slug, so that
no input can terminate a quoted header parameter or introduce additional ones.

#### Scenario: Quote in a parameter cannot break out of the filename

- **WHEN** a request supplies a value containing a double quote that reaches a download filename
- **THEN** the emitted header contains a sanitized filename and no injected parameter

### Requirement: Overload and failure produce structured, correlated responses

Connection-pool exhaustion SHALL produce a 503 carrying a `Retry-After` value
rather than an unhandled error. Any otherwise unhandled exception SHALL produce
a JSON response carrying the request correlation identifier that the middleware
records in its logs, so that a reported failure can be located in the logs.

#### Scenario: Pool exhaustion is a retryable 503

- **WHEN** a request cannot obtain a connection before the pool timeout
- **THEN** the response is a 503 with `Retry-After` rather than a 500

#### Scenario: An unhandled error is traceable

- **WHEN** a request fails with an unexpected exception
- **THEN** the JSON response carries the same correlation id logged for that request

### Requirement: Interactive docs work under the product's own policy

The advertised interactive documentation SHALL load its assets from this origin,
and the Content-Security-Policy SHALL NOT be relaxed to admit a third-party
script source. If the documentation is withdrawn instead, the README SHALL stop
advertising it.

A documented URL that renders blank under the policy the product itself sets is
a defect in one of the two; they SHALL agree.

#### Scenario: Docs render under the strict policy

- **WHEN** a browser loads the documentation page
- **THEN** its scripts and styles come from this origin and the policy admits no external script source

### Requirement: Transport and capability headers are asserted

Responses SHALL carry `Strict-Transport-Security` and `Permissions-Policy`
alongside the existing content-security, referrer, and content-type-options
headers.

#### Scenario: Security headers are present

- **WHEN** any response is returned
- **THEN** it carries transport-security and permissions-policy headers
