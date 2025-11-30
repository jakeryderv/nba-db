#!/usr/bin/env python3
"""
NBA Data Load Script
Loads cleaned CSV data into PostgreSQL database.
"""

import os
import sys
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CLEAN_DIR = os.path.join(PROJECT_ROOT, "data", "clean")

# Load environment variables
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "nba_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
}


def get_connection():
    """Create database connection."""
    return psycopg2.connect(**DB_CONFIG)


def load_csv(filename):
    """Load CSV file from clean directory."""
    filepath = os.path.join(CLEAN_DIR, filename)
    if not os.path.exists(filepath):
        print(f"  Skipping: {filename} not found")
        return None
    return pd.read_csv(filepath)


def truncate_tables(conn):
    """Truncate all tables in reverse dependency order."""
    print("\n=== Truncating Tables ===")
    tables = [
        "shots",
        "player_game_stats",
        "team_game_stats",
        "games",
        "players",
        "teams",
    ]
    with conn.cursor() as cur:
        for table in tables:
            cur.execute(f"TRUNCATE TABLE {table} CASCADE")
            print(f"  Truncated: {table}")
    conn.commit()


def load_teams(conn):
    """Load teams data."""
    print("\n=== Loading Teams ===")
    df = load_csv("teams.csv")
    if df is None:
        return 0

    columns = ["id", "full_name", "abbreviation", "nickname", "city", "state", "year_founded"]
    df = df[columns]

    with conn.cursor() as cur:
        values = [tuple(row) for row in df.itertuples(index=False, name=None)]
        execute_values(
            cur,
            """
            INSERT INTO teams (id, full_name, abbreviation, nickname, city, state, year_founded)
            VALUES %s
            ON CONFLICT (id) DO NOTHING
            """,
            values,
        )
    conn.commit()
    print(f"  Loaded: {len(df)} teams")
    return len(df)


def load_players(conn):
    """Load players data."""
    print("\n=== Loading Players ===")
    df = load_csv("players.csv")
    if df is None:
        return 0

    columns = ["id", "full_name", "first_name", "last_name", "is_active"]
    df = df[columns]

    # Convert is_active to boolean
    df["is_active"] = df["is_active"].apply(lambda x: str(x).lower() == "true")

    with conn.cursor() as cur:
        values = [tuple(row) for row in df.itertuples(index=False, name=None)]
        execute_values(
            cur,
            """
            INSERT INTO players (id, full_name, first_name, last_name, is_active)
            VALUES %s
            ON CONFLICT (id) DO NOTHING
            """,
            values,
        )
    conn.commit()
    print(f"  Loaded: {len(df)} players")
    return len(df)


