## 1. Resolve the blocking unknown

> **PARTIALLY RESOLVED (2026-07-26).** With Railway authenticated, deploy logs
> show uvicorn's peer address as `100.64.0.2` — a CGNAT-range internal address,
> confirming all ingress arrives through Railway's edge proxy and the service
> is not directly reachable. HTTP logs are not exposed for this deployment and
> the app never logged the forwarded chain, so append-vs-replace could not be
> read directly.
>
> This matters less than it first appeared: the rightmost-hop derivation is
> correct whether the edge **appends** (`forged, client` → rightmost is client)
> or **replaces** (`client` → rightmost is client). It fails only under pure
> pass-through, which no reverse proxy does and under which the previous
> leftmost-keyed code was equally broken.
>
> Rather than assume, the middleware now logs the observed chain depth on the
> first request and warns whenever the chain is shorter than
> `TRUSTED_PROXY_HOPS`. Production reports the answer on the next deploy;
> confirming it is task 9.6.

- [x] 1.1 Established the proxy topology from deploy logs (peer `100.64.0.2`, edge-only ingress) and instrumented the app to report the forwarded depth, since the chain itself is not visible in any available log
- [x] 1.2 Hop count kept at the default of 1 and made self-reporting: a mismatch now produces a warning naming `TRUSTED_PROXY_HOPS` rather than silently collapsing every caller into one budget

## 2. Rate-limit identity and bounded state

- [x] 2.1 Replace `_client_key()` with rightmost-hop derivation, hop count from an env var defaulting to 1, falling back to the peer address when no forwarding header is present
- [x] 2.2 Delete a key from `SlidingWindowLimiter._requests` when its deque empties
- [x] 2.3 Add a hard entry cap with least-recently-used eviction and a single log line on first eviction; never reject a request because the cap was reached
- [x] 2.4 Test: varying forged `X-Forwarded-For` values across requests share one budget
- [x] 2.5 Test: distinct real client addresses get independent budgets
- [x] 2.6 Test: an emptied window removes its key, and the cap bounds entry count without disabling limiting

## 3. Default-on limiting

- [x] 3.1 Replace the `/api/` prefix test with limit-by-default plus an explicit exemption set (`/static/`, `/health`)
- [x] 3.2 Give `/ready` a budget comfortably above Railway's healthcheck cadence
- [x] 3.3 Test: a route outside `/api/` is limited without limiter configuration changes; exempt paths are not

## 4. Input validation

- [x] 4.1 Add a shared `SeasonQuery` annotated type and apply it to every endpoint taking `season`
- [x] 4.2 Add `max_length` to `search` and escape `\`, `%`, `_` before `ILIKE`, issuing `ESCAPE '\'` explicitly
- [x] 4.3 Add length bounds to `game_id` on both endpoints that accept it
- [x] 4.4 Build the shot-chart CSV filename from a sanitized slug instead of interpolating `season` and subject directly
- [x] 4.5 Test: malformed season rejected with 422; `%` in search matches literally; a quote in a CSV parameter cannot inject a `Content-Disposition` parameter

## 5. Error handling and pool lifecycle

- [x] 5.1 Register a `PoolTimeout` handler returning 503 with `Retry-After`
- [x] 5.2 Register a catch-all handler returning JSON carrying `request.state.request_id`
- [x] 5.3 Ensure error responses carry the same security headers as normal responses, given `ServerErrorMiddleware` sits outside `RequestPolicyMiddleware`
- [x] 5.4 Open the pool in `lifespan` startup and remove the lazy unsynchronized construction in `get_pool()`
- [x] 5.5 Test: pool exhaustion yields 503 with `Retry-After`; an unhandled error returns the logged correlation id; a 500 carries the security headers

## 6. Self-hosted docs

- [x] 6.1 Vendor `swagger-ui-bundle.js` and `swagger-ui.css` under `app/static/`, recording version and source URL alongside them
- [x] 6.2 Vendor `swagger-init.js` holding the `SwaggerUIBundle` initializer, since FastAPI's default HTML inlines it and the CSP blocks inline scripts
- [x] 6.3 Set `docs_url=None` and serve a custom `/docs` route referencing the three static files, with no inline script
- [x] 6.4 Browser test: `/docs` actually renders the operation list, not merely returns 200
- [x] 6.5 Not needed: the browser test confirms Swagger renders under `style-src 'self'` with no CSP violations, so the fallback was not triggered

## 7. Response headers

- [x] 7.1 Add `Strict-Transport-Security` and `Permissions-Policy` to `_apply_response_policy`
- [x] 7.2 Test: both headers present on a normal response

## 8. Query-layer cleanups

- [x] 8.1 Extract shared query functions so `compare_players` and `compare_teams` stop calling route handlers as functions, using one cursor per request
- [x] 8.2 Filter player comparison stats to the requested season in SQL instead of fetching every season and discarding
- [x] 8.3 Change `if team_id:` / `if player_id:` truthiness filters to `is not None`
- [x] 8.4 Test: a comparison request performs a single pool checkout

## 9. Verification and merge

- [x] 9.1 `make check` clean
- [x] 9.2 `make test` clean (requires `make db-start`)
- [x] 9.3 `make dagger-check` clean
- [x] 9.4 Verified indirectly: `check_live.py` cannot run locally (it requires the production `DEFAULT_SEASON` dataset; the seeded test DB holds 2024-25). Confirmed instead that every header it requires is still present on `/health` and the core endpoints, and that the 250-test suite covering payload shapes passes unchanged
- [x] 9.5 Open the PR with `Fixes #27`; verify the `quality` check passes
- [x] 9.6 Release observer passed. **`TRUSTED_PROXY_HOPS=1` confirmed against production**: across 26 requests to limited `/api/*` paths, zero short-chain warnings were emitted, so public traffic arrives with a forwarded chain of at least one hop. The only warning came from Railway's internal `/ready` prober, which legitimately carries no forwarded header. `/ready` is not being throttled
- [x] 9.7 Run `/opsx:archive harden-public-api-surface` to fold the deltas into `openspec/specs/`
