# dataset-provenance

## Purpose

Every row this product serves claims to be official NBA data. Nothing in the
running system can re-derive that claim: the API reads a database, and a
database row looks the same whether it came from a verified extract or from a
hand-edited CSV. The claim therefore has to be carried forward from extraction
as evidence, and checked at the one place where data crosses into a database.

That evidence is the season manifest under `data/`: a JSON document recording
the source scope, the SHA-256 of every transformed file, the aggregate counts,
and the official verification report that compared those files against
stats.nba.com totals. `verify_manifest()` is the only sanctioned entry point
for a load, and it fails closed on every discrepancy rather than loading a
best-effort subset.

Provenance is retained after the load — the `seasons` row stores the manifest
digest and verification timestamps, so `/api/dataset-status` can state exactly
which artifact produced the live data.

## Requirements

### Requirement: A season enters a database only through a verified manifest

Every path that writes season data into any database — local, staging, or
production — SHALL first resolve its dataset through manifest verification,
and SHALL abort the entire operation if verification fails for any reason.
Verification SHALL confirm the manifest schema version, that the season and
season type match the requested season, that the generation timestamp is
timezone-aware, and that the recorded source provenance exactly matches the
scope the pipeline extracts.

A load path MUST NOT accept a dataset assembled by reading the transformed
files directly. Loading is the point where unverified data becomes
indistinguishable from verified data, so the check cannot be relocated to a
caller that a future path might omit.

#### Scenario: Missing manifest refuses the load

- **WHEN** a load is attempted for a season with no manifest file
- **THEN** the operation fails and no database is modified

#### Scenario: Manifest for a different season is rejected

- **WHEN** the manifest's season or season type does not match the requested season
- **THEN** verification fails and the load does not proceed

#### Scenario: Altered source scope is rejected

- **WHEN** the manifest's recorded provider, league, game-log scopes, or shot-chart scope differs from the pipeline's extraction scope
- **THEN** verification fails, because the files may describe a narrower dataset than the product claims

### Requirement: Manifested files are checksum-verified before and after reading

Verification SHALL confirm that the manifest's file set is exactly the set of
required transformed files, that every one exists, and that each file's SHA-256
matches its manifest entry. After the dataset has been read into memory, each
file's digest SHALL be recomputed and compared again, and each file's row count
and the aggregate counts SHALL be compared against the manifest.

The second digest comparison exists because the files are read after the first
one; without it, a file replaced between the check and the read would load
under the credentials of a manifest that no longer describes it.

#### Scenario: Edited transformed file is rejected

- **WHEN** any manifested CSV differs from its recorded SHA-256
- **THEN** verification fails naming the mismatched file, and no rows are loaded

#### Scenario: File replaced mid-read is rejected

- **WHEN** a manifested file's digest changes between the initial check and the completed read
- **THEN** verification fails rather than loading the data that was actually read

#### Scenario: Counts that disagree with the files are rejected

- **WHEN** the manifest's per-file row counts or aggregate counts do not match the loaded dataset
- **THEN** verification fails

### Requirement: A manifest is only valid with a passing official verification report

A manifest SHALL reference an official verification report, and verification
SHALL require that the report is present at the manifested path, matches its
recorded SHA-256, was produced by the official provider, and carries a passing
status. The report SHALL be re-read through its own validity check, and its
generation timestamp SHALL match the manifest's record of it. The report's
digest SHALL be confirmed again after the dataset has been read.

A failing or absent verification report SHALL prevent manifest generation, so
an unverified season cannot acquire a manifest to be loaded from.

#### Scenario: Unverified season cannot produce a manifest

- **WHEN** manifest generation runs for a season whose official verification did not pass
- **THEN** manifest generation fails and no manifest file is written

#### Scenario: Swapped verification report is rejected

- **WHEN** the verification report's digest or generation timestamp does not match what the manifest records
- **THEN** verification fails

### Requirement: Provenance is recorded in the database and exposed publicly

A completed load SHALL record, on the season row, the manifest digest, the
manifest generation timestamp, the official verification timestamp, and a
verification status of `passed` only when the loaded dataset carried a passing
manifest. The API SHALL expose this provenance so that a caller can compare
live data against the artifact that produced it.

#### Scenario: Verification status reflects the manifest

- **WHEN** a dataset is loaded without a passing manifest
- **THEN** the recorded verification status is `untracked` rather than `passed`

#### Scenario: Live provenance is checkable

- **WHEN** a client requests dataset status for the loaded season
- **THEN** the response carries the manifest digest and verification status recorded at load time

### Requirement: Transformed artifacts are generated, never edited

Files under `data/` — transformed CSVs, manifests, and verification reports —
SHALL be produced only by the extract, transform, verification, and manifest
commands. No change SHALL hand-edit them, and no change SHALL relax a
verification failure by regenerating a manifest over data that failed a check.

The manifest is written atomically through a temporary file so that an
interrupted generation cannot leave a partial manifest that later verifies
against nothing.

#### Scenario: Fixing a discrepancy re-runs the pipeline

- **WHEN** a checksum or count discrepancy is found
- **THEN** it is resolved by re-running extraction and transformation, not by editing the artifact or its manifest entry
