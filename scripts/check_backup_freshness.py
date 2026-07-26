#!/usr/bin/env python3
"""Assert that a recent backup exists and was recently proven restorable.

This runs on its own schedule, separate from the job that creates backups. A
check that lives inside the backup job cannot report that the backup job stopped
running: it produces silence, and silence is indistinguishable from success.

The concern is observability rather than recovery-point objective. The dataset is
a frozen single-season snapshot mutated only by operator promotion, so an older
dump restores to the same content. What this defends against is the whole loop
stopping while every remaining signal still reads healthy.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
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
    backup_prefix,
    list_prefix_objects,
)

PROVEN_POINTER_NAME = "last-proven.json"

# The backup runs daily, so 36 hours tolerates exactly one missed run and alarms
# on two. The drill runs monthly, so 40 days tolerates one missed drill.
DEFAULT_MAX_AGE_HOURS = 36
DEFAULT_MAX_DRILL_AGE_DAYS = 40


def _read_proven_pointer(client: S3Client, bucket: str, prefix: str) -> dict[str, Any]:
    """Return the drill's proven-copy pointer, distinguishing absent from corrupt."""
    key = f"{prefix}{PROVEN_POINTER_NAME}"
    try:
        response = client.get_object(Bucket=bucket, Key=key)
        raw = response["Body"].read()
    except Exception as exc:  # noqa: BLE001 - any retrieval failure means "no pointer"
        raise ArtifactArchiveError(
            f"No backup has ever been proven restorable: {key} is absent ({exc})"
        ) from exc
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


def check_freshness(
    *,
    client: S3Client,
    bucket: str,
    season: str,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    max_drill_age_days: float = DEFAULT_MAX_DRILL_AGE_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fail unless a recent backup exists and a recent drill proved one restorable."""
    if max_age_hours <= 0 or max_drill_age_days <= 0:
        raise ArtifactArchiveError("Freshness bounds must be positive")
    current = now or datetime.now(UTC)
    prefix = backup_prefix(season)
    objects = list_prefix_objects(client, bucket, prefix)
    backups = [
        item
        for item in objects
        if str(item.get("Key", "")).startswith(prefix)
        and str(item.get("Key", "")).endswith(".dump")
        and isinstance(item.get("LastModified"), datetime)
    ]
    if not backups:
        raise ArtifactArchiveError(
            f"No backup exists for {season}. The backup schedule has produced nothing."
        )

    newest = max(backups, key=lambda item: item["LastModified"])
    backup_age_hours = (current - newest["LastModified"]).total_seconds() / 3600
    if backup_age_hours > max_age_hours:
        raise ArtifactArchiveError(
            f"Newest backup for {season} is {backup_age_hours:.1f}h old, "
            f"older than the maximum of {max_age_hours}h. "
            "The backup schedule has probably stopped running."
        )

    pointer = _read_proven_pointer(client, bucket, prefix)
    drill_age_days = (current - pointer["proven_at"]).total_seconds() / 86400
    if drill_age_days > max_drill_age_days:
        raise ArtifactArchiveError(
            f"Last restore drill proved a backup {drill_age_days:.1f} days ago, "
            f"older than the maximum of {max_drill_age_days} days. "
            "Retention may expire the last proven copy before the next drill runs."
        )

    return {
        "season": season,
        "newest_backup": str(newest["Key"]).removeprefix(prefix),
        "newest_backup_age_hours": backup_age_hours,
        "backup_count": len(backups),
        "last_proven_backup": str(pointer["key"]).removeprefix(prefix),
        "drill_age_days": drill_age_days,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS)
    parser.add_argument("--max-drill-age-days", type=float, default=DEFAULT_MAX_DRILL_AGE_DAYS)
    args = parser.parse_args()
    try:
        client, bucket = _s3_client()
        report = check_freshness(
            client=client,
            bucket=bucket,
            season=args.season,
            max_age_hours=args.max_age_hours,
            max_drill_age_days=args.max_drill_age_days,
        )
    except ArtifactArchiveError as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(
        f"Backup freshness OK: newest {report['newest_backup_age_hours']:.1f}h old, "
        f"last drill {report['drill_age_days']:.1f} days ago."
    )


if __name__ == "__main__":
    main()
