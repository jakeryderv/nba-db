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

- [ ] 3.1 **Operator, before merge:** set `TRUSTED_EDGE=cloudflare` on the production service
- [x] 3.2 Leave staging undeclared, which is what restores correct limiting there
- [x] 3.3 `make check`, `make test`, `make dagger-check`
- [ ] 3.4 Merge only after 3.1, then confirm no forwarded-depth warnings appear in production logs
- [ ] 3.5 Archive the change
