-- Shot-location data for the guarded regular-season dataset.

CREATE TABLE IF NOT EXISTS shot_attempts (
    game_id VARCHAR(20) NOT NULL,
    event_id INTEGER NOT NULL,
    player_id BIGINT NOT NULL,
    team_id BIGINT NOT NULL,
    season VARCHAR(10) NOT NULL,
    period INTEGER NOT NULL,
    minutes_remaining INTEGER NOT NULL,
    seconds_remaining INTEGER NOT NULL,
    action_type VARCHAR(100) NOT NULL,
    shot_type VARCHAR(20) NOT NULL,
    zone_basic VARCHAR(50) NOT NULL,
    zone_area VARCHAR(50) NOT NULL,
    zone_range VARCHAR(50) NOT NULL,
    shot_distance INTEGER NOT NULL,
    loc_x INTEGER NOT NULL,
    loc_y INTEGER NOT NULL,
    shot_made BOOLEAN NOT NULL,
    PRIMARY KEY (game_id, event_id),
    FOREIGN KEY (game_id) REFERENCES games(id),
    FOREIGN KEY (player_id) REFERENCES players(id),
    FOREIGN KEY (team_id) REFERENCES teams(id),
    CONSTRAINT chk_shots_period CHECK (period BETWEEN 1 AND 20),
    CONSTRAINT chk_shots_clock CHECK (
        minutes_remaining BETWEEN 0 AND 12 AND seconds_remaining BETWEEN 0 AND 59
    ),
    CONSTRAINT chk_shots_distance CHECK (shot_distance BETWEEN 0 AND 100),
    CONSTRAINT chk_shots_coordinates CHECK (loc_x BETWEEN -400 AND 400 AND loc_y BETWEEN -100 AND 1000),
    CONSTRAINT chk_shots_type CHECK (shot_type IN ('2PT Field Goal', '3PT Field Goal'))
);

CREATE INDEX IF NOT EXISTS idx_shots_season ON shot_attempts(season);
CREATE INDEX IF NOT EXISTS idx_shots_player_season ON shot_attempts(player_id, season);
CREATE INDEX IF NOT EXISTS idx_shots_team_season ON shot_attempts(team_id, season);
CREATE INDEX IF NOT EXISTS idx_shots_game ON shot_attempts(game_id);
CREATE INDEX IF NOT EXISTS idx_shots_zone ON shot_attempts(season, zone_basic, zone_area, zone_range);

-- This procedure predates shot_attempts. Recreate it so its child-table
-- deletion order remains valid after this migration.
CREATE OR REPLACE PROCEDURE sp_delete_season(p_season VARCHAR(10), p_confirm BOOLEAN)
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT p_confirm THEN
        RAISE EXCEPTION 'Set p_confirm = TRUE to proceed.';
    END IF;

    DELETE FROM shot_attempts WHERE season = p_season;
    DELETE FROM player_game_stats WHERE season = p_season;
    DELETE FROM team_game_stats WHERE season = p_season;
    DELETE FROM games WHERE season = p_season;
    DELETE FROM seasons WHERE id = p_season;
END;
$$;
