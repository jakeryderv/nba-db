#!/usr/bin/env python3
"""Record which backup a restore drill proved restorable.

Retention is measured in days and the drill runs monthly, so without this the
only artifact ever demonstrated to work can expire on roughly the cadence of the
check that demonstrated it. The pruner reads this pointer and spares that key.

This runs after the drill rather than inside it: the drill executes in an
isolated container with no object-storage credentials, which is the correct place
for it to stay.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nba_config import DEFAULT_SEASON  # noqa: E402
from scripts.archive_dataset import (  # noqa: E402
    ArtifactArchiveError,
    _s3_client,
    backup_prefix,
    write_proven_pointer,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument(
        "--key",
        required=True,
        help="Object key of the backup the drill just proved restorable",
    )
    args = parser.parse_args()
    prefix = backup_prefix(args.season)
    if not args.key.startswith(prefix) or not args.key.endswith(".dump"):
        parser.exit(2, f"ERROR: key must be a .dump under {prefix}\n")
    try:
        client, bucket = _s3_client()
        pointer_key = write_proven_pointer(
            client, bucket, prefix, key=args.key, proven_at=datetime.now(UTC)
        )
    except ArtifactArchiveError as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    print(f"Recorded proven backup {args.key} at s3://{bucket}/{pointer_key}")


if __name__ == "__main__":
    main()
