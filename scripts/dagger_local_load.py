#!/usr/bin/env python3
"""Load a manifested season into the explicitly bound Dagger-local database."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

import psycopg

from db.config import get_db_config
from etl.season_lifecycle import CLEAN_ROOT, replace_season, verify_manifest
from scripts.init_db import apply_schema


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if os.getenv("DB_HOST") != "database" or os.getenv("DATABASE_URL"):
        raise RuntimeError("Dagger local load requires the bound 'database' service and no URL")
    if not os.getenv("DAGGER_OPERATION_ID", "").strip():
        raise RuntimeError("DAGGER_OPERATION_ID is required for a mutating local load")
    if os.getenv("DAGGER_LOCAL_CONFIRMATION") != "LOCAL DOCKER DATABASE":
        raise RuntimeError("Dagger local load requires the typed local-target confirmation")

    dataset = verify_manifest(CLEAN_ROOT, args.season)
    with psycopg.connect(**get_db_config()) as conn:
        apply_schema(conn)
        replace_season(conn, dataset, single_season=True)
    print(f"Dagger-local database now contains only season {args.season}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
