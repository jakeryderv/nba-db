## Context

Production is watched by two daily probes: the 08:13 UTC backup job's `curl` against
`/api/dataset-status`, and a ~10:55 UTC `check_live.py` contract verification reached
through the scheduled-CI to release-observer chain. They land ~2.5h apart, so the
worst-case detection gap is ~21 hours, and the first notice would come from the observer.

The service is a single replica with `restartPolicyType: ON_FAILURE` and a 3-retry cap.
Once that budget is spent a crash-loop stays down with no further restarts.

Backups run daily and a Dagger restore drill runs monthly. Both alert correctly *when
they run* — #45 fixed the reconciliation. Neither says anything when it stops running,
because the reconcile step is `if: always()` inside the job it reports on.

The dataset is a frozen single-season snapshot mutated only by operator promotion, so
backup staleness is not a data-loss question. It is an observability question: the loop
could stop entirely and every remaining signal would still read healthy.

## Goals / Non-Goals

**Goals:**

- Detect a stopped backup schedule within a day, from a job that is not the backup job.
- Detect a production outage within ~10 minutes instead of ~21 hours.
- Make the restore drill answer "can this serve?" rather than "did rows load?".
- Tie each backup artifact to the dataset production actually serves.
- Stop retention from expiring the only copy ever proven restorable.

**Non-Goals:**

- Changing backup frequency, retention length, or drill cadence. Their schedules are
  fine; their outcomes are unobserved.
- Off-platform monitoring. See the shared-failure-domain risk below.
- Multi-replica or automated failover. Single replica remains the deployment shape.
- Touching `/ready`'s cache headers — that belongs to #50.

## Decisions

### One new workflow with two schedules, not two workflows

`production-watch.yml` carries a `*/10 * * * *` liveness schedule and a `0 14 * * *`
backup-freshness schedule, selected by a mode step. This is the shape `maintenance.yml`
already uses, so it is the pattern this repo reads fluently.

Freshness is checked daily rather than every ten minutes because the thing it watches is
a daily job — checking 144 times a day would add S3 calls without shortening detection.
14:00 UTC sits well clear of the 08:13 backup, so a slow run is not read as a missing one.

*Alternative considered:* folding liveness into `release-observer.yml`. Rejected — that
workflow is `on: workflow_run` by design, and giving it a second, unrelated trigger would
blur what it means when it fails.

### The liveness probe reads `/ready`, not `/health`

`/health` is cheaper, but `/ready` is the contract that decides whether an instance
should be serving at all, so it is the honest thing to assert continuously.

Cost is not a real objection: `/ready` reconciles three counts over a 219k-row season on
indexed columns, so 144 probes a day is on the order of seconds of database time. The
endpoint's own rate limit defaults to 600/min.

The probe sends `Cache-Control: no-cache` and `Pragma: no-cache`, matching
`check_live.py`, so the edge cannot answer it. This is required by the spec and matters
concretely because Cloudflare rewrites cache directives on this zone.

The probe retries within the job (three attempts, spaced) before declaring failure. A
single transient blip should not open an issue; a real outage fails all three, so
detection stays at roughly one interval.

*Alternative considered:* running the full `check_live.py` every ten minutes. Rejected as
disproportionate — it is a contract check, and it already runs daily.

### Alert reconciliation becomes a composite action

The `reconcile()` bash function currently lives inline in `maintenance.yml`. A third
consumer makes that duplication a liability, and the spec requires that one concern's
recovery never clears another's alert — a property that only holds if every caller keys
titles the same way.

Extract to `.github/actions/reconcile-alert/action.yml`, taking a title and a pass/fail,
and have `maintenance.yml` and `production-watch.yml` both use it.

### Provenness is recorded in a pointer object, not object metadata

To keep the last proven backup out of the pruner's reach, the drill writes a small JSON
pointer — `database-backups/<season>/last-proven.json` — naming the key it proved and
when. `prune_backups` reads it and never deletes that key.

*Alternative considered:* S3 object tagging (`put_object_tagging`). Rejected because
tagging support in Railway's S3-compatible backend is unverified, while `put_object` and
`get_object` are already exercised by this codebase. Object *metadata* is immutable after
upload and would require a copy-object dance, which is worse.

