#!/usr/bin/env python3
"""Cross-check a transformed regular season against official NBA aggregates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

REPORT_FILENAME = "verification.json"
REPORT_SCHEMA_VERSION = 1
PROVIDER = "stats.nba.com via nba_api"
SEASON_TYPE = "Regular Season"
TEAM_ENDPOINT = "LeagueDashTeamStats"
PLAYER_ENDPOINT = "LeagueDashPlayerStats"

TEAM_STATS = {
    "GP": "games_played",
    "W": "wins",
    "L": "losses",
    "PTS": "points",
    "REB": "rebounds",
    "AST": "assists",
    "STL": "steals",
    "BLK": "blocks",
    "TOV": "turnovers",
    "FGM": "fgm",
    "FGA": "fga",
    "FG3M": "fg3m",
    "FG3A": "fg3a",
    "FTM": "ftm",
    "FTA": "fta",
}
PLAYER_STATS = {
    "GP": "games_played",
    "PTS": "points",
    "REB": "rebounds",
    "AST": "assists",
    "STL": "steals",
    "BLK": "blocks",
    "TOV": "turnovers",
    "FGM": "fgm",
    "FGA": "fga",
    "FG3M": "fg3m",
    "FG3A": "fg3a",
    "FTM": "ftm",
    "FTA": "fta",
}
EXACT_STATS = {"games_played", "wins", "losses", "points"}


class OfficialVerificationError(RuntimeError):
    """Raised when official aggregates cannot validate the local dataset."""


def report_path(clean_root: Path, season: str) -> Path:
    return clean_root / season / REPORT_FILENAME


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataset_hashes(clean_root: Path, paths: Mapping[str, Path]) -> dict[str, str]:
    return {str(path.relative_to(clean_root)): _sha256(path) for path in paths.values()}


def fetch_official_aggregates(season: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch NBA-produced team and player totals. This is intentionally local-only."""
    try:
        from nba_api.stats.endpoints import leaguedashplayerstats, leaguedashteamstats

        common = {
            "season": season,
            "season_type_all_star": SEASON_TYPE,
            "per_mode_detailed": "Totals",
            "league_id_nullable": "00",
            "timeout": 60,
        }
        teams = leaguedashteamstats.LeagueDashTeamStats(**common).get_data_frames()[0]
        players = leaguedashplayerstats.LeagueDashPlayerStats(**common).get_data_frames()[0]
    except Exception as exc:
        raise OfficialVerificationError(
            "Could not fetch official NBA aggregate totals; no manifest was created"
        ) from exc
    return teams, players


def _local_team_totals(games: pd.DataFrame, team_stats: pd.DataFrame) -> pd.DataFrame:
    totals = (
        team_stats.groupby("team_id", as_index=False)
        .agg(
            games_played=("game_id", "nunique"),
            points=("points", "sum"),
            rebounds=("rebounds", "sum"),
            assists=("assists", "sum"),
            steals=("steals", "sum"),
            blocks=("blocks", "sum"),
            turnovers=("turnovers", "sum"),
            fgm=("fgm", "sum"),
            fga=("fga", "sum"),
            fg3m=("fg3m", "sum"),
            fg3a=("fg3a", "sum"),
            ftm=("ftm", "sum"),
            fta=("fta", "sum"),
        )
        .set_index("team_id")
    )
    wins: dict[int, int] = {int(team_id): 0 for team_id in totals.index}
    losses = wins.copy()
    for game in games.itertuples(index=False):
        home_id = int(cast(Any, game.home_team_id))
        away_id = int(cast(Any, game.away_team_id))
        winner, loser = (
            (home_id, away_id)
            if int(cast(Any, game.home_score)) > int(cast(Any, game.away_score))
            else (away_id, home_id)
        )
        wins[winner] = wins.get(winner, 0) + 1
        losses[loser] = losses.get(loser, 0) + 1
    totals["wins"] = pd.Series(wins)
    totals["losses"] = pd.Series(losses)
    return totals


def _local_player_totals(player_stats: pd.DataFrame) -> pd.DataFrame:
    played = player_stats[player_stats["minutes"].notna()]
    return (
        played.groupby("player_id", as_index=False)
        .agg(
            games_played=("game_id", "nunique"),
            points=("points", "sum"),
            rebounds=("rebounds", "sum"),
            assists=("assists", "sum"),
            steals=("steals", "sum"),
            blocks=("blocks", "sum"),
            turnovers=("turnovers", "sum"),
            fgm=("fgm", "sum"),
            fga=("fga", "sum"),
            fg3m=("fg3m", "sum"),
            fg3a=("fg3a", "sum"),
            ftm=("ftm", "sum"),
            fta=("fta", "sum"),
        )
        .set_index("player_id")
    )


