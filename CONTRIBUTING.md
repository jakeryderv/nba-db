# Contributing

This is a single-operator project: one person runs the ETL, holds the production
credentials, and merges the changes. Contributions are welcome, but the workflow
below exists because the app is continuously deployed against a database that is
expensive to rebuild, not because of ceremony.

Agent instructions live in [AGENTS.md](AGENTS.md); this file is the human
version of the same rules.

## Getting set up

```bash
make install     # dependencies via uv
make db-start    # local PostgreSQL in Docker
make api         # serve the app at http://localhost:8000
```

## Before opening a pull request

```bash
make check         # formatting, ruff, docs, mypy
make test          # API + browser suite (needs make db-start first)
make dagger-check  # the full portable merge gate; same pipeline CI runs
```

`make check` and `make test` are the minimum. Run `make dagger-check` when the
change touches the database, the ETL, or CI itself.

If you invoke pytest directly, set `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` — the
Makefile already does.

## How changes land

- `main` is branch-protected: pull requests only, linear history, the `quality`
  check required, administrators included. Merging to `main` deploys to
  production.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/).
  No AI attribution or `Co-Authored-By` trailers.
- Planned work lives in GitHub Issues. Close them with `Fixes #N` in the
  implementing commit so the ledger cannot drift from the code.

## Specs come first for behavior changes

`openspec/specs/` owns the system's invariants and binding decisions — dataset
provenance, schema migrations, production access, the season lifecycle, release
readiness, and the public API surface. Where a spec exists, it wins; if the code
disagrees with it, say so rather than quietly following either.

Before non-trivial work, check `openspec/changes/` for an active change. Work
that alters a specced invariant should start with a change proposal
(`openspec new change`, or `/opsx:propose` if you use Claude Code). Small fixes
do not need one.

Absence of a spec means the code and README are authoritative for that area, not
that anything goes.

## Safety rails

These are not style preferences. Do not work around them, and do not weaken them
to make a change easier:

- **Season lifecycle commands that touch staging or production are
  operator-only** and require typed confirmations. Do not run them, weaken their
  guards, or handle `PRODUCTION_DATABASE_URL` beyond what an operator explicitly
  asks for.
- **Schema migrations are append-only.** They are numbered files under
  `db/schema/`, and editing one that has been applied fails a checksum check.
  Correct a mistake with the next numbered file, never by editing history.
- **Do not edit anything under `data/`** — transformed CSVs, manifests, and
  verification reports. Loads verify checksums and fail closed; a discrepancy is
  fixed by re-running the pipeline, not by editing the artifact.
- **The public API is read-only.** No endpoint may write data or trigger an ETL,
  lifecycle, or maintenance operation.

## Reporting problems

Open an issue. For anything security-related, follow [SECURITY.md](SECURITY.md)
instead of filing publicly.
