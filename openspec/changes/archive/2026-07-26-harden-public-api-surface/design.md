## Context

The app runs as a single Railway replica behind Railway's edge proxy. All
routes are sync `def` handlers on Starlette's default threadpool (~40 threads)
against a 10-connection pool. `RequestPolicyMiddleware` already establishes a
request correlation id, applies security headers, and rate limits — but only
for paths under `/api/`, keyed on a value the caller controls.

Two facts discovered while designing this change alter the obvious
implementations, and both are load-bearing below:

1. `uvicorn`'s `ProxyHeadersMiddleware` with `--forwarded-allow-ips="*"`
   returns `x_forwarded_for_hosts[0]` — the **leftmost**, caller-controlled
   value. Adopting the standard proxy-header flags with a wildcard would
   reproduce exactly the spoofing bug we are fixing, while looking like a fix.
2. FastAPI's `get_swagger_ui_html` emits an **inline** `<script>` block to
   construct `SwaggerUIBundle`. Under `script-src 'self'` with no nonce and no
   `'unsafe-inline'`, self-hosting the bundle is necessary but not sufficient —
   the page still renders blank because the initializer itself is blocked.

## Goals / Non-Goals

**Goals:**

- A rate-limit identity the caller cannot choose, with bounded limiter state.
- Limiting that covers new routes by default rather than by prefix coincidence.
- Boundary validation for every public parameter reaching SQL or a header.
- Structured, correlated responses for overload and unexpected failure.
- A working `/docs` under the existing CSP, with no third-party script source.

**Non-Goals:**

- Caching `/ready`. Bringing it under the limiter addresses its unauthenticated
  cost without putting staleness into a contract that deploy gating and
  promotion verification read as live truth. `release-readiness` is unchanged.
- Converting handlers to `async`. The threadpool/pool ratio is a real
  constraint, but changing the concurrency model is a larger change than this
  hardening pass and would need its own proposal.
- Distributed or persistent rate limiting. The process-local limiter remains
  correct for a single replica; it becomes wrong if the service is ever scaled
  out, and that is the trigger to revisit.
- Authenticating any endpoint. The product stays anonymous and read-only.

## Decisions

### Take the rightmost forwarding hop, not uvicorn's proxy-header handling

Each proxy **appends** the peer it received the request from, so a client that
sends `X-Forwarded-For: fake` reaches the app as `fake, <real-client>`. The
caller can prepend entries but cannot append past the edge, which makes the
rightmost entry the only value in that header the caller does not control.

The limiter therefore reads the last comma-separated value, with the number of
trusted hops configurable (default 1) so the position can be corrected by
configuration rather than a code change. If no forwarding header is present,
fall back to the peer address as today.

*Alternative rejected:* `--proxy-headers --forwarded-allow-ips="*"`. Per
finding 1 this returns the leftmost value, i.e. no fix at all. Enumerating
Railway's edge CIDRs would let uvicorn walk the list correctly, but that list
is not a stable published contract, and a stale list silently degrades to
trusting the wrong hop.

*Verified (2026-07-26), partially.* Deploy logs show uvicorn's peer address as
`100.64.0.2`, a CGNAT-range internal address: all ingress arrives through
Railway's edge and the service is not directly reachable. The forwarded chain
itself is visible in no available log — Railway's HTTP logs are not exposed for
this deployment — so append-vs-replace was not read directly.

That distinction turns out not to matter: the rightmost hop is the client under
**both** behaviors (`forged, client` when appending; `client` when replacing).
The derivation fails only under pure pass-through, which no reverse proxy does,
and under which the previous leftmost-keyed code was equally broken. What is
left is instrumentation rather than assumption: the middleware logs the chain
depth on first request and warns whenever it is shorter than the configured
hop count, so a wrong value announces itself instead of silently collapsing
every caller into one budget.

### Cap the limiter by evicting least-recently-used keys, not by rejecting

Deleting a key when its deque empties handles ordinary traffic. The hard cap is
a backstop for a flood of distinct keys; on reaching it, evict the
least-recently-used entry and log once. Rejecting requests at the cap would let
an attacker who fills the table trigger 429s for everyone — turning a memory
bound into a denial-of-service amplifier.

