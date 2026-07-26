## ADDED Requirements

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
