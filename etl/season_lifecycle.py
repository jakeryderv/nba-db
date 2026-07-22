#!/usr/bin/env python3
"""Build, validate, replace, and promote one regular-season dataset safely."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import psycopg
import requests  # type: ignore[import-untyped, unused-ignore]
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from db.config import get_db_config
from scripts.init_db import apply_schema

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLEAN_ROOT = PROJECT_ROOT / "data" / "clean"
MANIFEST_FILENAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = 3
SEASON_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")
GAME_ID_PATTERN = re.compile(r"^002\d{7}$")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

TEAM_COLUMNS = [
    "id",
    "full_name",
    "abbreviation",
    "nickname",
    "city",
    "state",
    "year_founded",
]
PLAYER_COLUMNS = ["id", "full_name", "first_name", "last_name", "is_active"]
GAME_COLUMNS = [
    "id",
    "game_date",
    "season",
    "home_team_id",
    "away_team_id",
    "home_score",
    "away_score",
]
TEAM_STATS_COLUMNS = [
    "game_id",
    "team_id",
    "season",
    "is_home",
    "minutes",
    "points",
    "rebounds",
    "offensive_rebounds",
    "defensive_rebounds",
    "assists",
    "steals",
    "blocks",
    "turnovers",
    "personal_fouls",
    "fgm",
    "fga",
    "fg_pct",
    "fg3m",
    "fg3a",
    "fg3_pct",
    "ftm",
    "fta",
    "ft_pct",
    "plus_minus",
]
PLAYER_STATS_COLUMNS = [
    "game_id",
    "player_id",
    "team_id",
    "season",
    "minutes",
    "points",
    "rebounds",
    "offensive_rebounds",
    "defensive_rebounds",
    "assists",
    "steals",
    "blocks",
    "turnovers",
    "personal_fouls",
    "fgm",
    "fga",
    "fg_pct",
    "fg3m",
    "fg3a",
    "fg3_pct",
    "ftm",
    "fta",
    "ft_pct",
    "plus_minus",
]
SHOT_COLUMNS = [
    "game_id",
    "event_id",
    "player_id",
    "team_id",
    "season",
    "period",
    "minutes_remaining",
    "seconds_remaining",
    "action_type",
    "shot_type",
    "zone_basic",
    "zone_area",
    "zone_range",
    "shot_distance",
    "loc_x",
    "loc_y",
    "shot_made",
]
COUNTING_STATS_COLUMNS = [
    "points",
    "rebounds",
    "offensive_rebounds",
    "defensive_rebounds",
    "assists",
    "steals",
    "blocks",
    "turnovers",
    "personal_fouls",
    "fgm",
    "fga",
    "fg3m",
    "fg3a",
    "ftm",
    "fta",
]
PERCENTAGE_COLUMNS = ["fg_pct", "fg3_pct", "ft_pct"]


class SeasonLifecycleError(RuntimeError):
    """Base error for a fail-closed season operation."""


class DatasetValidationError(SeasonLifecycleError):
    """Raised when transformed files do not form a valid season dataset."""


class ManifestVerificationError(SeasonLifecycleError):
    """Raised when a manifest is missing, malformed, or stale."""


class PromotionSafetyError(SeasonLifecycleError):
    """Raised before production access when a promotion guard is not satisfied."""


@dataclass(frozen=True)
class SeasonDataset:
    season: str
    teams: pd.DataFrame
    players: pd.DataFrame
    games: pd.DataFrame
    team_stats: pd.DataFrame
    player_stats: pd.DataFrame
    shots: pd.DataFrame
    manifest: dict[str, Any] | None = None
    manifest_sha256: str | None = None

    @property
    def counts(self) -> dict[str, int]:
        return {
            "teams": len(self.teams),
            "players": len(self.players),
            "games": len(self.games),
            "team_game_stats": len(self.team_stats),
            "player_game_stats": len(self.player_stats),
            "shot_attempts": len(self.shots),
        }

    @property
    def participating_players_count(self) -> int:
        """Players who appeared in the season, distinct from the shared catalog size."""
        return int(self.player_stats["player_id"].nunique())


def validate_season_name(season: str) -> None:
    match = SEASON_PATTERN.fullmatch(season)
    if not match:
        raise DatasetValidationError(f"Invalid season {season!r}; expected YYYY-YY")
    start, suffix = int(match.group(1)), int(match.group(2))
    if suffix != (start + 1) % 100:
        raise DatasetValidationError(f"Season {season!r} does not end in the following year")


def dataset_paths(clean_root: Path, season: str) -> dict[str, Path]:
    return {
        "teams": clean_root / "shared" / "teams.csv",
        "players": clean_root / "shared" / "players.csv",
        "games": clean_root / season / "games.csv",
        "team_game_stats": clean_root / season / "team_game_stats.csv",
        "player_game_stats": clean_root / season / "player_game_stats.csv",
        "shot_attempts": clean_root / season / "shot_attempts.csv",
    }


def manifest_path(clean_root: Path, season: str) -> Path:
    return clean_root / season / MANIFEST_FILENAME


def _read_csv(path: Path, game_id_column: str | None = None) -> pd.DataFrame:
    dtype: dict[Any, Any] | None = {game_id_column: "string"} if game_id_column else None
    try:
        return pd.read_csv(path, dtype=dtype)
    except (OSError, UnicodeError, ValueError, pd.errors.ParserError) as exc:
        raise DatasetValidationError(f"Could not parse {path.name} as CSV") from exc


def _check_columns(name: str, frame: pd.DataFrame, required: Sequence[str]) -> list[str]:
    missing = sorted(set(required) - set(frame.columns))
    return [f"{name}.csv is missing columns: {', '.join(missing)}"] if missing else []


def _duplicates(frame: pd.DataFrame, columns: list[str]) -> bool:
    return bool(frame.duplicated(columns, keep=False).any())


def _normalize_boolean_column(frame: pd.DataFrame, column: str, filename: str) -> None:
    def parse(value: Any) -> bool:
        normalized = str(value).strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
        raise DatasetValidationError(f"{filename}.{column} contains a non-boolean value")

    frame[column] = frame[column].map(parse)


def _normalize_numeric_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    filename: str,
    *,
    integral: bool = False,
    minimum: float | None = None,
    maximum: float | None = None,
    allow_null: bool = False,
) -> None:
    for column in columns:
        original = frame[column]
        try:
            parsed = pd.to_numeric(original, errors="coerce")
        except (TypeError, ValueError) as exc:
            raise DatasetValidationError(f"{filename}.{column} is not numeric") from exc
        parse_failures = original.notna() & parsed.isna()
        if parse_failures.any() or (not allow_null and parsed.isna().any()):
            raise DatasetValidationError(f"{filename}.{column} must contain finite numeric values")
        present = parsed.dropna()
        values = present.to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise DatasetValidationError(f"{filename}.{column} must contain finite numeric values")
        if integral and not np.equal(values, np.trunc(values)).all():
            raise DatasetValidationError(f"{filename}.{column} must contain integral values")
        if minimum is not None and (values < minimum).any():
            raise DatasetValidationError(f"{filename}.{column} must be at least {minimum:g}")
        if maximum is not None and (values > maximum).any():
            raise DatasetValidationError(f"{filename}.{column} must be at most {maximum:g}")
        try:
            if integral:
                frame[column] = parsed.astype("Int64" if allow_null else "int64")
            else:
                frame[column] = parsed.astype(float)
        except (OverflowError, TypeError, ValueError) as exc:
            raise DatasetValidationError(
                f"{filename}.{column} is outside the supported range"
            ) from exc


def _normalize_numerics(
    teams: pd.DataFrame,
    players: pd.DataFrame,
    games: pd.DataFrame,
    team_stats: pd.DataFrame,
    player_stats: pd.DataFrame,
    shots: pd.DataFrame,
) -> None:
    _normalize_numeric_columns(teams, ["id"], "teams.csv", integral=True, minimum=1)
    _normalize_numeric_columns(
        teams, ["year_founded"], "teams.csv", integral=True, minimum=1800, maximum=3000
    )
    _normalize_numeric_columns(players, ["id"], "players.csv", integral=True, minimum=1)
    _normalize_numeric_columns(
        games,
        ["home_team_id", "away_team_id"],
        "games.csv",
        integral=True,
        minimum=1,
    )
    _normalize_numeric_columns(
        games,
        ["home_score", "away_score"],
        "games.csv",
        integral=True,
        minimum=0,
    )
    _normalize_numeric_columns(
        team_stats, ["team_id"], "team_game_stats.csv", integral=True, minimum=1
    )
    _normalize_numeric_columns(
        player_stats,
        ["player_id", "team_id"],
        "player_game_stats.csv",
        integral=True,
        minimum=1,
    )
    _normalize_numeric_columns(
        team_stats,
        COUNTING_STATS_COLUMNS,
        "team_game_stats.csv",
        integral=True,
        minimum=0,
        maximum=400,
    )
    _normalize_numeric_columns(
        team_stats,
        ["minutes"],
        "team_game_stats.csv",
        integral=True,
        minimum=0,
        maximum=400,
        allow_null=True,
    )
    _normalize_numeric_columns(
        player_stats,
        COUNTING_STATS_COLUMNS,
        "player_game_stats.csv",
        integral=True,
        minimum=0,
    )
    _normalize_numeric_columns(
        player_stats,
        ["minutes"],
        "player_game_stats.csv",
        minimum=0,
        maximum=400,
        allow_null=True,
    )
    _normalize_numeric_columns(
        team_stats,
        PERCENTAGE_COLUMNS,
        "team_game_stats.csv",
        minimum=0,
        maximum=1,
        allow_null=True,
    )
    _normalize_numeric_columns(
        player_stats,
        PERCENTAGE_COLUMNS,
        "player_game_stats.csv",
        minimum=0,
        maximum=1,
        allow_null=True,
    )
    _normalize_numeric_columns(team_stats, ["plus_minus"], "team_game_stats.csv", allow_null=True)
    _normalize_numeric_columns(
        player_stats, ["plus_minus"], "player_game_stats.csv", allow_null=True
    )
    _normalize_numeric_columns(
        shots,
        ["event_id", "player_id", "team_id", "period"],
        "shot_attempts.csv",
        integral=True,
        minimum=1,
    )
    _normalize_numeric_columns(
        shots,
        ["minutes_remaining"],
        "shot_attempts.csv",
        integral=True,
        minimum=0,
        maximum=12,
    )
    _normalize_numeric_columns(
        shots,
        ["seconds_remaining"],
        "shot_attempts.csv",
        integral=True,
        minimum=0,
        maximum=59,
    )
    _normalize_numeric_columns(
        shots,
        ["shot_distance"],
        "shot_attempts.csv",
        integral=True,
        minimum=0,
        maximum=100,
    )
    _normalize_numeric_columns(shots, ["loc_x", "loc_y"], "shot_attempts.csv", integral=True)
    if (shots["period"] > 20).any():
        raise DatasetValidationError("shot_attempts.csv.period must be at most 20")
    if (shots["loc_x"].abs() > 400).any() or not shots["loc_y"].between(-100, 1000).all():
        raise DatasetValidationError("shot_attempts.csv contains coordinates outside the court")
    for filename, frame in (
        ("team_game_stats.csv", team_stats),
        ("player_game_stats.csv", player_stats),
    ):
        for makes, attempts in (("fgm", "fga"), ("fg3m", "fg3a"), ("ftm", "fta")):
            if (frame[makes] > frame[attempts]).any():
                raise DatasetValidationError(f"{filename}.{makes} cannot exceed {attempts}")


def _shot_total_comparison(dataset: SeasonDataset) -> pd.DataFrame:
    expected = dataset.player_stats[
        ["game_id", "player_id", "team_id", "fga", "fgm", "fg3a", "fg3m"]
    ].copy()
    shot_totals = dataset.shots.assign(
        fg3a=dataset.shots["shot_type"].eq("3PT Field Goal").astype(int),
        fg3m=(dataset.shots["shot_type"].eq("3PT Field Goal") & dataset.shots["shot_made"]).astype(
            int
        ),
    )
    actual = shot_totals.groupby(["game_id", "player_id"], as_index=False).agg(
        team_id=("team_id", "first"),
        fga=("event_id", "size"),
        fgm=("shot_made", "sum"),
        fg3a=("fg3a", "sum"),
        fg3m=("fg3m", "sum"),
    )
    comparison = expected.merge(
        actual,
        on=["game_id", "player_id"],
        how="outer",
        suffixes=("_stats", "_shots"),
    )
    no_attempts = comparison["team_id_stats"].notna() & comparison["team_id_shots"].isna()
    comparison.loc[no_attempts, "team_id_shots"] = comparison.loc[no_attempts, "team_id_stats"]
    comparison.loc[no_attempts, ["fga_shots", "fgm_shots", "fg3a_shots", "fg3m_shots"]] = 0
    return comparison.fillna(-1)


def shot_verification_summary(dataset: SeasonDataset) -> dict[str, Any]:
    """Describe accepted one-attempt source corrections for the manifest."""
    comparison = _shot_total_comparison(dataset)
    differences = []
    for row in comparison.itertuples(index=False):
        for stat_name in ("fga", "fg3a"):
            box_score = int(getattr(row, f"{stat_name}_stats"))
            shots = int(getattr(row, f"{stat_name}_shots"))
            if box_score != shots:
                differences.append(
                    {
                        "game_id": str(row.game_id),
                        "player_id": int(str(row.player_id)),
                        "team_id": int(str(row.team_id_stats)),
                        "stat": stat_name,
                        "box_score": box_score,
                        "shots": shots,
                        "difference": shots - box_score,
                        "tolerance": 1,
                    }
                )
    return {
        "status": "passed",
        "policy": "makes and team identity exact; attempt corrections differ by at most one",
        "difference_count": len(differences),
        "differences": differences,
    }


def _validate_relations(dataset: SeasonDataset) -> list[str]:
    errors: list[str] = []
    teams = set(dataset.teams["id"])
    players = set(dataset.players["id"])
    games = set(dataset.games["id"])

    if _duplicates(dataset.teams, ["id"]):
        errors.append("teams.csv contains duplicate id values")
    if _duplicates(dataset.players, ["id"]):
        errors.append("players.csv contains duplicate id values")
    if _duplicates(dataset.games, ["id"]):
        errors.append("games.csv contains duplicate id values")
    if _duplicates(dataset.team_stats, ["game_id", "team_id"]):
        errors.append("team_game_stats.csv contains duplicate (game_id, team_id) keys")
    if _duplicates(dataset.player_stats, ["game_id", "player_id"]):
        errors.append("player_game_stats.csv contains duplicate (game_id, player_id) keys")
    if _duplicates(dataset.shots, ["game_id", "event_id"]):
        errors.append("shot_attempts.csv contains duplicate (game_id, event_id) keys")

    for name, frame, column in (
        ("games.csv", dataset.games, "season"),
        ("team_game_stats.csv", dataset.team_stats, "season"),
        ("player_game_stats.csv", dataset.player_stats, "season"),
        ("shot_attempts.csv", dataset.shots, "season"),
    ):
        seasons = set(frame[column].dropna().astype(str))
        if seasons != {dataset.season}:
            errors.append(f"{name} must contain only season {dataset.season}")

    for name, values in (
        ("games.id", dataset.games["id"]),
        ("team_game_stats.game_id", dataset.team_stats["game_id"]),
        ("player_game_stats.game_id", dataset.player_stats["game_id"]),
        ("shot_attempts.game_id", dataset.shots["game_id"]),
    ):
        invalid = [value for value in values.astype(str) if not GAME_ID_PATTERN.fullmatch(value)]
        if invalid:
            errors.append(f"{name} contains IDs outside the official 002 regular-season format")

    if dataset.games["id"].isna().any() or dataset.games["game_date"].isna().any():
        errors.append("games.csv contains null game IDs or dates")
    if (dataset.games["home_team_id"] == dataset.games["away_team_id"]).any():
        errors.append("games.csv contains a game with the same home and away team")
    game_team_ids = set(dataset.games["home_team_id"]) | set(dataset.games["away_team_id"])
    if not game_team_ids <= teams:
        errors.append("games.csv references teams absent from teams.csv")
    if not set(dataset.team_stats["game_id"]) <= games:
        errors.append("team_game_stats.csv references games absent from games.csv")
    if not set(dataset.team_stats["team_id"]) <= teams:
        errors.append("team_game_stats.csv references teams absent from teams.csv")
    if not set(dataset.player_stats["game_id"]) <= games:
        errors.append("player_game_stats.csv references games absent from games.csv")
    if not set(dataset.player_stats["team_id"]) <= teams:
        errors.append("player_game_stats.csv references teams absent from teams.csv")
    if not set(dataset.player_stats["player_id"]) <= players:
        errors.append("player_game_stats.csv references players absent from players.csv")
    if not set(dataset.shots["game_id"]) <= games:
        errors.append("shot_attempts.csv references games absent from games.csv")
    if not set(dataset.shots["team_id"]) <= teams:
        errors.append("shot_attempts.csv references teams absent from teams.csv")
    if not set(dataset.shots["player_id"]) <= players:
        errors.append("shot_attempts.csv references players absent from players.csv")

    game_rows = dataset.games.set_index("id")
    grouped_teams = dataset.team_stats.groupby("game_id")
    if set(grouped_teams.groups) != games:
        errors.append("every game must have team statistics")
    for game_id, game in game_rows.iterrows():
        if game_id not in grouped_teams.groups:
            continue
        rows = grouped_teams.get_group(game_id)
        expected = {game["home_team_id"], game["away_team_id"]}
        if len(rows) != 2 or set(rows["team_id"]) != expected:
            errors.append(f"game {game_id} must have exactly its two participating team rows")
            continue
        home = rows[rows["team_id"] == game["home_team_id"]].iloc[0]
        away = rows[rows["team_id"] == game["away_team_id"]].iloc[0]
        standard_home_flags = bool(home["is_home"]) and not bool(away["is_home"])
        neutral_site_flags = not bool(home["is_home"]) and not bool(away["is_home"])
        if not (standard_home_flags or neutral_site_flags):
            errors.append(f"game {game_id} has incorrect is_home team flags")
        if int(home["points"]) != int(game["home_score"]) or int(away["points"]) != int(
            game["away_score"]
        ):
            errors.append(f"game {game_id} scores do not match team statistics")

    participants = {
        game_id: {row["home_team_id"], row["away_team_id"]} for game_id, row in game_rows.iterrows()
    }
    invalid_player_team = any(
        row.team_id not in participants.get(row.game_id, set())
        for row in dataset.player_stats[["game_id", "team_id"]].itertuples(index=False)
    )
    if invalid_player_team:
        errors.append("player_game_stats.csv contains a team that did not play in its game")
    invalid_shot_team = any(
        row.team_id not in participants.get(row.game_id, set())
        for row in dataset.shots[["game_id", "team_id"]].itertuples(index=False)
    )
    if invalid_shot_team:
        errors.append("shot_attempts.csv contains a team that did not play in its game")
    grouped_players = dataset.player_stats.groupby("game_id")
    if set(grouped_players.groups) != games:
        errors.append("every game must have player statistics")
    for game_id, expected_teams in participants.items():
        if (
            game_id in grouped_players.groups
            and set(grouped_players.get_group(game_id)["team_id"]) != expected_teams
        ):
            errors.append(f"game {game_id} must have player statistics for both teams")

    shot_team_counts = dataset.shots.groupby(["game_id", "player_id"])["team_id"].nunique()
    if (shot_team_counts > 1).any():
        errors.append("shot_attempts.csv assigns one player to multiple teams in a game")
    comparison = _shot_total_comparison(dataset)
    fatal = comparison[
        (comparison["team_id_stats"] != comparison["team_id_shots"])
        | (comparison["fgm_stats"] != comparison["fgm_shots"])
        | (comparison["fg3m_stats"] != comparison["fg3m_shots"])
        | ((comparison["fga_stats"] - comparison["fga_shots"]).abs() > 1)
        | ((comparison["fg3a_stats"] - comparison["fg3a_shots"]).abs() > 1)
    ]
    if not fatal.empty:
        errors.append(
            "shot_attempts.csv totals exceed the correction policy for "
            f"{len(fatal)} player-game rows"
        )
    return errors


def load_validated_dataset(clean_root: Path, season: str) -> SeasonDataset:
    """Read all required files and validate their full relational contract."""
    validate_season_name(season)
    paths = dataset_paths(clean_root, season)
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise DatasetValidationError("Missing required transformed files: " + ", ".join(missing))

    teams = _read_csv(paths["teams"])
    players = _read_csv(paths["players"])
    games = _read_csv(paths["games"], "id")
    team_stats = _read_csv(paths["team_game_stats"], "game_id")
    player_stats = _read_csv(paths["player_game_stats"], "game_id")
    shots = _read_csv(paths["shot_attempts"], "game_id")
    frames = {
        "teams": (teams, TEAM_COLUMNS),
        "players": (players, PLAYER_COLUMNS),
        "games": (games, GAME_COLUMNS),
        "team_game_stats": (team_stats, TEAM_STATS_COLUMNS),
        "player_game_stats": (player_stats, PLAYER_STATS_COLUMNS),
        "shot_attempts": (shots, SHOT_COLUMNS),
    }
    errors: list[str] = []
    for name, (frame, columns) in frames.items():
        if frame.empty:
            errors.append(f"{name}.csv must not be empty")
        errors.extend(_check_columns(name, frame, columns))
    if errors:
        raise DatasetValidationError("; ".join(errors))

    required_non_null = {
        "teams": (teams, TEAM_COLUMNS),
        "players": (players, ["id", "full_name", "is_active"]),
        "games": (games, GAME_COLUMNS),
        "team_game_stats": (
            team_stats,
            ["game_id", "team_id", "season", "is_home", "points"],
        ),
        "player_game_stats": (
            player_stats,
            ["game_id", "player_id", "team_id", "season", "points"],
        ),
        "shot_attempts": (shots, SHOT_COLUMNS),
    }
    null_errors = [
        f"{name}.csv contains null required values"
        for name, (frame, columns) in required_non_null.items()
        if frame[columns].isna().any().any()
    ]
    if null_errors:
        raise DatasetValidationError("; ".join(null_errors))
    _normalize_boolean_column(players, "is_active", "players.csv")
    _normalize_boolean_column(team_stats, "is_home", "team_game_stats.csv")
    _normalize_boolean_column(shots, "shot_made", "shot_attempts.csv")
    _normalize_numerics(teams, players, games, team_stats, player_stats, shots)

    if not shots["shot_type"].isin({"2PT Field Goal", "3PT Field Goal"}).all():
        raise DatasetValidationError("shot_attempts.csv contains an unsupported shot_type")
    for column in ("action_type", "shot_type", "zone_basic", "zone_area", "zone_range"):
        if shots[column].astype(str).str.strip().eq("").any():
            raise DatasetValidationError(f"shot_attempts.csv.{column} must not be empty")

    games = games[GAME_COLUMNS].copy()
    games["game_date"] = pd.to_datetime(games["game_date"], errors="coerce").dt.date
    dataset = SeasonDataset(
        season=season,
        teams=teams[TEAM_COLUMNS],
        players=players[PLAYER_COLUMNS],
        games=games,
        team_stats=team_stats[TEAM_STATS_COLUMNS],
        player_stats=player_stats[PLAYER_STATS_COLUMNS],
        shots=shots[SHOT_COLUMNS],
    )
    errors = _validate_relations(dataset)
    if errors:
        raise DatasetValidationError("; ".join(errors[:20]))
    return dataset


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_manifest(clean_root: Path, season: str) -> dict[str, Any]:
    from etl.official_verification import (
        OfficialVerificationError,
        load_valid_report,
        report_path,
    )

    dataset = load_validated_dataset(clean_root, season)
    paths = dataset_paths(clean_root, season)
    try:
        verification_report = load_valid_report(clean_root, season, paths)
    except OfficialVerificationError as exc:
        raise ManifestVerificationError(str(exc)) from exc
    verification_file = report_path(clean_root, season)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "season": season,
        "season_type": "Regular Season",
        "generated_at": datetime.now(UTC).isoformat(),
        "source": {
            "provider": "stats.nba.com via nba_api",
            "league_id": "00",
            "season": season,
            "season_type": "Regular Season",
            "game_log_scopes": ["teams", "players"],
            "shot_chart_scope": "all-teams",
        },
        "counts": dataset.counts,
        "files": {
            str(path.relative_to(clean_root)): {
                "sha256": _sha256(path),
                "rows": dataset.counts[name],
            }
            for name, path in paths.items()
        },
        "official_verification": {
            "path": str(verification_file.relative_to(clean_root)),
            "sha256": _sha256(verification_file),
            "status": verification_report["status"],
            "provider": verification_report["provider"],
            "generated_at": verification_report["generated_at"],
        },
        "shot_verification": shot_verification_summary(dataset),
    }
    output = manifest_path(clean_root, season)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, output)
    return manifest


def verify_manifest(clean_root: Path, season: str) -> SeasonDataset:
    from etl.official_verification import (
        OfficialVerificationError,
        load_valid_report,
        report_path,
    )

    path = manifest_path(clean_root, season)
    if not path.is_file():
        raise ManifestVerificationError(f"Missing required manifest: {path}")
    try:
        manifest = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise ManifestVerificationError("Season manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise ManifestVerificationError("Season manifest must be a JSON object")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ManifestVerificationError("Unsupported manifest schema version")
    if manifest.get("season") != season or manifest.get("season_type") != "Regular Season":
        raise ManifestVerificationError("Manifest season or season type does not match")
    try:
        generated_at = datetime.fromisoformat(manifest["generated_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ManifestVerificationError("Manifest generation timestamp is invalid") from exc
    if generated_at.utcoffset() is None:
        raise ManifestVerificationError("Manifest generation timestamp must include a timezone")
    source = manifest.get("source")
    if (
        not isinstance(source, dict)
        or source.get("provider") != "stats.nba.com via nba_api"
        or source.get("league_id") != "00"
        or source.get("season") != season
        or source.get("season_type") != "Regular Season"
        or source.get("game_log_scopes") != ["teams", "players"]
        or source.get("shot_chart_scope") != "all-teams"
    ):
        raise ManifestVerificationError("Manifest source provenance does not match the season")

    paths = dataset_paths(clean_root, season)
    expected_paths = {str(item.relative_to(clean_root)) for item in paths.values()}
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != expected_paths:
        raise ManifestVerificationError(
            "Manifest file set does not match required transformed files"
        )
    missing = [str(file_path) for file_path in paths.values() if not file_path.is_file()]
    if missing:
        raise ManifestVerificationError("Missing manifested files: " + ", ".join(missing))
    for file_path in paths.values():
        relative = str(file_path.relative_to(clean_root))
        entry = files[relative]
        if not isinstance(entry, dict):
            raise ManifestVerificationError(f"Manifest entry for {relative} is malformed")
        if entry.get("sha256") != _sha256(file_path):
            raise ManifestVerificationError(f"Checksum mismatch for {relative}")

    verification = manifest.get("official_verification")
    verification_file = report_path(clean_root, season)
    expected_verification_path = str(verification_file.relative_to(clean_root))
    if (
        not isinstance(verification, dict)
        or verification.get("path") != expected_verification_path
        or verification.get("status") != "passed"
        or verification.get("provider") != "stats.nba.com via nba_api"
        or not isinstance(verification.get("generated_at"), str)
    ):
        raise ManifestVerificationError("Manifest official verification metadata is invalid")
    if not verification_file.is_file():
        raise ManifestVerificationError(
            f"Missing manifested official verification report: {verification_file}"
        )
    if verification.get("sha256") != _sha256(verification_file):
        raise ManifestVerificationError("Checksum mismatch for official verification report")
    try:
        report = load_valid_report(clean_root, season, paths)
    except OfficialVerificationError as exc:
        raise ManifestVerificationError(str(exc)) from exc
    if report["generated_at"] != verification["generated_at"]:
        raise ManifestVerificationError("Official verification timestamp does not match manifest")

    dataset = load_validated_dataset(clean_root, season)
    for name, file_path in paths.items():
        relative = str(file_path.relative_to(clean_root))
        entry = files[relative]
        if entry.get("sha256") != _sha256(file_path):
            raise ManifestVerificationError(f"Checksum changed while reading {relative}")
        if entry.get("rows") != dataset.counts[name]:
            raise ManifestVerificationError(f"Row-count mismatch for {relative}")
    if manifest.get("counts") != dataset.counts:
        raise ManifestVerificationError("Manifest aggregate counts do not match transformed files")
    if manifest.get("shot_verification") != shot_verification_summary(dataset):
        raise ManifestVerificationError(
            "Manifest shot verification does not match transformed files"
        )
    if verification.get("sha256") != _sha256(verification_file):
        raise ManifestVerificationError("Official verification changed while reading")
    return SeasonDataset(
        **{
            **dataset.__dict__,
            "manifest": manifest,
            "manifest_sha256": _sha256(path),
        }
    )


def _rows(frame: pd.DataFrame, columns: list[str]) -> list[tuple[Any, ...]]:
    def python_value(value: Any) -> Any:
        if pd.isna(value):
            return None
        item = getattr(value, "item", None)
        return item() if callable(item) else value

    return [
        tuple(python_value(value) for value in row)
        for row in frame[columns].itertuples(index=False, name=None)
    ]


def _copy_rows(cur: psycopg.Cursor, table: str, columns: list[str], frame: pd.DataFrame) -> None:
    """Bulk-load validated rows with COPY to keep production WAL bounded."""
    column_list = ", ".join(columns)
    with cur.copy(f"COPY {table} ({column_list}) FROM STDIN") as copy:
        for row in _rows(frame, columns):
            copy.write_row(row)


def _scalar(cur: psycopg.Cursor) -> Any:
    row = cur.fetchone()
    if row is None:
        raise SeasonLifecycleError("Database verification query returned no row")
    return row[0]


def _verify_database(cur: psycopg.Cursor, dataset: SeasonDataset, single_season: bool) -> None:
    counts: dict[str, int] = {}
    for name, table in (
        ("games", "games"),
        ("team_game_stats", "team_game_stats"),
        ("player_game_stats", "player_game_stats"),
        ("shot_attempts", "shot_attempts"),
    ):
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE season = %s", (dataset.season,))
        counts[name] = _scalar(cur)
    for name in counts:
        if counts[name] != dataset.counts[name]:
            raise SeasonLifecycleError(
                f"Database {name} count {counts[name]} does not match manifest {dataset.counts[name]}"
            )
    cur.execute(
        """
        SELECT COUNT(*) FROM games g
        WHERE g.season = %s AND (
            length(g.id) <> 10 OR
            (SELECT COUNT(*) FROM team_game_stats t WHERE t.game_id = g.id) <> 2 OR
            EXISTS (
                SELECT 1 FROM team_game_stats t WHERE t.game_id = g.id AND (
                    t.season <> g.season OR t.team_id NOT IN (g.home_team_id, g.away_team_id) OR
                    (
                        t.is_home <> (t.team_id = g.home_team_id) AND
                        EXISTS (
                            SELECT 1 FROM team_game_stats home_flag
                            WHERE home_flag.game_id = g.id AND home_flag.is_home
                        )
                    ) OR
                    t.points <> CASE WHEN t.team_id = g.home_team_id THEN g.home_score ELSE g.away_score END
                )
            ) OR
            EXISTS (
                SELECT 1 FROM player_game_stats p WHERE p.game_id = g.id AND (
                    p.season <> g.season OR p.team_id NOT IN (g.home_team_id, g.away_team_id)
                )
            )
        )
        """,
        (dataset.season,),
    )
    if _scalar(cur):
        raise SeasonLifecycleError(
            "Database integrity verification failed inside replacement transaction"
        )
    cur.execute(
        """
        SELECT games_count, players_count, shot_attempts_count,
               verification_status, manifest_sha256
        FROM seasons WHERE id = %s
        """,
        (dataset.season,),
    )
    metadata = cur.fetchone()
    expected_status = "passed" if dataset.manifest else "untracked"
    if metadata != (
        dataset.counts["games"],
        dataset.participating_players_count,
        dataset.counts["shot_attempts"],
        expected_status,
        dataset.manifest_sha256,
    ):
        raise SeasonLifecycleError("Season metadata does not match the validated dataset")
    if single_season:
        cur.execute("SELECT array_agg(id ORDER BY id) FROM seasons")
        if _scalar(cur) != [dataset.season]:
            raise SeasonLifecycleError(
                "Single-season replacement left other seasons in the database"
            )
        cur.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT season FROM games
                UNION ALL SELECT season FROM team_game_stats
                UNION ALL SELECT season FROM player_game_stats
                UNION ALL SELECT season FROM shot_attempts
            ) loaded WHERE season <> %s
            """,
            (dataset.season,),
        )
        if _scalar(cur):
            raise SeasonLifecycleError("Single-season replacement left non-target data rows")
        for name, table in (("teams", "teams"), ("players", "players")):
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            if _scalar(cur) != dataset.counts[name]:
                raise SeasonLifecycleError(
                    f"Single-season replacement left stale shared {name} rows"
                )


