"""Verified dataset artifact packaging and upload behavior."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.archive_dataset import ArtifactArchiveError, archive_sources, upload_archive
from scripts.download_backup import latest_backup
from scripts.upload_backup import prune_backups, upload_backup


class FakeArchiveCheck:
    """Stand-in for subprocess.run inspecting the archive with pg_restore."""

    def __init__(self, returncode: int = 0, missing: bool = False, stderr: str = "") -> None:
        self.returncode = returncode
        self.missing = missing
        self.stderr = stderr
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **_kwargs) -> "FakeArchiveCheck":
        self.commands.append(command)
        if self.missing:
            raise FileNotFoundError("pg_restore")
        return self


class FakeS3:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, str, dict]] = []
        self.metadata: dict[str, str] = {}

    def upload_file(self, filename: str, bucket: str, key: str, ExtraArgs: dict) -> None:
        self.uploads.append((filename, bucket, key, ExtraArgs))
        if "Metadata" in ExtraArgs:
            self.metadata = ExtraArgs["Metadata"]

    def head_object(self, Bucket: str, Key: str) -> dict:
        return {"Metadata": self.metadata}


class FakeBackupStore(FakeS3):
    def __init__(self, objects: list[dict], payload: bytes = b"database backup") -> None:
        super().__init__()
        self.objects = objects
        self.payload = payload
        self.deleted: list[str] = []

    def list_objects_v2(self, **_kwargs) -> dict:
        return {"Contents": self.objects, "IsTruncated": False}

    def delete_object(self, Bucket: str, Key: str) -> dict:
        self.deleted.append(Key)
        return {}

    def download_file(self, _bucket: str, _key: str, filename: str) -> None:
        Path(filename).write_bytes(self.payload)


def test_archive_sources_require_raw_and_clean_season_and_shared_data(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    clean = tmp_path / "clean"
    for path in (raw / "2025-26", raw / "shared", clean / "2025-26", clean / "shared"):
        path.mkdir(parents=True)

    sources = archive_sources(raw, clean, "2025-26")

    assert [str(name) for _, name in sources] == [
        "data/raw/2025-26",
        "data/raw/shared",
        "data/clean/2025-26",
        "data/clean/shared",
    ]


def test_archive_sources_fail_closed_when_input_is_missing(tmp_path: Path) -> None:
    with pytest.raises(ArtifactArchiveError, match="Missing artifact source"):
        archive_sources(tmp_path / "raw", tmp_path / "clean", "2025-26")


def test_upload_verifies_archive_checksum_metadata(tmp_path: Path) -> None:
    archive = tmp_path / "dataset.tar.gz"
    receipt = tmp_path / "dataset.tar.gz.json"
    archive.write_bytes(b"archive")
    receipt.write_text("{}")
    client = FakeS3()
    metadata = {
        "season": "2025-26",
        "archive_path": str(archive),
        "receipt_path": str(receipt),
        "archive_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
    }

    location = upload_archive(metadata, client=client, bucket="nba-db-artifacts")

    assert location == "s3://nba-db-artifacts/verified-seasons/2025-26/dataset.tar.gz"
    assert len(client.uploads) == 2
    assert client.metadata == {"sha256": "a" * 64, "manifest": "b" * 64}


def test_upload_backup_uses_a_separate_retention_prefix(tmp_path: Path) -> None:
    backup = tmp_path / "production.dump"
    backup.write_bytes(b"database backup")
    client = FakeS3()
    archive_check = FakeArchiveCheck()

    receipt = upload_backup(
        backup,
        season="2025-26",
        manifest_sha256="b" * 64,
        client=client,
        bucket="nba-db-artifacts",
        runner=archive_check,
    )

    assert receipt["location"] == ("s3://nba-db-artifacts/database-backups/2025-26/production.dump")
    assert receipt["backup_bytes"] == len(b"database backup")
    assert client.metadata["manifest"] == "b" * 64
    assert archive_check.commands == [["pg_restore", "--list", str(backup)]]


def test_upload_backup_refuses_uninspectable_archive(tmp_path: Path) -> None:
    backup = tmp_path / "production.dump"
    backup.write_bytes(b"not a real archive")
    client = FakeS3()

    with pytest.raises(ArtifactArchiveError, match="failed pg_restore inspection"):
        upload_backup(
            backup,
            season="2025-26",
            manifest_sha256="b" * 64,
            client=client,
            bucket="nba-db-artifacts",
            runner=FakeArchiveCheck(returncode=1),
        )
    assert client.uploads == []


def test_upload_backup_requires_pg_restore(tmp_path: Path) -> None:
    backup = tmp_path / "production.dump"
    backup.write_bytes(b"database backup")
    client = FakeS3()

    with pytest.raises(ArtifactArchiveError, match="pg_restore is required"):
        upload_backup(
            backup,
            season="2025-26",
            manifest_sha256="b" * 64,
            client=client,
            bucket="nba-db-artifacts",
            runner=FakeArchiveCheck(missing=True),
        )
    assert client.uploads == []


def test_backup_retention_preserves_minimum_copies_and_deletes_expired_objects() -> None:
    now = datetime(2026, 7, 22, tzinfo=UTC)
    objects = [
        {
            "Key": f"database-backups/2025-26/backup-{index}.dump",
            "LastModified": now - timedelta(days=age),
        }
        for index, age in enumerate((1, 2, 10, 31, 60))
    ]
    client = FakeBackupStore(objects)

    deleted = prune_backups(
        client=client,
        bucket="nba-db-artifacts",
        season="2025-26",
        retention_days=30,
        minimum_copies=3,
        now=now,
    )

    assert deleted == [
        "database-backups/2025-26/backup-3.dump",
        "database-backups/2025-26/backup-4.dump",
    ]
    assert client.deleted == deleted


def test_latest_backup_download_verifies_checksum_metadata(tmp_path: Path) -> None:
    from scripts.archive_dataset import _sha256

    now = datetime(2026, 7, 22, tzinfo=UTC)
    payload = b"verified database backup"
    expected_file = tmp_path / "expected.dump"
    expected_file.write_bytes(payload)
    client = FakeBackupStore(
        [
            {
                "Key": "database-backups/2025-26/latest.dump",
                "LastModified": now,
            }
        ],
        payload=payload,
    )
    client.metadata = {"sha256": _sha256(expected_file), "manifest": "b" * 64}
    output = tmp_path / "downloaded.dump"

    result = latest_backup(
        client=client,
        bucket="nba-db-artifacts",
        season="2025-26",
        output_file=output,
    )

    assert output.read_bytes() == payload
    assert result["manifest_sha256"] == "b" * 64


def test_upload_backup_reports_why_inspection_failed(tmp_path: Path) -> None:
    """A validator too old to read the archive must not look like a bad backup.

    This is the failure that actually occurred: a PostgreSQL 16 client rejecting
    a v18 dump. Without pg_restore's own reason in the message, the alert reads
    as a corrupt backup and the investigation starts in the wrong place.
    """
    backup = tmp_path / "production.dump"
    backup.write_bytes(b"database backup")
    client = FakeS3()

    with pytest.raises(ArtifactArchiveError, match="unsupported version"):
        upload_backup(
            backup,
            season="2025-26",
            manifest_sha256="b" * 64,
            client=client,
            bucket="nba-db-artifacts",
            runner=FakeArchiveCheck(
                returncode=1,
                stderr="pg_restore: error: unsupported version (1.16) in file header\n",
            ),
        )
    assert client.uploads == []
