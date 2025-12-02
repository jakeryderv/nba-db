-- NBA Database Constraints (MySQL)
-- Note: MySQL 8.0.16+ supports CHECK constraints

-- Games constraints
ALTER TABLE games ADD CONSTRAINT chk_games_home_score_positive CHECK (home_score >= 0);
ALTER TABLE games ADD CONSTRAINT chk_games_away_score_positive CHECK (away_score >= 0);
ALTER TABLE games ADD CONSTRAINT chk_games_different_teams CHECK (home_team_id != away_team_id);

-- Player game stats constraints
ALTER TABLE player_game_stats ADD CONSTRAINT chk_pgs_points_positive CHECK (points >= 0);
ALTER TABLE player_game_stats ADD CONSTRAINT chk_pgs_rebounds_positive CHECK (rebounds >= 0);
ALTER TABLE player_game_stats ADD CONSTRAINT chk_pgs_assists_positive CHECK (assists >= 0);
ALTER TABLE player_game_stats ADD CONSTRAINT chk_pgs_fg_valid CHECK (fgm >= 0 AND fga >= 0 AND fgm <= fga);
ALTER TABLE player_game_stats ADD CONSTRAINT chk_pgs_fg3_valid CHECK (fg3m >= 0 AND fg3a >= 0 AND fg3m <= fg3a);
ALTER TABLE player_game_stats ADD CONSTRAINT chk_pgs_ft_valid CHECK (ftm >= 0 AND fta >= 0 AND ftm <= fta);

-- Team game stats constraints
ALTER TABLE team_game_stats ADD CONSTRAINT chk_tgs_points_positive CHECK (points >= 0);
ALTER TABLE team_game_stats ADD CONSTRAINT chk_tgs_rebounds_positive CHECK (rebounds >= 0);
ALTER TABLE team_game_stats ADD CONSTRAINT chk_tgs_assists_positive CHECK (assists >= 0);
ALTER TABLE team_game_stats ADD CONSTRAINT chk_tgs_fg_valid CHECK (fgm >= 0 AND fga >= 0 AND fgm <= fga);
ALTER TABLE team_game_stats ADD CONSTRAINT chk_tgs_fg3_valid CHECK (fg3m >= 0 AND fg3a >= 0 AND fg3m <= fg3a);
ALTER TABLE team_game_stats ADD CONSTRAINT chk_tgs_ft_valid CHECK (ftm >= 0 AND fta >= 0 AND ftm <= fta);

-- Teams constraints
ALTER TABLE teams ADD CONSTRAINT chk_teams_year_founded_valid CHECK (year_founded >= 1946 AND year_founded <= 2030);

-- Seasons constraints
ALTER TABLE seasons ADD CONSTRAINT chk_seasons_years_valid CHECK (start_year >= 1946 AND end_year = start_year + 1);
ALTER TABLE seasons ADD CONSTRAINT chk_seasons_counts_positive CHECK (games_count >= 0 AND players_count >= 0);
