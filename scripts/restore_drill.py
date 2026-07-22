#!/usr/bin/env python3
"""Restore a custom-format backup into a disposable recovery database and verify it."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nba_config import DEFAULT_SEASON  # noqa: E402


class RestoreDrillError(RuntimeError):
    """Raised when a restore drill is unsafe or the restored data is invalid."""


def recovery_config(database_url: str, confirmation: str) -> dict[str, Any]:
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise RestoreDrillError("RECOVERY_DATABASE_URL must be a PostgreSQL URL")
    config: dict[str, Any] = conninfo_to_dict(database_url)
    dbname = str(config.get("dbname", ""))
    if not re.fullmatch(r"[A-Za-z0-9_]+_recovery", dbname):
        raise RestoreDrillError("Recovery database name must end in _recovery")
    if confirmation != f"RESTORE {dbname}":
        raise RestoreDrillError(f"Type --confirm 'RESTORE {dbname}'")
    production_url = os.getenv("PRODUCTION_DATABASE_URL")
    if production_url and make_conninfo("", **config) == make_conninfo(
        "", **conninfo_to_dict(production_url)
    ):
        raise RestoreDrillError("Recovery and production database URLs must be distinct")
    return config


def _client_environment(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    safe = {key: value for key, value in config.items() if key not in {"password", "sslpassword"}}
    environment = os.environ.copy()
    for key in ("DATABASE_URL", "PRODUCTION_DATABASE_URL", "RECOVERY_DATABASE_URL"):
        environment.pop(key, None)
    if config.get("password") is not None:
        environment["PGPASSWORD"] = str(config["password"])
    if config.get("sslpassword") is not None:
        environment["PGSSLPASSWORD"] = str(config["sslpassword"])
    return safe, environment


def verify_restored_database(config: dict[str, Any], season: str) -> dict[str, int]:
    with psycopg.connect(**config) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, verification_status FROM seasons ORDER BY id")
        seasons = cur.fetchall()
        if seasons != [(season, "passed")]:
            raise RestoreDrillError("Restored database does not contain one verified season")
        cur.execute(
            """
            SELECT (SELECT COUNT(*) FROM games WHERE season = %s),
                   (SELECT COUNT(DISTINCT player_id)
                    FROM player_game_stats WHERE season = %s),
                   (SELECT COUNT(*) FROM shot_attempts WHERE season = %s),
                   (SELECT games_count FROM seasons WHERE id = %s),
                   (SELECT players_count FROM seasons WHERE id = %s),
                   (SELECT shot_attempts_count FROM seasons WHERE id = %s)
            """,
            (season, season, season, season, season, season),
        )
        row = cur.fetchone()
        if row is None:
            raise RestoreDrillError("Restored count query returned no row")
        live_games, live_players, live_shots, games, players, shots = row
        if (live_games, live_players, live_shots) != (games, players, shots):
            raise RestoreDrillError("Restored row counts do not match provenance metadata")
        if not games or not players or not shots:
            raise RestoreDrillError("Restored product dataset is empty")
        return {"games": games, "players": players, "shot_attempts": shots}


def run_restore_drill(
    backup_file: Path,
    config: dict[str, Any],
    season: str,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, int]:
    if not backup_file.is_file() or backup_file.is_symlink():
        raise RestoreDrillError("Backup must be an existing regular non-symlink file")
    dbname = str(config["dbname"])
    maintenance_config = {**config, "dbname": "postgres"}
    created = False
    safe, environment = _client_environment(config)
    archive_check = runner(
        ["pg_restore", "--list", str(backup_file)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if archive_check.returncode != 0:
        raise RestoreDrillError("Backup archive could not be inspected")
    try:
        with psycopg.connect(**maintenance_config, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
                if cur.fetchone():
                    raise RestoreDrillError(
                        "Recovery database already exists; refusing to overwrite"
                    )
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
                created = True
        restore = runner(
            [
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--dbname",
                make_conninfo("", **safe),
                str(backup_file),
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if restore.returncode != 0:
            raise RestoreDrillError("Backup restore failed")
        return verify_restored_database(config, season)
    finally:
        if created:
            with psycopg.connect(**maintenance_config, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = %s AND pid <> pg_backend_pid()",
                        (dbname,),
                    )
                    cur.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(dbname)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-file", required=True, type=Path)
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    database_url = os.getenv("RECOVERY_DATABASE_URL")
    if not database_url:
        parser.error("export RECOVERY_DATABASE_URL")
    config = recovery_config(database_url, args.confirm)
    counts = run_restore_drill(args.backup_file, config, args.season)
    print(
        f"Restore drill passed and disposable database removed: {args.season} · "
        f"{counts['games']} games · {counts['shot_attempts']} shots"
    )


if __name__ == "__main__":
    main()
