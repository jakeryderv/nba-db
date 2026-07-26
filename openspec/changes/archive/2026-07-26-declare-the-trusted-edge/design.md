## Context

Two defects from the same day's work, both in how the public surface handles
things it cannot observe about its own environment.

The limiter change that accompanied the Cloudflare flip preferred
`CF-Connecting-IP` on the argument that Cloudflare overwrites it on every
request. That argument is sound, and the implementation dropped its premise: it
trusts the header wherever it appears, including where Cloudflare is not in
front. Staging is exactly that case — publicly reachable, no proxy, serving the
same dataset.

The pool handler covered `PoolTimeout` only. `TooManyRequests` is raised when
the wait queue is full, and the two are siblings under `OperationalError`.

## Goals / Non-Goals

**Goals:**

- Trust an edge header only where an edge is known to be in front.
- Fail in the safe direction when the environment is unknown.
- Return a retryable 503 for every way the pool refuses a caller.

**Non-Goals:**

- Detecting the proxy from the request. See the decision below.
- Reworking pool sizing. The threadpool/pool ratio is worth revisiting, but
  shedding load correctly is the fix for returning 500s; capacity is a separate
  question with its own trade-offs.

## Decisions

### The deployment declares the edge; the app does not guess

`TRUSTED_EDGE` names the edge in front, and is unset by default.

*Alternatives rejected:*

- **Require a second edge-only header, such as `CF-Ray`.** Both headers are
  equally forgeable by anyone who can reach the origin directly, so this raises
  effort without changing the security property. Security theater.
- **Require the forwarded chain to be at least two hops.** A caller can pad the
  chain: sending `X-Forwarded-For: a, b` produces a three-hop chain after the
  platform appends. Forgeable upward, so useless as a gate.
- **Check the peer against Cloudflare's published ranges.** The strongest option
  in principle, but the peer is Railway's edge in both topologies — Cloudflare
  never connects to this container directly — so the check would compare against
  the wrong hop entirely.

Nothing in the request distinguishes the two topologies. A declaration is
therefore not a convenience; it is the only mechanism that can be correct.

### The default is no trust, not trust

An environment that has an edge but forgets to declare it degrades to positional
derivation: still bounded, still per-caller where the chain allows, and loudly
visible through the existing forwarded-depth warning. An environment that lacks
an edge but trusts the header accepts caller-chosen identity and silently stops
limiting. The first failure is recoverable and observable; the second is neither.

### Register the handler on both exception types

Starlette resolves handlers by walking `type(exc).__mro__`, so a handler
registered on each concrete class is found. Registering on the shared
`OperationalError` ancestor would be broader than intended — it would also
swallow genuine database operational errors that deserve the catch-all's
correlation id and stack trace.

## Risks / Trade-offs

- **Shipping the code before the production variable is set** → production falls
  back to positional derivation behind two proxies, the rightmost hop is
  Cloudflare's edge, and every caller shares one budget. Mitigation is ordering:
  set the variable first, where it is inert until this code exists to read it.
  The forwarded-depth warning would also surface it after the fact.
- **A future edge that sets a differently named header** → needs a code change,
  not just configuration. Accepted: the set of edges this app understands should
  be explicit and reviewed, not string-configurable.
