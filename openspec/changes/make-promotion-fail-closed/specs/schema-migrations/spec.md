## ADDED Requirements

### Requirement: A path that writes season data applies pending migrations first

Every command that writes a season into a database SHALL apply pending migrations
before it writes, against the same database it is about to write to.

Applying migrations only on some write paths lets environments diverge without
contradicting anything: each path is individually correct, and the gap only becomes
visible when a new migration exists. The failure then lands mid-operation on the path
that skipped it, which is the worst place to discover it and the least likely place
for someone to guess the cause.

This is not satisfied by the application applying migrations at boot. A load can run
against a database whose serving instance has not restarted, and an operator-driven
promotion does not wait for one.

#### Scenario: A pending migration is applied before a promotion writes

- **WHEN** a promotion runs against a database with an unapplied migration
- **THEN** the migration is applied first and the promotion proceeds, rather than failing partway through the replacement

#### Scenario: Every write path behaves the same way

- **WHEN** any command loads a season into a local, staging, or production database
- **THEN** it applies pending migrations before writing
