-- NBA Database Schema
-- Tables for storing NBA statistics data

-- Teams table
CREATE TABLE teams (
    id BIGINT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    abbreviation VARCHAR(3) NOT NULL UNIQUE,
    nickname VARCHAR(50) NOT NULL,
    city VARCHAR(50) NOT NULL,
    state VARCHAR(50) NOT NULL,
    year_founded INTEGER NOT NULL
);

-- Players table
CREATE TABLE players (
    id BIGINT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT FALSE
);

-- Games table
CREATE TABLE games (
    id VARCHAR(20) PRIMARY KEY,
    home_team_id BIGINT NOT NULL REFERENCES teams(id),
    away_team_id BIGINT NOT NULL REFERENCES teams(id),
    home_score INTEGER NOT NULL,
    away_score INTEGER NOT NULL,
    season VARCHAR(10) NOT NULL,
    game_date DATE
);

-- Player game statistics (box scores)
CREATE TABLE player_game_stats (
    id SERIAL PRIMARY KEY,
    game_id VARCHAR(20) NOT NULL REFERENCES games(id),
    player_id BIGINT NOT NULL REFERENCES players(id),
    team_id BIGINT NOT NULL REFERENCES teams(id),

    -- Basic info
    position VARCHAR(5),
    starter BOOLEAN,
    minutes INTERVAL,

    -- Traditional stats
    points INTEGER NOT NULL DEFAULT 0,
    rebounds INTEGER NOT NULL DEFAULT 0,
    offensive_rebounds INTEGER NOT NULL DEFAULT 0,
    defensive_rebounds INTEGER NOT NULL DEFAULT 0,
    assists INTEGER NOT NULL DEFAULT 0,
    steals INTEGER NOT NULL DEFAULT 0,
    blocks INTEGER NOT NULL DEFAULT 0,
    turnovers INTEGER NOT NULL DEFAULT 0,
    personal_fouls INTEGER NOT NULL DEFAULT 0,

    -- Shooting stats
    fgm INTEGER NOT NULL DEFAULT 0,
    fga INTEGER NOT NULL DEFAULT 0,
    fg_pct NUMERIC(5,3),
    fg3m INTEGER NOT NULL DEFAULT 0,
    fg3a INTEGER NOT NULL DEFAULT 0,
    fg3_pct NUMERIC(5,3),
    ftm INTEGER NOT NULL DEFAULT 0,
    fta INTEGER NOT NULL DEFAULT 0,
    ft_pct NUMERIC(5,3),

    -- Plus/minus
    plus_minus NUMERIC(6,1),

    -- Advanced stats
    offensive_rating NUMERIC(6,2),
    defensive_rating NUMERIC(6,2),
    net_rating NUMERIC(6,2),
    ast_pct NUMERIC(5,3),
    ast_ratio NUMERIC(5,2),
    reb_pct NUMERIC(5,3),
    ts_pct NUMERIC(5,3),
    usg_pct NUMERIC(5,3),
    pace NUMERIC(7,2),
    pie NUMERIC(5,3),

    season VARCHAR(10) NOT NULL,

    UNIQUE (game_id, player_id)
);

-- Team game statistics (box scores)
CREATE TABLE team_game_stats (
    id SERIAL PRIMARY KEY,
    game_id VARCHAR(20) NOT NULL REFERENCES games(id),
    team_id BIGINT NOT NULL REFERENCES teams(id),
    is_home BOOLEAN NOT NULL,

    -- Traditional stats
    points INTEGER NOT NULL DEFAULT 0,
    rebounds INTEGER NOT NULL DEFAULT 0,
    offensive_rebounds INTEGER NOT NULL DEFAULT 0,
    defensive_rebounds INTEGER NOT NULL DEFAULT 0,
    assists INTEGER NOT NULL DEFAULT 0,
    steals INTEGER NOT NULL DEFAULT 0,
    blocks INTEGER NOT NULL DEFAULT 0,
    turnovers INTEGER NOT NULL DEFAULT 0,
    personal_fouls INTEGER NOT NULL DEFAULT 0,

    -- Shooting stats
    fgm INTEGER NOT NULL DEFAULT 0,
    fga INTEGER NOT NULL DEFAULT 0,
    fg_pct NUMERIC(5,3),
    fg3m INTEGER NOT NULL DEFAULT 0,
    fg3a INTEGER NOT NULL DEFAULT 0,
    fg3_pct NUMERIC(5,3),
    ftm INTEGER NOT NULL DEFAULT 0,
    fta INTEGER NOT NULL DEFAULT 0,
    ft_pct NUMERIC(5,3),

    -- Advanced stats
    offensive_rating NUMERIC(6,2),
    defensive_rating NUMERIC(6,2),
    net_rating NUMERIC(6,2),
    pace NUMERIC(7,2),
    pie NUMERIC(5,3),

    season VARCHAR(10) NOT NULL,

    UNIQUE (game_id, team_id)
);

-- Shot chart detail
CREATE TABLE shots (
    id SERIAL PRIMARY KEY,
    game_id VARCHAR(20) NOT NULL REFERENCES games(id),
    game_event_id INTEGER NOT NULL,
    player_id BIGINT NOT NULL REFERENCES players(id),
    team_id BIGINT NOT NULL REFERENCES teams(id),

    -- Shot timing
    period INTEGER NOT NULL,
    minutes_remaining INTEGER NOT NULL,
    seconds_remaining INTEGER NOT NULL,

    -- Shot description
    event_type VARCHAR(20) NOT NULL,  -- 'Made Shot' or 'Missed Shot'
    action_type VARCHAR(50) NOT NULL,  -- 'Jump Shot', 'Layup', etc.
    shot_type VARCHAR(20) NOT NULL,    -- '2PT Field Goal' or '3PT Field Goal'

    -- Shot location zones
    shot_zone_basic VARCHAR(30),
    shot_zone_area VARCHAR(30),
    shot_zone_range VARCHAR(20),
    shot_distance INTEGER,

    -- Court coordinates (in tenths of feet from basket)
    loc_x INTEGER NOT NULL,
    loc_y INTEGER NOT NULL,

    -- Result
    shot_made BOOLEAN NOT NULL,

    -- Game context
    game_date DATE,
    home_team VARCHAR(3),
    away_team VARCHAR(3),

    season VARCHAR(10) NOT NULL,

    UNIQUE (game_id, game_event_id, player_id)
);
