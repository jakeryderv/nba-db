"""Ownership of the shared connection pool across overlapping lifespans.

The pool is a module global with no owner. Any second lifespan entered over the
same `app` object -- a nested test server, an embedded worker -- used to close it
on the way out while the first holder was still serving. The failure surfaced far
from the cause and looked like a database fault, so these tests assert the
ownership rule itself rather than a downstream symptom.
"""

from fastapi.testclient import TestClient

from app import db
from app.main import app


def test_inner_lifespan_does_not_close_the_outer_pool(client) -> None:
    """A nested lifespan's shutdown must not close a pool another holder is using.

    The session `client` fixture is the outer holder and stays yielded for the
    whole run. `tests/test_browser.py` really does this: its uvicorn server runs
    a second lifespan over this same app object.
    """
    outer_pool = db.get_pool()

    with TestClient(app):
        pass

    assert db._pool is outer_pool, "inner shutdown replaced or dropped the outer pool"
    assert not outer_pool.closed, "inner shutdown closed a pool still in use"
    assert client.get("/health").json()["database"] == "connected"


def test_last_holder_out_closes_the_pool() -> None:
    """Reference counting must not leak: once every holder leaves, the pool closes."""
    db.close_pool()

    first = db.acquire_pool()
    second = db.acquire_pool()
    assert second is first

    db.release_pool()
    assert not first.closed, "pool closed while a holder was still active"

    db.release_pool()
    assert first.closed, "pool outlived its last holder"
    assert db._pool is None


def test_close_pool_releases_every_holder() -> None:
    """Teardown needs an unconditional close that outstanding references cannot block."""
    db.acquire_pool()
    db.acquire_pool()

    db.close_pool()

    assert db._pool is None
    assert db.acquire_pool() is not None
    db.close_pool()
