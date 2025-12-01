#!/usr/bin/env python3
"""
NBA Data Load Script
Loads cleaned CSV data into PostgreSQL database.

Usage:
    python load.py                    # Default season (2024-25)
    python load.py --season 2023-24   # Specific season
"""

import argparse
import os
import sys

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BASE_CLEAN_DIR = os.path.join(PROJECT_ROOT, "data", "clean")
DEFAULT_SEASON = "2024-25"

# Load environment variables
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "nba_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
}


def get_season_clean_dir(season):
    """Get the clean data directory for a specific season."""
    return os.path.join(BASE_CLEAN_DIR, season)


def get_shared_clean_dir():
    """Get the shared clean data directory."""
    return os.path.join(BASE_CLEAN_DIR, "shared")


def get_connection():
    """Create database connection."""
    return psycopg2.connect(**DB_CONFIG)


def load_csv(filepath):
    """Load CSV file."""
    if not os.path.exists(filepath):
        print(f"  Skipping: {filepath} not found")
        return None
    return pd.read_csv(filepath)


def delete_season_data(conn, season):
    """Delete all data for a specific season (reverse dependency order)."""
    print(f"\n=== Deleting Existing Data for Season {season} ===")

    # Tables with season column (fact tables)
    season_tables = [
        "shots",
        "player_game_stats",
        "team_game_stats",
        "games",
    ]

    with conn.cursor() as cur:
        for table in season_tables:
            cur.execute(f"DELETE FROM {table} WHERE season = %s", (season,))
            print(f"  Deleted from {table}: {cur.rowcount} rows")


def load_teams(conn):
    """Load teams data (shared across seasons)."""
    print("\n=== Loading Teams ===")
    filepath = os.path.join(get_shared_clean_dir(), "teams.csv")
    df = load_csv(filepath)
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
    print(f"  Loaded: {len(df)} teams")
    return len(df)


def load_players(conn):
    """Load players data (shared across seasons)."""
    print("\n=== Loading Players ===")
    filepath = os.path.join(get_shared_clean_dir(), "players.csv")
    df = load_csv(filepath)
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
    print(f"  Loaded: {len(df)} players")
    return len(df)


def backfill_missing_players(conn, season):
    """Insert placeholder records for players in box scores but not in players table."""
    print("\n=== Backfilling Missing Players ===")

    season_dir = get_season_clean_dir(season)
    shared_dir = get_shared_clean_dir()

    players_df = load_csv(os.path.join(shared_dir, "players.csv"))
    box_scores_df = load_csv(os.path.join(season_dir, "player_box_scores.csv"))

    if players_df is None or box_scores_df is None:
        return 0

    # Also check existing players in database
    with get_connection() as check_conn:
        with check_conn.cursor() as cur:
            cur.execute("SELECT id FROM players")
            db_player_ids = {row[0] for row in cur.fetchall()}

    existing_ids = set(players_df["id"]) | db_player_ids
    box_score_ids = set(box_scores_df["player_id"])
    missing_ids = box_score_ids - existing_ids

    if not missing_ids:
        print("  No missing players")
        return 0

    # Get names from box scores where available
    missing_players = []
    for player_id in missing_ids:
        rows = box_scores_df[box_scores_df["player_id"] == player_id]
        name = (
            rows["name"].dropna().iloc[0]
            if not rows["name"].dropna().empty
            else f"Unknown Player {player_id}"
        )
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
    print(f"  Backfilled: {len(missing_players)} missing players")
    return len(missing_players)


def load_games(conn, season):
    """Load games data for a specific season."""
    print("\n=== Loading Games ===")
    filepath = os.path.join(get_season_clean_dir(season), "games.csv")
    df = load_csv(filepath)
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


