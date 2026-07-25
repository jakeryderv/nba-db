# schema-migrations

## Purpose

Schema changes reach production by being applied automatically at deploy time
against a database holding the only copy of a verified dataset. There is no
migration review step between merge and application, so the guarantees have to
be structural: migrations are append-only numbered files, each recorded with
its digest, and an applied file that later changes is a hard failure rather
than a silent divergence between what the database ran and what the repository
says it ran.

Applying edits to an already-applied file is the failure this prevents. The
edit would run on a fresh database and be skipped on an existing one, producing
two schemas from one source tree — a difference that surfaces much later as a
query failing only in production.

## Requirements

### Requirement: Migrations are append-only numbered files

Schema changes SHALL be introduced as a new numbered SQL file in `db/schema/`
taking the next number in sequence. Every file in that directory SHALL have a
numbered filename, and application SHALL happen in filename order. No change
SHALL modify a migration that has been applied anywhere, including to correct a
mistake — the correction is itself a new file.

#### Scenario: A schema fix is a new file

- **WHEN** an applied migration is found to be wrong
- **THEN** a new numbered migration corrects it and the original file is left untouched

#### Scenario: Unnumbered file fails the run

- **WHEN** a SQL file in the schema directory has no leading number
- **THEN** the migration run fails rather than applying files in an ambiguous order

### Requirement: Applied migrations are checksum-tracked and immutable

Each applied migration SHALL be recorded with its filename, the SHA-256 of its
contents, and the time it was applied. Before applying, the runner SHALL
compare each already-recorded file against its stored digest and SHALL fail
when they differ. Files already recorded and unchanged SHALL be skipped rather
than reapplied.

#### Scenario: Editing an applied migration fails the deploy

- **WHEN** a migration recorded in the database no longer matches its stored digest
- **THEN** the run raises a checksum error and applies nothing further

#### Scenario: Re-running is a no-op

- **WHEN** the migration runner executes against a database that is already current
- **THEN** every recorded migration is skipped and the schema is unchanged

### Requirement: A failed migration leaves no partial schema

A migration run that fails SHALL roll back, leaving neither partially applied
statements nor a recorded row claiming the file was applied.

#### Scenario: Failure rolls back

- **WHEN** a statement within a migration file fails
- **THEN** the transaction is rolled back and the file is not recorded as applied
