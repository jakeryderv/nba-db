#!/usr/bin/env python3
"""Initialize database schema from SQL files."""

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


def schema_is_initialized(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'teams'
            )
            """
        )
        return bool(cur.fetchone()[0])


def apply_schema(conn: psycopg.Connection) -> None:
    sql_files = sorted(SCHEMA_DIR.glob("*.sql"))
    if not sql_files:
        raise FileNotFoundError(f"No SQL files found in {SCHEMA_DIR}")

    with conn.cursor() as cur:
        for sql_file in sql_files:
            print(f"Applying {sql_file.name}...")
            for statement in split_sql(sql_file.read_text()):
                cur.execute(statement)
    conn.commit()
    print("Schema initialized successfully.")


def ensure_readonly_role(conn: psycopg.Connection) -> None:
    """Create/refresh the SELECT-only role the web app connects as."""
    password = os.getenv("READONLY_DB_PASSWORD")
    if not password:
        print("READONLY_DB_PASSWORD not set, skipping read-only role setup.")
        return

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'nba_readonly'")
        action = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(
            sql.SQL("{} ROLE nba_readonly LOGIN PASSWORD {}").format(
                sql.SQL(action), sql.Literal(password)
            )
        )
        cur.execute("GRANT USAGE ON SCHEMA public TO nba_readonly")
        cur.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO nba_readonly")
        cur.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO nba_readonly"
        )
    conn.commit()
    print("Read-only role nba_readonly is configured.")


def main() -> None:
    conn = psycopg.connect(**get_db_config())
    try:
        if schema_is_initialized(conn):
            print("Schema already initialized, skipping.")
        else:
            apply_schema(conn)
        ensure_readonly_role(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