def replace_season(
    conn: psycopg.Connection,
    dataset: SeasonDataset,
    *,
    single_season: bool = False,
    acquire_advisory_lock: bool = True,
) -> None:
    """Replace validated season data atomically; optionally prune every other season."""
    with conn.transaction():
        with conn.cursor() as cur:
            if acquire_advisory_lock:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    ("nba-db-season-lifecycle",),
                )
            cur.executemany(
                """
                INSERT INTO teams (id, full_name, abbreviation, nickname, city, state, year_founded)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    full_name = EXCLUDED.full_name, abbreviation = EXCLUDED.abbreviation,
                    nickname = EXCLUDED.nickname, city = EXCLUDED.city,
                    state = EXCLUDED.state, year_founded = EXCLUDED.year_founded
                """,
                _rows(dataset.teams, TEAM_COLUMNS),
            )
            cur.executemany(
                """
                INSERT INTO players (id, full_name, first_name, last_name, is_active)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    full_name = EXCLUDED.full_name, first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name, is_active = EXCLUDED.is_active
                """,
                _rows(dataset.players, PLAYER_COLUMNS),
            )
            if single_season:
                cur.execute(
                    "TRUNCATE shot_attempts, player_game_stats, team_game_stats, "
                    "games, seasons RESTART IDENTITY"
                )
                cur.execute(
                    "DELETE FROM players WHERE NOT (id = ANY(%s))",
                    (dataset.players["id"].astype(int).tolist(),),
                )
                cur.execute(
                    "DELETE FROM teams WHERE NOT (id = ANY(%s))",
                    (dataset.teams["id"].astype(int).tolist(),),
                )
            else:
                cur.execute(
                    "DELETE FROM shot_attempts WHERE season = %s OR game_id IN "
                    "(SELECT id FROM games WHERE season = %s)",
                    (dataset.season, dataset.season),
                )
                cur.execute(
                    "DELETE FROM player_game_stats WHERE season = %s OR game_id IN "
                    "(SELECT id FROM games WHERE season = %s)",
                    (dataset.season, dataset.season),
                )
                cur.execute(
                    "DELETE FROM team_game_stats WHERE season = %s OR game_id IN "
                    "(SELECT id FROM games WHERE season = %s)",
                    (dataset.season, dataset.season),
                )
                cur.execute("DELETE FROM games WHERE season = %s", (dataset.season,))
                cur.execute("DELETE FROM seasons WHERE id = %s", (dataset.season,))
            start_year = int(dataset.season[:4])
            cur.execute(
                """
                INSERT INTO seasons (id, start_year, end_year, games_count, players_count)
                VALUES (%s, %s, %s, 0, 0)
                """,
                (dataset.season, start_year, start_year + 1),
            )
            _copy_rows(cur, "games", GAME_COLUMNS, dataset.games)
            _copy_rows(cur, "team_game_stats", TEAM_STATS_COLUMNS, dataset.team_stats)
            _copy_rows(cur, "player_game_stats", PLAYER_STATS_COLUMNS, dataset.player_stats)
            _copy_rows(cur, "shot_attempts", SHOT_COLUMNS, dataset.shots)
            cur.execute("CALL sp_update_season_metadata(%s)", (dataset.season,))
            manifest = dataset.manifest or {}
            verification = manifest.get("official_verification", {})
            cur.execute(
                """
                UPDATE seasons
                SET shot_attempts_count = %s,
                    manifest_generated_at = %s,
                    verified_at = %s,
                    verification_status = %s,
                    manifest_sha256 = %s
                WHERE id = %s
                """,
                (
                    dataset.counts["shot_attempts"],
                    manifest.get("generated_at"),
                    verification.get("generated_at"),
                    "passed" if verification.get("status") == "passed" else "untracked",
                    dataset.manifest_sha256,
                    dataset.season,
                ),
            )
            _verify_database(cur, dataset, single_season)


