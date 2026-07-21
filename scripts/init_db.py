#!/usr/bin/env python3
"""Initialize database schema from SQL files."""

import hashlib
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db.config import get_db_config

SCHEMA_DIR = PROJECT_ROOT / "db" / "schema"


def split_sql(sql: str) -> list[str]:
    """Split SQL into statements, respecting dollar-quoted blocks."""
    statements: list[str] = []
    buffer: list[str] = []
    in_dollar_quote = False
    i = 0

    while i < len(sql):
        if sql[i : i + 2] == "$$":
            in_dollar_quote = not in_dollar_quote
            buffer.append("$$")
            i += 2
            continue

        if sql[i] == ";" and not in_dollar_quote:
            statement = "".join(buffer).strip()
            if statement and not all(
                line.strip().startswith("--") or not line.strip() for line in statement.splitlines()
            ):
                statements.append(statement)
            buffer = []
            i += 1
            continue

        buffer.append(sql[i])
        i += 1

    statement = "".join(buffer).strip()
    if statement:
        statements.append(statement)

    return statements


def apply_schema(conn: psycopg.Connection) -> None:
    """Apply new or changed schema files and record their checksums.

    Schema files are written to be idempotent so an existing database can be
    brought under migration tracking on its first run. Adding a numbered SQL
    file, or deliberately changing one, causes it to be applied transactionally.
    """
    sql_files = sorted(SCHEMA_DIR.glob("*.sql"))
    if not sql_files:
        raise FileNotFoundError(f"No SQL files found in {SCHEMA_DIR}")

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for sql_file in sql_files:
                contents = sql_file.read_text()
                checksum = hashlib.sha256(contents.encode()).hexdigest()
                cur.execute(
                    "SELECT checksum FROM schema_migrations WHERE filename = %s",
                    (sql_file.name,),
                )
                row = cur.fetchone()
                if row and row[0] == checksum:
                    print(f"Skipping {sql_file.name} (already applied).")
                    continue

                print(f"Applying {sql_file.name}...")
                for statement in split_sql(contents):
                    cur.execute(statement)
                cur.execute(
                    """
                    INSERT INTO schema_migrations (filename, checksum, applied_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (filename) DO UPDATE SET
                        checksum = EXCLUDED.checksum,
                        applied_at = EXCLUDED.applied_at
                    """,
                    (sql_file.name, checksum),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    print("Schema is up to date.")


def ensure_readonly_role(conn: psycopg.Connection) -> None:
    """Create/refresh the SELECT-only role the web app connects as."""
    password = os.getenv("READONLY_DB_PASSWORD")
    if not password:
        print("READONLY_DB_PASSWORD not set, skipping read-only role setup.")
        return
    role_name = os.getenv("READONLY_DB_USER", "nba_readonly")

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,))
        action = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(
            sql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(
                sql.SQL(action), sql.Identifier(role_name), sql.Literal(password)
            )
        )
        cur.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role_name))
        )
        cur.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(
                sql.Identifier(role_name)
            )
        )
        cur.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {}"
            ).format(sql.Identifier(role_name))
        )
    conn.commit()
    print(f"Read-only role {role_name} is configured.")


def main() -> None:
    conn = psycopg.connect(**get_db_config())
    try:
        apply_schema(conn)
        ensure_readonly_role(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