def load_player_game_stats(conn, season):
    """Load player game statistics for a specific season."""
    print("\n=== Loading Player Game Stats ===")
    filepath = os.path.join(get_season_clean_dir(season), "player_box_scores.csv")
    df = load_csv(filepath)
    if df is None:
        return 0

    # Convert minutes to interval format
    df["minutes"] = df["minutes"].apply(parse_minutes)

    # Convert starter to boolean
    df["starter"] = df["starter"].apply(lambda x: str(x).lower() == "true" if pd.notna(x) else None)

    # Replace NaN with None for database
    df = df.where(pd.notna(df), None)

    columns = [
        "game_id",
        "player_id",
        "team_id",
        "position",
        "starter",
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
        "offensive_rating",
        "defensive_rating",
        "net_rating",
        "ast_pct",
        "ast_ratio",
        "reb_pct",
        "ts_pct",
        "usg_pct",
        "pace",
        "pie",
        "season",
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
    print(f"  Loaded: {len(df)} player game stats")
    return len(df)


def load_team_game_stats(conn, season):
    """Load team game statistics for a specific season."""
    print("\n=== Loading Team Game Stats ===")
    filepath = os.path.join(get_season_clean_dir(season), "team_box_scores.csv")
    df = load_csv(filepath)
    if df is None:
        return 0

    # Convert is_home to boolean
    df["is_home"] = df["is_home"].apply(lambda x: str(x).lower() == "true")

    # Replace NaN with None for database
    df = df.where(pd.notna(df), None)

    columns = [
        "game_id",
        "team_id",
        "is_home",
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
        "offensive_rating",
        "defensive_rating",
        "net_rating",
        "pace",
        "pie",
        "season",
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
    print(f"  Loaded: {len(df)} team game stats")
    return len(df)


def load_shots(conn, season):
    """Load shot chart data for a specific season."""
    print("\n=== Loading Shots ===")
    filepath = os.path.join(get_season_clean_dir(season), "shots.csv")
    df = load_csv(filepath)
    if df is None:
        return 0

    # Replace NaN with None for database
    df = df.where(pd.notna(df), None)

    # Map column names from CSV to database
    df = df.rename(
        columns={
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
        }
    )

    # Convert shot_made to boolean
    df["shot_made"] = df["shot_made"].apply(lambda x: x == 1 if pd.notna(x) else None)

    # Parse game_date
    df["game_date"] = pd.to_datetime(df["game_date"], format="%Y%m%d", errors="coerce").dt.date

    columns = [
        "game_id",
        "game_event_id",
        "player_id",
        "team_id",
        "period",
        "minutes_remaining",
        "seconds_remaining",
        "event_type",
        "action_type",
        "shot_type",
        "shot_zone_basic",
        "shot_zone_area",
        "shot_zone_range",
        "shot_distance",
        "loc_x",
        "loc_y",
        "shot_made",
        "game_date",
        "home_team",
        "away_team",
        "season",
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
    print(f"  Loaded: {len(df)} shots")
    return len(df)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Load NBA data into PostgreSQL database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python load.py                    # Load current season (2024-25)
    python load.py --season 2023-24   # Load 2023-24 season
        """,
    )
    parser.add_argument(
        "--season",
        default=DEFAULT_SEASON,
        help=f"Season to load (default: {DEFAULT_SEASON})",
    )
    return parser.parse_args()


def update_season_record(conn, season):
    """Update or insert season record with counts."""
    print("\n=== Updating Season Record ===")

    # Parse season years
    parts = season.split("-")
    start_year = int(parts[0])
    end_year = int(f"20{parts[1]}") if len(parts[1]) == 2 else int(parts[1])

    with conn.cursor() as cur:
        # Get counts for this season
        cur.execute("SELECT COUNT(*) FROM games WHERE season = %s", (season,))
        games_count = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(DISTINCT player_id) FROM player_game_stats WHERE season = %s", (season,)
        )
        players_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM shots WHERE season = %s", (season,))
        shots_count = cur.fetchone()[0]

        # Upsert season record
        cur.execute(
            """
            INSERT INTO seasons (id, start_year, end_year, games_count, players_count, shots_count, loaded_at)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET
                games_count = EXCLUDED.games_count,
                players_count = EXCLUDED.players_count,
                shots_count = EXCLUDED.shots_count,
                loaded_at = CURRENT_TIMESTAMP
        """,
            (season, start_year, end_year, games_count, players_count, shots_count),
        )

    print(f"  Season {season}: {games_count} games, {players_count} players, {shots_count} shots")


def main():
    args = parse_args()
    season = args.season
    season_dir = get_season_clean_dir(season)

    print("=" * 50)
    print("NBA Data Load Script")
    print(f"Season: {season}")
    print(f"Clean Directory: {season_dir}")
    print(f"Database: {DB_CONFIG['dbname']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print("=" * 50)

    # Test connection
    try:
        conn = get_connection()
        conn.autocommit = False  # Ensure we're in transaction mode
        print("\n  Connected to database successfully")
    except Exception as e:
        print(f"\n  Error connecting to database: {e}")
        print("  Make sure PostgreSQL is running and credentials are correct")
        sys.exit(1)

    try:
        # All operations run in a single transaction for atomicity
        # If interrupted, everything rolls back to previous state

        # Delete existing data for this season only
        delete_season_data(conn, season)

        # Load dimension tables (shared across seasons, use ON CONFLICT)
        load_teams(conn)
        load_players(conn)
        backfill_missing_players(conn, season)

        # Load season-specific fact tables
        load_games(conn, season)
        load_player_game_stats(conn, season)
        load_team_game_stats(conn, season)
        load_shots(conn, season)

        # Update season tracking record
        update_season_record(conn, season)

        # Commit entire transaction
        conn.commit()

        print("\n" + "=" * 50)
        print(f"Load complete for season {season}!")
        print("=" * 50)

    except Exception as e:
        print(f"\n  Error during load: {e}")
        print("  Rolling back all changes...")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
