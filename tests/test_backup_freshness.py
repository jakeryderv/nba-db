"""Backup and drill freshness assertions made independently of the backup job."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts.archive_dataset import ArtifactArchiveError
from scripts.check_backup_freshness import (
    PROVEN_POINTER_NAME,
    check_freshness,
)

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
SEASON = "2025-26"
PREFIX = f"database-backups/{SEASON}/"


class FakeFreshnessStore:
    """Object store exposing a season's backups and an optional proven pointer."""

    def __init__(self, ages_hours: list[float], proven: dict | None = None) -> None:
        self.objects = [
            {
                "Key": f"{PREFIX}nba-db-production-{SEASON}-{index}.dump",
                "LastModified": NOW - timedelta(hours=age),
            }
            for index, age in enumerate(ages_hours)
        ]
        self.proven = proven

    def list_objects_v2(self, **_kwargs) -> dict:
        return {"Contents": self.objects, "IsTruncated": False}

    def get_object(self, Bucket: str, Key: str) -> dict:
        if self.proven is None or Key != f"{PREFIX}{PROVEN_POINTER_NAME}":
            raise LookupError("NoSuchKey")
        body = self.proven if isinstance(self.proven, bytes) else json.dumps(self.proven).encode()

        class _Body:
            @staticmethod
            def read() -> bytes:
                return body

        return {"Body": _Body()}


def _proven(age_days: float, key: str = f"{PREFIX}nba-db-production-{SEASON}-0.dump") -> dict:
    return {
        "key": key,
        "proven_at": (NOW - timedelta(days=age_days)).isoformat(),
        "season": SEASON,
    }


def test_recent_backup_and_recent_drill_pass() -> None:
    store = FakeFreshnessStore([2.0, 26.0], proven=_proven(3))
    report = check_freshness(
        client=store,
        bucket="bucket",
        season=SEASON,
        max_age_hours=36,
        max_drill_age_days=40,
        now=NOW,
    )
    assert report["newest_backup_age_hours"] == pytest.approx(2.0)
    assert report["drill_age_days"] == pytest.approx(3.0)


def test_stopped_backup_schedule_fails() -> None:
    store = FakeFreshnessStore([48.0, 72.0], proven=_proven(3))
    with pytest.raises(ArtifactArchiveError, match="older than the maximum"):
        check_freshness(
            client=store,
            bucket="bucket",
            season=SEASON,
            max_age_hours=36,
            max_drill_age_days=40,
            now=NOW,
        )


def test_single_missed_run_does_not_alarm() -> None:
    # The backup is daily, so a 36h bound tolerates exactly one skipped run.
    store = FakeFreshnessStore([30.0], proven=_proven(3))
    report = check_freshness(
        client=store,
        bucket="bucket",
        season=SEASON,
        max_age_hours=36,
        max_drill_age_days=40,
        now=NOW,
    )
    assert report["newest_backup_age_hours"] == pytest.approx(30.0)


def test_absent_backup_is_a_failure_not_an_empty_result() -> None:
    store = FakeFreshnessStore([], proven=_proven(3))
    with pytest.raises(ArtifactArchiveError, match="No backup exists"):
        check_freshness(
            client=store,
            bucket="bucket",
            season=SEASON,
            max_age_hours=36,
            max_drill_age_days=40,
            now=NOW,
        )


def test_stale_drill_fails() -> None:
    store = FakeFreshnessStore([2.0], proven=_proven(45))
    with pytest.raises(ArtifactArchiveError, match="drill"):
        check_freshness(
            client=store,
            bucket="bucket",
            season=SEASON,
            max_age_hours=36,
            max_drill_age_days=40,
            now=NOW,
        )


def test_missing_proven_pointer_fails() -> None:
    store = FakeFreshnessStore([2.0], proven=None)
    with pytest.raises(ArtifactArchiveError, match="ever been proven restorable"):
        check_freshness(
            client=store,
            bucket="bucket",
            season=SEASON,
            max_age_hours=36,
            max_drill_age_days=40,
            now=NOW,
        )


def test_malformed_proven_pointer_fails_closed() -> None:
    store = FakeFreshnessStore([2.0], proven=b"{not json")
    with pytest.raises(ArtifactArchiveError, match="unreadable|malformed"):
        check_freshness(
            client=store,
            bucket="bucket",
            season=SEASON,
            max_age_hours=36,
            max_drill_age_days=40,
            now=NOW,
        )


def test_freshness_check_does_not_depend_on_the_backup_job() -> None:
    """The check must not be satisfiable by the upload path having run.

    Importing the uploader would let a refactor route freshness through the very
    job whose silence it exists to detect.
    """
    import scripts.check_backup_freshness as module

    source = module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    assert "upload_backup" not in text
