#!/usr/bin/env python3
"""Upload and verify a protected PostgreSQL backup in object storage."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from etl.season_lifecycle import CLEAN_ROOT, verify_manifest  # noqa: E402
from nba_config import DEFAULT_SEASON  # noqa: E402
from scripts.archive_dataset import (  # noqa: E402
    ArtifactArchiveError,
    S3Client,
    _s3_client,
    _sha256,
)


def upload_backup(
    backup: Path,
    *,
    season: str,
    manifest_sha256: str,
    client: S3Client,
    bucket: str,
) -> dict[str, str | int]:
    """Upload a regular custom-format backup and verify its checksum metadata."""
    if not backup.is_file() or backup.is_symlink() or backup.suffix != ".dump":
        raise ArtifactArchiveError("Backup must be a regular non-symlink .dump file")
    checksum = _sha256(backup)
    key = f"database-backups/{season}/{backup.name}"
    metadata = {"sha256": checksum, "manifest": manifest_sha256}
    client.upload_file(str(backup), bucket, key, ExtraArgs={"Metadata": metadata})
    stored = client.head_object(Bucket=bucket, Key=key)
    if stored.get("Metadata", {}).get("sha256") != checksum:
        raise ArtifactArchiveError("Uploaded backup checksum metadata did not verify")
    return {
        "season": season,
        "created_at": datetime.now(UTC).isoformat(),
        "backup": backup.name,
        "backup_bytes": backup.stat().st_size,
        "backup_sha256": checksum,
        "manifest_sha256": manifest_sha256,
        "location": f"s3://{bucket}/{key}",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-file", required=True, type=Path)
    parser.add_argument("--season", default=DEFAULT_SEASON)
    args = parser.parse_args()
    try:
        dataset = verify_manifest(CLEAN_ROOT, args.season)
        client, bucket = _s3_client()
        receipt = upload_backup(
            args.backup_file,
            season=args.season,
            manifest_sha256=str(dataset.manifest_sha256),
            client=client,
            bucket=bucket,
        )
    except ArtifactArchiveError as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    receipt_path = args.backup_file.with_suffix(args.backup_file.suffix + ".json")
    if receipt_path.exists():
        parser.exit(2, f"ERROR: refusing to overwrite receipt: {receipt_path}\n")
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(f"Uploaded verified backup: {receipt['location']} ({receipt['backup_sha256']})")


if __name__ == "__main__":
    main()
