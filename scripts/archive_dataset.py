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

from nba_config import DEFAULT_SEASON  # noqa: E402

RAW_ROOT = PROJECT_ROOT / "data" / "raw"
CLEAN_ROOT = PROJECT_ROOT / "data" / "clean"


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

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]: ...

    def put_object(self, Bucket: str, Key: str, Body: bytes) -> dict[str, Any]: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


PROVEN_POINTER_NAME = "last-proven.json"


def backup_prefix(season: str) -> str:
    """Return the object-storage prefix holding a season's database backups."""
    return f"database-backups/{season}/"


def read_proven_pointer(client: S3Client, bucket: str, prefix: str) -> dict[str, Any] | None:
    """Return the drill's proven-copy pointer, or None when none has been written.

    Absent and corrupt are deliberately different answers. An absent pointer is a
    first run; a corrupt one is a fault, and callers that delete backups must
    stop rather than proceed without the protection it encodes.
    """
    key = f"{prefix}{PROVEN_POINTER_NAME}"
    try:
        raw = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception:  # noqa: BLE001 - any retrieval failure means "not written yet"
        return None
    try:
        pointer = json.loads(raw)
        proven_at = datetime.fromisoformat(str(pointer["proven_at"]))
        proved_key = str(pointer["key"])
    except (ValueError, TypeError, KeyError) as exc:
        raise ArtifactArchiveError(
            f"Proven-backup pointer is unreadable or malformed: {key} ({exc})"
        ) from exc
    if proven_at.tzinfo is None:
        proven_at = proven_at.replace(tzinfo=UTC)
    return {"key": proved_key, "proven_at": proven_at}


def write_proven_pointer(
    client: S3Client, bucket: str, prefix: str, *, key: str, proven_at: datetime
) -> str:
    """Record which backup a drill proved restorable, so retention can spare it."""
    pointer_key = f"{prefix}{PROVEN_POINTER_NAME}"
    body = json.dumps(
        {"key": key, "proven_at": proven_at.isoformat()}, indent=2, sort_keys=True
    ).encode()
    client.put_object(Bucket=bucket, Key=pointer_key, Body=body)
    return pointer_key


def list_prefix_objects(client: S3Client, bucket: str, prefix: str) -> list[dict[str, Any]]:
    """Return every object under a prefix, following continuation tokens.

    A truncated listing that omits its continuation token is treated as an error
    rather than a short result. Callers use these listings to decide what to keep
    and what to delete, and a silently partial view makes both decisions wrong.
    """
    objects: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        arguments: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token:
            arguments["ContinuationToken"] = token
        response = client.list_objects_v2(**arguments)
        objects.extend(response.get("Contents", []))
        if not response.get("IsTruncated"):
            return objects
        token = response.get("NextContinuationToken")
        if not token:
            raise ArtifactArchiveError("Backup listing was truncated without a continuation token")


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
    # Keep ETL-only numpy/pandas imports out of backup upload/download commands,
    # which intentionally run with the lightweight production + ops dependency set.
    from etl.season_lifecycle import verify_manifest

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
