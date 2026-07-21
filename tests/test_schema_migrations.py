"""Schema migrations can initialize and upgrade existing databases."""

import init_db
import psycopg
import pytest

from db.config import get_db_config


def test_existing_database_is_adopted_and_safe_to_reapply(client):
    with psycopg.connect(**get_db_config()) as conn:
        with conn.cursor() as cur:
            # Simulate a deployment created before migration tracking existed.
            cur.execute("DELETE FROM schema_migrations")
        conn.commit()

        init_db.apply_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT filename FROM schema_migrations ORDER BY filename")
            expected = sorted(path.name for path in init_db.SCHEMA_DIR.glob("*.sql"))
            assert [row[0] for row in cur.fetchall()] == expected
            cur.execute("SELECT COUNT(*) FROM teams")
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 2

        init_db.apply_schema(conn)


def test_applied_migration_checksum_drift_is_rejected(client, monkeypatch, tmp_path):
    migration = tmp_path / "97_checksum_test.sql"
    migration.write_text("CREATE TABLE migration_checksum_probe (id INTEGER);")
    monkeypatch.setattr(init_db, "SCHEMA_DIR", tmp_path)

    with psycopg.connect(**get_db_config()) as conn:
        init_db.apply_schema(conn)
        migration.write_text(
            "CREATE TABLE migration_checksum_probe (id INTEGER);"
            "ALTER TABLE migration_checksum_probe ADD COLUMN marker TEXT;"
        )

        with pytest.raises(init_db.MigrationChecksumError, match="restore it"):
            init_db.apply_schema(conn)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'migration_checksum_probe'
                ORDER BY ordinal_position
                """
            )
            assert [row[0] for row in cur.fetchall()] == ["id"]


def test_new_migration_is_applied_once(client, monkeypatch, tmp_path):
    migration = tmp_path / "98_apply_once_test.sql"
    migration.write_text(
        "CREATE TABLE migration_once_probe (id INTEGER);"
        "INSERT INTO migration_once_probe VALUES (1);"
    )
    monkeypatch.setattr(init_db, "SCHEMA_DIR", tmp_path)

    with psycopg.connect(**get_db_config()) as conn:
        init_db.apply_schema(conn)
        init_db.apply_schema(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM migration_once_probe")
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 1
