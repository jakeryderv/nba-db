# season-lifecycle

## Purpose

Loading a season replaces the entire contents of a database. In production that
database is the live product, and the operation is destructive by design: the
single-season posture deletes every other season and prunes shared rows. There
is no undo beyond the backup the command itself takes.

The command therefore assumes it is being run by an operator who could be
wrong about which database they are pointed at. Every guard here is aimed at
that: the target must be named explicitly, the season must be typed back, the
destructive intent must be typed out in full, and the resolved route must not
be able to be the local machine. Confirmations are compared against the
requested season rather than being a yes/no prompt, so a confirmation cannot be
supplied reflexively or scripted once and reused across seasons.

Agents do not run these commands. The guards exist for a human who has the
context to accept the consequences.
## Requirements
### Requirement: Staging and production loads require an explicitly named target and typed confirmations

A staging load SHALL require the literal target `staging`; a promotion SHALL
require the literal target `production`. Both SHALL require the operator to
retype the season being loaded, and SHALL refuse when it does not match.
Promotion SHALL additionally require the destructive intent to be typed out in
full as `DELETE OTHER SEASONS`.

These confirmations SHALL be positional facts about the operation — the season
name, the consequence — not generic acknowledgements, so that confirming
requires knowing what is being done.

#### Scenario: Mistyped season aborts

- **WHEN** the typed season confirmation does not match the season being loaded
- **THEN** the command fails before connecting to any database

#### Scenario: Promotion without the destructive confirmation aborts

- **WHEN** a promotion is invoked without the exact single-season confirmation phrase
- **THEN** the command fails before taking a backup or modifying data

### Requirement: Remote targets refuse local, unspecified, and socket routing

Staging and production connection resolution SHALL require an explicit database
URL from the environment, SHALL require it to be a PostgreSQL URL, and SHALL
refuse routes that are loopback, unspecified, Unix-socket, or empty — including
each entry of a multi-host route. A staging URL that resolves to the same
connection as the production URL SHALL be refused.

Conversely, a local load SHALL refuse to run when a database URL is set in the
environment and SHALL require a loopback host, so that a command meant for the
development database cannot reach a deployed one.

#### Scenario: Production URL pointing at localhost is refused

- **WHEN** the production database URL resolves to a loopback or unspecified address
- **THEN** promotion fails rather than rewriting the local database under production confirmations

#### Scenario: Staging pointed at production is refused

- **WHEN** the staging and production database URLs resolve to the same connection
- **THEN** the staging load fails

#### Scenario: Local load with a database URL set is refused

- **WHEN** a local load runs with a database URL present in the environment
- **THEN** it fails rather than using it

### Requirement: Promotion takes a verified, private backup before modifying data

Promotion SHALL create a backup before any data is modified, and SHALL abort
the promotion if the backup cannot be created or is not valid. Backup creation
SHALL refuse to overwrite an existing path, SHALL require a parent directory
that exists, is not a symlink, and permits no group or other access, and SHALL
create the artifact with owner-only permissions before writing.

The database password SHALL NOT appear in the dump command's arguments, and the
child process environment SHALL NOT carry the production or default database
URLs. The artifact SHALL be finalized by atomic rename, so a partial dump is
never left at the backup path.

#### Scenario: Failed dump aborts promotion

- **WHEN** the dump command fails or produces an empty file
- **THEN** the temporary artifact is removed and promotion aborts before touching the data

#### Scenario: World-readable backup directory aborts promotion

- **WHEN** the backup's parent directory permits group or other access
- **THEN** promotion fails before the dump runs

#### Scenario: Credentials stay out of the process table

- **WHEN** the dump runs
- **THEN** the password is passed by environment, not in the command arguments

### Requirement: Replacement is atomic, serialized, and self-verifying

A season replacement SHALL execute inside a single transaction. Concurrent
replacements SHALL be serialized by an advisory lock; for staging and
production the lock SHALL be held across backup, replacement, and live
verification as one operation.

Before the transaction commits, the replacement SHALL verify against the
database it just wrote: per-table row counts SHALL match the manifest, the
recorded season metadata SHALL match the validated dataset, and referential
consistency between games and their team and player lines SHALL hold. Under the
single-season posture it SHALL additionally confirm that no other season
remains in any table and that no stale shared team or player rows survive. Any
failure SHALL abort the transaction, leaving the previous contents intact.

#### Scenario: Count mismatch rolls back

- **WHEN** post-load counts disagree with the manifest inside the replacement transaction
- **THEN** the transaction aborts and the database retains its previous contents

#### Scenario: Leftover season rolls back

- **WHEN** a single-season replacement would leave rows from another season
- **THEN** the transaction aborts

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

### Requirement: Lifecycle commands are operator-only

Staging and promotion commands SHALL be run only by an operator. No automation,
CI job, or agent SHALL invoke them, supply their confirmations, or handle the
production database URL beyond what an operator explicitly asks for in the
moment. No change SHALL add a code path that satisfies these guards
programmatically.

#### Scenario: Automation does not promote

- **WHEN** a workflow or agent needs production data changed
- **THEN** it surfaces the request to the operator rather than invoking the promotion command

### Requirement: Promotion requires the season to have been staged

A promotion SHALL confirm, before it modifies anything, that staging is already
serving the exact dataset being promoted: the same manifest digest, a passing
verification status, and matching counts. Promotion SHALL refuse when staging
cannot be reached, when it serves a different manifest, or when it has not
verified the season.

The confirmation SHALL be evidence rather than assertion. It asks the staging
deployment what it is serving, so an operator cannot satisfy it by declaring the
rehearsal happened — staging has to actually hold the dataset. A flag, a
checklist tick, or a command-line acknowledgement would all be satisfiable by
the same mistake they are meant to catch.

This check SHALL run before the backup and outside the operation lock, so a
failure costs nothing and holds nothing.

#### Scenario: An unstaged season cannot be promoted

- **WHEN** promotion is attempted for a dataset staging is not serving
- **THEN** it fails before taking a backup or modifying production

#### Scenario: A different dataset in staging does not count as a rehearsal

- **WHEN** staging serves the same season under a different manifest digest
- **THEN** promotion fails, because the artifact rehearsed is not the artifact being promoted

#### Scenario: Unreachable staging blocks promotion

- **WHEN** staging cannot be reached
- **THEN** promotion fails rather than treating the absent answer as permission

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
