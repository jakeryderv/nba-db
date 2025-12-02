-- NBA Database Stored Procedures (MySQL)

DELIMITER //

-- Update Season Metadata
CREATE PROCEDURE sp_update_season_metadata(IN p_season VARCHAR(10))
BEGIN
    DECLARE v_games_count INTEGER;
    DECLARE v_players_count INTEGER;

    SELECT COUNT(DISTINCT game_id) INTO v_games_count
    FROM player_game_stats WHERE season = p_season;

    SELECT COUNT(DISTINCT player_id) INTO v_players_count
    FROM player_game_stats WHERE season = p_season;

    INSERT INTO seasons (id, start_year, end_year, games_count, players_count)
    VALUES (
        p_season,
        CAST(SUBSTRING_INDEX(p_season, '-', 1) AS UNSIGNED),
        2000 + CAST(SUBSTRING_INDEX(p_season, '-', -1) AS UNSIGNED),
        v_games_count,
        v_players_count
    )
    ON DUPLICATE KEY UPDATE
        games_count = v_games_count,
        players_count = v_players_count,
        loaded_at = CURRENT_TIMESTAMP;
END //

-- Delete Season Data
CREATE PROCEDURE sp_delete_season(IN p_season VARCHAR(10), IN p_confirm BOOLEAN)
BEGIN
    IF NOT p_confirm THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Set p_confirm = TRUE to proceed.';
    END IF;

    DELETE FROM player_game_stats WHERE season = p_season;
    DELETE FROM team_game_stats WHERE season = p_season;
    DELETE FROM games WHERE season = p_season;
    DELETE FROM seasons WHERE id = p_season;
END //

DELIMITER ;