def _official_totals(
    frame: pd.DataFrame,
    *,
    id_column: str,
    columns: Mapping[str, str],
) -> pd.DataFrame:
    required = {id_column, *columns}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise OfficialVerificationError(
            f"Official aggregate response is missing columns: {', '.join(missing)}"
        )
    official = frame[[id_column, *columns]].copy()
    for column in [id_column, *columns]:
        official[column] = pd.to_numeric(official[column], errors="coerce")
    if official.isna().any().any():
        raise OfficialVerificationError("Official aggregate response contains invalid totals")
    official = official[official["GP"] > 0]
    official[id_column] = official[id_column].astype("int64")
    if official[id_column].duplicated().any():
        raise OfficialVerificationError("Official aggregate response contains duplicate entities")
    return official.rename(columns=columns).set_index(id_column)


def _compare(
    local: pd.DataFrame,
    official: pd.DataFrame,
    *,
    entity: str,
    names: Mapping[int, str],
) -> dict[str, Any]:
    differences: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    ids = sorted({int(value) for value in local.index} | {int(value) for value in official.index})
    for entity_id in ids:
        if entity_id not in local.index:
            mismatches.append(
                {"id": entity_id, "name": names.get(entity_id), "issue": "missing_local"}
            )
            continue
        if entity_id not in official.index:
            mismatches.append(
                {"id": entity_id, "name": names.get(entity_id), "issue": "missing_official"}
            )
            continue
        for stat in local.columns:
            local_value = int(cast(Any, local.at[entity_id, stat]))
            official_value = int(cast(Any, official.at[entity_id, stat]))
            if local_value != official_value:
                tolerance = 0 if stat in EXACT_STATS else 1
                difference = {
                    "id": entity_id,
                    "name": names.get(entity_id),
                    "stat": stat,
                    "local": local_value,
                    "official": official_value,
                    "difference": local_value - official_value,
                    "tolerance": tolerance,
                }
                differences.append(difference)
                if abs(local_value - official_value) > tolerance:
                    mismatches.append(difference)
    return {
        "entity": entity,
        "checked": len(ids),
        "local_count": len(local),
        "official_count": len(official),
        "differences": differences,
        "mismatches": mismatches,
    }


def build_report(
    *,
    season: str,
    teams: pd.DataFrame,
    players: pd.DataFrame,
    games: pd.DataFrame,
    team_stats: pd.DataFrame,
    player_stats: pd.DataFrame,
    official_teams: pd.DataFrame,
    official_players: pd.DataFrame,
    hashes: Mapping[str, str],
) -> dict[str, Any]:
    local_teams = _local_team_totals(games, team_stats)
    local_players = _local_player_totals(player_stats)
    official_team_totals = _official_totals(official_teams, id_column="TEAM_ID", columns=TEAM_STATS)
    official_player_totals = _official_totals(
        official_players, id_column="PLAYER_ID", columns=PLAYER_STATS
    )
    team_names = {
        int(cast(Any, row.id)): str(row.full_name)
        for row in teams[["id", "full_name"]].itertuples(index=False)
    }
    player_names = {
        int(cast(Any, row.id)): str(row.full_name)
        for row in players[["id", "full_name"]].itertuples(index=False)
    }
    checks = {
        "teams": _compare(local_teams, official_team_totals, entity="teams", names=team_names),
        "players": _compare(
            local_players, official_player_totals, entity="players", names=player_names
        ),
    }
    difference_count = sum(len(check["differences"]) for check in checks.values())
    mismatch_count = sum(len(check["mismatches"]) for check in checks.values())
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "season": season,
        "season_type": SEASON_TYPE,
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": PROVIDER,
        "sources": [
            {"endpoint": TEAM_ENDPOINT, "per_mode": "Totals"},
            {"endpoint": PLAYER_ENDPOINT, "per_mode": "Totals"},
        ],
        "dataset_sha256": dict(hashes),
        "tolerance": {
            "games_records_points": 0,
            "other_counting_stats": 1,
            "reason": "NBA game-log and aggregate feeds can differ after one-count stat corrections",
        },
        "checks": checks,
        "difference_count": difference_count,
        "mismatch_count": mismatch_count,
        "status": "passed" if mismatch_count == 0 else "failed",
    }


