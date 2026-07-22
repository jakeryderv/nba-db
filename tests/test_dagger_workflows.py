"""Safety tests for host-mutating Dagger workflow helpers."""

import pytest

from scripts import dagger_local_load


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
