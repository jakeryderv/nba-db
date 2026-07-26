## Why

The limiter prefers `CF-Connecting-IP` because Cloudflare overwrites it on every
proxied request, making it unforgeable. That reasoning holds only where
Cloudflare is actually in front. The implementation trusts the header wherever
it appears, and staging is publicly reachable with no Cloudflare in front — so
on staging any caller can rotate that header per request and mint an unlimited
number of budgets.

That is the same defect the forwarded-hop derivation was written to avoid,
reintroduced through a different header. It contradicts the requirement it was
added under: *rate limiting keys on an identity the client cannot choose*.

Production is not currently exploitable, because Cloudflare overwrites the
header and the generated Railway domain has been removed. But that is a property
of today's environment rather than of the code: turning the proxy off would make
production silently vulnerable, with nothing failing to indicate it.

Separately, pool exhaustion has two failure modes and only one is handled.
`TooManyRequests` — raised when the wait queue is full — is a *sibling* of
`PoolTimeout` under `OperationalError`, not a subclass, so it falls through to
the catch-all and returns a 500 with a stack trace for ordinary overload.

## What Changes

- The edge client-address header is honored only where the deployment declares
  which edge it sits behind, via `TRUSTED_EDGE`. The declaration defaults to
  absent, so an environment with no edge in front is safe by default rather than
  by omission.
- An unrecognized declaration trusts nothing and logs a warning, rather than
  falling back to trusting the header.
- `TooManyRequests` joins `PoolTimeout` on the retryable-503 handler.

Not doing: detecting Cloudflare from the request itself. Nothing in a request
proves the topology — every header is caller-supplied, and the peer address is
the platform edge either way. A declaration is the only honest mechanism.

## Capabilities

### Modified Capabilities

- `public-api-surface`: the limiter-identity requirement gains the condition
  under which a proxy-set header may be trusted at all, and the requirement on
  overload responses is clarified to cover both pool-exhaustion modes rather
  than one.

## Impact

- `app/middleware.py`: edge declaration read once at middleware construction and
  threaded into client-key derivation.
- `app/main.py`: the exhaustion handler covers both exception types.
- `tests/`: coverage for an undeclared edge, a declared edge, an unrecognized
  declaration, and wait-queue overflow.
- **Deployment ordering matters.** Production must have `TRUSTED_EDGE=cloudflare`
  set *before* this ships. Without it, production falls back to positional
  derivation behind two proxies, where the rightmost hop is Cloudflare's edge
  and every caller collapses into one shared budget.
- Staging deliberately gets no declaration, which restores correct per-caller
  limiting there.
