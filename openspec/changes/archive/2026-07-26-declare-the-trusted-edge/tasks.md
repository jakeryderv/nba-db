## 1. Edge declaration

- [x] 1.1 Read `TRUSTED_EDGE` once at middleware construction, defaulting to absent
- [x] 1.2 Honor the edge client-address header only when the declaration matches a known edge
- [x] 1.3 Warn on an unrecognized declaration and trust nothing
- [x] 1.4 Test: an undeclared deployment ignores the header and keys on the forwarding chain
- [x] 1.5 Test: a declared deployment honors the header and separates callers behind one edge
- [x] 1.6 Test: an unrecognized declaration trusts nothing

## 2. Pool exhaustion

- [x] 2.1 Register the retryable-503 handler on `TooManyRequests` as well as `PoolTimeout`
- [x] 2.2 Test: a full wait queue yields 503 with `Retry-After`, not a 500

## 3. Rollout

- [x] 3.1 `TRUSTED_EDGE=cloudflare` set on the production service before merge; staging deliberately left undeclared
- [x] 3.2 Leave staging undeclared, which is what restores correct limiting there
- [x] 3.3 `make check`, `make test`, `make dagger-check`
- [x] 3.4 Merged as `b7bf724`. Production serves that revision and logs zero forwarded-depth observations, which is positive evidence the declared-edge path is in use — the observation only runs on the positional fallback
- [x] 3.5 Archive the change
