"""Database connection pool for FastAPI."""

from collections.abc import Generator
from contextlib import contextmanager

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from db.config import get_conninfo

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    """Get or create the connection pool."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=get_conninfo(),
            kwargs={"row_factory": dict_row},
            min_size=2,
            max_size=10,
        )
    return _pool


def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_db() -> Generator[Connection, None, None]:
    """Get a database connection from the pool."""
    pool = get_pool()
    with pool.connection() as conn:
        yield conn


@contextmanager
def get_cursor() -> Generator:
    """Get a database cursor that returns dicts. Auto-commits on success."""
    with get_db() as conn:
        with conn.cursor() as cur:
            try:
                yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
