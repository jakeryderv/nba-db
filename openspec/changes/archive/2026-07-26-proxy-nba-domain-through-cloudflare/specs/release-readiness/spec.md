## ADDED Requirements

### Requirement: Release verification observes the origin, not a cache

Verification that a release is live and correct SHALL read responses produced by
the running origin. Where a caching layer sits in front, verification SHALL
bypass it, and no cache rule SHALL be introduced over the endpoints verification
reads without doing so.

Verification asserts that every response carries the same release revision and
that live counts match the promoted manifest. A cached response from the
previous release satisfies neither honestly: it can fail the check for a healthy
deploy, or — worse — pass it while describing data the running instance is no
longer serving. The check is only meaningful against the origin.

#### Scenario: Cached responses cannot satisfy verification

- **WHEN** a caching layer holds responses for endpoints that release verification reads
- **THEN** verification bypasses the cache, so a response from the previous release cannot answer it

#### Scenario: A new cache rule is scoped away from verification

- **WHEN** caching is introduced over an endpoint that verification reads
- **THEN** the change either exempts that endpoint or purges the cache on release, and says which
