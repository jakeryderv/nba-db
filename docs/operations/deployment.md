<!-- Operator runbook for deploying, monitoring, and retaining artifacts. -->

# Deployment

Deployed on [Railway](https://railway.com) (`railway.toml`) after the required GitHub check succeeds:
Railpack installs only runtime dependencies, `scripts/init_db.py` applies pending checksum-tracked
schema migrations and refreshes the read-only role, then uvicorn serves the app. The deploy command
uses `uv run --no-sync`, preventing development tools and ETL-only scientific packages from being
installed during startup. Set `DATABASE_URL` (provided by the Railway Postgres plugin) and
`READONLY_DB_PASSWORD` on the service.

Schema migration files are immutable after they have been applied. To change the database, add the next numbered file under `db/schema/`; editing an applied file causes initialization to fail with a checksum error.

## Environments

The Railway project runs `production` and `staging`. Both `nba-api` services deploy from
`main`, so a merge reaches them within the same second.

**Staging is a rehearsal target for data, not a gate for code.** Its job is
`make season-stage`. A promotion refuses any dataset staging is not already serving, so
staging holds the only rehearsal standing between a manifested season and production —
see [Season lifecycle](season-lifecycle.md).

Code is gated instead by three checks that do not involve staging:

1. The required `quality` check on the pull request, before the merge.
2. Railway's `/ready` healthcheck, which withholds traffic from a new instance until it
   proves it is serving a complete, verified season.
3. The release observer, which waits for production to serve the merged SHA and then
   reruns the full live contract.

Routing code through staging as a fourth gate was considered and declined. Staging is not
behind Cloudflare and its smoke test asserts less than the production live check, so it
cannot rehearse the edge layer or the full contract. It would add a manual promotion step
to every merge in exchange for a weaker signal than the three checks above already give.

Treat staging as a parity twin: useful for reproducing a problem against production-like
data, never authoritative about whether a release is safe. If that trade ever changes —
staging fronted by Cloudflare and brought to smoke-test parity — revisit the decision
rather than quietly adding the gate, because a documented gate that does not gate is worse
than no gate.

## Verified artifact retention

The production Railway project contains the `nba-db-artifacts` S3-compatible bucket. Archive the
raw NBA responses, clean CSVs, verification report, and manifest only after manifest verification
passes. The command refuses repository-local output and existing filenames, writes a SHA-256
sidecar and JSON receipt, and verifies checksum metadata after upload.

```bash
install -d -m 700 "$HOME/.local/share/nba-db/artifacts"
bucket_credentials="$(railway bucket credentials --bucket nba-db-artifacts \
  --environment production --json)"
export AWS_ENDPOINT_URL="$(jq -r '.endpoint' <<< "$bucket_credentials")"
export AWS_ACCESS_KEY_ID="$(jq -r '.accessKeyId' <<< "$bucket_credentials")"
export AWS_SECRET_ACCESS_KEY="$(jq -r '.secretAccessKey' <<< "$bucket_credentials")"
export AWS_DEFAULT_REGION="$(jq -r '.region' <<< "$bucket_credentials")"
export AWS_S3_BUCKET_NAME="$(jq -r '.bucketName' <<< "$bucket_credentials")"
export AWS_S3_URL_STYLE="$(jq -r '.urlStyle' <<< "$bucket_credentials")"
make artifact-upload SEASON=2025-26 ARTIFACT_DIR="$HOME/.local/share/nba-db/artifacts"
make backup-upload SEASON=2025-26 BACKUP_FILE="$HOME/.local/share/nba-db/backups/<backup>.dump"
unset bucket_credentials
unset AWS_ENDPOINT_URL AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_S3_BUCKET_NAME AWS_DEFAULT_REGION AWS_S3_URL_STYLE
```

The uploader is an operator-only optional dependency (`uv run --extra ops`) and is not imported by
the web service. Object keys are versioned beneath `verified-seasons/<season>/` using an archive name
that includes the verified manifest checksum.

## Automated maintenance

The `Production Maintenance` workflow creates a PostgreSQL 18 custom-format backup every day at
08:13 UTC, uploads it with manifest and SHA-256 metadata, and deletes backups older than 30 days
while always retaining at least the newest seven copies. On the first day of each month at 09:43
UTC, it downloads the newest retained object, verifies its checksum, and runs the real Dagger
restore drill against isolated PostgreSQL 18. The workflow can also run either operation manually.

The workflow uses encrypted GitHub Actions secrets for `PRODUCTION_DATABASE_URL`,
`AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY`. Endpoint, bucket, region, URL style, and live API
URL are non-secret repository variables. A failed backup or restore creates or updates a visible
`production-alert` issue; the next successful maintenance run closes it.

## Anonymous product signals

The dashboard records a small allowlist of anonymous events—section views, comparisons, shot-chart
builds, CSV exports, and link sharing—to structured Railway logs. It sends no names, search terms,
player/team selections, cookies, or persistent browser identifiers. Use these signals with HTTP
metrics before prioritizing further navigation or workflow changes:

```bash
railway logs --service nba-api --environment production --since 7d \
  --filter 'Usage event=' --lines 500 --json
```

Every hash-routed view now has a `Copy view link` action, preserving the existing shareable player,
team, game, comparison, and shot-chart URLs. CSV export remains available from built shot charts.

## Production monitoring

`/health` checks database connectivity while `/ready` additionally fails unless the verified default
season and its critical row counts match provenance metadata. Every response carries an
`X-Request-ID`, `Server-Timing`, and `X-Response-Time-Ms`; application logs include the same request
ID and elevate requests over one second.

Run a bounded live contract check at any time:

```bash
make live-check API_URL=https://nba.jvs.sh
```

The scheduled and manually dispatched GitHub workflow runs this check using the configured
`LIVE_API_URL` repository variable. Its expected production totals are 1,230 games, 582
participating players, and 219,160 shots. Count drift, readiness failure, missing telemetry or
release headers, inconsistent release revisions, a response over three seconds, or a broken
core/shot exploration endpoint fails the job. Use Railway's HTTP metrics and logs with the returned
request ID to investigate latency or errors.

After every successful `main` CI run, the production release observer waits up to ten minutes for
Railway to serve that exact Git SHA, then reruns the complete live contract. Failed CI, a stale or
failed Railway deployment, and a broken live contract create or update a `production-alert` GitHub
issue. A later successful observation closes the incident automatically.

The public API applies a process-local sliding-window limit per client. Ordinary API reads default
to 600 requests per minute; the aggregate-heavy shot chart, shot profile, and CSV routes default to
120. Large responses use gzip when the client advertises support. Override the limits with the
documented environment variables only after reviewing production traffic.
