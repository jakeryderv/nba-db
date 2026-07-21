"""API tests against the seeded nba_db_test database."""

import time
from contextlib import contextmanager

from tests.conftest import CELTICS, JORDAN, LAKERS, LEBRON, SEED_SEASON, TATUM


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy", "database": "connected"}
    assert r.headers["cache-control"] == "no-store"


def test_health_does_not_expose_database_error(client, monkeypatch):
    @contextmanager
    def broken_cursor():
        raise RuntimeError("secret connection details")
        yield

    monkeypatch.setattr("app.main.get_cursor", broken_cursor)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "secret connection details" not in response.text


class TestAdminEndpointsRemoved:
    """The public app must expose no write or SQL-execution capability."""

    def test_query_endpoint_removed(self, client):
        r = client.post("/api/query", json={"query": "SELECT 1"})
        assert r.status_code == 404

    def test_etl_endpoint_removed(self, client):
        r = client.post("/api/etl", json={"seasons": ["2024-25"]})
        assert r.status_code == 404

    def test_create_player_removed(self, client):
        r = client.post("/api/players", json={"id": 999999, "full_name": "Nobody"})
        assert r.status_code == 405  # GET /api/players still exists

    def test_create_game_removed(self, client):
        r = client.post("/api/games", json={})
        assert r.status_code == 405  # GET /api/games still exists

    def test_create_player_game_stats_removed(self, client):
        r = client.post("/api/player-game-stats", json={})
        assert r.status_code == 405  # GET /api/player-game-stats still exists


def test_player_search_is_case_insensitive(client):
    r = client.get("/api/players", params={"search": "lebron"})
    assert r.status_code == 200
    names = [p["full_name"] for p in r.json()["data"]]
    assert names == ["LeBron James"]


def test_home_page_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<html" in r.text.lower()
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["content-security-policy"].startswith("default-src 'self'")
    assert "'unsafe-inline'" not in r.headers["content-security-policy"]