The pruner SHALL fail closed: an unreadable or malformed pointer aborts pruning rather
than proceeding without the protection. Deleting backups is the irreversible direction.

### Servability is proven by running the real boot path, not by booting the app

After restoring, the drill will:

1. Run `scripts/init_db.py` against the restored database — the same thing
   `railway.toml`'s `startCommand` runs on every production boot. This proves migrations
   apply cleanly to restored data and that `nba_readonly` and its grants are recreated.
2. Evaluate the application's readiness check against the restored database, so the drill
   asserts the same conditions the deployment healthcheck does, from the same code.
3. Connect *as* `nba_readonly` and run a representative read, proving the least-privilege
   path works rather than only the superuser path.
4. Compare the restored `seasons.manifest_sha256` against the manifest digest stamped on
   the backup object.

Step 1 is what makes the earlier "a restored database cannot serve production" claim
false — the role is recreated at boot. The drill's gap was never that recovery is broken;
it is that recovery was undemonstrated, and an undemonstrated recovery path is one nobody
should lean on during an incident.

*Alternative considered:* booting the full FastAPI app against the restored database and
curling `/ready`. Rejected as heavier without being more informative — app-level
regressions are already caught by every deploy, whereas the recovery-specific risk lives
in the database and role layer.

## Risks / Trade-offs

- **The checker shares a failure domain with the thing it checks.** Both run on GitHub
  Actions. If Actions is down, or the repo's schedules are disabled, backup and checker
  stop together and the silence returns. → This change removes the dominant failure mode
  (the backup job stops while everything reads green) but does not achieve true
  independence. Genuine independence needs an off-platform monitor; a Cloudflare Health
  Check on `/ready` is the natural upgrade for the liveness half if the zone plan allows
  it. Record the limitation in the operator docs rather than implying full coverage.
- **`*/10` GitHub cron is best-effort and can be delayed under platform load.** →
  Detection degrades gracefully; the check alerts on a failed probe, not a missed run, so
  a delayed run postpones detection rather than producing a false alarm.
- **A new pointer object is a new thing that can be wrong.** → The pruner fails closed on
  an unreadable pointer, so the failure mode is "kept too many backups," not "deleted the
  proven one."
- **144 extra `/ready` hits a day is a real if small load increase** against ~8
  requests/hour of organic traffic. → It is indexed counting, measured in seconds of
  database time per day, and it is the endpoint's designed purpose.
- **More alerting surface means more chances to cry wolf.** → In-job retries absorb
  transient failures, and per-concern titles keep one recovery from masking another.

## Migration Plan

Purely additive: new workflow, new composite action, extended drill assertions, a
retention guard. No schema change, no application change, no deploy-path change.

1. Land the composite action and repoint `maintenance.yml` at it — behavior-preserving,
   verifiable by dispatching the workflow.
2. Land `production-watch.yml` with `workflow_dispatch` and run both modes manually
   before trusting the schedules.
3. Land the drill and retention changes, then dispatch a restore drill to confirm the
   pointer object is written and the assertions pass against a real backup.

Rollback is per-step: each is an independent workflow or script change, and none alters
production behavior, so reverting a commit is sufficient.

## Open Questions

Both resolved with defaults rather than left open; each is a single configured value, so
an operator can revise it without reopening the design.

- **Maximum backup age: 36 hours.** The backup is daily, so this tolerates exactly one
  missed run and alarms on two. A 24h bound would alarm on any late run; a 48h bound
  would let two consecutive failures pass unremarked.
- **The freshness check also asserts the drill has run recently, bounded at 40 days.** A
  drill that stops firing is the same defect as a backup that stops, and it is the check
  that makes the retention guard meaningful — without a recent drill there is no recent
  proven copy to protect. 40 days tolerates one missed monthly run.
- **Left genuinely open:** whether to move the liveness half to an off-platform monitor.
  That is a hosting decision with a cost implication, not a code decision, and it is
  tracked as the upgrade path in the shared-failure-domain risk above.
