"""Schema migrations can initialize and upgrade existing databases."""

import init_db
import psycopg

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
            assert [row[0] for row in cur.fetchall()] == [
                "01_tables.sql",
                "02_constraints.sql",
                "03_indexes.sql",
                "04_triggers.sql",
                "05_views.sql",
                "06_procedures.sql",
            ]
            cur.execute("SELECT COUNT(*) FROM teams")
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 2

        init_db.apply_schema(conn)


def test_changed_schema_file_is_applied_once(client, monkeypatch, tmp_path):
    migration = tmp_path / "99_test_migration.sql"
    migration.write_text("CREATE TABLE IF NOT EXISTS migration_probe (id INTEGER);")
    monkeypatch.setattr(init_db, "SCHEMA_DIR", tmp_path)

    with psycopg.connect(**get_db_config()) as conn:
        init_db.apply_schema(conn)
        migration.write_text(
            "CREATE TABLE IF NOT EXISTS migration_probe (id INTEGER);"
            "ALTER TABLE migration_probe ADD COLUMN marker TEXT;"
        )
        init_db.apply_schema(conn)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'migration_probe'
                ORDER BY ordinal_position
                """
            )
            assert [row[0] for row in cur.fetchall()] == ["id", "marker"]

        # An unchanged migration is skipped, so its non-idempotent ALTER is safe.
        init_db.apply_schema(conn)
