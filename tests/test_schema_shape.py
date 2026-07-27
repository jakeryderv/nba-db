"""Schema-shape assertions for migration 10.

These read the catalog of the database the suite built by applying every
migration, so they assert what a fresh deployment actually gets rather than what
the SQL appears to say.
"""

import re

import psycopg
import pytest

from db.config import get_db_config


@pytest.fixture(scope="module")
def schema_conn(client):
    del client
    conn = psycopg.connect(**get_db_config())
    try:
        yield conn
    finally:
        conn.close()


def _scalar(conn, query, params=()):
    with conn.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
        return row[0] if row else None


def test_game_date_is_not_null(schema_conn) -> None:
    """The loader's validation already requires it; the schema should agree.

    A constraint enforced only in application code permits a database state the
    code refuses to produce, which is a difference that only shows up when
    something writes by another route.
    """
    nullable = _scalar(
        schema_conn,
        """
        SELECT is_nullable FROM information_schema.columns
        WHERE table_name = 'games' AND column_name = 'game_date'
        """,
    )
    assert nullable == "NO"


@pytest.mark.parametrize("column", ["home_team_id", "away_team_id"])
def test_game_team_foreign_keys_are_indexed(schema_conn, column: str) -> None:
    """Both are foreign keys with no index, so joins by team scan games."""
    indexed = _scalar(
        schema_conn,
        """
        SELECT COUNT(*) FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = 'games'::regclass AND a.attname = %s
        """,
        (column,),
    )
    assert indexed > 0, f"games.{column} is a foreign key with no index"


@pytest.mark.parametrize("table", ["team_game_stats", "player_game_stats"])
def test_surrogate_key_is_gone(schema_conn, table: str) -> None:
    """Nothing referenced these; the natural key is the real identity."""
    present = _scalar(
        schema_conn,
        """
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_name = %s AND column_name = 'id'
        """,
        (table,),
    )
    assert present == 0, f"{table}.id still exists"


@pytest.mark.parametrize(
    ("table", "columns"),
    [
        ("team_game_stats", "game_id, team_id"),
        ("player_game_stats", "game_id, player_id"),
    ],
)
def test_natural_key_is_the_primary_key(schema_conn, table: str, columns: str) -> None:
    definition = _scalar(
        schema_conn,
        """
        SELECT pg_get_constraintdef(oid) FROM pg_constraint
        WHERE conrelid = %s::regclass AND contype = 'p'
        """,
        (table,),
    )
    assert definition == f"PRIMARY KEY ({columns})", f"{table} primary key is {definition!r}"


def test_no_duplicate_index_left_behind(schema_conn) -> None:
    """Promoting the unique constraint must not leave its old index alongside.

    Adding a primary key over columns that already carry a unique constraint
    creates a second identical index, doubling write cost on every load for no
    benefit.
    """
    for table, columns in (
        ("team_game_stats", ["game_id", "team_id"]),
        ("player_game_stats", ["game_id", "player_id"]),
    ):
        count = _scalar(
            schema_conn,
            """
            SELECT COUNT(*) FROM pg_index i
            WHERE i.indrelid = %s::regclass
              AND i.indisunique
              AND (SELECT array_agg(a.attname ORDER BY a.attnum)
                   FROM pg_attribute a
                   WHERE a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)) = %s::name[]
            """,
            (table, columns),
        )
        assert count == 1, f"{table} has {count} unique indexes over {columns}, expected 1"


def test_standings_view_does_not_use_an_or_join(schema_conn) -> None:
    """An OR-join across two foreign keys cannot use either index."""
    definition = _scalar(
        schema_conn,
        "SELECT pg_get_viewdef('vw_team_standings'::regclass, true)",
    )
    # Word boundary matters: a naive substring check matches the OR inside
    # "score" and reports a disjunction that is not there.
    assert not re.search(r"\bOR\b", definition, re.IGNORECASE), (
        "vw_team_standings still joins with a disjunction"
    )
    assert "UNION ALL" in definition.upper()


@pytest.mark.parametrize(
    "view",
    [
        "vw_team_standings",
        "vw_game_summary",
        "vw_team_season_stats",
        # vw_player_season_averages is excluded: its only ORDER BY is inside a
        # DISTINCT ON, where it chooses which row survives rather than ordering
        # output. Removing it would change results, not just save a sort.
    ],
)
def test_views_do_not_order_results_callers_discard(schema_conn, view: str) -> None:
    """Every caller re-orders, so the view's ORDER BY is sorted work thrown away."""
    definition = _scalar(schema_conn, "SELECT pg_get_viewdef(%s::regclass, true)", (view,))
    assert "ORDER BY" not in definition.upper(), f"{view} still carries an ORDER BY"
