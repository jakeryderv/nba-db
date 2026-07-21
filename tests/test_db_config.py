"""Database connection configuration tests."""

from psycopg.conninfo import conninfo_to_dict

from db.config import get_conninfo, get_db_config


def test_database_url_preserves_options_and_decodes_credentials(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://nba:p%40ss%20word@db.example:5433/nba%20stats"
        "?sslmode=require&connect_timeout=7&application_name=nba%20api",
    )

    config = get_db_config()

    assert config == {
        "user": "nba",
        "password": "p@ss word",
        "dbname": "nba stats",
        "host": "db.example",
        "port": 5433,
        "sslmode": "require",
        "connect_timeout": "7",
        "application_name": "nba api",
    }


def test_readonly_conninfo_safely_escapes_override(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://owner:owner-pw@db.example/nba?sslmode=verify-full",
    )
    monkeypatch.setenv("READONLY_DB_USER", "nba read only")
    monkeypatch.setenv("READONLY_DB_PASSWORD", "space \\ quote ' password")

    parsed = conninfo_to_dict(get_conninfo(readonly=True))

    assert parsed["user"] == "nba read only"
    assert parsed["password"] == "space \\ quote ' password"
    assert parsed["sslmode"] == "verify-full"
    assert parsed["dbname"] == "nba"
