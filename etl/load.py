#!/usr/bin/env python3
"""Legacy loading helpers retained for migration tests.

The executable loader was retired because it bypassed manifested-dataset
verification and did not load the complete shot-attempt dataset. Supported
loads go through ``python -m etl.season_lifecycle``.
"""

import os
import sys

import pandas as pd
import psycopg
from dotenv import load_dotenv

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from db.config import get_db_config

BASE_CLEAN_DIR = os.path.join(PROJECT_ROOT, "data", "clean")
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


def get_season_clean_dir(season):
    return os.path.join(BASE_CLEAN_DIR, season)


def get_shared_clean_dir():
    return os.path.join(BASE_CLEAN_DIR, "shared")


def get_connection():
    return psycopg.connect(**get_db_config())


def read_clean_csv(filepath, game_id_column=None):
    """Read a clean CSV without allowing pandas to coerce NBA game IDs to integers."""
    dtype = {game_id_column: "string"} if game_id_column else None
    return pd.read_csv(filepath, dtype=dtype)


def migrate_legacy_game_ids(conn, official_game_ids):
    """Replace pandas-truncated game IDs while preserving already-migrated data."""
    mappings = sorted(
        {
            (game_id.lstrip("0") or "0", game_id)
            for value in official_game_ids
            if (game_id := str(value)) and game_id.lstrip("0") != game_id
        }
    )
    if not mappings:
        return

    # Create canonical parent rows first so child foreign keys can be migrated.
    # In a partially migrated database the canonical row wins conflicts; any
    # child row that exists only under the legacy ID is copied across.
    official_legacy = [(official, legacy) for legacy, official in mappings]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO games (
                id, game_date, season, home_team_id, away_team_id, home_score, away_score
            )
            SELECT %s, game_date, season, home_team_id, away_team_id, home_score, away_score
            FROM games
            WHERE id = %s
            ON CONFLICT (id) DO NOTHING
            """,
            official_legacy,
        )
        cur.executemany(
            """
            INSERT INTO team_game_stats (
                game_id, team_id, season, is_home,
                minutes, points, rebounds, offensive_rebounds, defensive_rebounds,
                assists, steals, blocks, turnovers, personal_fouls,
                fgm, fga, fg_pct, fg3m, fg3a, fg3_pct,
                ftm, fta, ft_pct, plus_minus
            )
            SELECT
                %s, team_id, season, is_home,
                minutes, points, rebounds, offensive_rebounds, defensive_rebounds,
                assists, steals, blocks, turnovers, personal_fouls,
                fgm, fga, fg_pct, fg3m, fg3a, fg3_pct,
                ftm, fta, ft_pct, plus_minus
            FROM team_game_stats
            WHERE game_id = %s
            ON CONFLICT (game_id, team_id) DO NOTHING
            """,
            official_legacy,
        )
        cur.executemany(
            """
            INSERT INTO player_game_stats (
                game_id, player_id, team_id, season,
                minutes, points, rebounds, offensive_rebounds, defensive_rebounds,
                assists, steals, blocks, turnovers, personal_fouls,
                fgm, fga, fg_pct, fg3m, fg3a, fg3_pct,
                ftm, fta, ft_pct, plus_minus
            )
            SELECT
                %s, player_id, team_id, season,
                minutes, points, rebounds, offensive_rebounds, defensive_rebounds,
                assists, steals, blocks, turnovers, personal_fouls,
                fgm, fga, fg_pct, fg3m, fg3a, fg3_pct,
                ftm, fta, ft_pct, plus_minus
            FROM player_game_stats
            WHERE game_id = %s
            ON CONFLICT (game_id, player_id) DO NOTHING
            """,
            official_legacy,
        )
        cur.executemany(
            """
            INSERT INTO shot_attempts (
                game_id, event_id, player_id, team_id, season, period,
                minutes_remaining, seconds_remaining, action_type, shot_type,
                zone_basic, zone_area, zone_range, shot_distance, loc_x, loc_y,
                shot_made
            )
            SELECT
                %s, event_id, player_id, team_id, season, period,
                minutes_remaining, seconds_remaining, action_type, shot_type,
                zone_basic, zone_area, zone_range, shot_distance, loc_x, loc_y,
                shot_made
            FROM shot_attempts
            WHERE game_id = %s
            ON CONFLICT (game_id, event_id) DO NOTHING
            """,
            official_legacy,
        )
        legacy_only = [(legacy,) for legacy, _official in mappings]
        cur.executemany("DELETE FROM shot_attempts WHERE game_id = %s", legacy_only)
        cur.executemany("DELETE FROM player_game_stats WHERE game_id = %s", legacy_only)
        cur.executemany("DELETE FROM team_game_stats WHERE game_id = %s", legacy_only)
        cur.executemany("DELETE FROM games WHERE id = %s", legacy_only)


def load_teams(conn):
    """Load teams from shared CSV."""
    print("\n=== Teams ===")
    filepath = os.path.join(get_shared_clean_dir(), "teams.csv")
    if not os.path.exists(filepath):
        print("  Skipping: teams.csv not found")
        return

    df = read_clean_csv(filepath)
    with conn.cursor() as cur:
        values = [
            tuple(None if pd.isna(v) else v for v in row)
            for row in df.itertuples(index=False, name=None)
        ]
        cur.executemany(
            """
            INSERT INTO teams (id, full_name, abbreviation, nickname, city, state, year_founded)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                full_name = EXCLUDED.full_name,
                abbreviation = EXCLUDED.abbreviation,
                nickname = EXCLUDED.nickname,
                city = EXCLUDED.city,
                state = EXCLUDED.state,
                year_founded = EXCLUDED.year_founded
            """,
            values,
        )
    print(f"    Upserted {len(df)} teams")


def load_players(conn):
    """Load players from shared CSV."""
    print("\n=== Players ===")
    filepath = os.path.join(get_shared_clean_dir(), "players.csv")
    if not os.path.exists(filepath):
        print("  Skipping: players.csv not found")
        return

    df = read_clean_csv(filepath)
    with conn.cursor() as cur:
        values = [
            tuple(None if pd.isna(v) else v for v in row)
            for row in df.itertuples(index=False, name=None)
        ]
        cur.executemany(
            """
            INSERT INTO players (id, full_name, first_name, last_name, is_active)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                full_name = EXCLUDED.full_name,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                is_active = EXCLUDED.is_active
            """,
            values,
        )
    print(f"    Upserted {len(df)} players")


def load_games(conn, season):
    """Load games for a season."""
    print("\n=== Games ===")
    filepath = os.path.join(get_season_clean_dir(season), "games.csv")
    if not os.path.exists(filepath):
        print("  Skipping: games.csv not found")
        return

    df = read_clean_csv(filepath, "id")
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.date
    migrate_legacy_game_ids(conn, df["id"].dropna())

    with conn.cursor() as cur:
        values = [
            tuple(None if pd.isna(v) else v for v in row)
            for row in df.itertuples(index=False, name=None)
        ]
        cur.executemany(
            """
            INSERT INTO games (id, game_date, season, home_team_id, away_team_id, home_score, away_score)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                game_date = EXCLUDED.game_date,
                season = EXCLUDED.season,
                home_team_id = EXCLUDED.home_team_id,
                away_team_id = EXCLUDED.away_team_id,
                home_score = EXCLUDED.home_score,
                away_score = EXCLUDED.away_score
            """,
            values,
        )
    print(f"    Upserted {len(df)} games")


def load_team_game_stats(conn, season):
    """Load team game stats for a season."""
    print("\n=== Team Game Stats ===")
    filepath = os.path.join(get_season_clean_dir(season), "team_game_stats.csv")
    if not os.path.exists(filepath):
        print("  Skipping: team_game_stats.csv not found")
        return

    df = read_clean_csv(filepath, "game_id")
    columns = [
        "game_id",
        "team_id",
        "season",
        "is_home",
        "minutes",
        "points",
        "rebounds",
        "offensive_rebounds",
        "defensive_rebounds",
        "assists",
        "steals",
        "blocks",
        "turnovers",
        "personal_fouls",
        "fgm",
        "fga",
        "fg_pct",
        "fg3m",
        "fg3a",
        "fg3_pct",
        "ftm",
        "fta",
        "ft_pct",
        "plus_minus",
    ]
    df = df[columns]

    with conn.cursor() as cur:
        values = [
            tuple(None if pd.isna(v) else v for v in row)
            for row in df.itertuples(index=False, name=None)
        ]
        cur.executemany(
            """
            INSERT INTO team_game_stats (
                game_id, team_id, season, is_home,
                minutes, points, rebounds, offensive_rebounds, defensive_rebounds,
                assists, steals, blocks, turnovers, personal_fouls,
                fgm, fga, fg_pct, fg3m, fg3a, fg3_pct,
                ftm, fta, ft_pct, plus_minus
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (game_id, team_id) DO UPDATE SET
                season = EXCLUDED.season,
                is_home = EXCLUDED.is_home,
                minutes = EXCLUDED.minutes,
                points = EXCLUDED.points,
                rebounds = EXCLUDED.rebounds,
                offensive_rebounds = EXCLUDED.offensive_rebounds,
                defensive_rebounds = EXCLUDED.defensive_rebounds,
                assists = EXCLUDED.assists,
                steals = EXCLUDED.steals,
                blocks = EXCLUDED.blocks,
                turnovers = EXCLUDED.turnovers,
                personal_fouls = EXCLUDED.personal_fouls,
                fgm = EXCLUDED.fgm,
                fga = EXCLUDED.fga,
                fg_pct = EXCLUDED.fg_pct,
                fg3m = EXCLUDED.fg3m,
                fg3a = EXCLUDED.fg3a,
                fg3_pct = EXCLUDED.fg3_pct,
                ftm = EXCLUDED.ftm,
                fta = EXCLUDED.fta,
                ft_pct = EXCLUDED.ft_pct,
                plus_minus = EXCLUDED.plus_minus
            """,
            values,
        )
    print(f"    Upserted {len(df)} team game stats")


def load_player_game_stats(conn, season):
    """Load player game stats for a season."""
    print("\n=== Player Game Stats ===")
    filepath = os.path.join(get_season_clean_dir(season), "player_game_stats.csv")
    if not os.path.exists(filepath):
        print("  Skipping: player_game_stats.csv not found")
        return

    df = read_clean_csv(filepath, "game_id")
    columns = [
        "game_id",
        "player_id",
        "team_id",
        "season",
        "minutes",
        "points",
        "rebounds",
        "offensive_rebounds",
        "defensive_rebounds",
        "assists",
        "steals",
        "blocks",
        "turnovers",
        "personal_fouls",
        "fgm",
        "fga",
        "fg_pct",
        "fg3m",
        "fg3a",
        "fg3_pct",
        "ftm",
        "fta",
        "ft_pct",
        "plus_minus",
    ]
    df = df[columns]

    with conn.cursor() as cur:
        values = [
            tuple(None if pd.isna(v) else v for v in row)
            for row in df.itertuples(index=False, name=None)
        ]
        cur.executemany(
            """
            INSERT INTO player_game_stats (
                game_id, player_id, team_id, season,
                minutes, points, rebounds, offensive_rebounds, defensive_rebounds,
                assists, steals, blocks, turnovers, personal_fouls,
                fgm, fga, fg_pct, fg3m, fg3a, fg3_pct,
                ftm, fta, ft_pct, plus_minus
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (game_id, player_id) DO UPDATE SET
                team_id = EXCLUDED.team_id,
                season = EXCLUDED.season,
                minutes = EXCLUDED.minutes,
                points = EXCLUDED.points,
                rebounds = EXCLUDED.rebounds,
                offensive_rebounds = EXCLUDED.offensive_rebounds,
                defensive_rebounds = EXCLUDED.defensive_rebounds,
                assists = EXCLUDED.assists,
                steals = EXCLUDED.steals,
                blocks = EXCLUDED.blocks,
                turnovers = EXCLUDED.turnovers,
                personal_fouls = EXCLUDED.personal_fouls,
                fgm = EXCLUDED.fgm,
                fga = EXCLUDED.fga,
                fg_pct = EXCLUDED.fg_pct,
                fg3m = EXCLUDED.fg3m,
                fg3a = EXCLUDED.fg3a,
                fg3_pct = EXCLUDED.fg3_pct,
                ftm = EXCLUDED.ftm,
                fta = EXCLUDED.fta,
                ft_pct = EXCLUDED.ft_pct,
                plus_minus = EXCLUDED.plus_minus
            """,
            values,
        )
    print(f"    Upserted {len(df)} player game stats")


def update_season_metadata(conn, season):
    """Update season metadata."""
    print("\n=== Season Metadata ===")
    with conn.cursor() as cur:
        cur.execute("CALL sp_update_season_metadata(%s)", (season,))
    print(f"    Updated metadata for {season}")


def ensure_season_row(conn, season):
    """Create the parent season row required by current relational constraints."""
    start_year = int(season[:4])
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO seasons (id, start_year, end_year)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (season, start_year, start_year + 1),
        )


def load_season(conn, season):
    """Load shared and season data atomically."""
    with conn.transaction():
        load_teams(conn)
        load_players(conn)
        ensure_season_row(conn, season)
        load_games(conn, season)
        load_team_game_stats(conn, season)
        load_player_game_stats(conn, season)
        update_season_metadata(conn, season)


if __name__ == "__main__":
    raise SystemExit(
        "Direct loading is disabled. Use `make season-load-local SEASON=2025-26` "
        "or the guarded season promotion workflow."
    )