def local_db_config() -> dict[str, Any]:
    if os.getenv("DATABASE_URL"):
        raise PromotionSafetyError("Local load requires DATABASE_URL to be unset")
    config = get_db_config()
    host = str(config.get("host", ""))
    if host not in LOCAL_HOSTS:
        raise PromotionSafetyError("Local load requires DB_HOST to be localhost")
    return config


def _route_is_unsafe(config: dict[str, Any]) -> bool:
    raw_host = str(config.get("host", ""))
    raw_hostaddr = str(config.get("hostaddr", ""))
    if not raw_host and not raw_hostaddr:
        return True
    for field, is_address in ((raw_host, False), (raw_hostaddr, True)):
        if not field:
            continue
        tokens = field.split(",")
        if any(not token.strip() for token in tokens):
            return True
        for token in tokens:
            route = token.strip()
            lowered = route.lower().rstrip(".")
            if (
                route.startswith(("/", "@"))
                or lowered in LOCAL_HOSTS
                or lowered.startswith("localhost.")
            ):
                return True
            try:
                address = ipaddress.ip_address(route)
            except ValueError:
                if is_address:
                    return True
            else:
                if address.is_loopback or address.is_unspecified:
                    return True
    return False


def production_db_config(target: str, season: str, confirmation: str) -> dict[str, Any]:
    if target != "production":
        raise PromotionSafetyError("Promotion requires the explicit target 'production'")
    if confirmation != season:
        raise PromotionSafetyError("Typed season confirmation does not match")
    production_url = os.getenv("PRODUCTION_DATABASE_URL")
    if not production_url:
        raise PromotionSafetyError("Promotion requires an explicit PRODUCTION_DATABASE_URL")
    if not production_url.startswith(("postgresql://", "postgres://")):
        raise PromotionSafetyError("PRODUCTION_DATABASE_URL must be a PostgreSQL URL")
    try:
        config: dict[str, Any] = conninfo_to_dict(production_url)
    except Exception as exc:
        raise PromotionSafetyError("PRODUCTION_DATABASE_URL is not a valid PostgreSQL URL") from exc
    if _route_is_unsafe(config):
        raise PromotionSafetyError(
            "Promotion refuses local, unspecified, or Unix-socket production routing"
        )
    return config


