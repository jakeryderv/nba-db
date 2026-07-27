"""Regression tests proving the data-quality checks detect real corruption.

The checks themselves run against a loaded season in the restore drill, where a
passing run says nothing about whether they *could* fail. These corrupt the
seeded fixture deliberately and assert each check catches it, then roll back.
"""

import psycopg
import pytest

from db.config import get_db_config
from db.quality_checks import (
    check_game_scores_match_team_stats,
    check_recorded_game_count_reconciles,
    check_shot_totals_match_player_game_stats,
)
from db.quality_checks import (
    check_natural_keys_are_enforced_by_constraints as check_natural_keys_enforced,
)
from tests.conftest import CELTICS, LEBRON, SEED_SEASON


def _connection() -> psycopg.Connection:
    return psycopg.connect(**get_db_config())


def test_score_check_detects_away_team_mismatch(client):
    """An away-score mismatch must fail the check and be rolled back afterward."""
    del client
    conn = _connection()
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

        with pytest.raises(AssertionError, match="1 game scores disagreeing"):
            check_game_scores_match_team_stats(conn, SEED_SEASON)
    finally:
        conn.rollback()
        conn.close()


def test_shot_total_check_detects_missing_attempt(client):
    del client
    conn = _connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM shot_attempts WHERE game_id = '0022400001' "
                "AND player_id = %s AND event_id = 1",
                (LEBRON,),
            )

        with pytest.raises(AssertionError, match="1 player-games where shot detail"):
            check_shot_totals_match_player_game_stats(conn, SEED_SEASON)
    finally:
        conn.rollback()
        conn.close()


def test_natural_key_check_detects_a_dropped_constraint(client):
    """A migration dropping a uniqueness constraint is the failure worth catching.

    Duplicates themselves cannot be inserted while the constraint stands, so the
    check asserts the constraint rather than scanning for rows that cannot exist.
    PostgreSQL has transactional DDL, so the drop rolls back with everything else.
    """
    del client
    conn = _connection()
    try:
        with conn.cursor() as cur:
            # Migration 10 promoted this natural key from a unique constraint
            # to the primary key, so the constraint to drop is the pkey.
            cur.execute("ALTER TABLE player_game_stats DROP CONSTRAINT player_game_stats_pkey")

        with pytest.raises(AssertionError, match="no longer enforced"):
            check_natural_keys_enforced(conn)
    finally:
        conn.rollback()
        conn.close()


def test_provenance_check_detects_a_count_that_stopped_reconciling(client):
    """Recorded counts come from the manifest, so drift means the data changed."""
    del client
    conn = _connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE seasons SET games_count = games_count + 1 WHERE id = %s",
                (SEED_SEASON,),
            )

        with pytest.raises(AssertionError, match="records .* games but holds"):
            check_recorded_game_count_reconciles(conn, SEED_SEASON)
    finally:
        conn.rollback()
        conn.close()


def test_every_check_is_exposed_as_a_test() -> None:
    """The pytest surface must not silently lose a check.

    `db/tests/test_data_quality.py` is aliased imports plus an `__all__` literal.
    Without that literal the linter reads the imports as unused and removes them,
    which deletes the entire suite while leaving a green run -- observed once
    while building this. Assert the two stay in step.
    """
    import db.tests.test_data_quality as surface
    from db.quality_checks import all_checks

    expected = {name.replace("check_", "test_", 1) for name, _ in all_checks()}
    exposed = {name for name in vars(surface) if name.startswith("test_")}

    assert expected == exposed, (
        f"pytest surface drifted from db.quality_checks: {expected ^ exposed}"
    )


def test_the_runner_covers_every_check() -> None:
    """A check that exists but never runs is the failure this area keeps producing."""
    import db.quality_checks as module
    from db.quality_checks import all_checks

    defined = {name for name in vars(module) if name.startswith("check_")}
    assert {name for name, _ in all_checks()} == defined
