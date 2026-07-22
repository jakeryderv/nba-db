"""Safety and integration tests for the executable backup restore drill."""

import shutil

import pytest

from db.config import get_db_config
from etl.season_lifecycle import create_backup
from scripts.restore_drill import RestoreDrillError, recovery_config, run_restore_drill
from tests.conftest import SEED_SEASON


def test_recovery_config_requires_disposable_name_and_typed_confirmation() -> None:
    with pytest.raises(RestoreDrillError, match="end in _recovery"):
        recovery_config("postgresql://owner:secret@db.example/nba", "RESTORE nba")
    with pytest.raises(RestoreDrillError, match="Type --confirm"):
        recovery_config(
            "postgresql://owner:secret@db.example/nba_recovery",
            "RESTORE something_else",
        )

    config = recovery_config(
        "postgresql://owner:secret@db.example/nba_recovery",
        "RESTORE nba_recovery",
    )
    assert config["dbname"] == "nba_recovery"
    assert config["password"] == "secret"


def test_recovery_config_refuses_production_url(monkeypatch) -> None:
    url = "postgresql://owner:secret@db.example/nba_recovery"
    monkeypatch.setenv("PRODUCTION_DATABASE_URL", url)

    with pytest.raises(RestoreDrillError, match="must be distinct"):
        recovery_config(url, "RESTORE nba_recovery")


def test_restore_omits_environment_specific_owners_and_acls(monkeypatch, tmp_path) -> None:
    from scripts import restore_drill

    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"archive")
    commands: list[list[str]] = []

    class Result:
        returncode = 0

    def runner(command, **_kwargs):
        commands.append(command)
        return Result()

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, *_args):
            return None

        def fetchone(self):
            return None

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(restore_drill.psycopg, "connect", lambda **_kwargs: Connection())
    monkeypatch.setattr(
        restore_drill,
        "verify_restored_database",
        lambda *_args: {"games": 1, "players": 1, "shot_attempts": 1},
    )

    restore_drill.run_restore_drill(
        backup,
        {"dbname": "nba_test_recovery", "host": "database", "user": "nba_user"},
        "2025-26",
        runner=runner,
    )

    restore_command = commands[1]
    assert "--no-owner" in restore_command
    assert "--no-acl" in restore_command


@pytest.mark.skipif(
    shutil.which("pg_dump") is None or shutil.which("pg_restore") is None,
    reason="PostgreSQL client tools are not installed",
)
def test_real_backup_can_be_restored_verified_and_removed(client, tmp_path) -> None:
    from app.db import get_cursor

    del client
    config = get_db_config()
    recovery = {**config, "dbname": "nba_db_test_recovery"}
    backup = tmp_path / "nba-db-test.dump"
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE seasons
            SET verification_status = 'passed', shot_attempts_count = 295
            WHERE id = %s
            """,
            (SEED_SEASON,),
        )
    try:
        create_backup(config, backup)
        counts = run_restore_drill(backup, recovery, SEED_SEASON)
        assert counts == {"games": 10, "players": 3, "shot_attempts": 295}
    finally:
        with get_cursor() as cur:
            cur.execute(
                """
                UPDATE seasons
                SET verification_status = 'untracked', shot_attempts_count = 0
                WHERE id = %s
                """,
                (SEED_SEASON,),
            )