def test_static_assets_are_served_with_revalidation_cache(client):
    for path, content_type in (
        ("/static/styles.css", "text/css"),
        ("/static/app.js", "text/javascript"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert content_type in response.headers["content-type"]
        assert response.headers["cache-control"] == "public, max-age=3600, must-revalidate"
        assert response.headers["x-content-type-options"] == "nosniff"


def test_list_seasons(client):
    r = client.get("/api/seasons")
    assert r.status_code == 200
    assert [s["id"] for s in r.json()] == [SEED_SEASON]
    assert r.headers["cache-control"] == "public, max-age=300, stale-while-revalidate=3600"


def test_representative_read_endpoints_respond_promptly(client):
    paths = [
        f"/api/standings?season={SEED_SEASON}",
        f"/api/teams/{LAKERS}/stats?season={SEED_SEASON}",
        f"/api/teams/{LAKERS}/players?season={SEED_SEASON}",
        f"/api/players/{LEBRON}/games?season={SEED_SEASON}",
        "/api/games/0022400001/boxscore",
    ]

    started = time.perf_counter()
    responses = [client.get(path) for path in paths]
    elapsed = time.perf_counter() - started

    assert all(response.status_code == 200 for response in responses)
    assert elapsed < 2.0, f"Representative API reads took {elapsed:.3f}s"


def test_list_teams_sorted_by_name(client):
    r = client.get("/api/teams")
    assert r.status_code == 200
    assert [t["id"] for t in r.json()] == [CELTICS, LAKERS]


def test_get_team(client):
    r = client.get(f"/api/teams/{LAKERS}")
    assert r.status_code == 200
    assert r.json()["abbreviation"] == "LAL"


def test_get_team_not_found(client):
    assert client.get("/api/teams/1").status_code == 404


def test_team_season_stats(client):
    r = client.get(f"/api/teams/{LAKERS}/stats", params={"season": SEED_SEASON})
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "team_id": LAKERS,
        "season": SEED_SEASON,
        "games_played": 10,
        "wins": 10,
        "losses": 0,
        "win_pct": 1.0,
        "home_wins": 10,
        "home_losses": 0,
        "away_wins": 0,
        "away_losses": 0,
        "ppg": 110.0,
        "opponent_ppg": 100.0,
        "point_diff": 10.0,
        "last_10_wins": 10,
        "last_10_losses": 0,
        "rpg": 45.0,
        "apg": 25.0,
        "spg": 0.0,
        "bpg": 0.0,
        "fg_pct": 0.444,
        "fg3_pct": 0.343,
        "ft_pct": 0.818,
        "efg_pct": 0.511,
    }


def test_team_season_stats_not_found(client):
    r = client.get(f"/api/teams/{LAKERS}/stats", params={"season": "1999-00"})
    assert r.status_code == 404


def test_team_players_are_ranked_by_scoring(client):
    r = client.get(f"/api/teams/{LAKERS}/players", params={"season": SEED_SEASON})
    assert r.status_code == 200
    body = r.json()
    assert body["team_id"] == LAKERS
    assert body["season"] == SEED_SEASON
    assert [(row["player_id"], row["ppg"]) for row in body["data"]] == [(LEBRON, 30.0)]


def test_team_players_reject_unknown_team(client):
    assert client.get("/api/teams/1/players", params={"season": SEED_SEASON}).status_code == 404


def test_list_players_active_filter(client):
    r = client.get("/api/players", params={"active": "false"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["data"][0]["id"] == JORDAN


def test_list_players_pagination(client):
    r = client.get("/api/players", params={"limit": 2, "offset": 0})
    body = r.json()
    assert body["total"] == 3
    assert len(body["data"]) == 2


def test_get_player_not_found(client):
    assert client.get("/api/players/1").status_code == 404


def test_player_season_averages(client):
    r = client.get(f"/api/players/{LEBRON}/stats")
    assert r.status_code == 200
    (row,) = r.json()
    assert row["season"] == SEED_SEASON
    assert row["games_played"] == 10
    assert row["team_id"] == LAKERS
    assert row["team_abbr"] == "LAL"
    assert row["mpg"] == 36.5
    assert row["ppg"] == 30.0


def test_player_stats_not_found(client):
    assert client.get("/api/players/1/stats").status_code == 404


def test_dnp_rows_do_not_create_player_averages(client):
    assert client.get(f"/api/players/{JORDAN}/stats").status_code == 404


def test_player_game_log(client):
    r = client.get(
        f"/api/players/{LEBRON}/games",
        params={"season": SEED_SEASON, "limit": 3},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 10
    assert body["limit"] == 3
    assert len(body["data"]) == 3
    expected = {
        "game_id": "0022400010",
        "opponent_id": CELTICS,
        "opponent_name": "Boston Celtics",
        "opponent_abbr": "BOS",
        "is_home": True,
        "result": "W",
        "team_score": 110,
        "opponent_score": 100,
    }
    assert {key: body["data"][0][key] for key in expected} == expected


def test_player_game_log_rejects_unknown_player(client):
    assert client.get("/api/players/1/games", params={"season": SEED_SEASON}).status_code == 404


def test_list_games_filtered_by_season_and_team(client):
    r = client.get("/api/games", params={"season": SEED_SEASON, "team_id": LAKERS})
    body = r.json()
    assert body["total"] == 10
    assert all(g["home_team"] == "Los Angeles Lakers" for g in body["data"])


def test_get_game(client):
    r = client.get("/api/games/0022400001")
    assert r.status_code == 200
    body = r.json()
    assert body["home_score"] == 110
    assert body["away_team"] == "Boston Celtics"


def test_get_game_not_found(client):
    assert client.get("/api/games/nope").status_code == 404


def test_boxscore(client):
    r = client.get("/api/games/0022400001/boxscore")
    assert r.status_code == 200
    body = r.json()
    assert [p["player_id"] for p in body["home_players"]] == [LEBRON]
    assert [p["player_id"] for p in body["away_players"]] == [TATUM]
    assert body["home_team_stats"]["points"] == 110
    assert body["away_team_stats"]["points"] == 100


def test_list_team_game_stats(client):
    r = client.get("/api/team-game-stats", params={"season": SEED_SEASON, "team_id": CELTICS})
    body = r.json()
    assert body["total"] == 10
    assert all(s["team_abbr"] == "BOS" for s in body["data"])


def test_list_player_game_stats(client):
    r = client.get("/api/player-game-stats", params={"season": SEED_SEASON, "player_id": TATUM})
    body = r.json()
    assert body["total"] == 5


def test_leaders_respects_min_games_threshold(client):
    r = client.get("/api/leaders/points", params={"season": SEED_SEASON})
    assert r.status_code == 200
    leaders = r.json()["data"]
    assert r.json()["minimum_games"] == 7
    assert [(leader["player_id"], leader["value"]) for leader in leaders] == [(LEBRON, 30.0)]


def test_player_comparison(client):
    r = client.get(
        "/api/comparisons/players",
        params=[
            ("player_ids", LEBRON),
            ("player_ids", TATUM),
            ("season", SEED_SEASON),
        ],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["season"] == SEED_SEASON
    assert [(row["player_id"], row["ppg"]) for row in body["data"]] == [
        (LEBRON, 30.0),
        (TATUM, 25.0),
    ]


def test_player_comparison_requires_two_distinct_players(client):
    r = client.get(
        "/api/comparisons/players",
        params=[("player_ids", LEBRON), ("player_ids", LEBRON), ("season", SEED_SEASON)],
    )
    assert r.status_code == 422


def test_team_comparison_includes_head_to_head(client):
    r = client.get(
        "/api/comparisons/teams",
        params=[("team_ids", LAKERS), ("team_ids", CELTICS), ("season", SEED_SEASON)],
    )
    assert r.status_code == 200
    body = r.json()
    assert [row["team"]["id"] for row in body["data"]] == [LAKERS, CELTICS]
    assert body["head_to_head"] == {
        "games_played": 10,
        "first_team_wins": 10,
        "second_team_wins": 0,
        "first_team_ppg": 110.0,
        "second_team_ppg": 100.0,
    }


def test_leaders_rejects_unknown_stat(client):
    r = client.get("/api/leaders/dunks", params={"season": SEED_SEASON})
    assert r.status_code == 422


def test_standings(client):
    r = client.get("/api/standings", params={"season": SEED_SEASON})
    assert r.status_code == 200
    rows = r.json()
    assert [(t["team_id"], t["wins"], t["losses"]) for t in rows] == [
        (LAKERS, 10, 0),
        (CELTICS, 0, 10),
    ]
    assert rows[0]["win_pct"] == 1.0
