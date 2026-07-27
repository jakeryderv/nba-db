"""The league-context memo must change timing only, never results."""

import contextlib

import pytest

from app.shot_context import league_context_cache
from tests.conftest import LAKERS, SEED_SEASON


@pytest.fixture(autouse=True)
def _clear_cache():
    league_context_cache.clear()
    yield
    league_context_cache.clear()


def _shot_chart(client, **params):
    query = {"season": SEED_SEASON, **params}
    response = client.get("/api/shot-chart", params=query)
    assert response.status_code == 200, response.text
    return response.json()


class _CountingCursor:
    """Delegating proxy: psycopg's Cursor.execute is read-only, so it cannot be patched."""

    def __init__(self, cursor, log: list[str]) -> None:
        self._cursor = cursor
        self._log = log

    def execute(self, query, params=None, **kwargs):
        self._log.append(str(query))
        return self._cursor.execute(query, params, **kwargs)

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __iter__(self):
        return iter(self._cursor)


def _count_league_queries(monkeypatch) -> list[str]:
    """Record every statement the handler executes, so hits are counted not timed."""
    import app.main as main

    executed: list[str] = []
    original = main.get_cursor

    @contextlib.contextmanager
    def counting_cursor():
        with original() as cur:
            yield _CountingCursor(cur, executed)

    monkeypatch.setattr(main, "get_cursor", counting_cursor)
    return executed


SUBJECT_PREDICATES = ("sa.player_id = %s", "sa.team_id = %s")


def _league_statements(executed: list[str]) -> list[str]:
    """League aggregates are the shot statements carrying no subject predicate.

    The subject column varies by request -- team_id for a team chart, player_id
    for a player chart -- so both must be excluded or a team chart's own queries
    are miscounted as league ones.
    """
    return [
        q
        for q in executed
        if "shot_attempts sa" in q and not any(p in q for p in SUBJECT_PREDICATES)
    ]


def test_response_is_identical_warm_and_cold(client) -> None:
    cold = _shot_chart(client, team_id=LAKERS)
    warm = _shot_chart(client, team_id=LAKERS)
    assert cold == warm
    assert cold["league_fg_pct"] == warm["league_fg_pct"]
    assert [z.get("league_fg_pct") for z in cold["zones"]] == [
        z.get("league_fg_pct") for z in warm["zones"]
    ]


def test_a_warm_request_issues_no_league_queries(client, monkeypatch) -> None:
    _shot_chart(client, team_id=LAKERS)  # populate

    executed = _count_league_queries(monkeypatch)
    _shot_chart(client, team_id=LAKERS)

    league = [q for q in _league_statements(executed) if "COUNT(*) FILTER" in q]
    assert league == [], f"warm request still ran league aggregates: {league}"


def test_a_cold_request_does_issue_league_queries(client, monkeypatch) -> None:
    """The counter must be able to see the queries it claims are absent."""
    executed = _count_league_queries(monkeypatch)
    _shot_chart(client, team_id=LAKERS)

    league = [q for q in _league_statements(executed) if "COUNT(*) FILTER" in q]
    assert league, "the query counter never observed a league aggregate"


def test_made_filter_skips_and_does_not_populate_the_cache(client) -> None:
    _shot_chart(client, team_id=LAKERS, made="true")
    assert league_context_cache.tracked_entries == 0


def test_different_filters_get_different_league_context(client) -> None:
    unfiltered = _shot_chart(client, team_id=LAKERS)
    filtered = _shot_chart(client, team_id=LAKERS, period=1)

    # Two cached values (fg_pct, zones) per distinct context, not one shared pair.
    assert league_context_cache.tracked_entries == 4
    # A period filter narrows the subject set, so the two responses describe
    # different slices -- confirming the contexts really were distinct.
    assert unfiltered["attempts"] >= filtered["attempts"]


def test_a_replaced_dataset_retires_cached_values(client) -> None:
    """Promotion changes loaded_at without restarting the process."""
    from app.db import get_cursor

    _shot_chart(client, team_id=LAKERS)
    before = league_context_cache.tracked_entries
    assert before > 0

    with get_cursor() as cur:
        cur.execute(
            "UPDATE seasons SET loaded_at = loaded_at + INTERVAL '1 hour' WHERE id = %s",
            (SEED_SEASON,),
        )
    try:
        _shot_chart(client, team_id=LAKERS)
        # New entries rather than reused ones: the old key can no longer be hit.
        assert league_context_cache.tracked_entries == before * 2
    finally:
        with get_cursor() as cur:
            cur.execute(
                "UPDATE seasons SET loaded_at = loaded_at - INTERVAL '1 hour' WHERE id = %s",
                (SEED_SEASON,),
            )
