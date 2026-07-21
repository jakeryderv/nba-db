"""Regression tests for refresh-safe, atomic ETL loading."""

from pathlib import Path

import pandas as pd
import psycopg
import pytest

from db.config import get_db_config
from etl import load
from tests.conftest import CELTICS, LAKERS, LEBRON

GAME_ID = "0022400001"
SEASON = "2024-25"


def _write_csv(root: Path, relative_path: str, row: dict) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([row]).to_csv(path, index=False)


def _game_row(**overrides) -> dict:
    row = {
        "id": GAME_ID,
        "game_date": "2024-11-01",
        "season": SEASON,
        "home_team_id": LAKERS,
        "away_team_id": CELTICS,
        "home_score": 121,
        "away_score": 119,
    }
    row.update(overrides)
    return row


def _stats_row(**overrides) -> dict:
    row = {
        "game_id": GAME_ID,
        "team_id": LAKERS,
        "season": SEASON,
        "minutes": 240,
        "points": 121,
        "rebounds": 50,
        "offensive_rebounds": 10,
        "defensive_rebounds": 40,
        "assists": 30,
        "steals": 8,
        "blocks": 6,
        "turnovers": 12,
        "personal_fouls": 18,
        "fgm": 45,
        "fga": 90,
        "fg_pct": 0.5,
        "fg3m": 15,
        "fg3a": 40,
        "fg3_pct": 0.375,
        "ftm": 16,
        "fta": 20,
        "ft_pct": 0.8,
        "plus_minus": 2,
    }
    row.update(overrides)
    return row


@pytest.fixture
def etl_conn(client):
    del client  # Ensures the test database and schema have been initialized.
    conn = psycopg.connect(**get_db_config())
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def test_loaders_preserve_game_ids_and_update_existing_rows(
    etl_conn, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(load, "BASE_CLEAN_DIR", str(tmp_path))
    _write_csv(
        tmp_path,
        "shared/teams.csv",
        {
            "id": LAKERS,
            "full_name": "Los Angeles Lakers Updated",
            "abbreviation": "LAL",
            "nickname": "Lakers",
            "city": "Los Angeles",
            "state": "California",
            "year_founded": 1947,
        },
    )
    _write_csv(
        tmp_path,
        "shared/players.csv",
        {
            "id": LEBRON,
            "full_name": "LeBron James Updated",
            "first_name": "LeBron",
            "last_name": "James",
            "is_active": False,
        },
    )
    _write_csv(tmp_path, f"{SEASON}/games.csv", _game_row())
    _write_csv(
        tmp_path,
        f"{SEASON}/team_game_stats.csv",
        _stats_row(is_home=True),
    )
    _write_csv(
        tmp_path,
        f"{SEASON}/player_game_stats.csv",
        _stats_row(player_id=LEBRON, minutes=38.5, points=41),
    )

    load.load_teams(etl_conn)
    load.load_players(etl_conn)
    load.load_games(etl_conn, SEASON)
    load.load_team_game_stats(etl_conn, SEASON)
    load.load_player_game_stats(etl_conn, SEASON)

    with etl_conn.cursor() as cur:
        cur.execute("SELECT full_name, year_founded FROM teams WHERE id = %s", (LAKERS,))
        assert cur.fetchone() == ("Los Angeles Lakers Updated", 1947)
        cur.execute("SELECT full_name, is_active FROM players WHERE id = %s", (LEBRON,))
        assert cur.fetchone() == ("LeBron James Updated", False)
        cur.execute("SELECT home_score, away_score FROM games WHERE id = %s", (GAME_ID,))
        assert cur.fetchone() == (121, 119)
        cur.execute(
            "SELECT points, rebounds FROM team_game_stats WHERE game_id = %s AND team_id = %s",
            (GAME_ID, LAKERS),
        )
        assert cur.fetchone() == (121, 50)
        cur.execute(
            "SELECT points, minutes FROM player_game_stats WHERE game_id = %s AND player_id = %s",
            (GAME_ID, LEBRON),
        )
        assert cur.fetchone() == (41, 38.5)
        cur.execute("SELECT COUNT(*) FROM games WHERE id = %s", (GAME_ID,))
        assert cur.fetchone()[0] == 1


def test_load_season_rolls_back_all_changes_on_failure(
    etl_conn, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(load, "BASE_CLEAN_DIR", str(tmp_path))
    _write_csv(
        tmp_path,
        "shared/teams.csv",
        {
            "id": LAKERS,
            "full_name": "This update must roll back",
            "abbreviation": "LAL",
            "nickname": "Lakers",
            "city": "Los Angeles",
            "state": "California",
            "year_founded": 1948,
        },
    )
    _write_csv(
        tmp_path,
        f"{SEASON}/games.csv",
        _game_row(id="0022499999", home_team_id=9999999999),
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        load.load_season(etl_conn, SEASON)

    with etl_conn.cursor() as cur:
        cur.execute("SELECT full_name FROM teams WHERE id = %s", (LAKERS,))
        assert cur.fetchone()[0] == "Los Angeles Lakers"


def test_season_metadata_counts_games_without_player_stats_and_handles_1990s(
    etl_conn,
) -> None:
    season = "1998-99"
    game_id = "0029800001"
    with etl_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO games (
                id, game_date, season, home_team_id, away_team_id, home_score, away_score
            ) VALUES (%s, '1998-11-01', %s, %s, %s, 100, 90)
            """,
            (game_id, season, LAKERS, CELTICS),
        )
        cur.execute("CALL sp_update_season_metadata(%s)", (season,))
        cur.execute(
            "SELECT start_year, end_year, games_count, players_count FROM seasons WHERE id = %s",
            (season,),
        )
        assert cur.fetchone() == (1998, 1999, 1, 0)


def test_player_season_shooting_percentages_are_weighted_by_attempts(client) -> None:
    player_id = 9990001
    conn = psycopg.connect(**get_db_config())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO players (id, full_name, first_name, last_name, is_active)"
                " VALUES (%s, 'Weighted Shooter', 'Weighted', 'Shooter', FALSE)",
                (player_id,),
            )
            cur.executemany(
                """
                INSERT INTO player_game_stats (
                    game_id, player_id, team_id, season, minutes, points, rebounds, assists,
                    fgm, fga, fg_pct, fg3m, fg3a, fg3_pct, ftm, fta, ft_pct
                ) VALUES (
                    %s, %s, %s, %s, 10, 10, 1, 1,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                [
                    (GAME_ID, player_id, LAKERS, SEASON, 1, 2, 0.5, 0, 1, 0.0, 1, 4, 0.25),
                    (
                        "0022400002",
                        player_id,
                        LAKERS,
                        SEASON,
                        9,
                        10,
                        0.9,
                        3,
                        4,
                        0.75,
                        8,
                        8,
                        1.0,
                    ),
                ],
            )
        conn.commit()

        response = client.get(f"/api/players/{player_id}/stats")

        assert response.status_code == 200
        (row,) = response.json()
        assert row["fg_pct"] == 0.833
        assert row["fg3_pct"] == 0.6
        assert row["ft_pct"] == 0.75
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM player_game_stats WHERE player_id = %s", (player_id,))
            cur.execute("DELETE FROM players WHERE id = %s", (player_id,))
        conn.commit()
        conn.close()
