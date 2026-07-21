"""Shared PostgreSQL connection configuration."""

import os
from typing import Any

from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict, make_conninfo

load_dotenv()


def get_db_config(readonly: bool = False) -> dict[str, Any]:
    """Return PostgreSQL connection parameters.

    With readonly=True and READONLY_DB_PASSWORD set, connect as the
    configured SELECT-only role instead of the owner.
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        # Let libpq parse the URI. Besides correctly decoding credentials, this
        # retains options such as sslmode, connect_timeout and application_name.
        config: dict[str, Any] = conninfo_to_dict(database_url)
        if "port" in config:
            config["port"] = int(config["port"])
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
            config["user"] = os.getenv("READONLY_DB_USER", "nba_readonly")
            config["password"] = ro_password

    return config


def get_conninfo(readonly: bool = False) -> str:
    """Return a PostgreSQL connection string."""
    # make_conninfo applies libpq escaping for spaces, quotes and backslashes.
    return make_conninfo("", **get_db_config(readonly=readonly))
