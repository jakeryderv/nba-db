# Production changelog

What changed in the running system, and when. This is an operator's record —
dataset promotions, edge and DNS changes, credential posture, and anything that
altered how production behaves.

It is deliberately not a list of merges. Per-release engineering notes are
generated from pull requests on the
[Releases page](https://github.com/jakeryderv/nba-db/releases); the current
verified state of production is in
[production-status.md](production-status.md). Add an entry here only when
something an operator would need to know about production actually changed.

## 2026-07-26

- **`nba.jvs.sh` is now proxied through Cloudflare.** Traffic path is Cloudflare
  edge, then Railway edge, then the app. Static assets serve from Cloudflare's
  cache; `/api/` responses stay uncached so release verification reads the
  origin. Reverting is one DNS edit — see production-status.md for the record id.
- **Removed the generated Railway service domain**
  (`nba-api-production-0cd7.up.railway.app`). It was still serving the
  application, which meant public traffic could bypass Cloudflare entirely, and
  it was published as the repository's homepage link. `nba.jvs.sh` is now the
  only route in.
- **Disabled Cloudflare Web Analytics RUM auto-injection.** It injected a beacon
  script that the application's `script-src 'self'` policy blocked on every page
  load. Server-side Cloudflare analytics are unaffected.
- **Public API surface hardened.** Rate limiting now keys on an address the
  caller cannot forge, covers the whole surface by default with an explicit
  exemption list, and bounds its own memory. Query parameters are validated at
  the boundary, pool exhaustion returns a retryable 503, and unhandled errors
  return the request correlation id. `/docs` now renders, from self-hosted
  assets, under the existing policy.

## 2026-07-25

- **Adopted OpenSpec.** `openspec/specs/` became the source of truth for the
  system's invariants and binding decisions.
- **`nba.jvs.sh` became the canonical production URL.**
- **Failed closed in three places**: readiness gating for deploys, read-only
  credential resolution, and backup validity. Railway now gates deploys on
  `/ready` rather than `/health`, so a deploy against an empty or unverified
  database never receives traffic.

## 2026-07-22

- **2025-26 Regular Season promoted to production** — 1,230 games, 582
  participating players, 219,160 shot attempts, verified against official NBA
  totals. Production runs a single verified season at a time.
- **Automated production operations**: scheduled backup and restore drills,
  release observation, and anonymous product signals.
