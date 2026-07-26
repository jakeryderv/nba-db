# backup-durability Specification

## Purpose

Backups exist to make one question answerable under pressure: can this product be
brought back? Every requirement here exists because some part of that loop could
report success while being unable to answer it.

The concern is observability rather than recovery-point objective. The dataset is
a frozen single-season snapshot mutated only by operator promotion, so an older
dump restores to the same content and staleness costs little. What costs a great
deal is the loop stopping while every remaining signal still reads healthy — a
check that lives inside the job it reports on cannot report that job's absence.

The same reasoning runs through the rest: counts reconciled against a dump's own
provenance prove self-consistency rather than correctness; a drill that loads
rows has not shown the database can serve; and retention that measures only age
and count can delete the one artifact ever proven to work.

## Requirements
### Requirement: A recent backup is asserted independently of the job that creates backups

A scheduled check SHALL assert that the newest retained backup exists and is no older
than a configured maximum age, and SHALL raise a visible alert when it is not. That
maximum SHALL be a small multiple of the backup interval, so a single missed run does not
alarm but a stopped schedule does. The check SHALL NOT be a step inside the backup job.

A signal emitted by the subject it reports on disappears exactly when the subject fails.
The existing alert reconciliation runs inside the maintenance job, so a schedule that
stops firing produces no alert at all — only silence, which is indistinguishable from
success. Independence is what converts absence into a signal.

The concern is observability rather than recovery-point objective. The dataset is a
frozen single-season snapshot mutated only by operator promotion, so an older dump
restores to the same content. What matters is that the whole loop could stop while every
remaining signal still looked healthy.

#### Scenario: A stopped backup schedule raises an alert

- **WHEN** no new backup has been uploaded for longer than the configured maximum age
- **THEN** the check fails and raises a visible alert, without depending on the backup job having run

#### Scenario: A single missed run does not alarm

- **WHEN** one scheduled backup is skipped but the newest backup is still within the maximum age
- **THEN** the check passes

#### Scenario: An absent backup is a failure, not an empty result

- **WHEN** no backup exists at all for the season
- **THEN** the check fails rather than reporting nothing to check

### Requirement: A restored backup is proven to match the dataset production serves

The restore drill SHALL compare the manifest digest recorded on the backup object against
the manifest digest recorded in the restored database, and SHALL fail when they disagree.

Reconciling row counts against the restored database's own provenance columns proves the
dump is internally consistent — it cannot detect a dump that is consistently wrong. The
uploader already stamps the manifest digest on every object and the downloader already
reads it back; comparing them is what ties the artifact to the dataset production
actually serves.

#### Scenario: A backup whose manifest disagrees with the restored data fails the drill

- **WHEN** the restored database records a different manifest digest than the backup object carries
- **THEN** the drill fails and reports the disagreement

#### Scenario: A backup missing manifest metadata cannot pass

- **WHEN** the backup object carries no manifest digest
- **THEN** the drill fails rather than skipping the comparison

### Requirement: The restore drill proves the restored database can serve

The restore drill SHALL verify that the restored database satisfies the application's
readiness contract, not merely that its rows loaded. It SHALL exercise the same readiness
conditions the deployment healthcheck asserts.

A drill that only counts rows answers "did the data arrive?" when the question during a
recovery is "can this serve traffic?" The application recreates its read-only role on
every boot, so recovery does work today — the gap is that the drill does not demonstrate
it, and an undemonstrated recovery path is one nobody should rely on under pressure.

#### Scenario: A restored database that fails readiness fails the drill

- **WHEN** the restored database would not satisfy the readiness contract
- **THEN** the drill fails rather than reporting a successful restore

#### Scenario: A successful drill reports what it proved

- **WHEN** the drill passes
- **THEN** it reports the season, verification status, and counts it confirmed

### Requirement: Retention preserves the last backup proven restorable

Retention SHALL NOT delete a backup that is the most recent copy proven restorable by a
drill. Pruning SHALL be evaluated against proven copies, not only against age and count.

Retention is measured in days and the drill runs monthly, so the only artifact ever
demonstrated to work can expire on roughly the cadence of the check that demonstrated it.
Keeping N newest copies does not help: it preserves recency, and recency is not evidence.

#### Scenario: The last proven copy survives expiry

- **WHEN** the newest drill-proven backup is older than the retention window
- **THEN** pruning retains it

#### Scenario: Unproven expired copies are still pruned

- **WHEN** an expired backup has never been proven restorable and a newer proven copy exists
- **THEN** pruning deletes it
