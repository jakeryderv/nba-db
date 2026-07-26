## Context

`nba.jvs.sh` is a `CNAME` to Railway with `proxied=false`; the apex `jvs.sh` is
already proxied, so this host is the exception rather than the rule. The
Railway-generated hostname returns `404 Application not found` — the app is
routed by `Host` header on the custom domain only.

Today's topology is one trusted hop. Railway's edge appends to
`X-Forwarded-For`, confirmed in production: 26 requests to limited paths
produced zero short-chain warnings, so `TRUSTED_PROXY_HOPS=1` is correct. That
edge is many peers — `100.64.0.5`, `.9`, `.10`, `.13`, `.14`, `.15`, `.17`,
`.19`, `.20` and more — which is why the peer-address fallback is weak and the
hop derivation is load-bearing.

Adding Cloudflare makes it two hops. That is the entire reason this is a code
change and not a DNS toggle.

## Goals / Non-Goals

**Goals:**

- Absorb volumetric traffic before it reaches the single replica.
- Serve static assets, including the 1.5 MB Swagger bundle, from the edge.
- Keep per-client rate limiting correct across the topology change.
- Make the identity derivation resilient to a future proxy layer, rather than
  correct only for the current hop count.

**Non-Goals:**

- Caching `/api/` responses. Cloudflare's defaults do not cache JSON, and a rule
  would put release verification at risk. Specified as a guard, not built.
- Cloudflare WAF, bot management, or edge rate limiting. The app limits itself;
  adding a second limiter with different keys and windows is a debugging burden
  for no clear gain at this traffic level.
- Removing the app's own rate limiting. It stays as the enforcement of record —
  the edge is defense in depth, not a replacement.
- Closing origin bypass. See Risks.

## Decisions

### Prefer `CF-Connecting-IP`, fall back to the hop derivation

Cloudflare sets `CF-Connecting-IP` to the connecting client and overwrites it on
every request, so a caller cannot supply it. That is categorically stronger than
counting positions: position depends on topology, and topology changes silently.

The fallback keeps today's behavior intact, so the code is correct both before
and after the DNS flip. That ordering matters — it means the code can ship,
bake, and be reverted independently of the DNS change.

*Alternative rejected:* setting `TRUSTED_PROXY_HOPS=2` and leaving the
derivation positional. It works, but couples a DNS setting to an environment
variable with no mechanical link between them; getting it wrong collapses every
caller into one budget, and the only signal is a log warning. It also breaks
again on the next topology change.

*Note on trust:* `CF-Connecting-IP` is only meaningful when Cloudflare is
actually in front. A caller reaching the origin directly could forge it. This is
acceptable for the same reason the forwarded-hop derivation is: the app is
reachable only through a proxy, and a direct-path attacker can forge the
forwarded chain today just as easily. The header does not widen the exposure; it
removes the topology coupling. Origin-side allowlisting is the real fix and
Railway does not offer it.

### Preflight the zone by hand, not by script

The DNS token at `~/.config/cloudflare/jvs-sh-dns-token` is scoped to DNS edits:
reading `rocket_loader`, `email_obfuscation`, and `ssl` returns
`Authentication error` / `Unauthorized`. So the preflight is an operator step in
the dashboard, or a new token with Zone Settings:Read.

Minting a broader token for a one-time check is worse than looking: it creates a
long-lived credential with more authority than any routine task needs. The
verification steps below are written to catch a wrong setting from the outside
anyway — a body-injecting feature shows up as a CSP violation in the browser
check, which is the failure that actually matters.

### The DNS flip is an operator action

Changing where a public domain points is outward-facing and immediate. It is a
typed, deliberate step by a person, never something automation performs — the
same posture the repo already takes for anything that touches production.

### Suppress the probe warning by peer range, not by path

Railway's readiness prober reaches the container directly, so it has no
forwarded header and trips the short-chain warning on every deploy. Suppressing
by path (`/ready`) would also silence the genuine case where public readiness
traffic arrives without a forwarded chain — which is exactly the condition worth
knowing about. Suppressing by peer range (loopback and CGNAT
`100.64.0.0/10`, which is where Railway's internal probes originate) keeps the
warning for anything arriving from a public path.

## Risks / Trade-offs

- **Cloudflare becomes a failure domain** → a Cloudflare incident takes the site
  down even when Railway is healthy. Mitigation is that the flip is reversible
  in one DNS edit, and the record's prior state is recorded in the tasks.
- **Origin bypass stays open** → the Railway hostname is already in certificate
  transparency logs, and anyone holding it can send `Host: nba.jvs.sh` straight
  to Railway, skipping Cloudflare entirely. Railway offers no origin IP
  allowlisting, so this cannot be closed from here. Accepted: the app's own rate
  limiting and validation remain the enforcement of record, which is why they are
  not being relaxed.
- **A future cache rule could corrupt release verification** → the observer
  asserts a consistent `X-Release-Revision` across responses, and
  `/api/shot-chart.csv` carries a cacheable extension by default. Nothing breaks
  today because Cloudflare does not cache JSON by default, but the guard is now a
  requirement so the next person adding caching meets it first.
- **A CSP-hostile toggle breaks the dashboard silently** → the failure is in the
  browser only; no origin log, healthcheck, or release check would notice. The
  browser verification step exists specifically to catch it, and the requirement
  records why the toggles stay off.
- **`CF-Connecting-IP` trusted without verifying the peer** → discussed above;
  no wider than today's exposure, and closing it properly needs origin
  allowlisting that Railway does not provide.

## Open Questions

- Should the static assets get a longer edge TTL than the origin's one hour?
  Deferred: measure first, and the vendored Swagger bundle is immutable per
  release anyway.
