"""Shared PostgreSQL connection configuration."""

import os
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()


def get_db_config(readonly: bool = False) -> dict[str, Any]:
    """Return PostgreSQL connection parameters.

    With readonly=True and READONLY_DB_PASSWORD set, connect as the
    SELECT-only nba_readonly role instead of the owner.
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        parsed = urlparse(database_url)
        config: dict[str, Any] = {
            "dbname": parsed.path.lstrip("/"),
            "user": parsed.username or "",
            "password": parsed.password or "",
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 5432,
        }
    else:
        config = {
            "dbname": os.getenv("DB_NAME", "nba_db"),
            "user": os.getenv("DB_USER", "nba_user"),
            "password": os.getenv("DB_PASSWORD", "nba_password"),
            "host": os.getenv("DB_HOST", "localhost"),
            "port": int(os.getenv("DB_PORT", "5432")),
        }

    if readonly:
        ro_password = os.getenv("READONLY_DB_PASSWORD")
        if ro_password:
            config["user"] = "nba_readonly"
            config["password"] = ro_password

    return config


def get_conninfo(readonly: bool = False) -> str:
    """Return a PostgreSQL connection string."""
    config = get_db_config(readonly=readonly)
    return (
        f"dbname={config['dbname']} "
        f"user={config['user']} "
        f"password={config['password']} "
        f"host={config['host']} "
        f"port={config['port']}"
    )
