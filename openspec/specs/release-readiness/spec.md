# release-readiness

## Purpose

Deploys are automatic on merge, and the platform decides whether a new instance
receives traffic by asking the instance itself. That makes readiness a
load-bearing contract rather than a diagnostic: whatever readiness accepts is
what the public gets.

A liveness check is not sufficient for this product. An instance can connect to
its database, answer every route, and still be serving an empty, partially
loaded, or unverified dataset — which is exactly the state a failed or
interrupted promotion leaves behind. Readiness therefore asserts the product's
actual precondition, that the verified default season is complete and
queryable, and fails closed on anything else.

## Requirements

### Requirement: Readiness asserts a complete, verified default season

The readiness endpoint SHALL confirm that the default season exists, that its
recorded verification status is `passed`, and that its recorded game,
participating-player, and shot-attempt counts each equal the counts actually
present in the tables. It SHALL return an unavailable status when any condition
fails, when the season row is absent, or when the check itself errors.

Comparing recorded counts against live counts is the point of the check: the
recorded counts come from the manifest at load time, so agreement means the
data in the tables is the data that was verified, not merely that some data
exists.

#### Scenario: Empty database is not ready

- **WHEN** the default season has no loaded rows
- **THEN** readiness returns unavailable and the instance receives no traffic

#### Scenario: Partial load is not ready

- **WHEN** live row counts disagree with the counts recorded for the season
- **THEN** readiness returns unavailable

#### Scenario: Unverified data is not ready

- **WHEN** the season's verification status is not `passed`
- **THEN** readiness returns unavailable

#### Scenario: Check failure is not ready

- **WHEN** the readiness query itself raises
- **THEN** the endpoint reports unavailable rather than a ready status

### Requirement: Deploys are gated on readiness, not liveness

The deployment healthcheck SHALL target the readiness endpoint. A new instance
SHALL NOT receive traffic on the strength of a liveness check alone.

#### Scenario: A deploy against an unverified database is held back

- **WHEN** an instance starts against a database that fails readiness
- **THEN** the platform healthcheck fails and the release does not take traffic

### Requirement: Readiness reports the season it verified

The readiness response SHALL name the season, its verification status, and the
live counts it confirmed, so that a promotion can compare the live deployment
against the manifest it promoted and a release check can confirm which dataset
is serving.

#### Scenario: Promotion verifies against the readiness response

- **WHEN** a promotion verifies the live deployment
- **THEN** it reads the season, verification status, and counts from readiness and compares them to the promoted manifest
