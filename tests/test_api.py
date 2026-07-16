"""API tests against the seeded nba_db_test database."""


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy", "database": "connected"}
