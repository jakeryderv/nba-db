<!-- Operator runbook. The binding rules live in openspec/specs/season-lifecycle. -->

# Safe season lifecycle

The guarded lifecycle handles exactly one NBA **Regular Season** dataset at a time. Preseason, All-Star, Play-In, and playoff datasets are outside this workflow's scope. Run extraction and official verification from a trusted machine that can reach `stats.nba.com`; GitHub Actions uses deterministic fixtures and its ephemeral PostgreSQL service, never calls NBA endpoints, and never loads production.

## 1. Build and validate one season

Choose the season deliberately. This force-downloads fresh source data, including bounded `ShotChartDetail` responses for all 30 teams, transforms it, validates file relationships and official Regular Season game IDs in the `002.......` format, then compares calculated team and player counting-stat totals with the NBA's `LeagueDashTeamStats` and `LeagueDashPlayerStats` totals. Per-team requests are deliberate because the NBA endpoint silently caps an all-league shot response at 102,400 rows. Shot makes, player/team identity, and 3PT makes must match each player-game box score exactly. FGA and 3PA may differ by one for a documented NBA source correction; every accepted difference is recorded in `manifest.json`, while anything larger fails closed. Games played, records, and points must match exactly. Other counting stats use the same documented one-count correction policy because NBA game-log and aggregate feeds can diverge after stat corrections; every difference remains visible in the report. Only a passing `data/clean/<season>/verification.json` can be bound into the manifest with source scope, row counts, and SHA-256 checksums for all six transformed files.

```bash
make season-build SEASON=2025-26
uv run python -m json.tool data/clean/2025-26/manifest.json
uv run python -m json.tool data/clean/2025-26/verification.json
```

The equivalent trusted-machine Dagger build requires an explicit freshness key so a changing external NBA response cannot be confused with a deterministic cached input. It returns a typed directory that must be deliberately exported to the host:

```bash
dagger call season-build \
  --season=2025-26 \
  --refresh-key=2026-07-22T010000Z \
  export --path=data
```

To build, load, and serve the season entirely in disposable Dagger services, use a unique operation ID and leave the command running:

```bash
dagger up local-refresh \
  --season=2025-26 \
  --refresh-key=2026-07-22T010000Z \
  --operation-id=local-refresh-2026-07-22T010000Z
```

To rerun only the network-backed cross-check after transformation, use `make verify-official SEASON=2025-26`. Do not edit transformed files after verification or manifest creation. The report records every transformed-file checksum, and local load and production promotion fail closed if the dataset, report, or manifest changed. This check validates season totals; the existing relational and API tests still cover per-game calculations and application behavior.

## 2. Replace the local database

Start PostgreSQL, ensure no production URL is present, then load the manifested season locally:

```bash
make db-start
unset DATABASE_URL PRODUCTION_DATABASE_URL
make season-load-local SEASON=2025-26
```

After exporting a Dagger season build, the persistent Docker Compose database can instead be loaded through an explicitly granted host-service tunnel:

```bash
dagger call local-load \
  --database=tcp://localhost:5432 \
  --season=2025-26 \
  --confirm-local-target='LOCAL DOCKER DATABASE' \
  --operation-id=local-load-2026-07-22T010000Z
```

`local-load` has no network extraction step. It verifies the exported manifest again and uses the same exact one-season replacement logic as the Make workflow. The required operation ID prevents a mutating execution layer from being reused accidentally.

This is an exact one-season replacement: all other local season rows are removed inside the replacement transaction, including shot attempts. Verify the local API, shot totals, and visualizations before considering production promotion. There is no raw load or multi-season Make target. `refresh` exists only as a compatibility alias for the same guarded build and localhost replacement; it is not a production promotion path.

## 3. Promote with backup and typed confirmations

Promotion refuses a season that staging is not already serving. Before anything
is modified, it reads staging's dataset status and requires the same manifest
digest, a passing verification status, and matching counts. Staging being
unreachable blocks the promotion rather than being treated as permission, so
`STAGING_API_URL` must be set and step 2 must have been run for this exact
artifact.

