-- Provenance and relational guarantees for the verified single-season dataset.

ALTER TABLE seasons ADD COLUMN IF NOT EXISTS shot_attempts_count BIGINT NOT NULL DEFAULT 0;
ALTER TABLE seasons ADD COLUMN IF NOT EXISTS manifest_generated_at TIMESTAMPTZ;
ALTER TABLE seasons ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
ALTER TABLE seasons ADD COLUMN IF NOT EXISTS verification_status VARCHAR(20) NOT NULL DEFAULT 'untracked';
ALTER TABLE seasons ADD COLUMN IF NOT EXISTS manifest_sha256 CHAR(64);

CREATE INDEX IF NOT EXISTS idx_games_season_date ON games(season, game_date);
CREATE INDEX IF NOT EXISTS idx_shots_season_action_type ON shot_attempts(season, action_type);

UPDATE seasons s
SET shot_attempts_count = (
    SELECT COUNT(*) FROM shot_attempts sa WHERE sa.season = s.id
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_seasons_verification_status' AND conrelid = 'seasons'::regclass
    ) THEN
        ALTER TABLE seasons ADD CONSTRAINT chk_seasons_verification_status
            CHECK (verification_status IN ('untracked', 'passed'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_seasons_manifest_sha256' AND conrelid = 'seasons'::regclass
    ) THEN
        ALTER TABLE seasons ADD CONSTRAINT chk_seasons_manifest_sha256
            CHECK (manifest_sha256 IS NULL OR manifest_sha256 ~ '^[0-9a-f]{64}$');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_games_id_season' AND conrelid = 'games'::regclass
    ) THEN
        ALTER TABLE games ADD CONSTRAINT uq_games_id_season UNIQUE (id, season);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_games_season' AND conrelid = 'games'::regclass
    ) THEN
        ALTER TABLE games ADD CONSTRAINT fk_games_season
            FOREIGN KEY (season) REFERENCES seasons(id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_tgs_game_season' AND conrelid = 'team_game_stats'::regclass
    ) THEN
        ALTER TABLE team_game_stats ADD CONSTRAINT fk_tgs_game_season
            FOREIGN KEY (game_id, season) REFERENCES games(id, season);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_pgs_game_season' AND conrelid = 'player_game_stats'::regclass
    ) THEN
        ALTER TABLE player_game_stats ADD CONSTRAINT fk_pgs_game_season
            FOREIGN KEY (game_id, season) REFERENCES games(id, season);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_shots_game_season' AND conrelid = 'shot_attempts'::regclass
    ) THEN
        ALTER TABLE shot_attempts ADD CONSTRAINT fk_shots_game_season
            FOREIGN KEY (game_id, season) REFERENCES games(id, season);
    END IF;
END;
$$;

-- Keep the compatibility view aligned with API semantics: DNP rows are not
-- appearances, and one season row uses the player's most recent team.
CREATE OR REPLACE VIEW vw_player_season_averages AS
WITH latest_team AS (
    SELECT DISTINCT ON (pgs.player_id, pgs.season)
        pgs.player_id,
        pgs.season,
        pgs.team_id
    FROM player_game_stats pgs
    JOIN games g ON g.id = pgs.game_id
    WHERE pgs.minutes IS NOT NULL
    ORDER BY pgs.player_id, pgs.season, g.game_date DESC NULLS LAST, g.id DESC
)
SELECT
    p.id AS player_id,
    p.full_name AS player_name,
    pgs.season,
    t.abbreviation AS team_abbr,
    COUNT(*) AS games_played,
    ROUND(AVG(pgs.points), 1) AS ppg,
    ROUND(AVG(pgs.rebounds), 1) AS rpg,
    ROUND(AVG(pgs.assists), 1) AS apg,
    ROUND(AVG(pgs.steals), 1) AS spg,
    ROUND(AVG(pgs.blocks), 1) AS bpg,
    ROUND(SUM(pgs.fgm)::NUMERIC / NULLIF(SUM(pgs.fga), 0), 3) AS fg_pct,
    ROUND(SUM(pgs.fg3m)::NUMERIC / NULLIF(SUM(pgs.fg3a), 0), 3) AS fg3_pct,
    ROUND(SUM(pgs.ftm)::NUMERIC / NULLIF(SUM(pgs.fta), 0), 3) AS ft_pct,
    ROUND(AVG(pgs.minutes), 1) AS mpg
FROM player_game_stats pgs
JOIN players p ON pgs.player_id = p.id
JOIN latest_team lt ON lt.player_id = pgs.player_id AND lt.season = pgs.season
JOIN teams t ON t.id = lt.team_id
WHERE pgs.minutes IS NOT NULL
GROUP BY p.id, p.full_name, pgs.season, t.abbreviation;
