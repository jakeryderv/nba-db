## MODIFIED Requirements

### Requirement: Rate limiting keys on an identity the client cannot choose

The rate limiter SHALL derive its client key from an identity the caller cannot
select. Where the trusted edge sets a dedicated client-address header that it
overwrites on every request, the limiter SHALL prefer that header, because a
value the proxy always replaces cannot be supplied by the caller at all.

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

- **WHEN** a request carries the trusted edge's client-address header
- **THEN** the limiter keys on it rather than on a position within the forwarding chain

#### Scenario: Adding a proxy layer does not collapse budgets

- **WHEN** an additional trusted proxy is placed in front of the origin
- **THEN** callers keep independent budgets, because identity comes from the header the nearest proxy overwrites rather than from a counted position

## ADDED Requirements

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
