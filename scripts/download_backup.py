#!/usr/bin/env python3
"""Download and checksum-verify the newest retained database backup."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
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


def latest_backup(
    *, client: S3Client, bucket: str, season: str, output_file: Path
) -> dict[str, str | int]:
    """Download the newest custom-format backup and verify its stored checksum."""
    if output_file.exists() or output_file.suffix != ".dump":
        raise ArtifactArchiveError("Output must be a new .dump file")
    if not output_file.parent.is_dir():
        raise ArtifactArchiveError("Backup output directory must already exist")
    prefix = f"database-backups/{season}/"
    objects: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        arguments: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token:
            arguments["ContinuationToken"] = token
        response = client.list_objects_v2(**arguments)
        objects.extend(response.get("Contents", []))
        if not response.get("IsTruncated"):
            break
        token = response.get("NextContinuationToken")
        if not token:
            raise ArtifactArchiveError("Backup listing was truncated without a continuation token")
    backups = [
        item
        for item in objects
        if str(item.get("Key", "")).startswith(prefix)
        and str(item.get("Key", "")).endswith(".dump")
        and isinstance(item.get("LastModified"), datetime)
    ]
    if not backups:
        raise ArtifactArchiveError(f"No retained backup exists for {season}")
    newest = max(backups, key=lambda item: item["LastModified"])
    key = str(newest["Key"])
    metadata = client.head_object(Bucket=bucket, Key=key).get("Metadata", {})
    expected_checksum = str(metadata.get("sha256", ""))
    manifest_sha256 = str(metadata.get("manifest", ""))
    if not SHA256.fullmatch(expected_checksum) or not SHA256.fullmatch(manifest_sha256):
        raise ArtifactArchiveError("Latest backup is missing verified checksum metadata")
    client.download_file(bucket, key, str(output_file))
    actual_checksum = _sha256(output_file)
    if actual_checksum != expected_checksum:
        output_file.unlink(missing_ok=True)
        raise ArtifactArchiveError("Downloaded backup checksum did not verify")
    return {
        "location": f"s3://{bucket}/{key}",
        "backup_file": str(output_file),
        "backup_bytes": output_file.stat().st_size,
        "backup_sha256": actual_checksum,
        "manifest_sha256": manifest_sha256,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--output-file", required=True, type=Path)
    args = parser.parse_args()
    try:
        client, bucket = _s3_client()
        result = latest_backup(
            client=client,
            bucket=bucket,
            season=args.season,
            output_file=args.output_file,
        )
    except ArtifactArchiveError as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    print(f"Downloaded verified backup: {result['location']} ({result['backup_sha256']})")


if __name__ == "__main__":
    main()
