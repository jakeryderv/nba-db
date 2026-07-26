## MODIFIED Requirements

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
