"""Safety and integration tests for the executable backup restore drill."""

import shutil

import pytest

from db.config import get_db_config
from etl.season_lifecycle import create_backup
from scripts.restore_drill import (
    RestoreDrillError,
    assert_manifest_matches,
    recovery_config,
    run_restore_drill,
)
from tests.conftest import SEED_SEASON

DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


def test_backup_whose_manifest_disagrees_with_restored_data_fails() -> None:
    with pytest.raises(RestoreDrillError, match="does not match"):
        assert_manifest_matches(restored=DIGEST, expected=OTHER_DIGEST)


def test_backup_missing_manifest_metadata_cannot_pass() -> None:
    # Skipping the comparison would let the drill report success while proving
    # only that the dump is self-consistent, not that it is production's data.
    with pytest.raises(RestoreDrillError, match="carries no manifest digest"):
        assert_manifest_matches(restored=DIGEST, expected=None)


def test_restored_database_missing_manifest_digest_fails() -> None:
    with pytest.raises(RestoreDrillError, match="records no manifest digest"):
        assert_manifest_matches(restored=None, expected=DIGEST)


def test_matching_manifest_digests_pass() -> None:
    # The assertion is that this does not raise.
    assert_manifest_matches(restored=DIGEST, expected=DIGEST)


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
        lambda *_args, **_kwargs: {"games": 1, "players": 1, "shot_attempts": 1},
    )

    # prove_servable is off because this test stubs the database out entirely;
    # the servability path is covered against a real restore below.
    restore_drill.run_restore_drill(
        backup,
        {"dbname": "nba_test_recovery", "host": "database", "user": "nba_user"},
        "2025-26",
        expected_manifest_sha256=DIGEST,
        prove_servable=False,
        runner=runner,
    )

    restore_command = commands[1]
    assert "--no-owner" in restore_command
    assert "--no-acl" in restore_command


@pytest.mark.skipif(
    shutil.which("pg_dump") is None or shutil.which("pg_restore") is None,
    reason="PostgreSQL client tools are not installed",
)
def test_real_backup_can_be_restored_verified_and_removed(client, tmp_path, monkeypatch) -> None:
    import psycopg

    from app.db import get_cursor

    del client
    config = get_db_config()
    recovery = {**config, "dbname": "nba_db_test_recovery"}
    backup = tmp_path / "nba-db-test.dump"
    # Roles are cluster-scoped, not per-database, so the drill's role setup would
    # otherwise reset the password of a real nba_readonly on this machine.
    drill_role = "nba_readonly_drill_test"
    monkeypatch.setenv("READONLY_DB_USER", drill_role)
    monkeypatch.setenv("READONLY_DB_PASSWORD", "drill-test-password")
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE seasons
            SET verification_status = 'passed', shot_attempts_count = 295,
                manifest_sha256 = %s
            WHERE id = %s
            """,
            (DIGEST, SEED_SEASON),
        )
    try:
        create_backup(config, backup)
        report = run_restore_drill(backup, recovery, SEED_SEASON, expected_manifest_sha256=DIGEST)
        assert report["games"] == 10
        assert report["players"] == 3
        assert report["shot_attempts"] == 295
        # The drill proved the restored database satisfies the same contract the
        # deployment healthcheck asserts, evaluated as the app's read-only role.
        assert report["readiness"]["status"] == "ready"
        assert report["readiness"]["counts"]["shot_attempts"] == 295
    finally:
        with get_cursor() as cur:
            cur.execute(
                """
                UPDATE seasons
                SET verification_status = 'untracked', shot_attempts_count = 0,
                    manifest_sha256 = NULL
                WHERE id = %s
                """,
                (SEED_SEASON,),
            )
        with psycopg.connect(**{**config, "dbname": "postgres"}, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'DROP ROLE IF EXISTS "{drill_role}"')


@pytest.mark.skipif(
    shutil.which("pg_dump") is None or shutil.which("pg_restore") is None,
    reason="PostgreSQL client tools are not installed",
)
def test_restore_drill_rejects_a_backup_from_a_different_dataset(
    client, tmp_path, monkeypatch
) -> None:
    """A dump whose manifest disagrees with production must not pass the drill."""
    from app.db import get_cursor

    del client
    config = get_db_config()
    recovery = {**config, "dbname": "nba_db_test_recovery"}
    backup = tmp_path / "nba-db-mismatch.dump"
    monkeypatch.setenv("READONLY_DB_PASSWORD", "drill-test-password")
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE seasons
            SET verification_status = 'passed', shot_attempts_count = 295,
                manifest_sha256 = %s
            WHERE id = %s
            """,
            (DIGEST, SEED_SEASON),
        )
    try:
        create_backup(config, backup)
        with pytest.raises(RestoreDrillError, match="does not match"):
            run_restore_drill(backup, recovery, SEED_SEASON, expected_manifest_sha256=OTHER_DIGEST)
    finally:
        with get_cursor() as cur:
            cur.execute(
                """
                UPDATE seasons
                SET verification_status = 'untracked', shot_attempts_count = 0,
                    manifest_sha256 = NULL
                WHERE id = %s
                """,
                (SEED_SEASON,),
            )
