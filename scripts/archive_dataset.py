#!/usr/bin/env python3
"""Package and optionally upload one verified season dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from etl.season_lifecycle import CLEAN_ROOT, verify_manifest  # noqa: E402
from nba_config import DEFAULT_SEASON  # noqa: E402

RAW_ROOT = PROJECT_ROOT / "data" / "raw"


class ArtifactArchiveError(RuntimeError):
    """Raised when a verified artifact cannot be safely archived or uploaded."""


class S3Client(Protocol):
    def upload_file(
        self, filename: str, bucket: str, key: str, ExtraArgs: dict[str, Any]
    ) -> Any: ...

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]: ...

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]: ...

    def delete_object(self, Bucket: str, Key: str) -> dict[str, Any]: ...

    def download_file(self, bucket: str, key: str, filename: str) -> Any: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_sources(raw_root: Path, clean_root: Path, season: str) -> list[tuple[Path, Path]]:
    """Return required source paths and their stable archive names."""
    sources = [
        (raw_root / season, Path("data/raw") / season),
        (raw_root / "shared", Path("data/raw/shared")),
        (clean_root / season, Path("data/clean") / season),
        (clean_root / "shared", Path("data/clean/shared")),
    ]
    missing = [str(path) for path, _ in sources if not path.is_dir()]
    if missing:
        raise ArtifactArchiveError(f"Missing artifact source directories: {', '.join(missing)}")
    return sources


def create_archive(
    *,
    season: str,
    output_dir: Path,
    raw_root: Path = RAW_ROOT,
    clean_root: Path = CLEAN_ROOT,
) -> dict[str, Any]:
    """Validate and package raw inputs plus clean verified outputs."""
    dataset = verify_manifest(clean_root, season)
    if not output_dir.is_dir():
        raise ArtifactArchiveError("Artifact output directory must already exist")
    if output_dir.resolve().is_relative_to(PROJECT_ROOT):
        raise ArtifactArchiveError("Artifact output directory must be outside the repository")

    manifest_prefix = str(dataset.manifest_sha256)[:12]
    archive = output_dir / f"nba-db-{season}-{manifest_prefix}.tar.gz"
    receipt = archive.with_suffix(archive.suffix + ".json")
    checksum_file = archive.with_suffix(archive.suffix + ".sha256")
    for target in (archive, receipt, checksum_file):
        if target.exists():
            raise ArtifactArchiveError(f"Refusing to overwrite existing artifact: {target}")

    with tarfile.open(archive, "w:gz", compresslevel=6) as bundle:
        for source, archive_name in archive_sources(raw_root, clean_root, season):
            bundle.add(source, arcname=archive_name, recursive=True)

    checksum = _sha256(archive)
    metadata = {
        "schema_version": 1,
        "season": season,
        "created_at": datetime.now(UTC).isoformat(),
        "archive": archive.name,
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": checksum,
        "manifest_sha256": dataset.manifest_sha256,
        "counts": dataset.counts,
        "contents": [str(name) for _, name in archive_sources(raw_root, clean_root, season)],
    }
    checksum_file.write_text(f"{checksum}  {archive.name}\n")
    receipt.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    return {**metadata, "archive_path": str(archive), "receipt_path": str(receipt)}


def _s3_client() -> tuple[S3Client, str]:
    required = {
        "endpoint_url": os.getenv("AWS_ENDPOINT_URL"),
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "region_name": os.getenv("AWS_DEFAULT_REGION"),
    }
    bucket = os.getenv("AWS_S3_BUCKET_NAME")
    missing = [
        name for name, value in {**required, "AWS_S3_BUCKET_NAME": bucket}.items() if not value
    ]
    if missing:
        raise ArtifactArchiveError(f"Missing object-storage configuration: {', '.join(missing)}")
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise ArtifactArchiveError("Install the ops extra to upload artifacts") from exc
    addressing_style = os.getenv("AWS_S3_URL_STYLE", "path")
    if addressing_style == "virtual-host":
        addressing_style = "virtual"
    client = boto3.client(
        "s3",
        **required,
        config=Config(s3={"addressing_style": addressing_style}),
    )
    return client, str(bucket)


def upload_archive(
    metadata: dict[str, Any], client: S3Client | None = None, bucket: str | None = None
) -> str:
    """Upload an archive and receipt, then verify stored checksum metadata."""
    if client is None or bucket is None:
        client, bucket = _s3_client()
    archive = Path(metadata["archive_path"])
    receipt = Path(metadata["receipt_path"])
    prefix = f"verified-seasons/{metadata['season']}"
    archive_key = f"{prefix}/{archive.name}"
    receipt_key = f"{prefix}/{receipt.name}"
    extra = {
        "Metadata": {"sha256": metadata["archive_sha256"], "manifest": metadata["manifest_sha256"]}
    }
    client.upload_file(str(archive), bucket, archive_key, ExtraArgs=extra)
    client.upload_file(
        str(receipt), bucket, receipt_key, ExtraArgs={"ContentType": "application/json"}
    )
    stored = client.head_object(Bucket=bucket, Key=archive_key)
    if stored.get("Metadata", {}).get("sha256") != metadata["archive_sha256"]:
        raise ArtifactArchiveError("Uploaded archive checksum metadata did not verify")
    return f"s3://{bucket}/{archive_key}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()
    try:
        metadata = create_archive(season=args.season, output_dir=args.output_dir)
        location = upload_archive(metadata) if args.upload else metadata["archive_path"]
    except ArtifactArchiveError as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    print(
        f"Archived verified {metadata['season']} dataset: {location} ({metadata['archive_sha256']})"
    )


if __name__ == "__main__":
    main()
