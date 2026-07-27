## Why

Loading a season currently makes the database unreadable for the duration of the load.
`replace_season` runs `TRUNCATE` and then copies every row inside one transaction, and
`TRUNCATE` takes an `ACCESS EXCLUSIVE` lock held until commit. On a live database that is
a full read outage measured in the length of the load, not in milliseconds.

Nothing in the specs prohibits this, because nothing says a replacement must keep the
database readable. That is the missing invariant: atomicity is specced, availability
during the operation is not.

Alongside it sits a set of schema defects that have accumulated because adding a
migration was unsafe until now. The promote path did not apply migrations at all until
that was fixed, so migration `10` is the first that can land safely.

- `games.game_date` is nullable while the loader's own validation requires it non-null.
  The schema permits a state the code refuses to produce, so the constraint lives in one
  place instead of two.
- `games.home_team_id` and `games.away_team_id` are foreign keys with no indexes.
- `vw_team_standings` joins with `t.id = g.home_team_id OR t.id = g.away_team_id`. An
  OR-join cannot use either index.
- `team_game_stats` and `player_game_stats` carry `SERIAL` surrogate primary keys that
  nothing references, while their real identity is already a unique constraint.
- Four views carry `ORDER BY` clauses every caller discards.

## What Changes

- **Migration `10`**: `game_date` NOT NULL, indexes on both game foreign keys, the
  standings view rewritten as a `UNION ALL` of home and away legs, surrogate keys dropped
  in favour of the natural keys, and the discarded `ORDER BY` clauses removed.
- **Load into new tables and swap by rename**, so the exclusive lock is held for the
  rename rather than for the whole load.
- Harden `split_sql` in `scripts/init_db.py`, which toggles on any `$$` and would
  mis-split a tagged dollar quote or a `$$` inside a string literal. Nothing in `01`-`09`
  trips it; migration `10` should not be the first thing to find out.
- Replace the O(n²) filter-inside-a-loop in `transform_games` with a grouped pass.
- Delete `etl/load.py` and its test. It is retired and unreachable, but still carries
  four unguarded `DELETE` statements and a `load_season` that silently skips shot
  attempts.

**Explicitly not changing**: the `minutes` column types. `team_game_stats.minutes` is
`INTEGER` and `player_game_stats.minutes` is `DECIMAL(5,1)`, and the API models mirror
that. Team minutes are genuinely integral — five players times forty-eight minutes — so
this reflects a real difference rather than drift, and widening it would be a breaking
API change bought for consistency alone.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `season-lifecycle`: the replacement requirement gains an availability constraint. A
  replacement must remain atomic and serialized, and must additionally not hold the
  database unreadable for the duration of the load.

## Impact

- **Schema**: one new append-only migration. It rewrites two tables' primary keys, which
  on production means ~26k player rows and ~2.5k team rows — small, but a real rewrite
  that must be applied by an operator through the promote path.
- **Code**: `etl/season_lifecycle.py` replacement strategy, `scripts/init_db.py`
  statement splitting, `etl/transform.py` game assembly; `etl/load.py` and
  `tests/test_etl_load.py` deleted.
- **Behavior**: reads continue during a load instead of blocking. Query plans for
  standings and for game lookups by team improve. No API response shape changes.
- **Interaction with the pre-commit verifier**: verification runs inside the replacement
  transaction and queries tables by name, so the rename must happen before it runs.
- **Dependencies**: none added.
- **Rails**: migration files are append-only and immutable once applied; this adds `10`
  rather than editing anything. Applying it to staging or production is an operator step.

Closes #31.