def validate_report(
    report: Any,
    *,
    season: str,
    hashes: Mapping[str, str],
) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise OfficialVerificationError("Official verification report must be a JSON object")
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise OfficialVerificationError("Unsupported official verification report version")
    if report.get("season") != season or report.get("season_type") != SEASON_TYPE:
        raise OfficialVerificationError("Official verification season or scope does not match")
    if report.get("provider") != PROVIDER:
        raise OfficialVerificationError("Official verification provider does not match")
    if report.get("sources") != [
        {"endpoint": TEAM_ENDPOINT, "per_mode": "Totals"},
        {"endpoint": PLAYER_ENDPOINT, "per_mode": "Totals"},
    ]:
        raise OfficialVerificationError("Official verification sources do not match")
    if report.get("tolerance") != {
        "games_records_points": 0,
        "other_counting_stats": 1,
        "reason": "NBA game-log and aggregate feeds can differ after one-count stat corrections",
    }:
        raise OfficialVerificationError("Official verification tolerance policy does not match")
    if report.get("dataset_sha256") != dict(hashes):
        raise OfficialVerificationError("Official verification is stale for the transformed files")
    try:
        generated_at = datetime.fromisoformat(report["generated_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OfficialVerificationError("Official verification timestamp is invalid") from exc
    if generated_at.utcoffset() is None:
        raise OfficialVerificationError("Official verification timestamp must include a timezone")
    checks = report.get("checks")
    if not isinstance(checks, dict) or set(checks) != {"teams", "players"}:
        raise OfficialVerificationError("Official verification checks are incomplete")
    for name in ("teams", "players"):
        check = checks[name]
        if (
            not isinstance(check, dict)
            or not isinstance(check.get("checked"), int)
            or check["checked"] < 1
            or not isinstance(check.get("differences"), list)
            or check.get("mismatches") != []
        ):
            raise OfficialVerificationError(f"Official {name} aggregate verification failed")
    difference_count = sum(len(checks[name]["differences"]) for name in ("teams", "players"))
    if report.get("difference_count") != difference_count:
        raise OfficialVerificationError("Official verification difference count does not match")
    if report.get("mismatch_count") != 0 or report.get("status") != "passed":
        raise OfficialVerificationError("Official aggregate verification did not pass")
    return report


def load_valid_report(
    clean_root: Path,
    season: str,
    paths: Mapping[str, Path],
) -> dict[str, Any]:
    path = report_path(clean_root, season)
    if not path.is_file():
        raise OfficialVerificationError(f"Missing required official verification report: {path}")
    try:
        report = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise OfficialVerificationError("Official verification report is not valid JSON") from exc
    return validate_report(report, season=season, hashes=dataset_hashes(clean_root, paths))


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def run_verification(
    clean_root: Path,
    season: str,
    *,
    fetcher: Callable[[str], tuple[pd.DataFrame, pd.DataFrame]] = fetch_official_aggregates,
) -> dict[str, Any]:
    from etl.season_lifecycle import dataset_paths, load_validated_dataset

    dataset = load_validated_dataset(clean_root, season)
    paths = dataset_paths(clean_root, season)
    official_teams, official_players = fetcher(season)
    report = build_report(
        season=season,
        teams=dataset.teams,
        players=dataset.players,
        games=dataset.games,
        team_stats=dataset.team_stats,
        player_stats=dataset.player_stats,
        official_teams=official_teams,
        official_players=official_players,
        hashes=dataset_hashes(clean_root, paths),
    )
    write_report(report_path(clean_root, season), report)
    if report["status"] != "passed":
        raise OfficialVerificationError(
            f"Official aggregate verification found {report['mismatch_count']} mismatches; "
            f"see {report_path(clean_root, season)}"
        )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-root", type=Path, default=None)
    parser.add_argument("--season", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    from etl.season_lifecycle import CLEAN_ROOT, SeasonLifecycleError

    try:
        report = run_verification(args.clean_root or CLEAN_ROOT, args.season)
        print(
            f"Official NBA aggregates match {args.season}: "
            f"{report['checks']['teams']['checked']} teams, "
            f"{report['checks']['players']['checked']} players"
        )
        return 0
    except (OfficialVerificationError, SeasonLifecycleError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
