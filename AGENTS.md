# Agent instructions

Read-only NBA stats API and dashboard backed by PostgreSQL with an operator-run ETL
pipeline. The README covers architecture; this file covers workflow rules and commands
that are not inferable from the code.

## Sources of truth

- `openspec/specs/` owns invariants and binding decisions. The README owns usage
  and architecture; `docs/operations/` owns the current production record. Where a
  spec exists, it wins — flag the disagreement rather than silently following code.
- Only a few capabilities are specced (dataset provenance, schema migrations,
  production access, season lifecycle, release readiness). Absence of a spec means
  the code and README are authoritative for that area, not that anything goes.
- Check `openspec/changes/` for an active change before non-trivial work, and use
  `/opsx:propose` for work that changes a specced invariant. Small fixes do not
  need a change proposal.
- Planned work lives in GitHub Issues. Close them with `Fixes #N` in the
  implementing commit.
- Agent instruction files under `.agent/`, `.claude/`, and `.codex/` are generated
  by `openspec init`/`openspec update` and are not tracked; only `openspec/` is.

## Git workflow

- `main` is branch-protected (PR-only, `quality` CI check required, linear history,
  admins included). Never attempt to push to `main` directly.
- Merge with `gh pr merge --squash --delete-branch` and an explicit `--subject`/`--body`.
- No AI attribution or `Co-Authored-By` lines in commit messages.
- Merging to `main` deploys to production: Railway picks up the commit, gated by the
  `/ready` healthcheck, and the release observer verifies the live contract afterward.

## Commands

- `make install`, `make db-start`, `make api` — setup and local run.
- `make test` — API + browser suite (needs `make db-start` first). If invoking pytest
  directly, set `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` (the Makefile already does).
- `make check` — formatting, ruff, docs, mypy. Run before claiming work done.
- `make dagger-check` — the full portable merge gate; same pipeline CI runs.

## Safety rails (do not work around these)

- Season lifecycle commands that touch staging or production are operator-only and
  require typed confirmations. Never run them, weaken their guards, or handle
  `PRODUCTION_DATABASE_URL` beyond what an operator explicitly asks for.
- Schema migrations are append-only numbered files under `db/schema/`; editing an
  applied file fails a checksum check. Always add the next numbered file instead.
- Do not edit transformed data, manifests, or verification reports under `data/` —
  loads verify checksums and fail closed.
