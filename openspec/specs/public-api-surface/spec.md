# public-api-surface Specification

## Purpose

The API is public, anonymous, and unauthenticated, served by a single replica in
front of one database. There is no account to rate-limit against and no tier to
degrade, so every protection has to derive from the request itself.

That makes two properties load-bearing. Identity must come from something the
caller cannot choose, because a limiter keyed on attacker-supplied input imposes
no limit at all. And limiter state must be bounded, because anything a caller can
vary becomes a way to grow memory on the one process serving everyone.

The surface is read-only by design, so these requirements are about availability
rather than integrity: the failure this capability exists to prevent is one
client, deliberately or accidentally, consuming the capacity of all of them.
## Requirements
### Requirement: Rate limiting keys on an identity the client cannot choose

The rate limiter SHALL derive its client key from an identity the caller cannot
select. Where the trusted edge sets a dedicated client-address header that it
overwrites on every request, the limiter SHALL prefer that header, because a
value the proxy always replaces cannot be supplied by the caller at all.

Such a header SHALL be trusted only where the deployment declares which edge it
sits behind, and the declaration SHALL default to absent. Nothing in a request
establishes the topology — every header is caller-supplied, and the peer address
is the platform edge whether or not another proxy sits in front — so an
undeclared environment SHALL trust no edge header at all. An unrecognized
declaration SHALL be treated as no declaration.

Defaulting to trust would place the failure in the wrong direction: an
environment reachable without the edge in front would accept a caller-chosen
identity, which is the same defect as keying on the leftmost forwarded value.

Otherwise the limiter SHALL derive the key from the hop attributed by the
trusted edge proxy, not from the first value of a client-supplied forwarding
header. Where a forwarding header carries multiple hops, the limiter SHALL read
the hop appended by the trusted proxy rather than the leftmost value, which is
under the caller's control.

A limiter keyed on attacker-chosen input imposes no limit at all: it converts a
shared budget into a per-request budget for anyone who varies the header. The
positional derivation is also fragile to topology: adding a proxy in front
shifts which position holds the client, and a stale position silently collapses
every caller into one shared budget. A header the nearest proxy guarantees to
overwrite survives that change; a counted position does not.

The peer address SHALL remain the last-resort fallback only. It is not a
substitute identity: a multi-instance edge presents many peer addresses, so one
caller's requests scatter across them and each scattered key carries its own
budget.

#### Scenario: Forged forwarding header does not mint a new budget

- **WHEN** a client sends a different fabricated forwarding value on each request
- **THEN** every request is attributed to the same client key and the limit applies across them

#### Scenario: Genuine client addresses are distinguished

- **WHEN** two distinct clients reach the app through the edge proxy
- **THEN** they receive independent budgets

#### Scenario: A proxy-set client header takes precedence

- **WHEN** a request carries the trusted edge's client-address header and the deployment declares that edge
- **THEN** the limiter keys on it rather than on a position within the forwarding chain

#### Scenario: An undeclared deployment ignores the edge header

- **WHEN** a request carries an edge client-address header but the deployment declares no edge
- **THEN** the header is ignored and the key comes from the forwarding chain, so a caller varying it cannot mint budgets

#### Scenario: An unrecognized declaration trusts nothing

- **WHEN** the declared edge is not one the application knows how to trust
- **THEN** no edge header is trusted and the condition is reported

#### Scenario: Adding a proxy layer does not collapse budgets

- **WHEN** an additional trusted proxy is placed in front of the origin
- **THEN** callers keep independent budgets, because identity comes from the header the nearest proxy overwrites rather than from a counted position

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
rather than an unhandled error. This SHALL cover every way the pool refuses a
caller — both waiting past the pool timeout and finding the wait queue already
full. These arrive as distinct exception types that are siblings rather than
one deriving from the other, so handling the one that is easiest to reach
leaves ordinary overload returning an unhandled error.

Any otherwise unhandled exception SHALL produce a JSON response carrying the
request correlation identifier that the middleware records in its logs, so that
a reported failure can be located in the logs.

#### Scenario: Pool exhaustion is a retryable 503

- **WHEN** a request cannot obtain a connection before the pool timeout
- **THEN** the response is a 503 with `Retry-After` rather than a 500

#### Scenario: A full wait queue is also a retryable 503

- **WHEN** a request arrives while the pool's wait queue is already full
- **THEN** the response is a 503 with `Retry-After` rather than an unhandled error

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

### Requirement: The delivery path does not inject content into responses

No layer between the application and the browser SHALL inject script, style, or
markup into responses. Edge features that rewrite response bodies — script
loaders, address obfuscators, injected analytics — SHALL be confirmed disabled
before the delivery path is changed, and SHALL remain disabled.

This is not a deployment preference. The application declares
`script-src 'self'` with no inline allowance, so injected script is blocked by
the browser and whatever it wrapped stops working. The failure appears in the
browser, not in any origin log or healthcheck, and it arrives via a toggle in a
control panel rather than a commit — so it will not be caught by tests or the
release observer.

#### Scenario: A body-rewriting edge feature is refused

- **WHEN** a delivery-layer feature would inject script into responses
- **THEN** it is left disabled, because the content-security policy would block it and break the page

#### Scenario: Delivery changes are preflighted

- **WHEN** the delivery path in front of the origin changes
- **THEN** the absence of body-rewriting features is confirmed before the change takes effect

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
