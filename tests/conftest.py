"""Shared fixtures: dedicated test database (nba_db_test) with seed data."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Point the app at the test database BEFORE any app/db imports.
# DATABASE_URL is set to "" (not popped): load_dotenv() only fills in MISSING
# keys, so an empty value blocks a .env-supplied DATABASE_URL from being
# loaded, and get_db_config() treats "" as unset.
os.environ["DATABASE_URL"] = ""
os.environ["DB_NAME"] = "nba_db_test"

import init_db  # scripts/init_db.py (via sys.path above)
import psycopg
import pytest
from fastapi.testclient import TestClient

from db.config import get_db_config

SEED_SEASON = "2024-25"
LAKERS = 1610612747
CELTICS = 1610612738
LEBRON = 2544
TATUM = 1628369
JORDAN = 893


def _connect_admin() -> psycopg.Connection:
    """Connect to the maintenance database to create/drop the test DB."""
    config = get_db_config() | {"dbname": "postgres"}
    return psycopg.connect(**config, autocommit=True)


def _seed(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO teams (id, full_name, abbreviation, nickname, city, state, year_founded)"
            " VALUES (%s, 'Los Angeles Lakers', 'LAL', 'Lakers', 'Los Angeles', 'California', 1948),"
            " (%s, 'Boston Celtics', 'BOS', 'Celtics', 'Boston', 'Massachusetts', 1946)",
            (LAKERS, CELTICS),
        )
        cur.execute(
            "INSERT INTO players (id, full_name, first_name, last_name, is_active)"
            " VALUES (%s, 'LeBron James', 'LeBron', 'James', TRUE),"
            " (%s, 'Jayson Tatum', 'Jayson', 'Tatum', TRUE),"
            " (%s, 'Michael Jordan', 'Michael', 'Jordan', FALSE)",
            (LEBRON, TATUM, JORDAN),
        )
        cur.execute(
            "INSERT INTO seasons (id, start_year, end_year, games_count, players_count)"
            " VALUES (%s, 2024, 2025, 10, 3)",
            (SEED_SEASON,),
        )
        for i in range(1, 11):
            game_id = f"00224000{i:02d}"
            cur.execute(
                "INSERT INTO games (id, game_date, season, home_team_id, away_team_id,"
                " home_score, away_score) VALUES (%s, %s, %s, %s, %s, 110, 100)",
                (game_id, f"2024-11-{i:02d}", SEED_SEASON, LAKERS, CELTICS),
            )
            for team_id, is_home, points in ((LAKERS, True, 110), (CELTICS, False, 100)):
                cur.execute(
                    "INSERT INTO team_game_stats (game_id, team_id, season, is_home, points,"
                    " rebounds, assists, fgm, fga, fg3m, fg3a, ftm, fta)"
                    " VALUES (%s, %s, %s, %s, %s, 45, 25, 40, 90, 12, 35, 18, 22)",
                    (game_id, team_id, SEED_SEASON, is_home, points),
                )
            # LeBron plays all 10 games and qualifies for the 70% leader threshold.
            cur.execute(
                "INSERT INTO player_game_stats (game_id, player_id, team_id, season, minutes,"
                " points, rebounds, assists, fgm, fga, fg3m, fg3a, ftm, fta)"
                " VALUES (%s, %s, %s, %s, 36.5, 30, 8, 9, 12, 20, 2, 6, 4, 5)",
                (game_id, LEBRON, LAKERS, SEED_SEASON),
            )
            lebron_shots = []
            for shot in range(1, 21):
                is_three = shot <= 6
                made = shot <= 2 or 7 <= shot <= 16
                lebron_shots.append(
                    (
                        game_id,
                        shot,
                        LEBRON,
                        LAKERS,
                        SEED_SEASON,
                        1 + (shot - 1) // 5,
                        11 - ((shot - 1) % 5),
                        (shot * 7) % 60,
                        "Jump Shot" if is_three else "Driving Layup Shot",
                        "3PT Field Goal" if is_three else "2PT Field Goal",
                        "Above the Break 3" if is_three else "Restricted Area",
                        "Center(C)",
                        "24+ ft." if is_three else "Less Than 8 ft.",
                        25 if is_three else 2,
                        (shot - 10) * 12,
                        230 if is_three else 15 + shot,
                        made,
                    )
                )
            cur.executemany(
                """
                INSERT INTO shot_attempts (
                    game_id, event_id, player_id, team_id, season, period,
                    minutes_remaining, seconds_remaining, action_type, shot_type,
                    zone_basic, zone_area, zone_range, shot_distance, loc_x, loc_y,
                    shot_made
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                lebron_shots,
            )
            # Tatum plays only games 1-5: below the leaders threshold.
            if i <= 5:
                cur.execute(
                    "INSERT INTO player_game_stats (game_id, player_id, team_id, season, minutes,"
                    " points, rebounds, assists, fgm, fga, fg3m, fg3a, ftm, fta)"
                    " VALUES (%s, %s, %s, %s, 34.0, 25, 7, 4, 9, 19, 3, 8, 4, 4)",
                    (game_id, TATUM, CELTICS, SEED_SEASON),
                )
                tatum_shots = []
                for shot in range(1, 20):
                    is_three = shot <= 8
                    made = shot <= 3 or 9 <= shot <= 14
                    tatum_shots.append(
                        (
                            game_id,
                            100 + shot,
                            TATUM,
                            CELTICS,
                            SEED_SEASON,
                            1 + (shot - 1) // 5,
                            11 - ((shot - 1) % 5),
                            (shot * 9) % 60,
                            "Pullup Jump Shot",
                            "3PT Field Goal" if is_three else "2PT Field Goal",
                            "Above the Break 3" if is_three else "Mid-Range",
                            "Right Side(R)" if is_three else "Center(C)",
                            "24+ ft." if is_three else "8-16 ft.",
                            26 if is_three else 14,
                            100 - shot * 6,
                            245 if is_three else 120 + shot,
                            made,
                        )
                    )
                cur.executemany(
                    """
                    INSERT INTO shot_attempts (
                        game_id, event_id, player_id, team_id, season, period,
                        minutes_remaining, seconds_remaining, action_type, shot_type,
                        zone_basic, zone_area, zone_range, shot_distance, loc_x, loc_y,
                        shot_made
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    tatum_shots,
                )
            # A DNP row must not count as an appearance or affect averages/leaders.
            if i == 10:
                cur.execute(
                    "INSERT INTO player_game_stats (game_id, player_id, team_id, season, minutes)"
                    " VALUES (%s, %s, %s, %s, NULL)",
                    (game_id, JORDAN, LAKERS, SEED_SEASON),
                )
    conn.commit()


@pytest.fixture(scope="session")
def client():
    with _connect_admin() as admin:
        admin.execute("DROP DATABASE IF EXISTS nba_db_test")
        admin.execute("CREATE DATABASE nba_db_test")

    init_db.main()  # applies db/schema/*.sql to nba_db_test

    with psycopg.connect(**get_db_config()) as conn:
        _seed(conn)

    from app.db import close_pool
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client

    close_pool()
