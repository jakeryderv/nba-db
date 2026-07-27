-- NBA Database Schema Hardening (PostgreSQL)
--
-- Idempotent, like every migration here, so an existing deployment can adopt it
-- and a re-run is a no-op. Guarded with DO blocks where the underlying DDL is
-- not itself idempotent.

-- 1. game_date is required.
--
-- The loader's own validation already refuses a null game date, so the schema
-- permitted a state the code would not produce. A constraint enforced in one
-- place only holds for writers that go through that place.
ALTER TABLE games ALTER COLUMN game_date SET NOT NULL;

-- 2. Index both game foreign keys.
--
-- Both columns are foreign keys with no index, so any lookup of a team's games
-- scans the table, and the rewritten standings view below depends on these.
CREATE INDEX IF NOT EXISTS idx_games_home_team ON games(home_team_id);
CREATE INDEX IF NOT EXISTS idx_games_away_team ON games(away_team_id);

-- 3. Make the natural keys the primary keys.
--
-- team_game_stats and player_game_stats carried SERIAL surrogate keys that
-- nothing referenced -- no foreign key, no query, no application code -- while
-- their real identity was already enforced by a unique constraint.
--
-- The unique constraint is dropped before the primary key is added rather than
-- alongside it. Adding a primary key over columns that already carry a unique
-- constraint builds a second identical index, so every write would maintain two
-- indexes over the same columns for no benefit.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'team_game_stats' AND column_name = 'id'
    ) THEN
        ALTER TABLE team_game_stats DROP CONSTRAINT IF EXISTS team_game_stats_game_id_team_id_key;
        ALTER TABLE team_game_stats DROP CONSTRAINT IF EXISTS team_game_stats_pkey;
        ALTER TABLE team_game_stats DROP COLUMN id;
        ALTER TABLE team_game_stats ADD PRIMARY KEY (game_id, team_id);
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'player_game_stats' AND column_name = 'id'
    ) THEN
        ALTER TABLE player_game_stats
            DROP CONSTRAINT IF EXISTS player_game_stats_game_id_player_id_key;
        ALTER TABLE player_game_stats DROP CONSTRAINT IF EXISTS player_game_stats_pkey;
        ALTER TABLE player_game_stats DROP COLUMN id;
        ALTER TABLE player_game_stats ADD PRIMARY KEY (game_id, player_id);
    END IF;
END;
$$;

-- 4. Rewrite the standings view without an OR-join.
--
-- `JOIN games g ON t.id = g.home_team_id OR t.id = g.away_team_id` cannot use
-- either index: PostgreSQL has no way to satisfy a disjunction across two
-- columns from one index scan. A UNION ALL of the home and away legs is the
-- same result set expressed so each leg can use its own index.
--
-- The ORDER BY is dropped along with the rewrite; see note 5.
CREATE OR REPLACE VIEW vw_team_standings AS
WITH team_games AS (
    SELECT
        g.home_team_id AS team_id,
        g.season,
        g.home_score AS team_score,
        g.away_score AS opponent_score
    FROM games g
    UNION ALL
    SELECT
        g.away_team_id AS team_id,
        g.season,
        g.away_score AS team_score,
        g.home_score AS opponent_score
    FROM games g
)
-- Column list, order, and types must match the view being replaced:
-- CREATE OR REPLACE VIEW cannot insert a column into the middle of one.
SELECT
    t.id AS team_id,
    t.full_name AS team_name,
    t.abbreviation,
    tg.season,
    SUM(CASE WHEN tg.team_score > tg.opponent_score THEN 1 ELSE 0 END) AS wins,
    SUM(CASE WHEN tg.team_score < tg.opponent_score THEN 1 ELSE 0 END) AS losses,
    ROUND(
        SUM(CASE WHEN tg.team_score > tg.opponent_score THEN 1 ELSE 0 END)::NUMERIC
        / NULLIF(COUNT(*), 0), 3
    ) AS win_pct
FROM teams t
JOIN team_games tg ON tg.team_id = t.id
GROUP BY t.id, t.full_name, t.abbreviation, tg.season;

-- 5. Drop ORDER BY from views whose callers re-order.
--
-- Every caller applies its own ordering, so the view's sort is work done and
-- then thrown away. Definitions are otherwise unchanged.
--
-- vw_player_season_averages is deliberately absent. Migration 09 redefined it
-- with a team_abbr column and DNP-aware semantics, and its only ORDER BY sits
-- inside a DISTINCT ON, where it selects which row survives rather than
-- ordering output. Rewriting it from the 05 text would silently revert 09.
CREATE OR REPLACE VIEW vw_game_summary AS
SELECT
    g.id AS game_id,
    g.game_date,
    g.season,
    ht.full_name AS home_team,
    ht.abbreviation AS home_abbr,
    g.home_score,
    at.full_name AS away_team,
    at.abbreviation AS away_abbr,
    g.away_score,
    CASE WHEN g.home_score > g.away_score THEN ht.abbreviation ELSE at.abbreviation END AS winner
FROM games g
JOIN teams ht ON g.home_team_id = ht.id
JOIN teams at ON g.away_team_id = at.id;

CREATE OR REPLACE VIEW vw_team_season_stats AS
SELECT
    t.id AS team_id,
    t.full_name AS team_name,
    t.abbreviation,
    tgs.season,
    COUNT(*) AS games_played,
    ROUND(AVG(tgs.points), 1) AS ppg,
    ROUND(AVG(tgs.rebounds), 1) AS rpg,
    ROUND(AVG(tgs.assists), 1) AS apg,
    ROUND(SUM(tgs.fgm)::NUMERIC / NULLIF(SUM(tgs.fga), 0) * 100, 1) AS fg_pct,
    ROUND(SUM(tgs.fg3m)::NUMERIC / NULLIF(SUM(tgs.fg3a), 0) * 100, 1) AS fg3_pct
FROM team_game_stats tgs
JOIN teams t ON tgs.team_id = t.id
GROUP BY t.id, t.full_name, t.abbreviation, tgs.season;
