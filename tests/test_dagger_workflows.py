"""Safety tests for host-mutating Dagger workflow helpers."""

from pathlib import Path

import pytest

from scripts import dagger_local_load

PROJECT_ROOT = Path(__file__).parents[1]


def test_dagger_local_load_requires_bound_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="bound 'database' service"):
        dagger_local_load.main(["--season", "2025-26"])


def test_dagger_local_load_requires_operation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_HOST", "database")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DAGGER_OPERATION_ID", raising=False)

    with pytest.raises(RuntimeError, match="DAGGER_OPERATION_ID"):
        dagger_local_load.main(["--season", "2025-26"])


def test_dagger_local_load_requires_typed_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DB_HOST", "database")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DAGGER_OPERATION_ID", "test-operation")
    monkeypatch.delenv("DAGGER_LOCAL_CONFIRMATION", raising=False)

    with pytest.raises(RuntimeError, match="typed local-target confirmation"):
        dagger_local_load.main(["--season", "2025-26"])


def test_dagger_exposes_isolated_real_backup_restore() -> None:
    dagger_module = (PROJECT_ROOT / ".dagger/src/nba_db_ci/main.py").read_text()

    assert "async def restore_backup(" in dagger_module
    assert '"RESTORE nba_db_recovery"' in dagger_module
    assert '"postgresql://nba_user:nba_password@database:5432/nba_db_recovery"' in dagger_module
