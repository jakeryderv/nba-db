## 1. Gate promotion on a staged season

- [x] 1.1 Add a staging confirmation that compares manifest digest, verification status, and counts against the dataset being promoted
- [x] 1.2 Require `--staging-api-url` on the promote subcommand, reusing the existing credential-free HTTPS validation
- [x] 1.3 Run the check before the backup and outside the operation lock
- [x] 1.4 Guard `STAGING_API_URL` in the Makefile's `require-promotion`
- [x] 1.5 Test: a different manifest, an unreachable staging, and a matching dataset

## 2. Documentation

- [x] 2.1 Document the gate in the promotion step of `docs/operations/season-lifecycle.md`
- [x] 2.2 Record `STAGING_API_URL` in the README configuration table

## 3. Verification

- [x] 3.1 `make check`, `make test`
- [x] 3.2 `make dagger-check`
- [x] 3.3 Merged as `b6853f5`; archived here

## 4. Deliberately deferred

- [ ] 4.1 The code delivery model — production tracking a release branch that trails `main` — is not part of this change. It rewrites the "merge to main deploys to production" contract in AGENTS.md, README, CONTRIBUTING, the PR template, and the release observer trigger, and needs its own change rather than riding along with a data-path fix
