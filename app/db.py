"""Database connection pool for FastAPI."""

import logging
import os
import threading
from collections.abc import Generator
from contextlib import contextmanager

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from db.config import get_conninfo

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None
# Handlers are sync and run concurrently on a threadpool, so an unguarded
# check-then-create here lets two cold requests build two pools and leak one.
# The application opens the pool during lifespan startup; this lock keeps the
# fallback path correct rather than relying on that ordering.
_pool_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    """Get or create the connection pool."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        # The SELECT-only role is the expected production posture; owner
        # credentials are a deliberate, visible local-development fallback.
        readonly = bool(os.getenv("READONLY_DB_PASSWORD"))
        if not readonly:
            logger.warning("READONLY_DB_PASSWORD is not set; connecting with owner credentials")
        _pool = ConnectionPool(
            conninfo=get_conninfo(readonly=readonly),
            kwargs={
                "row_factory": dict_row,
                "options": "-c statement_timeout=15000 -c idle_in_transaction_session_timeout=15000",
            },
            min_size=2,
            max_size=10,
            max_waiting=20,
            timeout=5,
            open=True,
        )
    return _pool


def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    with _pool_lock:
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
