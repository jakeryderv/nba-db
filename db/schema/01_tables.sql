-- NBA Database Schema (PostgreSQL)
-- Simplified tables for teams, players, games, and game stats

-- Seasons table (tracks loaded seasons)
CREATE TABLE IF NOT EXISTS seasons (
    id VARCHAR(10) PRIMARY KEY,  -- e.g., '2024-25'
    start_year INTEGER NOT NULL,
    end_year INTEGER NOT NULL,
    games_count INTEGER DEFAULT 0,
    players_count INTEGER DEFAULT 0,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Teams table
CREATE TABLE IF NOT EXISTS teams (
    id BIGINT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    abbreviation VARCHAR(3) NOT NULL UNIQUE,
    nickname VARCHAR(50) NOT NULL,
    city VARCHAR(50) NOT NULL,
    state VARCHAR(50) NOT NULL,
    year_founded INTEGER NOT NULL
);

-- Players table
CREATE TABLE IF NOT EXISTS players (
    id BIGINT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    first_name VARCHAR(50),
    last_name VARCHAR(50),
    is_active BOOLEAN NOT NULL DEFAULT FALSE
);

-- Games table
CREATE TABLE IF NOT EXISTS games (
    id VARCHAR(20) PRIMARY KEY,
    game_date DATE,
    season VARCHAR(10) NOT NULL,
    home_team_id BIGINT NOT NULL,
    away_team_id BIGINT NOT NULL,
    home_score INTEGER NOT NULL,
    away_score INTEGER NOT NULL,
    FOREIGN KEY (home_team_id) REFERENCES teams(id),
    FOREIGN KEY (away_team_id) REFERENCES teams(id)
);

-- Team game statistics
CREATE TABLE IF NOT EXISTS team_game_stats (
    id SERIAL PRIMARY KEY,
    game_id VARCHAR(20) NOT NULL,
    team_id BIGINT NOT NULL,
    season VARCHAR(10) NOT NULL,
    is_home BOOLEAN NOT NULL,

    -- Stats
    minutes INTEGER,
    points INTEGER NOT NULL DEFAULT 0,
    rebounds INTEGER NOT NULL DEFAULT 0,
    offensive_rebounds INTEGER NOT NULL DEFAULT 0,
    defensive_rebounds INTEGER NOT NULL DEFAULT 0,
    assists INTEGER NOT NULL DEFAULT 0,
    steals INTEGER NOT NULL DEFAULT 0,
    blocks INTEGER NOT NULL DEFAULT 0,
    turnovers INTEGER NOT NULL DEFAULT 0,
    personal_fouls INTEGER NOT NULL DEFAULT 0,

    -- Shooting
    fgm INTEGER NOT NULL DEFAULT 0,
    fga INTEGER NOT NULL DEFAULT 0,
    fg_pct DECIMAL(5,3),
    fg3m INTEGER NOT NULL DEFAULT 0,
    fg3a INTEGER NOT NULL DEFAULT 0,
    fg3_pct DECIMAL(5,3),
    ftm INTEGER NOT NULL DEFAULT 0,
    fta INTEGER NOT NULL DEFAULT 0,
    ft_pct DECIMAL(5,3),
    plus_minus DECIMAL(6,1),

    UNIQUE (game_id, team_id),
    FOREIGN KEY (game_id) REFERENCES games(id),
    FOREIGN KEY (team_id) REFERENCES teams(id)
);

-- Player game statistics
CREATE TABLE IF NOT EXISTS player_game_stats (
    id SERIAL PRIMARY KEY,
    game_id VARCHAR(20) NOT NULL,
    player_id BIGINT NOT NULL,
    team_id BIGINT NOT NULL,
    season VARCHAR(10) NOT NULL,

    -- Stats
    minutes DECIMAL(5,1),
    points INTEGER NOT NULL DEFAULT 0,
    rebounds INTEGER NOT NULL DEFAULT 0,
    offensive_rebounds INTEGER NOT NULL DEFAULT 0,
    defensive_rebounds INTEGER NOT NULL DEFAULT 0,
    assists INTEGER NOT NULL DEFAULT 0,
    steals INTEGER NOT NULL DEFAULT 0,
    blocks INTEGER NOT NULL DEFAULT 0,
    turnovers INTEGER NOT NULL DEFAULT 0,
    personal_fouls INTEGER NOT NULL DEFAULT 0,

    -- Shooting
    fgm INTEGER NOT NULL DEFAULT 0,
    fga INTEGER NOT NULL DEFAULT 0,
    fg_pct DECIMAL(5,3),
    fg3m INTEGER NOT NULL DEFAULT 0,
    fg3a INTEGER NOT NULL DEFAULT 0,
    fg3_pct DECIMAL(5,3),
    ftm INTEGER NOT NULL DEFAULT 0,
    fta INTEGER NOT NULL DEFAULT 0,
    ft_pct DECIMAL(5,3),
    plus_minus DECIMAL(6,1),

    UNIQUE (game_id, player_id),
    FOREIGN KEY (game_id) REFERENCES games(id),
    FOREIGN KEY (player_id) REFERENCES players(id),
    FOREIGN KEY (team_id) REFERENCES teams(id)
);