def staging_db_config(target: str, season: str, confirmation: str) -> dict[str, Any]:
    """Resolve an explicitly confirmed, non-local staging database."""
    if target != "staging":
        raise PromotionSafetyError("Staging load requires the explicit target 'staging'")
    if confirmation != season:
        raise PromotionSafetyError("Typed season confirmation does not match")
    staging_url = os.getenv("STAGING_DATABASE_URL")
    if not staging_url:
        raise PromotionSafetyError("Staging load requires an explicit STAGING_DATABASE_URL")
    if not staging_url.startswith(("postgresql://", "postgres://")):
        raise PromotionSafetyError("STAGING_DATABASE_URL must be a PostgreSQL URL")
    try:
        config: dict[str, Any] = conninfo_to_dict(staging_url)
    except Exception as exc:
        raise PromotionSafetyError("STAGING_DATABASE_URL is not a valid PostgreSQL URL") from exc
    if _route_is_unsafe(config):
        raise PromotionSafetyError(
            "Staging load refuses local, unspecified, or Unix-socket routing"
        )
    production_url = os.getenv("PRODUCTION_DATABASE_URL")
    if production_url and make_conninfo("", **config) == make_conninfo(
        "", **conninfo_to_dict(production_url)
    ):
        raise PromotionSafetyError("Staging and production database URLs must be different")
    return config


