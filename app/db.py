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
# How many holders have opened the pool and not yet let go. The pool is a
# module global, so nothing about its lifetime follows from any single lifespan:
# an unconditional close on one shutdown pulls it out from under every other
# holder. Counting the holders makes the last one out responsible for closing.
_pool_refs = 0


def _open_locked() -> ConnectionPool:
    """Return the pool, building it if needed. Caller must hold `_pool_lock`."""
    global _pool
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


def get_pool() -> ConnectionPool:
    """Get or create the connection pool.

    This is the per-request accessor and claims no ownership: a handler borrows
    the pool for the length of a call. Holders that outlive a request -- an
    application lifespan -- use `acquire_pool`/`release_pool` instead.
    """
    with _pool_lock:
        return _open_locked()


def acquire_pool() -> ConnectionPool:
    """Open the pool on behalf of a holder that will later release it."""
    global _pool_refs
    with _pool_lock:
        _pool_refs += 1
        return _open_locked()


def release_pool() -> None:
    """Drop one holder's claim, closing the pool once the last one lets go."""
    global _pool, _pool_refs
    with _pool_lock:
        if _pool_refs > 0:
            _pool_refs -= 1
        if _pool_refs > 0:
            return
        if _pool is not None:
            _pool.close()
            _pool = None


def close_pool() -> None:
    """Close the pool unconditionally, regardless of outstanding holders.

    For process exit and test teardown, where the point is to leave nothing
    open. Ordinary shutdown should go through `release_pool` so that a holder
    still serving requests keeps its pool.
    """
    global _pool, _pool_refs
    with _pool_lock:
        _pool_refs = 0
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
