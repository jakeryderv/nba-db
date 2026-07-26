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


class FakeRetentionStore:
    """Backup store with a proven-copy pointer, for retention decisions."""

    def __init__(self, ages_days: list[float], pointer: object = None) -> None:
        self.objects = [
            {
                "Key": f"{PREFIX}backup-{index}.dump",
                "LastModified": NOW - timedelta(days=age),
            }
            for index, age in enumerate(ages_days)
        ]
        self.pointer = pointer
        self.deleted: list[str] = []

    def list_objects_v2(self, **_kwargs) -> dict:
        return {"Contents": self.objects, "IsTruncated": False}

    def delete_object(self, Bucket: str, Key: str) -> dict:
        self.deleted.append(Key)
        return {}

    def get_object(self, Bucket: str, Key: str) -> dict:
        if self.pointer is None:
            raise LookupError("NoSuchKey")
        body = (
            self.pointer if isinstance(self.pointer, bytes) else json.dumps(self.pointer).encode()
        )

        class _Body:
            @staticmethod
            def read() -> bytes:
                return body

        return {"Body": _Body()}


def test_retention_preserves_the_last_proven_copy() -> None:
    from scripts.upload_backup import prune_backups

    # Ten daily backups; the only drill-proven copy is the oldest, well past the
    # retention window. Keeping the newest N does not save it -- recency is not
    # evidence.
    store = FakeRetentionStore(
        [float(day) for day in range(10)] + [45.0],
        pointer={"key": f"{PREFIX}backup-10.dump", "proven_at": NOW.isoformat()},
    )
    deleted = prune_backups(
        client=store,
        bucket="bucket",
        season=SEASON,
        retention_days=30,
        minimum_copies=7,
        now=NOW,
    )
    assert f"{PREFIX}backup-10.dump" not in deleted
    assert f"{PREFIX}backup-10.dump" not in store.deleted


def test_retention_still_prunes_expired_unproven_copies() -> None:
    from scripts.upload_backup import prune_backups

    store = FakeRetentionStore(
        [float(day) for day in range(7)] + [40.0, 50.0],
        pointer={"key": f"{PREFIX}backup-0.dump", "proven_at": NOW.isoformat()},
    )
    deleted = prune_backups(
        client=store,
        bucket="bucket",
        season=SEASON,
        retention_days=30,
        minimum_copies=7,
        now=NOW,
    )
    assert f"{PREFIX}backup-7.dump" in deleted
    assert f"{PREFIX}backup-8.dump" in deleted


def test_retention_fails_closed_on_an_unreadable_pointer() -> None:
    from scripts.upload_backup import prune_backups

    store = FakeRetentionStore([float(day) for day in range(10)] + [45.0], pointer=b"{bad json")
    with pytest.raises(ArtifactArchiveError, match="unreadable|malformed"):
        prune_backups(
            client=store,
            bucket="bucket",
            season=SEASON,
            retention_days=30,
            minimum_copies=7,
            now=NOW,
        )
    # Deleting is the irreversible direction, so nothing may be removed.
    assert store.deleted == []


def test_retention_proceeds_when_no_copy_has_been_proven_yet() -> None:
    """An absent pointer is a first run, not a corrupt one."""
    from scripts.upload_backup import prune_backups

    store = FakeRetentionStore([float(day) for day in range(7)] + [45.0], pointer=None)
    deleted = prune_backups(
        client=store,
        bucket="bucket",
        season=SEASON,
        retention_days=30,
        minimum_copies=7,
        now=NOW,
    )
    assert f"{PREFIX}backup-7.dump" in deleted


def test_proven_pointer_is_not_itself_prunable() -> None:
    """The pointer must survive retention; it is not a .dump."""
    from scripts.upload_backup import prune_backups

    store = FakeRetentionStore([float(day) for day in range(7)] + [45.0], pointer=None)
    store.objects.append(
        {"Key": f"{PREFIX}{PROVEN_POINTER_NAME}", "LastModified": NOW - timedelta(days=90)}
    )
    prune_backups(
        client=store,
        bucket="bucket",
        season=SEASON,
        retention_days=30,
        minimum_copies=7,
        now=NOW,
    )
    assert f"{PREFIX}{PROVEN_POINTER_NAME}" not in store.deleted


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
