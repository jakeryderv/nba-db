"""The nba_readonly role can SELECT but cannot write."""

import psycopg
import pytest
from psycopg.errors import InsufficientPrivilege

import init_db
from db.config import get_db_config


def test_readonly_role_can_select_but_not_insert(client, monkeypatch):
    monkeypatch.setenv("READONLY_DB_PASSWORD", "test-readonly-pw")

    conn = psycopg.connect(**get_db_config())
    try:
        init_db.ensure_readonly_role(conn)
        init_db.ensure_readonly_role(conn)  # idempotent: safe to run twice
    finally:
        conn.close()

    ro_config = get_db_config(readonly=True)
    assert ro_config["user"] == "nba_readonly"
    assert ro_config["dbname"] == "nba_db_test"

    with psycopg.connect(**ro_config) as ro_conn, ro_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM teams")
        assert cur.fetchone()[0] == 2
        with pytest.raises(InsufficientPrivilege):
            cur.execute("INSERT INTO players (id, full_name) VALUES (999, 'Nope')")


def test_config_ignores_readonly_flag_when_password_unset(client, monkeypatch):
    monkeypatch.delenv("READONLY_DB_PASSWORD", raising=False)
    config = get_db_config(readonly=True)
    assert config["user"] != "nba_readonly"
