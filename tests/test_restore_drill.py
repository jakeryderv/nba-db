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
        check_data_quality=False,
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
    import psycopg

    from app.db import get_cursor

    del client
    config = get_db_config()
    recovery = {**config, "dbname": "nba_db_test_recovery"}
    backup = tmp_path / "nba-db-test.dump"
    # Roles are cluster-scoped, not per-database, so the drill uses a disposable
    # name rather than resetting a real nba_readonly on this machine.
    #
    # Passed as arguments, never through os.environ. Setting READONLY_DB_* here
    # would make get_db_config resolve readonly credentials, and any pool built
    # in this process while that held would cache them permanently -- surviving
    # monkeypatch teardown and breaking every later test once this test drops
    # the role.
    drill_role = "nba_readonly_drill_test"
    drill_password = "drill-test-password"
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
        # The seed fixture holds two teams and ten games, so the data-quality
        # checks correctly reject it; they are exercised against real data by the
        # scheduled drill instead.
        report = run_restore_drill(
            backup,
            recovery,
            SEED_SEASON,
            expected_manifest_sha256=DIGEST,
            check_data_quality=False,
            readonly_role=drill_role,
            readonly_password=drill_password,
        )
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
def test_restore_drill_rejects_a_backup_from_a_different_dataset(client, tmp_path) -> None:
    """A dump whose manifest disagrees with production must not pass the drill."""
    from app.db import get_cursor

    del client
    config = get_db_config()
    recovery = {**config, "dbname": "nba_db_test_recovery"}
    backup = tmp_path / "nba-db-mismatch.dump"
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
            run_restore_drill(
                backup,
                recovery,
                SEED_SEASON,
                expected_manifest_sha256=OTHER_DIGEST,
                check_data_quality=False,
                readonly_password="drill-test-password",
            )
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


def test_data_quality_failure_fails_the_drill() -> None:
    """A restored dataset that fails its checks must not report a passing drill."""
    from scripts import restore_drill

    class Result:
        returncode = 1
        stdout = "db/tests/test_data_quality.py::test_teams_not_empty FAILED\n1 failed"
        stderr = ""

    with pytest.raises(RestoreDrillError, match="failed quality checks"):
        restore_drill.verify_restored_data_quality(
            {"dbname": "nba_db_recovery", "host": "database", "user": "nba_user"},
            "2025-26",
            runner=lambda *_args, **_kwargs: Result(),
        )


def test_data_quality_runs_against_the_restored_database_not_the_ambient_one() -> None:
    """The checks must be pointed at the recovery database the drill just made.

    Inheriting an ambient DATABASE_URL would quietly validate whatever database
    the operator happened to have configured, and report it as the backup's.
    """
    from scripts import restore_drill

    captured: dict = {}

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def runner(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs.get("env", {})
        return Result()

    restore_drill.verify_restored_data_quality(
        {"dbname": "nba_db_recovery", "host": "database", "user": "nba_user"},
        "2025-26",
        runner=runner,
    )

    assert "nba_db_recovery" in captured["env"]["DATABASE_URL"]
    assert captured["env"]["DATA_QUALITY_SEASON"] == "2025-26"
    assert any("db/tests" in str(part) for part in captured["command"])


def test_the_drill_does_not_reach_for_readonly_credentials_in_the_environment() -> None:
    """Drill credentials must be arguments, not process-wide state.

    A pool built anywhere in the process while READONLY_DB_USER/PASSWORD are
    temporarily set captures those credentials in its conninfo for the pool's
    lifetime. Restoring the environment does not undo that, so once the drill
    drops its disposable role every later request through that pool fails to
    authenticate. The symptom appears far from the cause, in unrelated tests.
    """
    import inspect

    from scripts import restore_drill

    for function in (
        restore_drill.prepare_restored_database,
        restore_drill.verify_restored_database_can_serve,
    ):
        source = inspect.getsource(function)
        assert "READONLY_DB_PASSWORD" not in source, f"{function.__name__} reads the environment"
        assert "READONLY_DB_USER" not in source, f"{function.__name__} reads the environment"
        parameters = inspect.signature(function).parameters
        assert "readonly_role" in parameters and "readonly_password" in parameters


def test_ensure_readonly_role_accepts_explicit_credentials() -> None:
    """The CLI may still read the environment; callers must not have to."""
    import inspect

    from scripts.init_db import ensure_readonly_role

    parameters = inspect.signature(ensure_readonly_role).parameters
    assert "role" in parameters and "password" in parameters
