## MODIFIED Requirements

### Requirement: Replacement is atomic, serialized, and self-verifying

A season replacement SHALL execute inside a single transaction. Concurrent
replacements SHALL be serialized by an advisory lock; for staging and
production the lock SHALL be held across backup, replacement, and live
verification as one operation.

A replacement SHALL NOT render the database unreadable for the duration of the
load. Any lock that blocks readers SHALL be held only for the swap that makes the
new data current, not for the copying that produces it.

Atomicity and availability are separate properties, and satisfying the first says
nothing about the second. Emptying the live tables and refilling them inside one
transaction is perfectly atomic and takes an exclusive lock for the whole load, so
every reader blocks for as long as the copy takes. Building the new contents
alongside the old and swapping at the end is equally atomic and blocks readers only
for the swap.

Before the transaction commits, the replacement SHALL verify against the
database it just wrote: per-table row counts SHALL match the manifest, the
recorded season metadata SHALL match the validated dataset, and referential
consistency between games and their team and player lines SHALL hold. Under the
single-season posture it SHALL additionally confirm that no other season
remains in any table and that no stale shared team or player rows survive. Any
failure SHALL abort the transaction, leaving the previous contents intact.

Verification SHALL observe the data as it will be served. Where the new contents are
built alongside the old, verification therefore runs after the swap and before the
commit, so that it reads the same table names a caller will.

#### Scenario: Count mismatch rolls back

- **WHEN** post-load counts disagree with the manifest inside the replacement transaction
- **THEN** the transaction aborts and the database retains its previous contents

#### Scenario: Leftover season rolls back

- **WHEN** a single-season replacement would leave rows from another season
- **THEN** the transaction aborts

#### Scenario: Readers are not blocked for the length of the load

- **WHEN** a season is loaded into a database that is serving reads
- **THEN** reads continue against the previous contents until the swap, rather than blocking for the duration of the copy

#### Scenario: Verification reads the served tables

- **WHEN** the replacement verifies its work before committing
- **THEN** it queries the tables under the names callers use, after any swap has taken place