Promotion requires the dedicated `PRODUCTION_DATABASE_URL` environment variable. It is never accepted as a CLI argument and is intentionally distinct from the app's ordinary `DATABASE_URL`. Read the secret without echoing it or storing it in shell history:

```bash
read -rsp "Production database URL: " PRODUCTION_DATABASE_URL
printf '\n'
export PRODUCTION_DATABASE_URL
```

Create a protected backup directory outside the repository, then run promotion. The backup file must be a new path; the command refuses to overwrite an existing file.

```bash
install -d -m 700 "$HOME/.local/share/nba-db/backups"
make season-promote \
  SEASON=2025-26 \
  TARGET=production \
  CONFIRM_SEASON=2025-26 \
  CONFIRM_SINGLE_SEASON='DELETE OTHER SEASONS' \
  BACKUP_FILE="$HOME/.local/share/nba-db/backups/nba-db-before-2025-26-20260721T180000Z.dump" \
  API_URL=https://nba.jvs.sh
unset PRODUCTION_DATABASE_URL
```

Dagger also exposes the same guarded promotion and returns the backup as a typed file. The database URL is introduced as a Dagger secret, while the data directory and backup destination remain explicit host grants:

```bash
dagger call promote \
  --season=2025-26 \
  --confirm-season=2025-26 \
  --confirm-single-season='DELETE OTHER SEASONS' \
  --api-url=https://nba.jvs.sh \
  --backup-name=nba-db-before-2025-26-20260722T010000Z.dump \
  --operation-id=production-2025-26-20260722T010000Z \
  --production-database-url=env:PRODUCTION_DATABASE_URL \
  export --path="$HOME/.local/share/nba-db/backups/nba-db-before-2025-26-20260722T010000Z.dump"
unset PRODUCTION_DATABASE_URL
```

The typed confirmations remain enforced inside the lifecycle command. Neither GitHub Actions nor Railway receives `PRODUCTION_DATABASE_URL`, calls `stats.nba.com`, or invokes these mutating functions.

Promotion verifies the manifest again, rejects local database targets, and takes a database advisory lock held from the protected custom-format `pg_dump` through the final live smoke check. It atomically replaces production so it contains exactly the confirmed season, then checks live health, season metadata, game identity/count, a sampled box score, standings, and points leaders against the manifest and promoted season. The API smoke check retries briefly; if it ultimately fails, the database replacement has already committed, so investigate immediately and restore the backup if the promoted data is not acceptable.

Before production promotion, load the same manifested data into an isolated staging database and
smoke-test the staging app. Keep staging and production in separate Railway environments with
separate PostgreSQL services and variables. Export the staging secret rather than passing it on the
command line:

```bash
export STAGING_DATABASE_URL
make season-stage \
  TARGET=staging \
  CONFIRM_SEASON=2025-26 \
  STAGING_API_URL=https://your-staging-app.example
unset STAGING_DATABASE_URL
```

The staging command refuses local routes and refuses to run when staging and production URLs are
the same. It applies migrations, replaces staging with the manifested season, and runs the same live
API smoke suite. Smoke requests force cache revalidation.

## Backup restore guidance

Keep the reported backup path and restrict access to it. Run the executable restore drill against a
database name ending in `_recovery`; the command refuses an existing database, inspects the archive,
restores it, verifies the one-season provenance counts, and removes the disposable database even
when verification fails:

```bash
export RECOVERY_DATABASE_URL='postgresql://.../nba_recovery'
make restore-drill \
  BACKUP_FILE="$HOME/.local/share/nba-db/backups/<backup>.dump" \
  RESTORE_CONFIRM='RESTORE nba_recovery'
unset RECOVERY_DATABASE_URL
```

Only after this drill passes should an operator schedule a controlled production restore. A real
production restore remains a manual incident operation because it replaces the entire database
state, including seasons that promotion removed.

The same drill can run without host PostgreSQL client tools by passing the backup as a typed Dagger
file. Dagger creates and removes an isolated PostgreSQL 18 service for the operation:

```bash
dagger call restore-backup \
  --backup="$HOME/.local/share/nba-db/backups/<backup>.dump" \
  --season=2025-26 \
  --source=.
```
