## Why

The release checklist has always said to stage a season before promoting it, and
nothing enforced it. `season-promote` took a production target, typed
confirmations, and a backup path — but never asked whether the dataset had been
loaded anywhere else first. The rehearsal was honor-system, and the one step
designed to catch a bad dataset before it reaches production could be skipped by
forgetting it.

A 2026-07-26 review of the two environments found this alongside a broader
finding: staging deploys from `main` at the same moment as production — 0.4
seconds apart, same commit — so it cannot gate code either. This change closes
the half that governs data, which is the half that matters most here: code
deploys are already gated by the readiness healthcheck and verified afterward by
the release observer, while a bad dataset promotion replaces the contents of the
production database.

## What Changes

- Promotion confirms staging is already serving the exact dataset being
  promoted — same manifest digest, verification passed, matching counts —
  before it takes a backup or touches production.
- The confirmation queries staging's public dataset status rather than accepting
  an assertion, so it cannot be satisfied by claiming the step happened.
- `STAGING_API_URL` becomes required for promotion, guarded in the Makefile
  alongside the existing typed confirmations.

## Capabilities

### Modified Capabilities

- `season-lifecycle`: gains a requirement that promotion is preceded by a
  verified staging load of the same artifact.

## Impact

- `etl/season_lifecycle.py`: a staging confirmation, and a required
  `--staging-api-url` on the promote subcommand.
- `Makefile`: `require-promotion` guards `STAGING_API_URL`.
- `docs/operations/season-lifecycle.md`: the promotion step documents the gate.
- No change to the data path, the schema, or the public API.
