"""Regression tests for standalone data-quality checks."""

import psycopg

from db.config import get_db_config
from db.tests.test_data_quality import (
    test_game_scores_match_team_stats as check_game_scores_match_team_stats,
)
from tests.conftest import CELTICS


def test_score_check_detects_away_team_mismatch(client):
    """An away-score mismatch must fail the check and be rolled back afterward."""
    conn = psycopg.connect(**get_db_config())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE team_game_stats
                SET points = points + 1
                WHERE game_id = '0022400001' AND team_id = %s
                """,
                (CELTICS,),
            )

        result = check_game_scores_match_team_stats(conn)
        assert not result.passed
        assert result.message == "Found 1 mismatches"
    finally:
        conn.rollback()
        conn.close()
