## ADDED Requirements

### Requirement: Production is observed continuously, not only after a deploy

A scheduled check SHALL confirm that production is serving, on an interval bounded in
minutes rather than hours, independently of whether a deploy has occurred.

Release verification runs only after a merge, so between merges nothing watches
production. The service runs as a single replica with a capped restart policy: once the
retry budget is exhausted a crash-loop stays down permanently. The failures that produce
that state — an exhausted volume, a rotated credential, a bad migration — arrive on their
own schedule, not on the deploy schedule, so a post-deploy-only signal cannot see them.

The interval bounds how long production can be down unobserved. It SHALL be short enough
that detection is measured in minutes.

#### Scenario: An outage between deploys is detected

- **WHEN** production stops serving and no deploy occurs
- **THEN** the scheduled check observes the failure within its interval

#### Scenario: Observation does not depend on deploy activity

- **WHEN** no merge has happened for an extended period
- **THEN** the check still runs on its schedule

### Requirement: The liveness check reads the origin, not a cache

The check SHALL read a response produced by the running origin. Where a caching layer
sits in front of production, the check SHALL bypass it.

A cached response outlives the instance that produced it. Satisfying a liveness check
from cache reports that production was healthy when the response was stored, which is
precisely the claim the check exists to avoid making. The edge in front of production
rewrites cache directives, so bypass has to be asserted by the check rather than assumed
from the origin's own headers.

#### Scenario: A cached response cannot satisfy the check

- **WHEN** a caching layer holds a response for the endpoint the check reads
- **THEN** the check bypasses the cache and evaluates a freshly produced response

### Requirement: A failing check raises a signal that a later success clears

A failed check SHALL raise a visible alert, repeated failures SHALL update that alert
rather than creating duplicates, and a subsequent success SHALL close it. The alert SHALL
identify the failing concern specifically enough that one operation's recovery cannot
resolve another's alert.

An alert nobody can find is not an alert, and a duplicate per failed run is noise that
trains operators to ignore the channel. Closing on recovery is what keeps an open alert
meaningful as a statement about the present.

#### Scenario: Repeated failures do not create duplicate alerts

- **WHEN** the check fails on consecutive runs
- **THEN** the existing alert is updated rather than a second one opened

#### Scenario: Recovery closes the alert

- **WHEN** the check succeeds after a failure
- **THEN** the open alert is closed

#### Scenario: One concern's recovery does not clear another's alert

- **WHEN** two distinct scheduled concerns raise alerts and only one recovers
- **THEN** the other concern's alert remains open
