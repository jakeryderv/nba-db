## ADDED Requirements

### Requirement: Replacement data is verified before the transaction commits

A promotion SHALL verify the replacement data inside the transaction that wrote it,
before that transaction commits. Verification SHALL assert the loaded rows against the
manifest's recorded counts and against the data-quality checks. A failure SHALL roll
the transaction back, leaving the previous data in place.

The distinction that matters is what can be checked when. Data correctness is knowable
before the commit: the rows are present in the transaction, so they can be counted and
reconciled. Deployment correctness is not, because the serving application reads through
its own connections and cannot observe an uncommitted transaction. Moving what can move
means a dataset that fails its own checks never becomes visible at all, rather than
becoming visible and then being reported as bad.

The checks SHALL be the same code the restore drill runs, not a reimplementation. Two
copies of a correctness check drift, and the copy that drifts is discovered during an
incident.

#### Scenario: Data that fails verification never becomes visible

- **WHEN** the replacement rows do not satisfy the manifest counts or the data-quality checks
- **THEN** the transaction rolls back and the database still holds the previous season

#### Scenario: A failed promotion needs no recovery

- **WHEN** pre-commit verification fails
- **THEN** the command reports the failure and no restore is required, because nothing was committed

## MODIFIED Requirements

### Requirement: Staging and promotion verify the live deployment against the manifest

After replacement, a staging load or promotion SHALL verify the deployed API
while still holding the operation lock, retrying a bounded number of times.
Verification SHALL confirm health, that readiness reports the promoted season
with passing verification and matching counts, that public dataset status
reports the promoted manifest digest, and that the seasons, games, boxscore,
standings, and leaders endpoints are consistent with the promoted dataset.

Live verification runs after the replacement transaction has committed, because the
serving application cannot observe an uncommitted transaction. A failure at this stage
therefore means a bad deployment is already serving. The command SHALL report the
failure.

The backup taken at the start of the promotion is the recovery path, and that path
SHALL be documented as an executable procedure and SHALL be exercised. Naming a backup
is not a recovery plan: an operator meeting this failure for the first time is meeting
it under pressure, and a procedure that has never been run is indistinguishable from
one that does not work.

Recovery SHALL NOT be automatic. Once the data itself is verified before commit, a
live-verification failure is more likely to be a deployment or edge fault than a data
fault, and restoring a database does not fix those while itself being destructive.

#### Scenario: Live counts that disagree fail the promotion

- **WHEN** the deployed readiness or dataset-status response does not match the promoted manifest
- **THEN** the command exits with an error identifying the mismatch

#### Scenario: Transient unavailability is retried

- **WHEN** the deployment is briefly unreachable immediately after replacement
- **THEN** verification retries before declaring failure

#### Scenario: The failure names the recovery procedure

- **WHEN** live verification fails after the commit
- **THEN** the reported error identifies the backup taken for this promotion and where the recovery procedure is documented
