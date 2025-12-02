#!/usr/bin/env python3
"""
NBA Data Load Script
Loads clean CSVs into MySQL database.

Usage:
    python load.py                    # Default season (2024-25)
    python load.py --season 2023-24   # Specific season
"""

import argparse
import os

import pandas as pd
import mysql.connector
from dotenv import load_dotenv

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BASE_CLEAN_DIR = os.path.join(PROJECT_ROOT, "data", "clean")
DEFAULT_SEASON = "2024-25"

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

DB_CONFIG = {
    "database": os.getenv("DB_NAME", "nba_db"),
    "user": os.getenv("DB_USER", "nba_user"),
    "password": os.getenv("DB_PASSWORD", "nba_password"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
}


def get_season_clean_dir(season):
    return os.path.join(BASE_CLEAN_DIR, season)


def get_shared_clean_dir():
    return os.path.join(BASE_CLEAN_DIR, "shared")


def get_connection():
    return mysql.connector.connect(**DB_CONFIG)


def load_teams(conn):
    """Load teams from shared CSV."""
    print("\n=== Teams ===")
    filepath = os.path.join(get_shared_clean_dir(), "teams.csv")
    if not os.path.exists(filepath):
        print("  Skipping: teams.csv not found")
        return

    df = pd.read_csv(filepath)
    with conn.cursor() as cur:
        values = [tuple(None if pd.isna(v) else v for v in row) for row in df.itertuples(index=False, name=None)]
        cur.executemany(
            """
            INSERT IGNORE INTO teams (id, full_name, abbreviation, nickname, city, state, year_founded)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            values,
        )
    conn.commit()
    print(f"    Loaded {len(df)} teams")


def load_players(conn):
    """Load players from shared CSV."""
    print("\n=== Players ===")
    filepath = os.path.join(get_shared_clean_dir(), "players.csv")
    if not os.path.exists(filepath):
        print("  Skipping: players.csv not found")
        return

    df = pd.read_csv(filepath)
    with conn.cursor() as cur:
        values = [tuple(None if pd.isna(v) else v for v in row) for row in df.itertuples(index=False, name=None)]
        cur.executemany(
            """
            INSERT IGNORE INTO players (id, full_name, first_name, last_name, is_active)
            VALUES (%s, %s, %s, %s, %s)
            """,
            values,
        )
    conn.commit()
    print(f"    Loaded {len(df)} players")


def load_games(conn, season):
    """Load games for a season."""
    print("\n=== Games ===")
    filepath = os.path.join(get_season_clean_dir(season), "games.csv")
    if not os.path.exists(filepath):
        print("  Skipping: games.csv not found")
        return

    df = pd.read_csv(filepath)
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.date

    with conn.cursor() as cur:
        values = [tuple(None if pd.isna(v) else v for v in row) for row in df.itertuples(index=False, name=None)]
        cur.executemany(
            """
            INSERT IGNORE INTO games (id, game_date, season, home_team_id, away_team_id, home_score, away_score)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            values,
        )
    conn.commit()
    print(f"    Loaded {len(df)} games")


def load_team_game_stats(conn, season):
    """Load team game stats for a season."""
    print("\n=== Team Game Stats ===")
    filepath = os.path.join(get_season_clean_dir(season), "team_game_stats.csv")
    if not os.path.exists(filepath):
        print("  Skipping: team_game_stats.csv not found")
        return

    df = pd.read_csv(filepath)
    columns = [
        "game_id", "team_id", "season", "is_home",
        "minutes", "points", "rebounds", "offensive_rebounds", "defensive_rebounds",
        "assists", "steals", "blocks", "turnovers", "personal_fouls",
        "fgm", "fga", "fg_pct", "fg3m", "fg3a", "fg3_pct",
        "ftm", "fta", "ft_pct", "plus_minus",
    ]
    df = df[columns]

    with conn.cursor() as cur:
        values = [tuple(None if pd.isna(v) else v for v in row) for row in df.itertuples(index=False, name=None)]
        cur.executemany(
            """
            INSERT IGNORE INTO team_game_stats (
                game_id, team_id, season, is_home,
                minutes, points, rebounds, offensive_rebounds, defensive_rebounds,
                assists, steals, blocks, turnovers, personal_fouls,
                fgm, fga, fg_pct, fg3m, fg3a, fg3_pct,
                ftm, fta, ft_pct, plus_minus
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            values,
        )
    conn.commit()
    print(f"    Loaded {len(df)} team game stats")


def load_player_game_stats(conn, season):
    """Load player game stats for a season."""
    print("\n=== Player Game Stats ===")
    filepath = os.path.join(get_season_clean_dir(season), "player_game_stats.csv")
    if not os.path.exists(filepath):
        print("  Skipping: player_game_stats.csv not found")
        return

    df = pd.read_csv(filepath)
    columns = [
        "game_id", "player_id", "team_id", "season",
        "minutes", "points", "rebounds", "offensive_rebounds", "defensive_rebounds",
        "assists", "steals", "blocks", "turnovers", "personal_fouls",
        "fgm", "fga", "fg_pct", "fg3m", "fg3a", "fg3_pct",
        "ftm", "fta", "ft_pct", "plus_minus",
    ]
    df = df[columns]

    with conn.cursor() as cur:
        values = [tuple(None if pd.isna(v) else v for v in row) for row in df.itertuples(index=False, name=None)]
        cur.executemany(
            """
            INSERT IGNORE INTO player_game_stats (
                game_id, player_id, team_id, season,
                minutes, points, rebounds, offensive_rebounds, defensive_rebounds,
                assists, steals, blocks, turnovers, personal_fouls,
                fgm, fga, fg_pct, fg3m, fg3a, fg3_pct,
                ftm, fta, ft_pct, plus_minus
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            values,
        )
    conn.commit()
    print(f"    Loaded {len(df)} player game stats")


def update_season_metadata(conn, season):
    """Update season metadata."""
    print("\n=== Season Metadata ===")
    with conn.cursor() as cur:
        cur.callproc("sp_update_season_metadata", (season,))
    conn.commit()
    print(f"    Updated metadata for {season}")


def main():
    parser = argparse.ArgumentParser(description="Load NBA data into database")
    parser.add_argument("--season", default=DEFAULT_SEASON, help=f"Season (default: {DEFAULT_SEASON})")
    args = parser.parse_args()

    season = args.season
    print("=" * 50)
    print(f"NBA Data Load - Season {season}")
    print("=" * 50)

    conn = get_connection()
    try:
        load_teams(conn)
        load_players(conn)
        load_games(conn, season)
        load_team_game_stats(conn, season)
        load_player_game_stats(conn, season)
        update_season_metadata(conn, season)
    finally:
        conn.close()

    print("\n" + "=" * 50)
    print("Load complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
