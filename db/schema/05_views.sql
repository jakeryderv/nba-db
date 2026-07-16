-- NBA Database Views (PostgreSQL)

-- Team Standings
CREATE OR REPLACE VIEW vw_team_standings AS
SELECT
    t.id AS team_id,
    t.full_name AS team_name,
    t.abbreviation,
    g.season,
    SUM(CASE
        WHEN (g.home_team_id = t.id AND g.home_score > g.away_score)
          OR (g.away_team_id = t.id AND g.away_score > g.home_score)
        THEN 1 ELSE 0
    END) AS wins,
    SUM(CASE
        WHEN (g.home_team_id = t.id AND g.home_score < g.away_score)
          OR (g.away_team_id = t.id AND g.away_score < g.home_score)
        THEN 1 ELSE 0
    END) AS losses,
    ROUND(
        SUM(CASE
            WHEN (g.home_team_id = t.id AND g.home_score > g.away_score)
              OR (g.away_team_id = t.id AND g.away_score > g.home_score)
            THEN 1 ELSE 0
        END)::NUMERIC / NULLIF(COUNT(*), 0), 3
    ) AS win_pct
FROM teams t
JOIN games g ON t.id = g.home_team_id OR t.id = g.away_team_id
GROUP BY t.id, t.full_name, t.abbreviation, g.season
ORDER BY g.season DESC, wins DESC;

-- Player Season Averages
CREATE OR REPLACE VIEW vw_player_season_averages AS
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
JOIN teams t ON pgs.team_id = t.id
GROUP BY p.id, p.full_name, pgs.season, t.abbreviation
ORDER BY pgs.season DESC, ppg DESC;

-- Game Summary
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
JOIN teams at ON g.away_team_id = at.id
ORDER BY g.game_date DESC;

-- Team Season Stats
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
GROUP BY t.id, t.full_name, t.abbreviation, tgs.season
ORDER BY tgs.season DESC, ppg DESC;
