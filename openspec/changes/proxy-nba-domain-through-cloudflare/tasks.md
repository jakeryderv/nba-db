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
- [ ] 3.4 Open the PR, confirm `quality` passes, merge
- [ ] 3.5 Confirm the release observer passes and production is unchanged — the code is a no-op until the DNS record moves

## 4. Preflight the zone (operator, dashboard)

- [ ] 4.1 Record the current DNS record exactly as it stands, so the flip can be reverted without reconstructing it: `CNAME nba.jvs.sh -> 5kr2j4o6.up.railway.app`, `proxied=false`
- [ ] 4.2 Confirm Rocket Loader is **off** for the zone
- [ ] 4.3 Confirm Email Obfuscation is **off** for the zone
- [ ] 4.4 Confirm SSL/TLS mode is **Full (strict)** — not Flexible, which would put plaintext between Cloudflare and the origin behind a padlock
- [ ] 4.5 Note that the DNS-scoped token cannot read these settings, so this is a dashboard check; if it should be automatable later, mint a Zone Settings:Read token deliberately rather than widening the existing one

## 5. Flip (operator)

- [ ] 5.1 Set `proxied=true` on the `nba.jvs.sh` record — an explicit, typed operator action, never automation
- [ ] 5.2 Confirm DNS now answers with Cloudflare addresses rather than Railway's

## 6. Verify from the outside

- [ ] 6.1 `https://nba.jvs.sh/health` and `/ready` return 200 with the expected headers
- [ ] 6.2 `railway logs` shows no short-chain warnings for public traffic after the flip — the direct signal that identity derivation survived the topology change
- [ ] 6.3 Load the dashboard in a browser: it renders, and the console shows no CSP violations (the check that catches a body-injecting edge feature)
- [ ] 6.4 Load `/docs` in a browser: Swagger renders, no CSP violations
- [ ] 6.5 `scripts/check_live.py` passes against the proxied domain
- [ ] 6.6 Confirm the release observer passes on the next deploy
- [ ] 6.7 Confirm static assets are served from the edge and API responses are not cached, so release verification still reads the origin

## 7. Record and close

- [x] 7.1 Pulled forward into the code PR rather than done after the flip: the README would otherwise describe identity derivation incorrectly for the whole cycle between shipping the code and moving DNS
- [ ] 7.2 Record the proxied posture in `docs/operations/production-status.md`
- [ ] 7.3 Run `/opsx:archive proxy-nba-domain-through-cloudflare`

## Rollback

- [ ] R.1 If the dashboard breaks, `/docs` breaks, or callers start sharing a budget: set `proxied=false` on the record. That reverts the topology in one edit; the code change is inert without the proxy and does not need reverting
