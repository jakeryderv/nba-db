-- Correct season metadata for historical seasons and incomplete player logs.

CREATE OR REPLACE PROCEDURE sp_update_season_metadata(p_season VARCHAR(10))
LANGUAGE plpgsql
AS $$
DECLARE
    v_start_year INTEGER;
    v_end_suffix INTEGER;
    v_end_year INTEGER;
    v_games_count INTEGER;
    v_players_count INTEGER;
BEGIN
    v_start_year := CAST(split_part(p_season, '-', 1) AS INTEGER);
    v_end_suffix := CAST(split_part(p_season, '-', 2) AS INTEGER);
    v_end_year := v_start_year + ((v_end_suffix - (v_start_year % 100) + 100) % 100);

    SELECT COUNT(*) INTO v_games_count
    FROM games WHERE season = p_season;

    SELECT COUNT(DISTINCT player_id) INTO v_players_count
    FROM player_game_stats WHERE season = p_season;

    INSERT INTO seasons (id, start_year, end_year, games_count, players_count)
    VALUES (
        p_season,
        v_start_year,
        v_end_year,
        v_games_count,
        v_players_count
    )
    ON CONFLICT (id) DO UPDATE SET
        start_year = EXCLUDED.start_year,
        end_year = EXCLUDED.end_year,
        games_count = EXCLUDED.games_count,
        players_count = EXCLUDED.players_count,
        loaded_at = CURRENT_TIMESTAMP;
END;
$$;
