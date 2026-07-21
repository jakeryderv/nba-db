-- NBA Database Constraints (PostgreSQL)
-- Guard each constraint so this migration can adopt an existing deployment.

DO $$
BEGIN
    -- Games constraints
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_games_home_score_positive' AND conrelid = 'games'::regclass) THEN
        ALTER TABLE games ADD CONSTRAINT chk_games_home_score_positive CHECK (home_score >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_games_away_score_positive' AND conrelid = 'games'::regclass) THEN
        ALTER TABLE games ADD CONSTRAINT chk_games_away_score_positive CHECK (away_score >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_games_different_teams' AND conrelid = 'games'::regclass) THEN
        ALTER TABLE games ADD CONSTRAINT chk_games_different_teams CHECK (home_team_id != away_team_id);
    END IF;

    -- Player game stats constraints
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_pgs_points_positive' AND conrelid = 'player_game_stats'::regclass) THEN
        ALTER TABLE player_game_stats ADD CONSTRAINT chk_pgs_points_positive CHECK (points >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_pgs_rebounds_positive' AND conrelid = 'player_game_stats'::regclass) THEN
        ALTER TABLE player_game_stats ADD CONSTRAINT chk_pgs_rebounds_positive CHECK (rebounds >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_pgs_assists_positive' AND conrelid = 'player_game_stats'::regclass) THEN
        ALTER TABLE player_game_stats ADD CONSTRAINT chk_pgs_assists_positive CHECK (assists >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_pgs_fg_valid' AND conrelid = 'player_game_stats'::regclass) THEN
        ALTER TABLE player_game_stats ADD CONSTRAINT chk_pgs_fg_valid CHECK (fgm >= 0 AND fga >= 0 AND fgm <= fga);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_pgs_fg3_valid' AND conrelid = 'player_game_stats'::regclass) THEN
        ALTER TABLE player_game_stats ADD CONSTRAINT chk_pgs_fg3_valid CHECK (fg3m >= 0 AND fg3a >= 0 AND fg3m <= fg3a);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_pgs_ft_valid' AND conrelid = 'player_game_stats'::regclass) THEN
        ALTER TABLE player_game_stats ADD CONSTRAINT chk_pgs_ft_valid CHECK (ftm >= 0 AND fta >= 0 AND ftm <= fta);
    END IF;

    -- Team game stats constraints
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_tgs_points_positive' AND conrelid = 'team_game_stats'::regclass) THEN
        ALTER TABLE team_game_stats ADD CONSTRAINT chk_tgs_points_positive CHECK (points >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_tgs_rebounds_positive' AND conrelid = 'team_game_stats'::regclass) THEN
        ALTER TABLE team_game_stats ADD CONSTRAINT chk_tgs_rebounds_positive CHECK (rebounds >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_tgs_assists_positive' AND conrelid = 'team_game_stats'::regclass) THEN
        ALTER TABLE team_game_stats ADD CONSTRAINT chk_tgs_assists_positive CHECK (assists >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_tgs_fg_valid' AND conrelid = 'team_game_stats'::regclass) THEN
        ALTER TABLE team_game_stats ADD CONSTRAINT chk_tgs_fg_valid CHECK (fgm >= 0 AND fga >= 0 AND fgm <= fga);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_tgs_fg3_valid' AND conrelid = 'team_game_stats'::regclass) THEN
        ALTER TABLE team_game_stats ADD CONSTRAINT chk_tgs_fg3_valid CHECK (fg3m >= 0 AND fg3a >= 0 AND fg3m <= fg3a);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_tgs_ft_valid' AND conrelid = 'team_game_stats'::regclass) THEN
        ALTER TABLE team_game_stats ADD CONSTRAINT chk_tgs_ft_valid CHECK (ftm >= 0 AND fta >= 0 AND ftm <= fta);
    END IF;

    -- Teams and seasons constraints
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_teams_year_founded_valid' AND conrelid = 'teams'::regclass) THEN
        ALTER TABLE teams ADD CONSTRAINT chk_teams_year_founded_valid CHECK (year_founded >= 1946 AND year_founded <= 2030);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_seasons_years_valid' AND conrelid = 'seasons'::regclass) THEN
        ALTER TABLE seasons ADD CONSTRAINT chk_seasons_years_valid CHECK (start_year >= 1946 AND end_year = start_year + 1);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_seasons_counts_positive' AND conrelid = 'seasons'::regclass) THEN
        ALTER TABLE seasons ADD CONSTRAINT chk_seasons_counts_positive CHECK (games_count >= 0 AND players_count >= 0);
    END IF;
END;
$$;
