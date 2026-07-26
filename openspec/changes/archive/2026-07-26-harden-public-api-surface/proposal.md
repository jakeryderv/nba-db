## Why

The public HTTP surface is the one part of this product that unauthenticated
strangers interact with continuously, and a full-repo review on 2026-07-25
(#27) found its protections are advisory rather than structural: the rate
limiter is bypassable by any client willing to forge a header, and forging it
also grows an unbounded in-process dictionary on the single replica. Several
query parameters reach SQL and a response header without bounds or escaping,
and pool exhaustion under load surfaces as an unhandled plain-text 500 carrying
no correlation id.

The injection and XSS posture is already strong; this closes the remaining gaps
as one hardening pass, before the surface grows further.

## What Changes

- Rate limiting keys on the trusted proxy hop rather than the first
  client-supplied `X-Forwarded-For` value, so a client can no longer mint a
  fresh budget per request.
- The limiter evicts keys whose window empties and caps its total entries, so
  forged identities cannot exhaust memory.
- Rate limiting becomes default-on for the whole surface with an explicit
  exemption list, rather than covering only paths under `/api/`. This closes
  the unauthenticated cost of `/ready`, which runs a full-season `COUNT(*)`
  per hit.
- `season` gains a shared validated query type across the endpoints that accept
  it; unknown-format seasons are rejected rather than silently returning empty
  results. `search` gains a length bound and `LIKE` metacharacter escaping;
  `game_id` gains a length bound.
- The shot-chart CSV filename is built from a sanitized slug, closing
  header-parameter injection through the `Content-Disposition` value.
- Pool exhaustion returns 503 with `Retry-After`; unhandled errors return JSON
  carrying the request correlation id that the middleware already logs.
- The connection pool is opened during application startup instead of being
  lazily constructed from threaded request handlers, where concurrent cold
  requests can build and leak a second pool.
- Swagger UI assets are self-hosted under `/static`, making the advertised
  `/docs` page work without relaxing the Content-Security-Policy.
- `Strict-Transport-Security` and `Permissions-Policy` join the response policy.
- Comparison endpoints stop calling other route handlers as functions; shared
  query helpers replace them, removing up to five sequential pool checkouts and
  the every-season fetch that discarded all but one row.

Not doing: caching `/ready`. The issue floats it, but bringing `/ready` under
the rate limiter addresses the unauthenticated cost without introducing
staleness into a contract that both Railway deploy gating and promotion smoke
verification read as live truth.

## Capabilities

### New Capabilities

- `public-api-surface`: how the public HTTP surface treats untrusted input and
  load — client identity for rate limiting, bounded limiter state, exemption
  posture, query-parameter validation, response-header construction, and error
  responses.

### Modified Capabilities

- `production-access`: the "Pooled connections are bounded" requirement gains
  the pool's lifecycle — created once at application startup rather than lazily
  from request handlers.

Unchanged: `release-readiness`. Rejecting the `/ready` cache keeps that
contract exactly as specified, which is why that option was chosen.

## Impact

- `app/middleware.py`: client-key derivation, limiter eviction and cap,
  exemption-based dispatch, two new response headers.
- `app/main.py`: shared validated query types, CSV filename construction,
  exception handlers, lifespan startup, self-hosted docs routes, comparison
  query helpers, `is not None` filters.
- `app/db.py`: explicit pool open, removal of the lazy unsynchronized path.
- `app/static/`: vendored Swagger UI bundle and stylesheet.
- `tests/`: coverage for spoofed forwarding headers, limiter eviction,
  rejected parameters, sanitized filenames, and the error handlers.
- No database, ETL, or schema impact. No change to response payload shapes, so
  `scripts/check_live.py` and the browser suite should pass unmodified.
