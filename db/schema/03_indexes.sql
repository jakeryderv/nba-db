-- NBA Database Indexes
-- Optimizes query performance on common access patterns

-- Games indexes
CREATE INDEX idx_games_season ON games(season);
CREATE INDEX idx_games_home_team ON games(home_team_id);
CREATE INDEX idx_games_away_team ON games(away_team_id);
CREATE INDEX idx_games_date ON games(game_date);

-- Player game stats indexes (most queried table)
CREATE INDEX idx_player_game_stats_player ON player_game_stats(player_id);
CREATE INDEX idx_player_game_stats_game ON player_game_stats(game_id);
CREATE INDEX idx_player_game_stats_team ON player_game_stats(team_id);
CREATE INDEX idx_player_game_stats_season ON player_game_stats(season);

-- Composite index for player season queries (e.g., player averages per season)
CREATE INDEX idx_player_game_stats_player_season ON player_game_stats(player_id, season);

-- Team game stats indexes
CREATE INDEX idx_team_game_stats_team ON team_game_stats(team_id);
CREATE INDEX idx_team_game_stats_game ON team_game_stats(game_id);
CREATE INDEX idx_team_game_stats_season ON team_game_stats(season);

-- Shots indexes
CREATE INDEX idx_shots_player ON shots(player_id);
CREATE INDEX idx_shots_game ON shots(game_id);
CREATE INDEX idx_shots_team ON shots(team_id);
CREATE INDEX idx_shots_season ON shots(season);

-- Shot location index for zone analysis
CREATE INDEX idx_shots_zone ON shots(shot_zone_basic, shot_zone_area);

-- Shot result index for efficiency queries
CREATE INDEX idx_shots_made ON shots(shot_made);

-- Players indexes
CREATE INDEX idx_players_active ON players(is_active);
CREATE INDEX idx_players_name ON players(last_name, first_name);

-- Teams index
CREATE INDEX idx_teams_abbreviation ON teams(abbreviation);