### Exemption list instead of prefix matching

Dispatch limits every request except paths in an explicit exemption set. This
inverts the default so a new route is covered on the day it is added.
`/static/` is the expected exemption; `/health` should stay exempt so platform
liveness probing is never rate limited, while `/ready` becomes limited with a
budget generous enough for Railway's healthcheck cadence.

### Validate season by format, and be precise about what that fixes

A shared `SeasonQuery = Annotated[str, Query(pattern=r"^\d{4}-\d{2}$", max_length=7)]`
replaces the repeated bare `str` parameters. Note that this rejects *malformed*
seasons only; a well-formed but unloaded season (`1999-00`) still returns an
empty result. The issue describes this as fixing "unknown seasons silently
returning empty results" — it fixes the malformed half. Validating against
loaded seasons would require a database lookup per request on a
single-season product, which is not worth it; the empty result for a
well-formed unloaded season is correct behavior.

### Escape LIKE metacharacters explicitly

Escape `\`, `%`, and `_` in the search term and issue `ILIKE %s ESCAPE '\'`, so
the pattern semantics are explicit in the SQL rather than dependent on session
settings. This is a correctness fix as much as a hardening one: a search for a
literal `%` currently matches everything.

### Serve the Swagger initializer as a static file

Per finding 2, self-hosting `swagger-ui-bundle.js` and `swagger-ui.css` under
`/static/` is not enough. Disable the built-in docs route and serve a custom
one whose HTML references both the vendored bundle **and** a vendored
`swagger-init.js` holding the initializer — no inline script anywhere.

*Alternatives rejected:* a CSP nonce would require per-request policy
generation in middleware for one page; a hash would need recomputing whenever
FastAPI changes its template. Both are more moving parts than a static file.

### Apply response policy to error responses too

Starlette's `ServerErrorMiddleware` sits outside `RequestPolicyMiddleware`, so
a response produced by a catch-all exception handler bypasses
`_apply_response_policy` and would ship without security headers. The handlers
must apply the policy themselves, or the error must be converted inside the
middleware. Whichever is chosen, a test must assert that a 500 carries the same
headers as a 200 — this is the kind of gap that reappears silently.

### Open the pool in lifespan startup

`lifespan` currently only closes the pool. Opening it at startup removes the
unsynchronized check-then-create in `get_pool()` reached from threaded
handlers. Startup failure then surfaces as a failed deploy rather than as a
first-request error — which is the desired behavior given deploys are gated on
`/ready` anyway.

## Risks / Trade-offs

- **The rightmost-hop inference is wrong for Railway** → the limiter would key
  on a value that is still caller-controlled, or on the edge's own address
  (collapsing all clients into one budget, which would be immediately visible
  as spurious 429s). Verify against production logs before merge; the
  configurable hop count is the remediation if the position differs.
- **Vendored Swagger assets go stale** → they are pinned, unversioned by the
  package manager, and will drift from FastAPI's expected version across
  upgrades. Record the version and source URL next to the files so a future
  upgrade is mechanical.
- **Swagger UI may need `style-src 'unsafe-inline'`** → it injects style tags at
  runtime, which the current policy blocks. If the page still renders wrong
  after removing the inline script, the fallback is `docs_url=None` plus a
  README change rather than weakening `style-src` globally. The browser suite
  should assert the page actually renders, not merely that it returns 200.
- **Stricter validation rejects requests that used to work** → dashboard URLs
  are shareable and may carry old parameters. The formats accepted are those
  the UI already produces, but the browser suite should exercise a shared
  shot-chart URL end to end.
- **Limiting `/ready` could throttle the platform healthcheck** → give it a
  budget well above Railway's probe cadence, and confirm the deploy still
  passes its healthcheck in staging before promoting.

## Open Questions

- ~~Does Railway's edge append to `X-Forwarded-For`, or replace it?~~ Resolved
  as far as it can be from outside: ingress is edge-only, and the derivation is
  correct under both behaviors. The configured depth is now self-reporting, so
  production confirms it on the next deploy (task 9.6).
- Should `/api/telemetry` (the one non-GET route) keep a separate budget from
  read traffic? It is currently limited in the same group as reads.
