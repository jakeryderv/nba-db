"""Fixtures for data-quality checks against a loaded database.

These assert properties of a real manifested season -- thirty teams, a full
schedule, shot detail reconciling to box scores. The application test suite runs
against a small seeded fixture, so these deliberately do not run there: pointed
at seed data every assertion would have to be loosened until it checked nothing.

They run where real data exists: the restore drill, which restores a production
backup, and an operator's local load.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest

from db.config import get_db_config
from nba_config import DEFAULT_SEASON


@pytest.fixture(scope="session")
def conn() -> Iterator[psycopg.Connection]:
    """A read connection to the loaded database under test."""
    connection = psycopg.connect(**get_db_config())
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture(scope="session")
def season() -> str:
    """The season these checks are scoped to.

    Scoping matters once a database can hold more than one season: an unscoped
    count silently mixes them, and the reconciliation checks would compare a
    season's recorded provenance against every season's rows.
    """
    return os.getenv("DATA_QUALITY_SEASON", DEFAULT_SEASON)
