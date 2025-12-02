--
-- PostgreSQL database dump
--

\restrict utgDPlcfBsoGl2GYLojXQ2cz9vN6BDjHg26V26kFAXlMCGIWEahOC3zrl61dSa7

-- Dumped from database version 16.11
-- Dumped by pg_dump version 16.11

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: fn_audit_trigger(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_audit_trigger() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log (table_name, operation, record_id, new_values)
        VALUES (TG_TABLE_NAME, TG_OP, NEW.id::VARCHAR, to_jsonb(NEW));
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO audit_log (table_name, operation, record_id, old_values, new_values)
        VALUES (TG_TABLE_NAME, TG_OP, NEW.id::VARCHAR, to_jsonb(OLD), to_jsonb(NEW));
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO audit_log (table_name, operation, record_id, old_values)
        VALUES (TG_TABLE_NAME, TG_OP, OLD.id::VARCHAR, to_jsonb(OLD));
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$;


ALTER FUNCTION public.fn_audit_trigger() OWNER TO postgres;

--
-- Name: fn_calculate_fantasy_points(bigint, character varying); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_calculate_fantasy_points(p_player_id bigint, p_season character varying) RETURNS TABLE(game_id character varying, game_date date, fantasy_points numeric)
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- Standard fantasy scoring:
    -- Points: 1, Rebounds: 1.2, Assists: 1.5, Steals: 3, Blocks: 3, Turnovers: -1
    RETURN QUERY
    SELECT
        pgs.game_id,
        g.game_date,
        ROUND(
            pgs.points * 1.0 +
            pgs.rebounds * 1.2 +
            pgs.assists * 1.5 +
            pgs.steals * 3.0 +
            pgs.blocks * 3.0 -
            pgs.turnovers * 1.0, 1
        ) AS fantasy_pts
    FROM player_game_stats pgs
    JOIN games g ON pgs.game_id = g.id
    WHERE pgs.player_id = p_player_id
      AND pgs.season = p_season
    ORDER BY g.game_date DESC;
END;
$$;


ALTER FUNCTION public.fn_calculate_fantasy_points(p_player_id bigint, p_season character varying) OWNER TO postgres;

--
-- Name: fn_get_game_high(character varying, character varying, integer); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_get_game_high(p_stat character varying, p_season character varying, p_limit integer DEFAULT 10) RETURNS TABLE(rank bigint, player_name character varying, team_abbr character varying, game_date date, opponent character varying, stat_value integer)
    LANGUAGE plpgsql
    AS $_$
BEGIN
    IF p_stat NOT IN ('points', 'rebounds', 'assists', 'steals', 'blocks') THEN
        RAISE EXCEPTION 'Invalid stat: %. Valid options: points, rebounds, assists, steals, blocks', p_stat;
    END IF;

    RETURN QUERY EXECUTE format(
        'SELECT
            ROW_NUMBER() OVER (ORDER BY pgs.%I DESC)::BIGINT,
            p.full_name,
            t.abbreviation,
            g.game_date,
            CASE
                WHEN g.home_team_id = pgs.team_id THEN at.abbreviation
                ELSE ht.abbreviation
            END,
            pgs.%I
        FROM player_game_stats pgs
        JOIN players p ON pgs.player_id = p.id
        JOIN teams t ON pgs.team_id = t.id
        JOIN games g ON pgs.game_id = g.id
        JOIN teams ht ON g.home_team_id = ht.id
        JOIN teams at ON g.away_team_id = at.id
        WHERE pgs.season = $1
        ORDER BY pgs.%I DESC
        LIMIT $2',
        p_stat, p_stat, p_stat
    ) USING p_season, p_limit;
END;
$_$;


ALTER FUNCTION public.fn_get_game_high(p_stat character varying, p_season character varying, p_limit integer) OWNER TO postgres;

--
-- Name: fn_get_head_to_head(bigint, bigint, character varying); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_get_head_to_head(p_team1_id bigint, p_team2_id bigint, p_season character varying DEFAULT NULL::character varying) RETURNS TABLE(team1_name character varying, team2_name character varying, season character varying, team1_wins bigint, team2_wins bigint, team1_ppg numeric, team2_ppg numeric, games_played bigint)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        t1.full_name,
        t2.full_name,
        g.season,
        SUM(CASE
            WHEN (g.home_team_id = p_team1_id AND g.home_score > g.away_score)
              OR (g.away_team_id = p_team1_id AND g.away_score > g.home_score)
            THEN 1 ELSE 0
        END)::BIGINT,
        SUM(CASE
            WHEN (g.home_team_id = p_team2_id AND g.home_score > g.away_score)
              OR (g.away_team_id = p_team2_id AND g.away_score > g.home_score)
            THEN 1 ELSE 0
        END)::BIGINT,
        ROUND(AVG(CASE
            WHEN g.home_team_id = p_team1_id THEN g.home_score
            ELSE g.away_score
        END)::NUMERIC, 1),
        ROUND(AVG(CASE
            WHEN g.home_team_id = p_team2_id THEN g.home_score
            ELSE g.away_score
        END)::NUMERIC, 1),
        COUNT(*)::BIGINT
    FROM games g
    JOIN teams t1 ON t1.id = p_team1_id
    JOIN teams t2 ON t2.id = p_team2_id
    WHERE ((g.home_team_id = p_team1_id AND g.away_team_id = p_team2_id)
        OR (g.home_team_id = p_team2_id AND g.away_team_id = p_team1_id))
      AND (p_season IS NULL OR g.season = p_season)
    GROUP BY t1.full_name, t2.full_name, g.season
    ORDER BY g.season DESC;
END;
$$;


ALTER FUNCTION public.fn_get_head_to_head(p_team1_id bigint, p_team2_id bigint, p_season character varying) OWNER TO postgres;

--
-- Name: fn_get_player_averages(bigint, character varying); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_get_player_averages(p_player_id bigint, p_season character varying DEFAULT NULL::character varying) RETURNS TABLE(player_name character varying, season character varying, games_played bigint, ppg numeric, rpg numeric, apg numeric, spg numeric, bpg numeric, fg_pct numeric, fg3_pct numeric, ft_pct numeric, mpg numeric)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.full_name,
        pgs.season,
        COUNT(*)::BIGINT,
        ROUND(AVG(pgs.points)::NUMERIC, 1),
        ROUND(AVG(pgs.rebounds)::NUMERIC, 1),
        ROUND(AVG(pgs.assists)::NUMERIC, 1),
        ROUND(AVG(pgs.steals)::NUMERIC, 1),
        ROUND(AVG(pgs.blocks)::NUMERIC, 1),
        ROUND(SUM(pgs.fgm)::NUMERIC / NULLIF(SUM(pgs.fga), 0), 3),
        ROUND(SUM(pgs.fg3m)::NUMERIC / NULLIF(SUM(pgs.fg3a), 0), 3),
        ROUND(SUM(pgs.ftm)::NUMERIC / NULLIF(SUM(pgs.fta), 0), 3),
        ROUND(AVG(EXTRACT(EPOCH FROM pgs.minutes) / 60)::NUMERIC, 1)
    FROM player_game_stats pgs
    JOIN players p ON pgs.player_id = p.id
    WHERE pgs.player_id = p_player_id
      AND (p_season IS NULL OR pgs.season = p_season)
    GROUP BY p.full_name, pgs.season
    ORDER BY pgs.season DESC;

    -- Raise notice if no data found
    IF NOT FOUND THEN
        RAISE NOTICE 'No stats found for player_id: %', p_player_id;
    END IF;
END;
$$;


ALTER FUNCTION public.fn_get_player_averages(p_player_id bigint, p_season character varying) OWNER TO postgres;

--
-- Name: fn_get_player_shooting_zones(bigint, character varying); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_get_player_shooting_zones(p_player_id bigint, p_season character varying DEFAULT NULL::character varying) RETURNS TABLE(zone character varying, attempts bigint, makes bigint, fg_pct numeric)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.shot_zone_basic,
        COUNT(*)::BIGINT,
        SUM(CASE WHEN s.shot_made THEN 1 ELSE 0 END)::BIGINT,
        ROUND(
            SUM(CASE WHEN s.shot_made THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100, 1
        )
    FROM shots s
    WHERE s.player_id = p_player_id
      AND (p_season IS NULL OR s.season = p_season)
    GROUP BY s.shot_zone_basic
    ORDER BY COUNT(*) DESC;
END;
$$;


ALTER FUNCTION public.fn_get_player_shooting_zones(p_player_id bigint, p_season character varying) OWNER TO postgres;

--
-- Name: fn_get_stat_leaders(character varying, character varying, integer); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_get_stat_leaders(p_stat character varying, p_season character varying, p_limit integer DEFAULT 10) RETURNS TABLE(rank bigint, player_id bigint, player_name character varying, team_abbr character varying, games_played bigint, stat_value numeric)
    LANGUAGE plpgsql
    AS $_$
BEGIN
    -- Validate stat parameter
    IF p_stat NOT IN ('points', 'rebounds', 'assists', 'steals', 'blocks', 'fg_pct', 'fg3_pct') THEN
        RAISE EXCEPTION 'Invalid stat: %. Valid options: points, rebounds, assists, steals, blocks, fg_pct, fg3_pct', p_stat;
    END IF;

    RETURN QUERY EXECUTE format(
        'SELECT
            ROW_NUMBER() OVER (ORDER BY AVG(pgs.%I) DESC)::BIGINT AS rank,
            p.id,
            p.full_name,
            t.abbreviation,
            COUNT(*)::BIGINT AS games_played,
            ROUND(AVG(pgs.%I)::NUMERIC, 1) AS stat_value
        FROM player_game_stats pgs
        JOIN players p ON pgs.player_id = p.id
        JOIN teams t ON pgs.team_id = t.id
        WHERE pgs.season = $1
        GROUP BY p.id, p.full_name, t.abbreviation
        HAVING COUNT(*) >= 10
        ORDER BY stat_value DESC
        LIMIT $2',
        p_stat, p_stat
    ) USING p_season, p_limit;
END;
$_$;


ALTER FUNCTION public.fn_get_stat_leaders(p_stat character varying, p_season character varying, p_limit integer) OWNER TO postgres;

--
-- Name: fn_get_team_record(bigint, character varying); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_get_team_record(p_team_id bigint, p_season character varying DEFAULT NULL::character varying) RETURNS TABLE(team_name character varying, season character varying, wins bigint, losses bigint, win_pct numeric, home_wins bigint, home_losses bigint, away_wins bigint, away_losses bigint)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        t.full_name,
        g.season,
        SUM(CASE
            WHEN (g.home_team_id = t.id AND g.home_score > g.away_score)
              OR (g.away_team_id = t.id AND g.away_score > g.home_score)
            THEN 1 ELSE 0
        END)::BIGINT,
        SUM(CASE
            WHEN (g.home_team_id = t.id AND g.home_score < g.away_score)
              OR (g.away_team_id = t.id AND g.away_score < g.home_score)
            THEN 1 ELSE 0
        END)::BIGINT,
        ROUND(
            SUM(CASE
                WHEN (g.home_team_id = t.id AND g.home_score > g.away_score)
                  OR (g.away_team_id = t.id AND g.away_score > g.home_score)
                THEN 1 ELSE 0
            END)::NUMERIC / NULLIF(COUNT(*), 0), 3
        ),
        SUM(CASE WHEN g.home_team_id = t.id AND g.home_score > g.away_score THEN 1 ELSE 0 END)::BIGINT,
        SUM(CASE WHEN g.home_team_id = t.id AND g.home_score < g.away_score THEN 1 ELSE 0 END)::BIGINT,
        SUM(CASE WHEN g.away_team_id = t.id AND g.away_score > g.home_score THEN 1 ELSE 0 END)::BIGINT,
        SUM(CASE WHEN g.away_team_id = t.id AND g.away_score < g.home_score THEN 1 ELSE 0 END)::BIGINT
    FROM teams t
    JOIN games g ON t.id = g.home_team_id OR t.id = g.away_team_id
    WHERE t.id = p_team_id
      AND (p_season IS NULL OR g.season = p_season)
    GROUP BY t.full_name, g.season
    ORDER BY g.season DESC;
END;
$$;


ALTER FUNCTION public.fn_get_team_record(p_team_id bigint, p_season character varying) OWNER TO postgres;

--
-- Name: fn_search_players(character varying, boolean, integer); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_search_players(p_search_term character varying, p_active_only boolean DEFAULT false, p_limit integer DEFAULT 25) RETURNS TABLE(player_id bigint, full_name character varying, is_active boolean, games_played bigint, latest_season character varying)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.id,
        p.full_name,
        p.is_active,
        COALESCE(stats.games, 0)::BIGINT,
        stats.season
    FROM players p
    LEFT JOIN (
        SELECT
            player_id,
            COUNT(*) AS games,
            MAX(season) AS season
        FROM player_game_stats
        GROUP BY player_id
    ) stats ON p.id = stats.player_id
    WHERE p.full_name ILIKE '%' || p_search_term || '%'
      AND (NOT p_active_only OR p.is_active = TRUE)
    ORDER BY
        CASE WHEN p.full_name ILIKE p_search_term || '%' THEN 0 ELSE 1 END,
        stats.games DESC NULLS LAST,
        p.full_name
    LIMIT p_limit;
END;
$$;


ALTER FUNCTION public.fn_search_players(p_search_term character varying, p_active_only boolean, p_limit integer) OWNER TO postgres;

--
-- Name: fn_update_player_active_status(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_update_player_active_status() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- When a player has stats inserted, ensure they're marked as active
    UPDATE players
    SET is_active = TRUE
    WHERE id = NEW.player_id AND is_active = FALSE;

    RETURN NEW;
END;
$$;


ALTER FUNCTION public.fn_update_player_active_status() OWNER TO postgres;

--
-- Name: fn_update_season_counts(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_update_season_counts() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_season VARCHAR(10);
BEGIN
    -- Get the season from the affected row
    IF TG_OP = 'DELETE' THEN
        v_season := OLD.season;
    ELSE
        v_season := NEW.season;
    END IF;

    -- Update the season counts
    UPDATE seasons SET
        games_count = (SELECT COUNT(DISTINCT game_id) FROM player_game_stats WHERE season = v_season),
        players_count = (SELECT COUNT(DISTINCT player_id) FROM player_game_stats WHERE season = v_season),
        shots_count = (SELECT COUNT(*) FROM shots WHERE season = v_season)
    WHERE id = v_season;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    ELSE
        RETURN NEW;
    END IF;
END;
$$;


ALTER FUNCTION public.fn_update_season_counts() OWNER TO postgres;

--
-- Name: fn_validate_game_score(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_validate_game_score() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- NBA games typically have scores between 70-170
    -- Warn but allow unusual scores (just log them)
    IF NEW.home_score < 70 OR NEW.home_score > 200 OR
       NEW.away_score < 70 OR NEW.away_score > 200 THEN
        -- Log unusual score for review
        INSERT INTO audit_log (table_name, operation, record_id, new_values)
        VALUES ('games', 'UNUSUAL_SCORE', NEW.id,
                jsonb_build_object('home_score', NEW.home_score, 'away_score', NEW.away_score));
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.fn_validate_game_score() OWNER TO postgres;

--
-- Name: fn_validate_rebounds(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_validate_rebounds() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- Ensure total rebounds equals offensive + defensive
    IF NEW.rebounds != NEW.offensive_rebounds + NEW.defensive_rebounds THEN
        -- Auto-correct: set rebounds to sum of offensive and defensive
        NEW.rebounds := NEW.offensive_rebounds + NEW.defensive_rebounds;
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.fn_validate_rebounds() OWNER TO postgres;

--
-- Name: fn_validate_shot_result(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_validate_shot_result() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- Ensure shot_made boolean matches event_type string
    IF NEW.event_type = 'Made Shot' AND NEW.shot_made = FALSE THEN
        NEW.shot_made := TRUE;
    ELSIF NEW.event_type = 'Missed Shot' AND NEW.shot_made = TRUE THEN
        NEW.shot_made := FALSE;
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.fn_validate_shot_result() OWNER TO postgres;

--
-- Name: sp_delete_season(character varying, boolean); Type: PROCEDURE; Schema: public; Owner: postgres
--

CREATE PROCEDURE public.sp_delete_season(IN p_season character varying, IN p_confirm boolean DEFAULT false)
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_games_count INTEGER;
BEGIN
    IF NOT p_confirm THEN
        RAISE EXCEPTION 'Deletion not confirmed. Set p_confirm = TRUE to proceed.';
    END IF;

    -- Get count for logging
    SELECT COUNT(*) INTO v_games_count FROM games WHERE season = p_season;

    -- Delete in order (child tables first)
    DELETE FROM shots WHERE season = p_season;
    DELETE FROM player_game_stats WHERE season = p_season;
    DELETE FROM team_game_stats WHERE season = p_season;
    DELETE FROM games WHERE season = p_season;
    DELETE FROM seasons WHERE id = p_season;

    RAISE NOTICE 'Deleted season %: % games and all related data removed', p_season, v_games_count;
END;
$$;


ALTER PROCEDURE public.sp_delete_season(IN p_season character varying, IN p_confirm boolean) OWNER TO postgres;

--
-- Name: sp_update_season_metadata(character varying); Type: PROCEDURE; Schema: public; Owner: postgres
--

CREATE PROCEDURE public.sp_update_season_metadata(IN p_season character varying)
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_games_count INTEGER;
    v_players_count INTEGER;
    v_shots_count INTEGER;
BEGIN
    -- Calculate counts
    SELECT COUNT(DISTINCT game_id) INTO v_games_count
    FROM player_game_stats WHERE season = p_season;

    SELECT COUNT(DISTINCT player_id) INTO v_players_count
    FROM player_game_stats WHERE season = p_season;

    SELECT COUNT(*) INTO v_shots_count
    FROM shots WHERE season = p_season;

    -- Update or insert season record
    INSERT INTO seasons (id, start_year, end_year, games_count, players_count, shots_count)
    VALUES (
        p_season,
        SPLIT_PART(p_season, '-', 1)::INTEGER,
        2000 + SPLIT_PART(p_season, '-', 2)::INTEGER,
        v_games_count,
        v_players_count,
        v_shots_count
    )
    ON CONFLICT (id) DO UPDATE SET
        games_count = v_games_count,
        players_count = v_players_count,
        shots_count = v_shots_count,
        loaded_at = CURRENT_TIMESTAMP;

    RAISE NOTICE 'Season % updated: % games, % players, % shots',
        p_season, v_games_count, v_players_count, v_shots_count;
END;
$$;


ALTER PROCEDURE public.sp_update_season_metadata(IN p_season character varying) OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audit_log (
    id integer NOT NULL,
    table_name character varying(50) NOT NULL,
    operation character varying(10) NOT NULL,
    record_id character varying(50),
    old_values jsonb,
    new_values jsonb,
    changed_by character varying(100) DEFAULT CURRENT_USER,
    changed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.audit_log OWNER TO postgres;

--
-- Name: audit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.audit_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.audit_log_id_seq OWNER TO postgres;

--
-- Name: audit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.audit_log_id_seq OWNED BY public.audit_log.id;


--
-- Name: games; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.games (
    id character varying(20) NOT NULL,
    home_team_id bigint NOT NULL,
    away_team_id bigint NOT NULL,
    home_score integer NOT NULL,
    away_score integer NOT NULL,
    season character varying(10) NOT NULL,
    game_date date,
    CONSTRAINT chk_games_away_score_positive CHECK ((away_score >= 0)),
    CONSTRAINT chk_games_different_teams CHECK ((home_team_id <> away_team_id)),
    CONSTRAINT chk_games_home_score_positive CHECK ((home_score >= 0))
);


ALTER TABLE public.games OWNER TO postgres;

--
-- Name: player_game_stats; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.player_game_stats (
    id integer NOT NULL,
    game_id character varying(20) NOT NULL,
    player_id bigint NOT NULL,
    team_id bigint NOT NULL,
    "position" character varying(5),
    starter boolean,
    minutes interval,
    points integer DEFAULT 0 NOT NULL,
    rebounds integer DEFAULT 0 NOT NULL,
    offensive_rebounds integer DEFAULT 0 NOT NULL,
    defensive_rebounds integer DEFAULT 0 NOT NULL,
    assists integer DEFAULT 0 NOT NULL,
    steals integer DEFAULT 0 NOT NULL,
    blocks integer DEFAULT 0 NOT NULL,
    turnovers integer DEFAULT 0 NOT NULL,
    personal_fouls integer DEFAULT 0 NOT NULL,
    fgm integer DEFAULT 0 NOT NULL,
    fga integer DEFAULT 0 NOT NULL,
    fg_pct numeric(5,3),
    fg3m integer DEFAULT 0 NOT NULL,
    fg3a integer DEFAULT 0 NOT NULL,
    fg3_pct numeric(5,3),
    ftm integer DEFAULT 0 NOT NULL,
    fta integer DEFAULT 0 NOT NULL,
    ft_pct numeric(5,3),
    plus_minus numeric(6,1),
    offensive_rating numeric(6,2),
    defensive_rating numeric(6,2),
    net_rating numeric(6,2),
    ast_pct numeric(5,3),
    ast_ratio numeric(5,2),
    reb_pct numeric(5,3),
    ts_pct numeric(5,3),
    usg_pct numeric(5,3),
    pace numeric(7,2),
    pie numeric(5,3),
    season character varying(10) NOT NULL,
    CONSTRAINT chk_pgs_assists_positive CHECK ((assists >= 0)),
    CONSTRAINT chk_pgs_blocks_positive CHECK ((blocks >= 0)),
    CONSTRAINT chk_pgs_fg3_pct_range CHECK (((fg3_pct IS NULL) OR ((fg3_pct >= (0)::numeric) AND (fg3_pct <= (1)::numeric)))),
    CONSTRAINT chk_pgs_fg3_valid CHECK (((fg3m >= 0) AND (fg3a >= 0) AND (fg3m <= fg3a))),
    CONSTRAINT chk_pgs_fg_pct_range CHECK (((fg_pct IS NULL) OR ((fg_pct >= (0)::numeric) AND (fg_pct <= (1)::numeric)))),
    CONSTRAINT chk_pgs_fg_valid CHECK (((fgm >= 0) AND (fga >= 0) AND (fgm <= fga))),
    CONSTRAINT chk_pgs_fouls_valid CHECK (((personal_fouls >= 0) AND (personal_fouls <= 6))),
    CONSTRAINT chk_pgs_ft_pct_range CHECK (((ft_pct IS NULL) OR ((ft_pct >= (0)::numeric) AND (ft_pct <= (1)::numeric)))),
    CONSTRAINT chk_pgs_ft_valid CHECK (((ftm >= 0) AND (fta >= 0) AND (ftm <= fta))),
    CONSTRAINT chk_pgs_points_positive CHECK ((points >= 0)),
    CONSTRAINT chk_pgs_rebounds_positive CHECK (((rebounds >= 0) AND (offensive_rebounds >= 0) AND (defensive_rebounds >= 0))),
    CONSTRAINT chk_pgs_steals_positive CHECK ((steals >= 0)),
    CONSTRAINT chk_pgs_ts_pct_range CHECK (((ts_pct IS NULL) OR ((ts_pct >= (0)::numeric) AND (ts_pct <= (2)::numeric)))),
    CONSTRAINT chk_pgs_turnovers_positive CHECK ((turnovers >= 0))
);


ALTER TABLE public.player_game_stats OWNER TO postgres;

--
-- Name: player_game_stats_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.player_game_stats_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.player_game_stats_id_seq OWNER TO postgres;

--
-- Name: player_game_stats_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.player_game_stats_id_seq OWNED BY public.player_game_stats.id;


--
-- Name: players; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.players (
    id bigint NOT NULL,
    full_name character varying(100) NOT NULL,
    first_name character varying(50) NOT NULL,
    last_name character varying(50) NOT NULL,
    is_active boolean DEFAULT false NOT NULL
);


ALTER TABLE public.players OWNER TO postgres;

--
-- Name: seasons; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.seasons (
    id character varying(10) NOT NULL,
    start_year integer NOT NULL,
    end_year integer NOT NULL,
    loaded_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    games_count integer DEFAULT 0,
    players_count integer DEFAULT 0,
    shots_count integer DEFAULT 0,
    CONSTRAINT chk_seasons_counts_positive CHECK (((games_count >= 0) AND (players_count >= 0) AND (shots_count >= 0))),
    CONSTRAINT chk_seasons_years_valid CHECK (((start_year >= 1946) AND (end_year = (start_year + 1))))
);


ALTER TABLE public.seasons OWNER TO postgres;

--
-- Name: shots; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.shots (
    id integer NOT NULL,
    game_id character varying(20) NOT NULL,
    game_event_id integer NOT NULL,
    player_id bigint NOT NULL,
    team_id bigint NOT NULL,
    period integer NOT NULL,
    minutes_remaining integer NOT NULL,
    seconds_remaining integer NOT NULL,
    event_type character varying(20) NOT NULL,
    action_type character varying(50) NOT NULL,
    shot_type character varying(20) NOT NULL,
    shot_zone_basic character varying(30),
    shot_zone_area character varying(30),
    shot_zone_range character varying(20),
    shot_distance integer,
    loc_x integer NOT NULL,
    loc_y integer NOT NULL,
    shot_made boolean NOT NULL,
    game_date date,
    home_team character varying(3),
    away_team character varying(3),
    season character varying(10) NOT NULL,
    CONSTRAINT chk_shots_distance_valid CHECK (((shot_distance IS NULL) OR (shot_distance >= 0))),
    CONSTRAINT chk_shots_event_type_valid CHECK (((event_type)::text = ANY ((ARRAY['Made Shot'::character varying, 'Missed Shot'::character varying])::text[]))),
    CONSTRAINT chk_shots_loc_x_valid CHECK (((loc_x >= '-250'::integer) AND (loc_x <= 250))),
    CONSTRAINT chk_shots_loc_y_valid CHECK (((loc_y >= '-100'::integer) AND (loc_y <= 900))),
    CONSTRAINT chk_shots_minutes_valid CHECK (((minutes_remaining >= 0) AND (minutes_remaining <= 12))),
    CONSTRAINT chk_shots_period_valid CHECK (((period >= 1) AND (period <= 10))),
    CONSTRAINT chk_shots_seconds_valid CHECK (((seconds_remaining >= 0) AND (seconds_remaining <= 59))),
    CONSTRAINT chk_shots_shot_type_valid CHECK (((shot_type)::text = ANY ((ARRAY['2PT Field Goal'::character varying, '3PT Field Goal'::character varying])::text[])))
);


ALTER TABLE public.shots OWNER TO postgres;

--
-- Name: shots_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.shots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.shots_id_seq OWNER TO postgres;

--
-- Name: shots_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.shots_id_seq OWNED BY public.shots.id;


--
-- Name: team_game_stats; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.team_game_stats (
    id integer NOT NULL,
    game_id character varying(20) NOT NULL,
    team_id bigint NOT NULL,
    is_home boolean NOT NULL,
    points integer DEFAULT 0 NOT NULL,
    rebounds integer DEFAULT 0 NOT NULL,
    offensive_rebounds integer DEFAULT 0 NOT NULL,
    defensive_rebounds integer DEFAULT 0 NOT NULL,
    assists integer DEFAULT 0 NOT NULL,
    steals integer DEFAULT 0 NOT NULL,
    blocks integer DEFAULT 0 NOT NULL,
    turnovers integer DEFAULT 0 NOT NULL,
    personal_fouls integer DEFAULT 0 NOT NULL,
    fgm integer DEFAULT 0 NOT NULL,
    fga integer DEFAULT 0 NOT NULL,
    fg_pct numeric(5,3),
    fg3m integer DEFAULT 0 NOT NULL,
    fg3a integer DEFAULT 0 NOT NULL,
    fg3_pct numeric(5,3),
    ftm integer DEFAULT 0 NOT NULL,
    fta integer DEFAULT 0 NOT NULL,
    ft_pct numeric(5,3),
    offensive_rating numeric(6,2),
    defensive_rating numeric(6,2),
    net_rating numeric(6,2),
    pace numeric(7,2),
    pie numeric(5,3),
    season character varying(10) NOT NULL,
    CONSTRAINT chk_tgs_assists_positive CHECK ((assists >= 0)),
    CONSTRAINT chk_tgs_blocks_positive CHECK ((blocks >= 0)),
    CONSTRAINT chk_tgs_fg3_pct_range CHECK (((fg3_pct IS NULL) OR ((fg3_pct >= (0)::numeric) AND (fg3_pct <= (1)::numeric)))),
    CONSTRAINT chk_tgs_fg3_valid CHECK (((fg3m >= 0) AND (fg3a >= 0) AND (fg3m <= fg3a))),
    CONSTRAINT chk_tgs_fg_pct_range CHECK (((fg_pct IS NULL) OR ((fg_pct >= (0)::numeric) AND (fg_pct <= (1)::numeric)))),
    CONSTRAINT chk_tgs_fg_valid CHECK (((fgm >= 0) AND (fga >= 0) AND (fgm <= fga))),
    CONSTRAINT chk_tgs_ft_pct_range CHECK (((ft_pct IS NULL) OR ((ft_pct >= (0)::numeric) AND (ft_pct <= (1)::numeric)))),
    CONSTRAINT chk_tgs_ft_valid CHECK (((ftm >= 0) AND (fta >= 0) AND (ftm <= fta))),
    CONSTRAINT chk_tgs_points_positive CHECK ((points >= 0)),
    CONSTRAINT chk_tgs_rebounds_positive CHECK (((rebounds >= 0) AND (offensive_rebounds >= 0) AND (defensive_rebounds >= 0))),
    CONSTRAINT chk_tgs_steals_positive CHECK ((steals >= 0)),
    CONSTRAINT chk_tgs_turnovers_positive CHECK ((turnovers >= 0))
);


ALTER TABLE public.team_game_stats OWNER TO postgres;

--
-- Name: team_game_stats_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.team_game_stats_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.team_game_stats_id_seq OWNER TO postgres;

--
-- Name: team_game_stats_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.team_game_stats_id_seq OWNED BY public.team_game_stats.id;


--
-- Name: teams; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.teams (
    id bigint NOT NULL,
    full_name character varying(100) NOT NULL,
    abbreviation character varying(3) NOT NULL,
    nickname character varying(50) NOT NULL,
    city character varying(50) NOT NULL,
    state character varying(50) NOT NULL,
    year_founded integer NOT NULL,
    CONSTRAINT chk_teams_year_founded_valid CHECK (((year_founded >= 1946) AND (year_founded <= 2025)))
);


ALTER TABLE public.teams OWNER TO postgres;

--
-- Name: vw_double_doubles; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.vw_double_doubles AS
 SELECT p.id AS player_id,
    p.full_name AS player_name,
    pgs.season,
    count(*) AS double_doubles
   FROM (public.player_game_stats pgs
     JOIN public.players p ON ((pgs.player_id = p.id)))
  WHERE (((((
        CASE
            WHEN (pgs.points >= 10) THEN 1
            ELSE 0
        END +
        CASE
            WHEN (pgs.rebounds >= 10) THEN 1
            ELSE 0
        END) +
        CASE
            WHEN (pgs.assists >= 10) THEN 1
            ELSE 0
        END) +
        CASE
            WHEN (pgs.steals >= 10) THEN 1
            ELSE 0
        END) +
        CASE
            WHEN (pgs.blocks >= 10) THEN 1
            ELSE 0
        END) >= 2)
  GROUP BY p.id, p.full_name, pgs.season
  ORDER BY pgs.season DESC, (count(*)) DESC;


ALTER VIEW public.vw_double_doubles OWNER TO postgres;

--
-- Name: vw_game_summary; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.vw_game_summary AS
 SELECT g.id AS game_id,
    g.game_date,
    g.season,
    ht.full_name AS home_team,
    ht.abbreviation AS home_abbr,
    g.home_score,
    at.full_name AS away_team,
    at.abbreviation AS away_abbr,
    g.away_score,
        CASE
            WHEN (g.home_score > g.away_score) THEN ht.abbreviation
            ELSE at.abbreviation
        END AS winner,
    abs((g.home_score - g.away_score)) AS margin
   FROM ((public.games g
     JOIN public.teams ht ON ((g.home_team_id = ht.id)))
     JOIN public.teams at ON ((g.away_team_id = at.id)))
  ORDER BY g.game_date DESC, g.id DESC;


ALTER VIEW public.vw_game_summary OWNER TO postgres;

--
-- Name: vw_player_game_log; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.vw_player_game_log AS
 SELECT pgs.game_id,
    g.game_date,
    p.id AS player_id,
    p.full_name AS player_name,
    t.abbreviation AS team_abbr,
    pgs.season,
        CASE
            WHEN pgs.starter THEN 'Y'::text
            ELSE 'N'::text
        END AS started,
    ((EXTRACT(epoch FROM pgs.minutes))::integer / 60) AS minutes,
    pgs.points,
    pgs.rebounds,
    pgs.assists,
    pgs.steals,
    pgs.blocks,
    pgs.turnovers,
    ((pgs.fgm || '-'::text) || pgs.fga) AS fg,
    ((pgs.fg3m || '-'::text) || pgs.fg3a) AS fg3,
    ((pgs.ftm || '-'::text) || pgs.fta) AS ft,
    pgs.plus_minus,
        CASE
            WHEN (g.home_team_id = pgs.team_id) THEN ('vs '::text || (at.abbreviation)::text)
            ELSE ('@ '::text || (ht.abbreviation)::text)
        END AS matchup,
        CASE
            WHEN (g.home_team_id = pgs.team_id) THEN (g.home_score > g.away_score)
            ELSE (g.away_score > g.home_score)
        END AS team_won
   FROM (((((public.player_game_stats pgs
     JOIN public.players p ON ((pgs.player_id = p.id)))
     JOIN public.teams t ON ((pgs.team_id = t.id)))
     JOIN public.games g ON (((pgs.game_id)::text = (g.id)::text)))
     JOIN public.teams ht ON ((g.home_team_id = ht.id)))
     JOIN public.teams at ON ((g.away_team_id = at.id)))
  ORDER BY g.game_date DESC, p.full_name;


ALTER VIEW public.vw_player_game_log OWNER TO postgres;

--
-- Name: vw_player_season_averages; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.vw_player_season_averages AS
 SELECT p.id AS player_id,
    p.full_name AS player_name,
    pgs.season,
    t.abbreviation AS team_abbr,
    count(*) AS games_played,
    round(avg(pgs.points), 1) AS ppg,
    round(avg(pgs.rebounds), 1) AS rpg,
    round(avg(pgs.assists), 1) AS apg,
    round(avg(pgs.steals), 1) AS spg,
    round(avg(pgs.blocks), 1) AS bpg,
    round(avg(pgs.turnovers), 1) AS topg,
    round(avg(pgs.fgm), 1) AS fgm,
    round(avg(pgs.fga), 1) AS fga,
    round(((sum(pgs.fgm))::numeric / (NULLIF(sum(pgs.fga), 0))::numeric), 3) AS fg_pct,
    round(avg(pgs.fg3m), 1) AS fg3m,
    round(avg(pgs.fg3a), 1) AS fg3a,
    round(((sum(pgs.fg3m))::numeric / (NULLIF(sum(pgs.fg3a), 0))::numeric), 3) AS fg3_pct,
    round(avg(pgs.ftm), 1) AS ftm,
    round(avg(pgs.fta), 1) AS fta,
    round(((sum(pgs.ftm))::numeric / (NULLIF(sum(pgs.fta), 0))::numeric), 3) AS ft_pct,
    round(avg((EXTRACT(epoch FROM pgs.minutes) / (60)::numeric)), 1) AS mpg,
    round(avg(pgs.plus_minus), 1) AS plus_minus
   FROM ((public.player_game_stats pgs
     JOIN public.players p ON ((pgs.player_id = p.id)))
     JOIN public.teams t ON ((pgs.team_id = t.id)))
  GROUP BY p.id, p.full_name, pgs.season, t.abbreviation
  ORDER BY pgs.season DESC, (round(avg(pgs.points), 1)) DESC;


ALTER VIEW public.vw_player_season_averages OWNER TO postgres;

--
-- Name: vw_player_shooting; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.vw_player_shooting AS
 SELECT p.id AS player_id,
    p.full_name AS player_name,
    pgs.season,
    count(*) AS games,
    sum(pgs.fgm) AS total_fgm,
    sum(pgs.fga) AS total_fga,
    round((((sum(pgs.fgm))::numeric / (NULLIF(sum(pgs.fga), 0))::numeric) * (100)::numeric), 1) AS fg_pct,
    sum(pgs.fg3m) AS total_fg3m,
    sum(pgs.fg3a) AS total_fg3a,
    round((((sum(pgs.fg3m))::numeric / (NULLIF(sum(pgs.fg3a), 0))::numeric) * (100)::numeric), 1) AS fg3_pct,
    sum(pgs.ftm) AS total_ftm,
    sum(pgs.fta) AS total_fta,
    round((((sum(pgs.ftm))::numeric / (NULLIF(sum(pgs.fta), 0))::numeric) * (100)::numeric), 1) AS ft_pct,
    round((((sum(pgs.points))::numeric / NULLIF(((2)::numeric * ((sum(pgs.fga))::numeric + (0.44 * (sum(pgs.fta))::numeric))), (0)::numeric)) * (100)::numeric), 1) AS ts_pct,
    round(((((sum(pgs.fgm))::numeric + (0.5 * (sum(pgs.fg3m))::numeric)) / (NULLIF(sum(pgs.fga), 0))::numeric) * (100)::numeric), 1) AS efg_pct
   FROM (public.player_game_stats pgs
     JOIN public.players p ON ((pgs.player_id = p.id)))
  GROUP BY p.id, p.full_name, pgs.season
 HAVING (sum(pgs.fga) >= 50)
  ORDER BY pgs.season DESC, (round((((sum(pgs.points))::numeric / NULLIF(((2)::numeric * ((sum(pgs.fga))::numeric + (0.44 * (sum(pgs.fta))::numeric))), (0)::numeric)) * (100)::numeric), 1)) DESC;


ALTER VIEW public.vw_player_shooting OWNER TO postgres;

--
-- Name: vw_recent_games; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.vw_recent_games AS
 SELECT game_id,
    game_date,
    season,
    home_team,
    home_abbr,
    home_score,
    away_team,
    away_abbr,
    away_score,
    winner,
    margin
   FROM public.vw_game_summary
  ORDER BY game_date DESC, game_id DESC
 LIMIT 50;


ALTER VIEW public.vw_recent_games OWNER TO postgres;

--
-- Name: vw_scoring_leaders; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.vw_scoring_leaders AS
 SELECT p.id AS player_id,
    p.full_name AS player_name,
    t.abbreviation AS team_abbr,
    pgs.season,
    count(*) AS games_played,
    round(avg(pgs.points), 1) AS ppg,
    sum(pgs.points) AS total_points,
    rank() OVER (PARTITION BY pgs.season ORDER BY (avg(pgs.points)) DESC) AS rank
   FROM ((public.player_game_stats pgs
     JOIN public.players p ON ((pgs.player_id = p.id)))
     JOIN public.teams t ON ((pgs.team_id = t.id)))
  GROUP BY p.id, p.full_name, t.abbreviation, pgs.season
 HAVING (count(*) >= 10)
  ORDER BY pgs.season DESC, (round(avg(pgs.points), 1)) DESC;


ALTER VIEW public.vw_scoring_leaders OWNER TO postgres;

--
-- Name: vw_shot_zones; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.vw_shot_zones AS
 SELECT p.id AS player_id,
    p.full_name AS player_name,
    s.season,
    s.shot_zone_basic AS zone,
    count(*) AS attempts,
    sum(
        CASE
            WHEN s.shot_made THEN 1
            ELSE 0
        END) AS makes,
    round((((sum(
        CASE
            WHEN s.shot_made THEN 1
            ELSE 0
        END))::numeric / (count(*))::numeric) * (100)::numeric), 1) AS fg_pct
   FROM (public.shots s
     JOIN public.players p ON ((s.player_id = p.id)))
  GROUP BY p.id, p.full_name, s.season, s.shot_zone_basic
  ORDER BY p.full_name, (count(*)) DESC;


ALTER VIEW public.vw_shot_zones OWNER TO postgres;

--
-- Name: vw_team_season_stats; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.vw_team_season_stats AS
 SELECT t.id AS team_id,
    t.full_name AS team_name,
    t.abbreviation,
    tgs.season,
    count(*) AS games_played,
    round(avg(tgs.points), 1) AS ppg,
    round(avg(tgs.rebounds), 1) AS rpg,
    round(avg(tgs.assists), 1) AS apg,
    round(avg(tgs.steals), 1) AS spg,
    round(avg(tgs.blocks), 1) AS bpg,
    round(avg(tgs.turnovers), 1) AS topg,
    round((((sum(tgs.fgm))::numeric / (NULLIF(sum(tgs.fga), 0))::numeric) * (100)::numeric), 1) AS fg_pct,
    round((((sum(tgs.fg3m))::numeric / (NULLIF(sum(tgs.fg3a), 0))::numeric) * (100)::numeric), 1) AS fg3_pct,
    round((((sum(tgs.ftm))::numeric / (NULLIF(sum(tgs.fta), 0))::numeric) * (100)::numeric), 1) AS ft_pct,
    round(avg(tgs.offensive_rating), 1) AS avg_off_rating,
    round(avg(tgs.defensive_rating), 1) AS avg_def_rating,
    round(avg(tgs.pace), 1) AS avg_pace
   FROM (public.team_game_stats tgs
     JOIN public.teams t ON ((tgs.team_id = t.id)))
  GROUP BY t.id, t.full_name, t.abbreviation, tgs.season
  ORDER BY tgs.season DESC, (round(avg(tgs.points), 1)) DESC;


ALTER VIEW public.vw_team_season_stats OWNER TO postgres;

--
-- Name: vw_team_standings; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.vw_team_standings AS
 SELECT t.id AS team_id,
    t.full_name AS team_name,
    t.abbreviation,
    g.season,
    sum(
        CASE
            WHEN (((g.home_team_id = t.id) AND (g.home_score > g.away_score)) OR ((g.away_team_id = t.id) AND (g.away_score > g.home_score))) THEN 1
            ELSE 0
        END) AS wins,
    sum(
        CASE
            WHEN (((g.home_team_id = t.id) AND (g.home_score < g.away_score)) OR ((g.away_team_id = t.id) AND (g.away_score < g.home_score))) THEN 1
            ELSE 0
        END) AS losses,
    round(((sum(
        CASE
            WHEN (((g.home_team_id = t.id) AND (g.home_score > g.away_score)) OR ((g.away_team_id = t.id) AND (g.away_score > g.home_score))) THEN 1
            ELSE 0
        END))::numeric / (NULLIF(count(*), 0))::numeric), 3) AS win_pct,
    sum(
        CASE
            WHEN ((g.home_team_id = t.id) AND (g.home_score > g.away_score)) THEN 1
            ELSE 0
        END) AS home_wins,
    sum(
        CASE
            WHEN ((g.home_team_id = t.id) AND (g.home_score < g.away_score)) THEN 1
            ELSE 0
        END) AS home_losses,
    sum(
        CASE
            WHEN ((g.away_team_id = t.id) AND (g.away_score > g.home_score)) THEN 1
            ELSE 0
        END) AS away_wins,
    sum(
        CASE
            WHEN ((g.away_team_id = t.id) AND (g.away_score < g.home_score)) THEN 1
            ELSE 0
        END) AS away_losses,
    round(avg(
        CASE
            WHEN (g.home_team_id = t.id) THEN g.home_score
            ELSE g.away_score
        END), 1) AS ppg,
    round(avg(
        CASE
            WHEN (g.home_team_id = t.id) THEN g.away_score
            ELSE g.home_score
        END), 1) AS opp_ppg
   FROM (public.teams t
     JOIN public.games g ON (((t.id = g.home_team_id) OR (t.id = g.away_team_id))))
  GROUP BY t.id, t.full_name, t.abbreviation, g.season
  ORDER BY g.season DESC, (sum(
        CASE
            WHEN (((g.home_team_id = t.id) AND (g.home_score > g.away_score)) OR ((g.away_team_id = t.id) AND (g.away_score > g.home_score))) THEN 1
            ELSE 0
        END)) DESC, (round(((sum(
        CASE
            WHEN (((g.home_team_id = t.id) AND (g.home_score > g.away_score)) OR ((g.away_team_id = t.id) AND (g.away_score > g.home_score))) THEN 1
            ELSE 0
        END))::numeric / (NULLIF(count(*), 0))::numeric), 3)) DESC;


ALTER VIEW public.vw_team_standings OWNER TO postgres;

--
-- Name: audit_log id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_log ALTER COLUMN id SET DEFAULT nextval('public.audit_log_id_seq'::regclass);


--
-- Name: player_game_stats id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.player_game_stats ALTER COLUMN id SET DEFAULT nextval('public.player_game_stats_id_seq'::regclass);


--
-- Name: shots id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.shots ALTER COLUMN id SET DEFAULT nextval('public.shots_id_seq'::regclass);


--
-- Name: team_game_stats id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.team_game_stats ALTER COLUMN id SET DEFAULT nextval('public.team_game_stats_id_seq'::regclass);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);


--
-- Name: games games_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.games
    ADD CONSTRAINT games_pkey PRIMARY KEY (id);


--
-- Name: player_game_stats player_game_stats_game_id_player_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.player_game_stats
    ADD CONSTRAINT player_game_stats_game_id_player_id_key UNIQUE (game_id, player_id);


--
-- Name: player_game_stats player_game_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.player_game_stats
    ADD CONSTRAINT player_game_stats_pkey PRIMARY KEY (id);


--
-- Name: players players_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.players
    ADD CONSTRAINT players_pkey PRIMARY KEY (id);


--
-- Name: seasons seasons_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.seasons
    ADD CONSTRAINT seasons_pkey PRIMARY KEY (id);


--
-- Name: shots shots_game_id_game_event_id_player_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.shots
    ADD CONSTRAINT shots_game_id_game_event_id_player_id_key UNIQUE (game_id, game_event_id, player_id);


--
-- Name: shots shots_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.shots
    ADD CONSTRAINT shots_pkey PRIMARY KEY (id);


--
-- Name: team_game_stats team_game_stats_game_id_team_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.team_game_stats
    ADD CONSTRAINT team_game_stats_game_id_team_id_key UNIQUE (game_id, team_id);


--
-- Name: team_game_stats team_game_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.team_game_stats
    ADD CONSTRAINT team_game_stats_pkey PRIMARY KEY (id);


--
-- Name: teams teams_abbreviation_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.teams
    ADD CONSTRAINT teams_abbreviation_key UNIQUE (abbreviation);


--
-- Name: teams teams_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.teams
    ADD CONSTRAINT teams_pkey PRIMARY KEY (id);


--
-- Name: idx_audit_log_table; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_audit_log_table ON public.audit_log USING btree (table_name);


--
-- Name: idx_audit_log_timestamp; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_audit_log_timestamp ON public.audit_log USING btree (changed_at);


--
-- Name: idx_games_away_team; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_games_away_team ON public.games USING btree (away_team_id);


--
-- Name: idx_games_date; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_games_date ON public.games USING btree (game_date);


--
-- Name: idx_games_home_team; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_games_home_team ON public.games USING btree (home_team_id);


--
-- Name: idx_games_season; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_games_season ON public.games USING btree (season);


--
-- Name: idx_player_game_stats_game; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_player_game_stats_game ON public.player_game_stats USING btree (game_id);


--
-- Name: idx_player_game_stats_player; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_player_game_stats_player ON public.player_game_stats USING btree (player_id);


--
-- Name: idx_player_game_stats_player_season; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_player_game_stats_player_season ON public.player_game_stats USING btree (player_id, season);


--
-- Name: idx_player_game_stats_season; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_player_game_stats_season ON public.player_game_stats USING btree (season);


--
-- Name: idx_player_game_stats_team; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_player_game_stats_team ON public.player_game_stats USING btree (team_id);


--
-- Name: idx_players_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_players_active ON public.players USING btree (is_active);


--
-- Name: idx_players_name; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_players_name ON public.players USING btree (last_name, first_name);


--
-- Name: idx_shots_game; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_shots_game ON public.shots USING btree (game_id);


--
-- Name: idx_shots_made; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_shots_made ON public.shots USING btree (shot_made);


--
-- Name: idx_shots_player; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_shots_player ON public.shots USING btree (player_id);


--
-- Name: idx_shots_season; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_shots_season ON public.shots USING btree (season);


--
-- Name: idx_shots_team; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_shots_team ON public.shots USING btree (team_id);


--
-- Name: idx_shots_zone; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_shots_zone ON public.shots USING btree (shot_zone_basic, shot_zone_area);


--
-- Name: idx_team_game_stats_game; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_team_game_stats_game ON public.team_game_stats USING btree (game_id);


--
-- Name: idx_team_game_stats_season; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_team_game_stats_season ON public.team_game_stats USING btree (season);


--
-- Name: idx_team_game_stats_team; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_team_game_stats_team ON public.team_game_stats USING btree (team_id);


--
-- Name: idx_teams_abbreviation; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_teams_abbreviation ON public.teams USING btree (abbreviation);


--
-- Name: games trg_audit_games; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_audit_games AFTER INSERT OR DELETE OR UPDATE ON public.games FOR EACH ROW EXECUTE FUNCTION public.fn_audit_trigger();


--
-- Name: player_game_stats trg_audit_player_game_stats; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_audit_player_game_stats AFTER INSERT OR DELETE OR UPDATE ON public.player_game_stats FOR EACH ROW EXECUTE FUNCTION public.fn_audit_trigger();


--
-- Name: team_game_stats trg_audit_team_game_stats; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_audit_team_game_stats AFTER INSERT OR DELETE OR UPDATE ON public.team_game_stats FOR EACH ROW EXECUTE FUNCTION public.fn_audit_trigger();


--
-- Name: player_game_stats trg_update_player_active; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_update_player_active AFTER INSERT ON public.player_game_stats FOR EACH ROW EXECUTE FUNCTION public.fn_update_player_active_status();


--
-- Name: player_game_stats trg_update_season_counts_on_player_stats; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_update_season_counts_on_player_stats AFTER INSERT OR DELETE ON public.player_game_stats FOR EACH ROW EXECUTE FUNCTION public.fn_update_season_counts();


--
-- Name: games trg_validate_game_score; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_validate_game_score BEFORE INSERT OR UPDATE ON public.games FOR EACH ROW EXECUTE FUNCTION public.fn_validate_game_score();


--
-- Name: player_game_stats trg_validate_player_rebounds; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_validate_player_rebounds BEFORE INSERT OR UPDATE ON public.player_game_stats FOR EACH ROW EXECUTE FUNCTION public.fn_validate_rebounds();


--
-- Name: shots trg_validate_shot_result; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_validate_shot_result BEFORE INSERT OR UPDATE ON public.shots FOR EACH ROW EXECUTE FUNCTION public.fn_validate_shot_result();


--
-- Name: team_game_stats trg_validate_team_rebounds; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_validate_team_rebounds BEFORE INSERT OR UPDATE ON public.team_game_stats FOR EACH ROW EXECUTE FUNCTION public.fn_validate_rebounds();


--
-- Name: games games_away_team_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.games
    ADD CONSTRAINT games_away_team_id_fkey FOREIGN KEY (away_team_id) REFERENCES public.teams(id);


--
-- Name: games games_home_team_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.games
    ADD CONSTRAINT games_home_team_id_fkey FOREIGN KEY (home_team_id) REFERENCES public.teams(id);


--
-- Name: player_game_stats player_game_stats_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.player_game_stats
    ADD CONSTRAINT player_game_stats_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id);


--
-- Name: player_game_stats player_game_stats_player_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.player_game_stats
    ADD CONSTRAINT player_game_stats_player_id_fkey FOREIGN KEY (player_id) REFERENCES public.players(id);


--
-- Name: player_game_stats player_game_stats_team_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.player_game_stats
    ADD CONSTRAINT player_game_stats_team_id_fkey FOREIGN KEY (team_id) REFERENCES public.teams(id);


--
-- Name: shots shots_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.shots
    ADD CONSTRAINT shots_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id);


--
-- Name: shots shots_player_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.shots
    ADD CONSTRAINT shots_player_id_fkey FOREIGN KEY (player_id) REFERENCES public.players(id);


--
-- Name: shots shots_team_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.shots
    ADD CONSTRAINT shots_team_id_fkey FOREIGN KEY (team_id) REFERENCES public.teams(id);


--
-- Name: team_game_stats team_game_stats_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.team_game_stats
    ADD CONSTRAINT team_game_stats_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id);


--
-- Name: team_game_stats team_game_stats_team_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.team_game_stats
    ADD CONSTRAINT team_game_stats_team_id_fkey FOREIGN KEY (team_id) REFERENCES public.teams(id);


--
-- PostgreSQL database dump complete
--

\unrestrict utgDPlcfBsoGl2GYLojXQ2cz9vN6BDjHg26V26kFAXlMCGIWEahOC3zrl61dSa7

