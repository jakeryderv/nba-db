"""Verified dataset artifact packaging and upload behavior."""

from pathlib import Path

import pytest

from scripts.archive_dataset import ArtifactArchiveError, archive_sources, upload_archive
from scripts.upload_backup import upload_backup


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

    receipt = upload_backup(
        backup,
        season="2025-26",
        manifest_sha256="b" * 64,
        client=client,
        bucket="nba-db-artifacts",
    )

    assert receipt["location"] == ("s3://nba-db-artifacts/database-backups/2025-26/production.dump")
    assert receipt["backup_bytes"] == len(b"database backup")
    assert client.metadata["manifest"] == "b" * 64
