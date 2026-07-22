# Production Operations Record

Last verified: 2026-07-22

## Deployment baseline

- Railway project: `nba-db` (`d009c2d2-13eb-4166-8896-352c189c0083`)
- Production app: `nba-api` (`2a6e95b6-3d4c-48ec-b0bb-7918d6e520fe`)
- Production database: PostgreSQL 18 (`8ad40080-cc94-4407-9809-3ccbf54ec910`)
- Baseline production deployment inspected during this hardening work:
  `3b1575e1-b1ca-4ee8-b57b-88e0923ed3c0`, status `SUCCESS`, commit
  `810c444aa1a307fc72089f2bba638da5bfee246d`.
- Staging app and its isolated PostgreSQL 18 service are running in the Railway `staging`
  environment.

## Verified dataset

- Season: 2025-26 Regular Season
- Loaded into production: 2026-07-22 18:16:21 UTC
- Manifest generated: 2026-07-22 02:37:06 UTC
- Official verification completed: 2026-07-22 02:36:59 UTC
- Manifest SHA-256: `6047a7de50630305bd78cb36f693e4b04c27923f536987242ebb47fb968edb2e`
- Counts: 1,230 games; 582 participating players; 2,460 team-game rows; 26,651
  player-game rows; 219,160 shots.

## Monitoring and retention

- GitHub repository variable `LIVE_API_URL` is configured for the scheduled and manual live check.
- Railway's six-hour snapshot at implementation time showed 48 requests, zero 5xx responses,
  29 ms p50, 37 ms p95, roughly 0.1% CPU utilization, and 25% memory utilization.
- Railway bucket `nba-db-artifacts` (`370ace3a-51c4-46ee-8196-da265858f6eb`) exists in production.
- Verified dataset archive: `verified-seasons/2025-26/nba-db-2025-26-6047a7de5063.tar.gz`;
  SHA-256 `5bce4c20e0e3726b62e015e75c0568a0a2478f317e2b94acf8d620671087eb4d`.
- Production backup: `database-backups/2025-26/nba-db-production-2025-26-20260722.dump`;
  4,021,231 bytes; SHA-256
  `abf80f4c3813ec7e1a510fda4b10d8ef46131216e9cdc25099caabf353cfeece`.
- The production backup restored successfully into disposable PostgreSQL 18 and verified 1,230
  games, 582 participating players, and 219,160 shots. The recovery database was removed by the
  drill.
- Bucket verification after both uploads: three objects, 14.5 MB total. Never record credentials or
  database URLs in this file.
- Current latency is comfortably within the three-second live-check budget. No speculative index
  changes were made because Railway p95 was 37 ms; continue tuning only when metrics or query plans
  identify a real bottleneck.

## Release checklist

1. Pass the complete Dagger gate.
2. Stage and smoke-test the exact manifested dataset.
3. Create a protected production backup.
4. Promote using the typed single-season confirmations.
5. Run the production live contract check.
6. Restore the backup into an isolated `_recovery` database and record the result.
7. Upload the verified raw/clean artifact and receipt to `nba-db-artifacts`.
