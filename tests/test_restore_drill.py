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
