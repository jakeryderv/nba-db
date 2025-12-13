"""Database connection pool for FastAPI."""

import os
from collections.abc import Generator
from contextlib import contextmanager

import mysql.connector
from mysql.connector import pooling
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DB_CONFIG = {
    "database": os.getenv("DB_NAME", "nba_db"),
    "user": os.getenv("DB_USER", "nba_user"),
    "password": os.getenv("DB_PASSWORD", "nba_password"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
}

# Connection pool (initialized lazily)
_pool: pooling.MySQLConnectionPool | None = None


def get_pool() -> pooling.MySQLConnectionPool:
    """Get or create the connection pool."""
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="nba_pool",
            pool_size=10,
            pool_reset_session=True,
            **DB_CONFIG
        )
    return _pool


def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool is not None:
        # MySQL connector pool doesn't have a closeall method
        # Connections are closed when they go out of scope
        _pool = None


@contextmanager
def get_db() -> Generator[mysql.connector.MySQLConnection, None, None]:
    """Get a database connection from the pool."""
    pool = get_pool()
    conn = pool.get_connection()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_cursor() -> Generator[mysql.connector.cursor.MySQLCursorDict, None, None]:
    """Get a database cursor that returns dicts. Auto-commits on success."""
    with get_db() as conn:
        cur = conn.cursor(dictionary=True)
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
