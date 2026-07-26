## Why

`nba.jvs.sh` resolves straight to Railway, so every request — including ones the
rate limiter is about to reject — reaches the single replica and costs it a
connection, a thread, and middleware work before being refused. The apex
`jvs.sh` is already proxied through Cloudflare; this host was the deliberate
exception, held back until the public surface could defend itself. That work
shipped (#27), so the reason to wait is gone.

Putting Cloudflare in front absorbs volumetric traffic before it reaches the
container and serves the static assets — including the 1.5 MB Swagger bundle —
from the edge.

The DNS toggle cannot be flipped on its own. Behind the proxy the forwarded
chain becomes `client, cf-edge`, so the rightmost hop — the value the limiter
now keys on — would be Cloudflare's near-constant edge address, collapsing
every caller into one shared budget. The identity derivation has to change in
the same breath as the DNS record.

## What Changes

- The rate limiter prefers `CF-Connecting-IP` when present, falling back to the
  existing forwarded-hop derivation. Cloudflare sets and overwrites that header
  on every request, making it unforgeable by position rather than by counting.
- The Cloudflare zone is preflighted before the flip: Rocket Loader and Email
  Obfuscation confirmed off, SSL/TLS mode confirmed Full (strict).
- `nba.jvs.sh` is switched to proxied, as an explicit operator step.
- The false-alarm warning introduced by #27 is suppressed for internal probes:
  Railway's readiness prober arrives without a forwarded header, so every deploy
  currently logs a warning claiming rate limiting is degraded when it is not.

Not doing: any caching rule over `/api/`. Cloudflare's defaults do not cache
JSON responses, and adding a rule would put the release observer's
revision-consistency check at risk of reading a cached response from the
previous deploy. If that changes later, the guard is specified here first.

## Capabilities

### Modified Capabilities

- `public-api-surface`: the limiter-identity requirement gains precedence for a
  proxy-set unforgeable header over positional derivation. A new requirement
  forbids the delivery path from injecting script into responses, because the
  app's own `script-src 'self'` policy makes any such injection a break.
- `release-readiness`: a new requirement that release verification observes
  origin responses rather than cached ones, so a future edge-cache rule cannot
  quietly satisfy the check with a response from the previous release.

Deliberately not specced: origin-bypass exposure. The Railway hostname is
already in certificate transparency logs, and Railway offers no origin IP
allowlisting, so any requirement to prevent bypass would be unenforceable
aspiration. It is recorded in the design as an accepted limitation instead.

## Impact

- `app/middleware.py`: client-key derivation, probe-aware warning suppression.
- `tests/`: coverage for header precedence, forged `CF-Connecting-IP` from a
  non-proxied path, and warning suppression for internal probes.
- `README.md`: the `TRUSTED_PROXY_HOPS` row gains the Cloudflare interaction.
- `docs/operations/production-status.md`: records the proxied posture.
- Cloudflare zone `jvs.sh`: one DNS record changed; no zone settings changed,
  only verified.
- No database, ETL, schema, or payload-shape impact.
