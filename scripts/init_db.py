#!/usr/bin/env python3
"""Initialize database schema from SQL files."""

import hashlib
import os
import re
import sys
from pathlib import Path

import psycopg
from psycopg import sql

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db.config import get_db_config

SCHEMA_DIR = PROJECT_ROOT / "db" / "schema"
MIGRATION_FILENAME = re.compile(r"^\d+_[a-z0-9_]+\.sql$")


class MigrationChecksumError(RuntimeError):
    """Raised when an already-applied migration has been edited."""


DOLLAR_TAG = re.compile(r"\$\$|\$[A-Za-z_][A-Za-z0-9_]*\$")


def _has_executable_line(statement: str) -> bool:
    """Whether a fragment contains anything other than comments and blank lines."""
    return any(
        line.strip() and not line.strip().startswith("--") for line in statement.splitlines()
    )


def _scan_delimited(sql: str, start: int, quote: str) -> int:
    """Return the index just past a quoted run, treating a doubled quote as escaped."""
    index = start + 1
    while index < len(sql):
        if sql[index] == quote:
            if index + 1 < len(sql) and sql[index + 1] == quote:
                index += 2
                continue
            return index + 1
        index += 1
    return len(sql)


def split_sql(sql: str) -> list[str]:
    """Split SQL into statements, ignoring semicolons that are not statement ends.

    A semicolon only terminates a statement outside string literals, quoted
    identifiers, comments, and dollar-quoted bodies. The previous implementation
    tracked only bare `$$`, so a tagged quote such as `$func$`, a `$$` inside a
    literal, or a semicolon inside a literal or comment would split a statement
    in the middle.

    That failure is silent rather than loud: the fragments are often individually
    valid SQL, so a migration applies in pieces and records its checksum as
    though it had applied whole. Nothing in migrations 01-09 trips it, which is
    exactly why it is worth fixing before one does.
    """
    statements: list[str] = []
    buffer: list[str] = []
    index = 0
    length = len(sql)
    open_tag: str | None = None

    while index < length:
        if open_tag is not None:
            if sql.startswith(open_tag, index):
                buffer.append(open_tag)
                index += len(open_tag)
                open_tag = None
            else:
                buffer.append(sql[index])
                index += 1
            continue

        if sql.startswith("--", index):
            end = sql.find("\n", index)
            end = length if end == -1 else end
            buffer.append(sql[index:end])
            index = end
            continue

        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            end = length if end == -1 else end + 2
            buffer.append(sql[index:end])
            index = end
            continue

        character = sql[index]
        if character in "'\"":
            end = _scan_delimited(sql, index, character)
            buffer.append(sql[index:end])
            index = end
            continue

        tag = DOLLAR_TAG.match(sql, index)
        if tag:
            open_tag = tag.group(0)
            buffer.append(open_tag)
            index += len(open_tag)
            continue

        if character == ";":
            statement = "".join(buffer).strip()
            if statement and _has_executable_line(statement):
                statements.append(statement)
            buffer = []
            index += 1
            continue

        buffer.append(character)
        index += 1

    # The trailing fragment gets the same comment filter as the others. Without
    # it, a file that is entirely comments yields one comment-only "statement"
    # that is then executed -- harmless in PostgreSQL, but an inconsistency that
    # makes the two paths disagree about what counts as a statement.
    statement = "".join(buffer).strip()
    if statement and _has_executable_line(statement):
        statements.append(statement)

    return statements


def apply_schema(conn: psycopg.Connection) -> None:
    """Apply new numbered schema files and record their checksums.

    Schema files are written to be idempotent so an existing database can be
    brought under migration tracking on its first run. Applied files are
    immutable: every schema change after that must use a new numbered SQL file.
    """
    sql_files = sorted(SCHEMA_DIR.glob("*.sql"))
    if not sql_files:
        raise FileNotFoundError(f"No SQL files found in {SCHEMA_DIR}")
    invalid_names = [path.name for path in sql_files if not MIGRATION_FILENAME.fullmatch(path.name)]
    if invalid_names:
        names = ", ".join(invalid_names)
        raise ValueError(f"Schema migration filenames must be numbered: {names}")

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
                if row:
                    if row[0] != checksum:
                        raise MigrationChecksumError(
                            f"Applied schema migration {sql_file.name} has changed; "
                            "restore it and add a new numbered migration instead"
                        )
                    print(f"Skipping {sql_file.name} (already applied).")
                    continue

                print(f"Applying {sql_file.name}...")
                for statement in split_sql(contents):
                    cur.execute(statement)
                cur.execute(
                    """
                    INSERT INTO schema_migrations (filename, checksum, applied_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
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
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role_name)))
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
