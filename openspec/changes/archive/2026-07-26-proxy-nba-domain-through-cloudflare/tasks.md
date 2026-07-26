## 1. Client identity

- [x] 1.1 Prefer `CF-Connecting-IP` in `_client_key` when present and well-formed, falling back to the existing forwarded-hop derivation, then to the peer address
- [x] 1.2 Bound and sanitize the header value the same way the forwarded hop is, so a malformed value cannot become an oversized or unbounded key
- [x] 1.3 Test: the header takes precedence over the forwarded chain when both are present
- [x] 1.4 Test: with the header present, two callers behind the same edge keep independent budgets
- [x] 1.5 Test: with the header absent, behavior is byte-for-byte today's — the pre-flip path must not regress
- [x] 1.6 Test: a two-hop chain (`client, cf-edge`) without the header still resolves to a per-caller key, so a partial rollout degrades rather than collapses

## 2. Probe warning

- [x] 2.1 Suppress the short-chain warning for requests whose peer is loopback or CGNAT `100.64.0.0/10`, keeping it for anything arriving from a public path
- [x] 2.2 Test: an internal-range peer with no forwarded header logs no warning; a public peer with a short chain still does

## 3. Ship the code before touching DNS

- [x] 3.1 `make check` clean
- [x] 3.2 `make test` clean (requires `make db-start`)
- [x] 3.3 `make dagger-check` clean
- [x] 3.4 PR #40, `quality` passed, merged as `6a9cc2f`
- [x] 3.5 Release observer passed on the deploy of `6a9cc2f`; production behavior unchanged, as expected while the header was absent

## 4. Preflight the zone (operator, dashboard)

- [x] 4.1 Recorded before the flip: record id `5c144c57d73860e5d0323ccb36131cb4`, `CNAME nba.jvs.sh -> 5kr2j4o6.up.railway.app`, ttl `1` (auto), `proxied=false`
- [x] 4.2 Rocket Loader: no injection observed in the live browser check after the flip (no `rocket-loader`, `rocketscript`, or `data-cf-settings` markers)
- [x] 4.3 Email Obfuscation: moot — it only rewrites pages containing email addresses, and the served HTML has none. No `__cf_email__` markers observed
- [x] 4.4 SSL/TLS mode is not Flexible: requests complete over HTTP/2 with zero redirects, where Flexible against a HTTPS-redirecting origin produces a redirect loop
- [x] 4.5 Confirmed: the DNS-scoped token cannot read zone settings or RUM configuration (`Authentication error`). **The preflight approach used here was wrong and should not be repeated** — inferring from the already-proxied apex proved nothing, because that page has neither scripts nor email addresses for any feature to rewrite. The flip proceeded on an inference and an injecting feature was in fact enabled; see the Web Analytics note below

## 5. Flip (operator)

- [x] 5.1 Set `proxied=true` on the record, at the operator's explicit instruction
- [x] 5.2 Resolves to Cloudflare: `104.21.36.246`, `172.67.201.101`, `2606:4700:3037::6815:24f6`, `2606:4700:3037::ac43:c965`

## 6. Verify from the outside

- [x] 6.1 `/health` and `/ready` return 200 over HTTP/2 with HSTS, `X-Release-Revision`, and the rest of the response policy intact
- [x] 6.2 Zero forwarded-depth observations or warnings since the flip. The observation only runs on the positional fallback, so its absence is positive evidence that every request resolved via `CF-Connecting-IP`
- [x] 6.3 Dashboard renders with 0 CSP violations, 0 page errors — **after** disabling Web Analytics RUM injection; it reported 1 violation before
- [x] 6.4 `/docs` renders Swagger with 0 CSP violations and 0 failed requests
- [x] 6.5 `check_live.py --api-url https://nba.jvs.sh` passed: 2025-26, 1230 games, 219160 shots, max 277.4ms, manifest digest matched
- [x] 6.6 Release observer passed at 19:32 UTC, after the flip — verifying the live contract through Cloudflare
- [x] 6.7 Static assets `cf-cache-status: HIT` (the 1.5 MB Swagger bundle no longer reaches Railway); `/api/` responses `DYNAMIC`, so release verification still reads the origin as the requirement demands

## 7. Record and close

- [x] 7.1 Pulled forward into the code PR rather than done after the flip: the README would otherwise describe identity derivation incorrectly for the whole cycle between shipping the code and moving DNS
- [x] 7.2 Record the proxied posture in `docs/operations/production-status.md`
- [x] 7.3 Run `/opsx:archive proxy-nba-domain-through-cloudflare`

## Rollback

- [x] R.1 Not needed. Retained for reference: if the dashboard breaks, `/docs` breaks, or callers start sharing a budget: set `proxied=false` on the record. That reverts the topology in one edit; the code change is inert without the proxy and does not need reverting
