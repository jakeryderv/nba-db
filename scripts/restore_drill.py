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
from psycopg.rows import dict_row

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.readiness import evaluate_readiness  # noqa: E402
from nba_config import DEFAULT_SEASON  # noqa: E402
from scripts.init_db import apply_schema, ensure_readonly_role  # noqa: E402


class RestoreDrillError(RuntimeError):
    """Raised when a restore drill is unsafe or the restored data is invalid."""


def assert_manifest_matches(*, restored: str | None, expected: str | None) -> None:
    """Require the restored dataset to be the one the backup object claims.

    Reconciling counts against the restored database's own provenance columns
    proves the dump is internally consistent; it cannot detect a dump that is
    consistently wrong. The uploader stamps the manifest digest on every object
    precisely so this comparison can tie the artifact to the dataset production
    serves, and skipping it when metadata is absent would defeat the point.
    """
    if not expected:
        raise RestoreDrillError(
            "Backup carries no manifest digest; cannot prove it matches production data"
        )
    if not restored:
        raise RestoreDrillError("Restored database records no manifest digest")
    if restored != expected:
        raise RestoreDrillError(
            f"Restored manifest does not match the backup's recorded digest: "
            f"{restored} != {expected}"
        )


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


def verify_restored_database(
    config: dict[str, Any],
    season: str,
    *,
    expected_manifest_sha256: str | None = None,
) -> dict[str, int]:
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
        cur.execute("SELECT manifest_sha256 FROM seasons WHERE id = %s", (season,))
        manifest_row = cur.fetchone()
        restored_manifest = str(manifest_row[0]) if manifest_row and manifest_row[0] else None
    assert_manifest_matches(restored=restored_manifest, expected=expected_manifest_sha256)
    return {"games": games, "players": players, "shot_attempts": shots}


def prepare_restored_database(config: dict[str, Any]) -> None:
    """Run the same boot path production runs, against the restored database.

    railway.toml's startCommand runs init_db on every boot, so this is what
    actually stands between a restored dump and a serving instance: pending
    migrations get applied and the read-only role and its grants are recreated.
    A drill that skips it proves the data arrived, not that the database can be
    brought up.
    """
    if not os.getenv("READONLY_DB_PASSWORD"):
        raise RestoreDrillError(
            "READONLY_DB_PASSWORD must be set so the drill can prove the "
            "least-privilege role is recreated on the restored database"
        )
    with psycopg.connect(**config) as conn:
        apply_schema(conn)
        ensure_readonly_role(conn)


def verify_restored_database_can_serve(config: dict[str, Any], season: str) -> dict[str, Any]:
    """Assert the readiness contract against the restored database as the app's role.

    Evaluating readiness through nba_readonly proves two things at once: that the
    restored database satisfies the contract the deployment healthcheck asserts,
    and that the least-privilege role the app actually connects as can read it.
    Checking as the superuser would prove neither.
    """
    role = os.getenv("READONLY_DB_USER", "nba_readonly")
    readonly_config = {
        **config,
        "user": role,
        "password": os.environ["READONLY_DB_PASSWORD"],
    }
    with psycopg.connect(**readonly_config, row_factory=dict_row) as conn, conn.cursor() as cur:
        payload = evaluate_readiness(cur, season)
    if payload is None:
        raise RestoreDrillError(
            "Restored database does not satisfy the readiness contract; "
            "it would not be given traffic by the platform healthcheck"
        )
    return payload


def run_restore_drill(
    backup_file: Path,
    config: dict[str, Any],
    season: str,
    *,
    expected_manifest_sha256: str | None = None,
    prove_servable: bool = True,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
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
        # Same reasoning as upload_backup: distinguish an unreadable archive
        # from a validator too old to read it.
        detail = (archive_check.stderr or "").strip().splitlines()
        reason = detail[-1].strip() if detail else "pg_restore gave no reason"
        raise RestoreDrillError(f"Backup archive could not be inspected: {reason}")
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
                "--no-acl",
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
        counts = verify_restored_database(
            config, season, expected_manifest_sha256=expected_manifest_sha256
        )
        report: dict[str, Any] = {**counts, "manifest_sha256": expected_manifest_sha256}
        if prove_servable:
            prepare_restored_database(config)
            report["readiness"] = verify_restored_database_can_serve(config, season)
        return report
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
    parser.add_argument(
        "--manifest-sha256",
        required=True,
        help="Manifest digest recorded on the backup object, compared against the restored data",
    )
    args = parser.parse_args()
    database_url = os.getenv("RECOVERY_DATABASE_URL")
    if not database_url:
        parser.error("export RECOVERY_DATABASE_URL")
    config = recovery_config(database_url, args.confirm)
    try:
        report = run_restore_drill(
            args.backup_file,
            config,
            args.season,
            expected_manifest_sha256=args.manifest_sha256,
        )
    except RestoreDrillError as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    readiness = report.get("readiness", {})
    print(
        f"Restore drill passed and disposable database removed: {args.season} · "
        f"{report['games']} games · {report['shot_attempts']} shots · "
        f"manifest {args.manifest_sha256[:12]} · "
        f"readiness {readiness.get('status', 'unproven')} as the app's read-only role"
    )


if __name__ == "__main__":
    main()
