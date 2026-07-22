#!/usr/bin/env python3
"""Upload and verify a protected PostgreSQL backup in object storage."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nba_config import DEFAULT_SEASON  # noqa: E402
from scripts.archive_dataset import (  # noqa: E402
    ArtifactArchiveError,
    S3Client,
    _s3_client,
    _sha256,
)

SHA256 = re.compile(r"[0-9a-f]{64}")


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


def prune_backups(
    *,
    client: S3Client,
    bucket: str,
    season: str,
    retention_days: int,
    minimum_copies: int = 7,
    now: datetime | None = None,
) -> list[str]:
    """Delete expired backup objects while always preserving the newest copies."""
    if retention_days <= 0:
        raise ArtifactArchiveError("Backup retention days must be positive")
    if minimum_copies <= 0:
        raise ArtifactArchiveError("Minimum backup copies must be positive")
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(days=retention_days)
    prefix = f"database-backups/{season}/"
    objects: list[dict[str, Any]] = []
    continuation_token: str | None = None
    while True:
        arguments: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if continuation_token:
            arguments["ContinuationToken"] = continuation_token
        response = client.list_objects_v2(**arguments)
        objects.extend(response.get("Contents", []))
        if not response.get("IsTruncated"):
            break
        continuation_token = response.get("NextContinuationToken")
        if not continuation_token:
            raise ArtifactArchiveError("Backup listing was truncated without a continuation token")

    candidates = sorted(objects, key=lambda item: item["LastModified"], reverse=True)
    deleted: list[str] = []
    for item in candidates[minimum_copies:]:
        modified = item.get("LastModified")
        key = str(item.get("Key", ""))
        if not isinstance(modified, datetime) or not key.startswith(prefix):
            raise ArtifactArchiveError("Object storage returned invalid backup metadata")
        if modified < cutoff:
            client.delete_object(Bucket=bucket, Key=key)
            deleted.append(key)
    return deleted


def _manifest_sha256(season: str, supplied: str | None) -> str:
    if supplied is not None:
        if not SHA256.fullmatch(supplied):
            raise ArtifactArchiveError(
                "Manifest SHA-256 must be 64 lowercase hexadecimal characters"
            )
        return supplied
    from etl.season_lifecycle import CLEAN_ROOT, verify_manifest

    dataset = verify_manifest(CLEAN_ROOT, season)
    return str(dataset.manifest_sha256)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-file", required=True, type=Path)
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--retention-days", type=int)
    parser.add_argument("--minimum-copies", type=int, default=7)
    args = parser.parse_args()
    receipt_path = args.backup_file.with_suffix(args.backup_file.suffix + ".json")
    if receipt_path.exists():
        parser.exit(2, f"ERROR: refusing to overwrite receipt: {receipt_path}\n")
    try:
        manifest_sha256 = _manifest_sha256(args.season, args.manifest_sha256)
        client, bucket = _s3_client()
        receipt = upload_backup(
            args.backup_file,
            season=args.season,
            manifest_sha256=manifest_sha256,
            client=client,
            bucket=bucket,
        )
        if args.retention_days is not None:
            receipt["pruned_objects"] = len(
                prune_backups(
                    client=client,
                    bucket=bucket,
                    season=args.season,
                    retention_days=args.retention_days,
                    minimum_copies=args.minimum_copies,
                )
            )
    except ArtifactArchiveError as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(f"Uploaded verified backup: {receipt['location']} ({receipt['backup_sha256']})")


if __name__ == "__main__":
    main()
