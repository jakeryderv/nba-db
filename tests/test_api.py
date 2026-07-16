"""API tests against the seeded nba_db_test database."""


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy", "database": "connected"}


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