@contextmanager
def promotion_operation_lock(config: dict[str, Any]) -> Iterator[None]:
    """Serialize backup through smoke verification across all cooperating promoters."""
    coordination = psycopg.connect(**config, autocommit=True)
    locked = False
    try:
        coordination.execute("SELECT pg_advisory_lock(hashtext(%s))", ("nba-db-season-lifecycle",))
        locked = True
        yield
    finally:
        if locked:
            try:
                coordination.execute(
                    "SELECT pg_advisory_unlock(hashtext(%s))",
                    ("nba-db-season-lifecycle",),
                )
            except psycopg.Error:
                pass  # Closing the session releases the lock even if explicit unlock fails.
        coordination.close()


def create_backup(
    config: dict[str, Any], output: Path, runner: Callable[..., Any] = subprocess.run
) -> None:
    """Create and verify a new pg_dump artifact without exposing its password in argv."""
    if output.exists():
        raise PromotionSafetyError(f"Backup path already exists: {output}")
    parent = output.parent
    if not parent.is_dir() or parent.is_symlink():
        raise PromotionSafetyError("Backup parent must be an existing non-symlink directory")
    if stat.S_IMODE(parent.stat().st_mode) & 0o077:
        raise PromotionSafetyError("Backup parent directory must not permit group or other access")
    temporary = output.with_name(output.name + ".tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise PromotionSafetyError("Could not securely precreate the backup artifact") from exc
    os.close(descriptor)
    try:
        temporary.chmod(0o600)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise PromotionSafetyError("Could not restrict backup permissions") from exc
    safe_config = {
        key: value for key, value in config.items() if key not in {"password", "sslpassword"}
    }
    environment = os.environ.copy()
    environment.pop("PRODUCTION_DATABASE_URL", None)
    environment.pop("DATABASE_URL", None)
    if config.get("password") is not None:
        environment["PGPASSWORD"] = str(config["password"])
    if config.get("sslpassword") is not None:
        environment["PGSSLPASSWORD"] = str(config["sslpassword"])
    command = [
        "pg_dump",
        "--format=custom",
        "--file",
        str(temporary),
        "--dbname",
        make_conninfo("", **safe_config),
    ]
    try:
        result = runner(command, env=environment, capture_output=True, text=True, check=False)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise PromotionSafetyError("pg_dump could not be executed; promotion aborted") from exc
    if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        raise PromotionSafetyError("pg_dump did not create a valid backup; promotion aborted")
    try:
        temporary.chmod(0o600)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise PromotionSafetyError(
            "Could not restrict backup permissions; promotion aborted"
        ) from exc
    try:
        os.replace(temporary, output)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise PromotionSafetyError("Could not finalize the backup artifact") from exc


def _smoke_once(api_url: str, dataset: SeasonDataset, get: Callable[..., Any]) -> None:
    request_options = {
        "timeout": 10,
        "headers": {"Cache-Control": "no-cache", "Pragma": "no-cache"},
    }
    health = get(f"{api_url}/health", **request_options)
    health.raise_for_status()
    if health.json() != {"status": "healthy", "database": "connected"}:
        raise SeasonLifecycleError("Live health response is not healthy")
    readiness = get(f"{api_url}/ready", **request_options)
    readiness.raise_for_status()
    readiness_body = readiness.json()
    if (
        readiness_body.get("status") != "ready"
        or readiness_body.get("season") != dataset.season
        or readiness_body.get("verification_status") != "passed"
        or readiness_body.get("counts", {}).get("games") != dataset.counts["games"]
        or readiness_body.get("counts", {}).get("players") != dataset.participating_players_count
        or readiness_body.get("counts", {}).get("shot_attempts") != dataset.counts["shot_attempts"]
    ):
        raise SeasonLifecycleError("Live readiness response does not match the promoted manifest")
    status = get(
        f"{api_url}/api/dataset-status",
        params={"season": dataset.season},
        **request_options,
    )
    status.raise_for_status()
    status_body = status.json()
    if (
        status_body.get("verification_status") != "passed"
        or status_body.get("manifest_sha256") != dataset.manifest_sha256
        or status_body.get("counts", {}).get("shot_attempts") != dataset.counts["shot_attempts"]
    ):
        raise SeasonLifecycleError("Live provenance response does not match the promoted manifest")
    seasons = get(f"{api_url}/api/seasons", **request_options)
    seasons.raise_for_status()
    seasons_body = seasons.json()
    season_rows = [row for row in seasons_body if row.get("id") == dataset.season]
    if (
        len(seasons_body) != 1
        or len(season_rows) != 1
        or season_rows[0].get("games_count") != dataset.counts["games"]
    ):
        raise SeasonLifecycleError("Live seasons response does not match the promoted manifest")
    games = get(
        f"{api_url}/api/games",
        params={"season": dataset.season, "limit": 1},
        **request_options,
    )
    games.raise_for_status()
    body = games.json()
    listed_games = body.get("data", [])
    official_ids = set(dataset.games["id"].astype(str))
    if (
        body.get("total") != dataset.counts["games"]
        or len(listed_games) != 1
        or listed_games[0].get("id") not in official_ids
    ):
        raise SeasonLifecycleError("Live games response does not match the promoted manifest")
    sampled_game_id = str(dataset.games.iloc[0]["id"])
    boxscore = get(f"{api_url}/api/games/{sampled_game_id}/boxscore", **request_options)
    boxscore.raise_for_status()
    boxscore_body = boxscore.json()
    if (
        boxscore_body.get("game", {}).get("id") != sampled_game_id
        or boxscore_body.get("home_team_stats") is None
        or boxscore_body.get("away_team_stats") is None
        or len(boxscore_body.get("home_players", [])) + len(boxscore_body.get("away_players", []))
        != int((dataset.player_stats["game_id"] == sampled_game_id).sum())
    ):
        raise SeasonLifecycleError("Live boxscore response does not contain the promoted game")
    standings = get(
        f"{api_url}/api/standings",
        params={"season": dataset.season},
        **request_options,
    )
    standings.raise_for_status()
    standings_body = standings.json()
    expected_team_ids = set(dataset.games["home_team_id"]) | set(dataset.games["away_team_id"])
    if (
        not standings_body
        or any(row.get("season") != dataset.season for row in standings_body)
        or {row.get("team_id") for row in standings_body} != expected_team_ids
    ):
        raise SeasonLifecycleError("Live standings response does not match the promoted season")
    leaders = get(
        f"{api_url}/api/leaders/points",
        params={"season": dataset.season, "limit": 1},
        **request_options,
    )
    leaders.raise_for_status()
    leaders_body = leaders.json()
    if (
        leaders_body.get("stat") != "points"
        or leaders_body.get("season") != dataset.season
        or not isinstance(leaders_body.get("data"), list)
    ):
        raise SeasonLifecycleError("Live leaders response does not match the promoted season")


def verify_live_api(
    api_url: str,
    dataset: SeasonDataset,
    *,
    get: Callable[..., Any] = requests.get,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            _smoke_once(api_url.rstrip("/"), dataset, get)
            return
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                sleep(2)
    raise SeasonLifecycleError(
        f"Live API smoke verification failed after the database commit: {last_error}"
    ) from last_error


def _production_api_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise PromotionSafetyError("Promotion requires an explicit credential-free HTTPS API_URL")
    return value.rstrip("/")


def _staging_api_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise PromotionSafetyError(
            "Staging load requires an explicit credential-free HTTPS API_URL"
        )
    return value.rstrip("/")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-root", type=Path, default=CLEAN_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate-season", "manifest", "load-local"):
        child = subparsers.add_parser(command)
        child.add_argument("--season", required=True)
    stage = subparsers.add_parser("stage")
    stage.add_argument("--season", required=True)
    stage.add_argument("--target", required=True)
    stage.add_argument("--confirm-season", required=True)
    stage.add_argument("--api-url", required=True)
    promote = subparsers.add_parser("promote")
    promote.add_argument("--season", required=True)
    promote.add_argument("--target", required=True)
    promote.add_argument("--confirm-season", required=True)
    promote.add_argument("--confirm-single-season", required=True)
    promote.add_argument("--backup-file", type=Path, required=True)
    promote.add_argument("--api-url", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate-season":
            validate_season_name(args.season)
            print(f"Validated season {args.season}")
            return 0
        if args.command == "manifest":
            manifest = generate_manifest(args.clean_root, args.season)
            print(
                f"Validated {args.season} Regular Season and wrote manifest "
                f"with {manifest['counts']['games']} games"
            )
            return 0
        if args.command == "load-local":
            dataset = verify_manifest(args.clean_root, args.season)
            config = local_db_config()
            with psycopg.connect(**config) as conn:
                apply_schema(conn)
                replace_season(conn, dataset, single_season=True)
            print(f"Local database now contains only season {args.season}")
            return 0
        if args.command == "stage":
            config = staging_db_config(args.target, args.season, args.confirm_season)
            api_url = _staging_api_url(args.api_url)
            dataset = verify_manifest(args.clean_root, args.season)
            with promotion_operation_lock(config):
                with psycopg.connect(**config) as conn:
                    apply_schema(conn)
                    replace_season(
                        conn,
                        dataset,
                        single_season=True,
                        acquire_advisory_lock=False,
                    )
                verify_live_api(api_url, dataset)
            print(f"Staging now contains only season {args.season}")
            return 0

        if args.confirm_single_season != "DELETE OTHER SEASONS":
            raise PromotionSafetyError(
                "Promotion requires --confirm-single-season 'DELETE OTHER SEASONS'"
            )
        config = production_db_config(args.target, args.season, args.confirm_season)
        api_url = _production_api_url(args.api_url)
        dataset = verify_manifest(args.clean_root, args.season)
        with promotion_operation_lock(config):
            create_backup(config, args.backup_file)
            with psycopg.connect(**config) as conn:
                replace_season(
                    conn,
                    dataset,
                    single_season=True,
                    acquire_advisory_lock=False,
                )
            verify_live_api(api_url, dataset)
        print(f"Promoted only season {args.season}; backup: {args.backup_file}")
        return 0
    except SeasonLifecycleError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
