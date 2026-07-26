## Context

Two environments deploy the same commit within half a second of each other, so
staging leads production by nothing. Issue #47 asked which of two coherent
answers to take: make staging a real gate, or stop calling it one. The decision
was to make it a gate.

"Gate" means different things for the two things that flow through staging.

## Goals / Non-Goals

**Goals:**

- Promotion cannot proceed for a dataset staging has not verified.
- The check is evidence about the running staging deployment, not a token an
  operator can supply.

**Non-Goals:**

- Changing the code delivery model in this change. See below.

## Decisions

### Gate the data path first, and separately from the code path

The data path is where a gate earns the most: promotion replaces the entire
contents of the production database, and a bad dataset is expensive to undo. The
code path already has two gates that the data path lacks — Railway holds a
release behind the `/ready` healthcheck, and the release observer verifies the
live contract afterward.

So this change gates promotion, and leaves simultaneous code deploys alone.

### Ask staging what it is serving

The check reads staging's public dataset status and compares the manifest digest,
verification status, and counts against the dataset being promoted.

*Alternatives rejected:*

- **A `--confirm-staged` flag.** Satisfiable by the same oversight it exists to
  catch. Typed confirmations work for intent ("delete other seasons") because the
  operator supplies knowledge; they do not work for facts about another system.
- **A receipt file written by `season-stage`.** Copyable, forgeable, and can
  outlive the state it describes — staging could have been reloaded since.
- **Querying the staging database directly.** Would work, but requires promotion
  to hold staging credentials it otherwise never needs.

Asking the running deployment is the only option where the answer describes the
present rather than the past.

### Run the check before the backup, outside the lock

A failure then costs nothing: no backup taken, no advisory lock held, production
untouched.

## Risks / Trade-offs

- **Staging drifts from production and blocks a legitimate promotion** → the
  failure is loud and specific, and the remedy is to run `season-stage`, which
  is the step being enforced. Acceptable.
- **Staging outage blocks promotion** → deliberate. An absent answer is not
  permission; promotion of a dataset nothing has rehearsed is the condition this
  exists to prevent.
- **This does not make staging a gate for code** → stated plainly rather than
  implied. The remaining work is a delivery-model change: production would track
  a release branch that trails `main`, which rewrites the "merge to main deploys
  to production" contract documented in AGENTS.md, README, CONTRIBUTING, the PR
  template, and the release observer's trigger. That is worth doing deliberately,
  not as a rider on a data-path fix.
