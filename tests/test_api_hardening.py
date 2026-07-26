"""Boundary validation and failure-response behavior of the public surface."""

from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

from tests.conftest import CELTICS, LAKERS, LEBRON, SEED_SEASON, TATUM


def test_malformed_season_is_rejected(client) -> None:
    """An unparseable season is a client error, not an empty result set."""
    assert client.get("/api/standings", params={"season": "not-a-season"}).status_code == 422
    assert client.get("/api/leaders/points", params={"season": "2024"}).status_code == 422
    assert client.get("/api/games", params={"season": "2024-25-26"}).status_code == 422


def test_well_formed_season_still_works(client) -> None:
    assert client.get("/api/standings", params={"season": SEED_SEASON}).status_code == 200


def test_search_metacharacters_match_literally(client) -> None:
    """A bare '%' used to match every player; it must now match none."""
    unescaped = client.get("/api/players", params={"search": "%"})
    assert unescaped.status_code == 200
    assert unescaped.json()["total"] == 0

    underscore = client.get("/api/players", params={"search": "_"})
    assert underscore.status_code == 200
    assert underscore.json()["total"] == 0

    # A real substring search is unaffected.
    real = client.get("/api/players", params={"search": "LeBron"})
    assert real.json()["total"] == 1


def test_oversized_parameters_are_rejected(client) -> None:
    assert client.get("/api/players", params={"search": "x" * 101}).status_code == 422
    assert (
        client.get(
            "/api/player-game-stats",
            params={"season": SEED_SEASON, "game_id": "y" * 21},
        ).status_code
        == 422
    )


def test_csv_filename_cannot_inject_header_parameters(client) -> None:
    """A quote in a subject value must not terminate the quoted filename."""
    response = client.get(
        "/api/shot-chart.csv",
        params={"season": SEED_SEASON, "player_id": 2544},
    )
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition.count('"') == 2
    assert disposition.startswith('attachment; filename="')


def test_pool_exhaustion_is_a_retryable_503(client, monkeypatch) -> None:
    def exhausted():
        raise PoolTimeout("no connection available")

    monkeypatch.setattr("app.main.get_cursor", exhausted)
    response = client.get("/api/seasons")

    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert response.json()["detail"] == "Service busy; retry shortly"
    # The response travelled back through the middleware, so policy applies.
    assert response.headers["x-content-type-options"] == "nosniff"


def test_unhandled_error_returns_the_logged_correlation_id(client, monkeypatch) -> None:
    def boom():
        raise RuntimeError("unexpected")

    monkeypatch.setattr("app.main.get_cursor", boom)
    # The catch-all handler runs in ServerErrorMiddleware, which re-raises for a
    # client configured to surface server exceptions.
    quiet = TestClient(client.app, raise_server_exceptions=False)
    response = quiet.get("/api/seasons")

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "Internal server error"
    assert body["request_id"]
    assert body["request_id"] == response.headers["x-request-id"]
    # A 500 must carry the same headers as any other response.
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["strict-transport-security"]
    assert response.headers["content-security-policy"]


def test_comparison_endpoints_take_one_pool_checkout(client, monkeypatch) -> None:
    """Composing responses by calling other route handlers cost up to 5 checkouts."""
    import app.main as main

    checkouts = 0
    original = main.get_cursor

    def counting_cursor():
        nonlocal checkouts
        checkouts += 1
        return original()

    monkeypatch.setattr(main, "get_cursor", counting_cursor)

    players = client.get(
        "/api/comparisons/players",
        params={"player_ids": [LEBRON, TATUM], "season": SEED_SEASON},
    )
    assert players.status_code == 200
    assert checkouts == 1

    checkouts = 0
    teams = client.get(
        "/api/comparisons/teams",
        params={"team_ids": [LAKERS, CELTICS], "season": SEED_SEASON},
    )
    assert teams.status_code == 200
    assert checkouts == 1


def test_wait_queue_overflow_is_also_a_retryable_503(client, monkeypatch) -> None:
    """TooManyRequests is a sibling of PoolTimeout, not a subclass.

    Registering only PoolTimeout left the queue-full case falling through to the
    catch-all, so ordinary overload returned 500 with a stack trace instead of a
    retryable 503.
    """
    from psycopg_pool import TooManyRequests

    def queue_full():
        raise TooManyRequests("wait queue is full")

    monkeypatch.setattr("app.main.get_cursor", queue_full)
    response = client.get("/api/seasons")

    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert response.json()["detail"] == "Service busy; retry shortly"
