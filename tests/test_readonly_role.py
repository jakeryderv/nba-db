"""The nba_readonly role can SELECT but cannot write."""

from uuid import uuid4

import init_db
import psycopg
import pytest
from psycopg import sql
from psycopg.errors import InsufficientPrivilege

from db.config import get_db_config


def test_readonly_role_can_select_but_not_insert(client, monkeypatch):
    role_name = f"nba_readonly_test_{uuid4().hex}"
    monkeypatch.setenv("READONLY_DB_USER", role_name)
    monkeypatch.setenv("READONLY_DB_PASSWORD", "test-readonly-pw")

    conn = psycopg.connect(**get_db_config())
    try:
        init_db.ensure_readonly_role(conn)
        init_db.ensure_readonly_role(conn)  # idempotent: safe to run twice

        ro_config = get_db_config(readonly=True)
        assert ro_config["user"] == role_name
        assert ro_config["dbname"] == "nba_db_test"

        with psycopg.connect(**ro_config) as ro_conn, ro_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM teams")
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 2
            with pytest.raises(InsufficientPrivilege):
                cur.execute("INSERT INTO players (id, full_name) VALUES (999, 'Nope')")
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,))
            if cur.fetchone():
                cur.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
                cur.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
        conn.commit()
        conn.close()


def test_config_ignores_readonly_flag_when_password_unset(client, monkeypatch):
    monkeypatch.delenv("READONLY_DB_PASSWORD", raising=False)
    config = get_db_config(readonly=True)
    assert config["user"] != "nba_readonly"