def backfill_missing_players(conn):
    """Insert placeholder records for players in box scores but not in players table."""
    print("\n=== Backfilling Missing Players ===")

    players_df = load_csv("players.csv")
    box_scores_df = load_csv("player_box_scores.csv")

    if players_df is None or box_scores_df is None:
        return 0

    existing_ids = set(players_df["id"])
    box_score_ids = set(box_scores_df["player_id"])
    missing_ids = box_score_ids - existing_ids

    if not missing_ids:
        print("  No missing players")
        return 0

    # Get names from box scores where available
    missing_players = []
    for player_id in missing_ids:
        rows = box_scores_df[box_scores_df["player_id"] == player_id]
        name = rows["name"].dropna().iloc[0] if not rows["name"].dropna().empty else f"Unknown Player {player_id}"
        parts = name.split(" ", 1) if isinstance(name, str) else ["Unknown", str(player_id)]
        first_name = parts[0] if parts else "Unknown"
        last_name = parts[1] if len(parts) > 1 else ""
        missing_players.append((player_id, name, first_name, last_name, True))

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO players (id, full_name, first_name, last_name, is_active)
            VALUES %s
            ON CONFLICT (id) DO NOTHING
            """,
            missing_players,
        )
    conn.commit()
    print(f"  Backfilled: {len(missing_players)} missing players")
    return len(missing_players)


def load_games(conn):
    """Load games data."""
    print("\n=== Loading Games ===")
    df = load_csv("games.csv")
    if df is None:
        return 0

    # Rename columns to match schema
    df = df.rename(columns={"game_id": "id"})
    columns = ["id", "home_team_id", "away_team_id", "home_score", "away_score", "season"]

    # Select only needed columns
    df = df[columns]

    with conn.cursor() as cur:
        values = [tuple(row) for row in df.itertuples(index=False, name=None)]
        execute_values(
            cur,
            """
            INSERT INTO games (id, home_team_id, away_team_id, home_score, away_score, season)
            VALUES %s
            ON CONFLICT (id) DO NOTHING
            """,
            values,
        )
    conn.commit()
    print(f"  Loaded: {len(df)} games")
    return len(df)


def parse_minutes(minutes_str):
    """Convert 'MM:SS' string to PostgreSQL interval string."""
    if pd.isna(minutes_str) or minutes_str == "" or minutes_str is None:
        return None
    try:
        parts = str(minutes_str).split(":")
        if len(parts) == 2:
            mins, secs = parts
            return f"{mins} minutes {secs} seconds"
        return None
    except Exception:
        return None


def load_player_game_stats(conn):
    """Load player game statistics."""
    print("\n=== Loading Player Game Stats ===")
    df = load_csv("player_box_scores.csv")
    if df is None:
        return 0

    # Convert minutes to interval format
    df["minutes"] = df["minutes"].apply(parse_minutes)

    # Convert starter to boolean
    df["starter"] = df["starter"].apply(lambda x: str(x).lower() == "true" if pd.notna(x) else None)

    # Replace NaN with None for database
    df = df.where(pd.notna(df), None)

    columns = [
        "game_id", "player_id", "team_id", "position", "starter", "minutes",
        "points", "rebounds", "offensive_rebounds", "defensive_rebounds",
        "assists", "steals", "blocks", "turnovers", "personal_fouls",
        "fgm", "fga", "fg_pct", "fg3m", "fg3a", "fg3_pct",
        "ftm", "fta", "ft_pct", "plus_minus",
        "offensive_rating", "defensive_rating", "net_rating",
        "ast_pct", "ast_ratio", "reb_pct", "ts_pct", "usg_pct", "pace", "pie",
        "season"
    ]

    # Ensure all columns exist
    for col in columns:
        if col not in df.columns:
            df[col] = None

    df = df[columns]

    with conn.cursor() as cur:
        values = [tuple(row) for row in df.itertuples(index=False, name=None)]
        execute_values(
            cur,
            """
            INSERT INTO player_game_stats (
                game_id, player_id, team_id, position, starter, minutes,
                points, rebounds, offensive_rebounds, defensive_rebounds,
                assists, steals, blocks, turnovers, personal_fouls,
                fgm, fga, fg_pct, fg3m, fg3a, fg3_pct,
                ftm, fta, ft_pct, plus_minus,
                offensive_rating, defensive_rating, net_rating,
                ast_pct, ast_ratio, reb_pct, ts_pct, usg_pct, pace, pie,
                season
            )
            VALUES %s
            ON CONFLICT (game_id, player_id) DO NOTHING
            """,
            values,
            page_size=1000,
        )
    conn.commit()
    print(f"  Loaded: {len(df)} player game stats")
    return len(df)


def load_team_game_stats(conn):
    """Load team game statistics."""
    print("\n=== Loading Team Game Stats ===")
    df = load_csv("team_box_scores.csv")
    if df is None:
        return 0

    # Convert is_home to boolean
    df["is_home"] = df["is_home"].apply(lambda x: str(x).lower() == "true")

    # Replace NaN with None for database
    df = df.where(pd.notna(df), None)

    columns = [
        "game_id", "team_id", "is_home",
        "points", "rebounds", "offensive_rebounds", "defensive_rebounds",
        "assists", "steals", "blocks", "turnovers", "personal_fouls",
        "fgm", "fga", "fg_pct", "fg3m", "fg3a", "fg3_pct",
        "ftm", "fta", "ft_pct",
        "offensive_rating", "defensive_rating", "net_rating", "pace", "pie",
        "season"
    ]

    # Ensure all columns exist
    for col in columns:
        if col not in df.columns:
            df[col] = None

    df = df[columns]

    with conn.cursor() as cur:
        values = [tuple(row) for row in df.itertuples(index=False, name=None)]
        execute_values(
            cur,
            """
            INSERT INTO team_game_stats (
                game_id, team_id, is_home,
                points, rebounds, offensive_rebounds, defensive_rebounds,
                assists, steals, blocks, turnovers, personal_fouls,
                fgm, fga, fg_pct, fg3m, fg3a, fg3_pct,
                ftm, fta, ft_pct,
                offensive_rating, defensive_rating, net_rating, pace, pie,
                season
            )
            VALUES %s
            ON CONFLICT (game_id, team_id) DO NOTHING
            """,
            values,
        )
    conn.commit()
    print(f"  Loaded: {len(df)} team game stats")
    return len(df)


def load_shots(conn):
    """Load shot chart data."""
    print("\n=== Loading Shots ===")
    df = load_csv("shots.csv")
    if df is None:
        return 0

    # Replace NaN with None for database
    df = df.where(pd.notna(df), None)

    # Map column names from CSV to database
    df = df.rename(columns={
        "game_id": "game_id",
        "game_event_id": "game_event_id",
        "player_id": "player_id",
        "team_id": "team_id",
        "period": "period",
        "minutes_remaining": "minutes_remaining",
        "seconds_remaining": "seconds_remaining",
        "event_type": "event_type",
        "action_type": "action_type",
        "shot_type": "shot_type",
        "shot_zone_basic": "shot_zone_basic",
        "shot_zone_area": "shot_zone_area",
        "shot_zone_range": "shot_zone_range",
        "shot_distance": "shot_distance",
        "loc_x": "loc_x",
        "loc_y": "loc_y",
        "shot_made_flag": "shot_made",
        "game_date": "game_date",
        "htm": "home_team",
        "vtm": "away_team",
    })

    # Convert shot_made to boolean
    df["shot_made"] = df["shot_made"].apply(lambda x: x == 1 if pd.notna(x) else None)

    # Parse game_date
    df["game_date"] = pd.to_datetime(df["game_date"], format="%Y%m%d", errors="coerce").dt.date

    columns = [
        "game_id", "game_event_id", "player_id", "team_id",
        "period", "minutes_remaining", "seconds_remaining",
        "event_type", "action_type", "shot_type",
        "shot_zone_basic", "shot_zone_area", "shot_zone_range", "shot_distance",
        "loc_x", "loc_y", "shot_made",
        "game_date", "home_team", "away_team", "season"
    ]

    # Ensure all columns exist
    for col in columns:
        if col not in df.columns:
            df[col] = None

    df = df[columns]

    with conn.cursor() as cur:
        values = [tuple(row) for row in df.itertuples(index=False, name=None)]
        execute_values(
            cur,
            """
            INSERT INTO shots (
                game_id, game_event_id, player_id, team_id,
                period, minutes_remaining, seconds_remaining,
                event_type, action_type, shot_type,
                shot_zone_basic, shot_zone_area, shot_zone_range, shot_distance,
                loc_x, loc_y, shot_made,
                game_date, home_team, away_team, season
            )
            VALUES %s
            ON CONFLICT (game_id, game_event_id, player_id) DO NOTHING
            """,
            values,
            page_size=1000,
        )
    conn.commit()
    print(f"  Loaded: {len(df)} shots")
    return len(df)


def main():
    print("=" * 50)
    print("NBA Data Load Script")
    print(f"Clean Directory: {CLEAN_DIR}")
    print(f"Database: {DB_CONFIG['dbname']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print("=" * 50)

    # Test connection
    try:
        conn = get_connection()
        print("\n  Connected to database successfully")
    except Exception as e:
        print(f"\n  Error connecting to database: {e}")
        print("  Make sure PostgreSQL is running and credentials are correct")
        sys.exit(1)

    try:
        # Truncate existing data
        truncate_tables(conn)

        # Load dimension tables first (no foreign key dependencies)
        load_teams(conn)
        load_players(conn)
        backfill_missing_players(conn)

        # Load games (depends on teams)
        load_games(conn)

        # Load fact tables (depend on dimension tables and games)
        load_player_game_stats(conn)
        load_team_game_stats(conn)
        load_shots(conn)

        print("\n" + "=" * 50)
        print("Load complete!")
        print("=" * 50)

    except Exception as e:
        print(f"\n  Error during load: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
