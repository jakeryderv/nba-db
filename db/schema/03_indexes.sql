-- NBA Database Indexes (MySQL)

-- Games indexes
CREATE INDEX idx_games_season ON games(season);
CREATE INDEX idx_games_date ON games(game_date);

-- Player game stats indexes
CREATE INDEX idx_player_game_stats_player ON player_game_stats(player_id);
CREATE INDEX idx_player_game_stats_game ON player_game_stats(game_id);
CREATE INDEX idx_player_game_stats_season ON player_game_stats(season);
CREATE INDEX idx_player_game_stats_player_season ON player_game_stats(player_id, season);

-- Team game stats indexes
CREATE INDEX idx_team_game_stats_team ON team_game_stats(team_id);
CREATE INDEX idx_team_game_stats_game ON team_game_stats(game_id);
CREATE INDEX idx_team_game_stats_season ON team_game_stats(season);

-- Players indexes
CREATE INDEX idx_players_active ON players(is_active);
