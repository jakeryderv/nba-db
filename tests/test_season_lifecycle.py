"""Safe single-season lifecycle tests without NBA or production access."""

import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import psycopg
import pytest

from db.config import get_db_config
from etl import extract, official_verification, transform
from etl import season_lifecycle as lifecycle
from tests.conftest import CELTICS, LAKERS

SEASON = "2025-26"
GAME_ID = "0022500001"
PLAYER_ONE = 1001
PLAYER_TWO = 1002


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def write_valid_dataset(root: Path) -> None:
    _write(
        root / "shared/teams.csv",
        [
            {
                "id": LAKERS,
                "full_name": "Los Angeles Lakers",
                "abbreviation": "LAL",
                "nickname": "Lakers",
                "city": "Los Angeles",
                "state": "California",
                "year_founded": 1948,
            },
            {
                "id": CELTICS,
                "full_name": "Boston Celtics",
                "abbreviation": "BOS",
                "nickname": "Celtics",
                "city": "Boston",
                "state": "Massachusetts",
                "year_founded": 1946,
            },
        ],
    )
    _write(
        root / "shared/players.csv",
        [
            {
                "id": PLAYER_ONE,
                "full_name": "Player One",
                "first_name": "Player",
                "last_name": "One",
                "is_active": True,
            },
            {
                "id": PLAYER_TWO,
                "full_name": "Player Two",
                "first_name": "Player",
                "last_name": "Two",
                "is_active": True,
            },
        ],
    )
    _write(
        root / SEASON / "games.csv",
        [
            {
                "id": GAME_ID,
                "game_date": "2025-11-01",
                "season": SEASON,
                "home_team_id": LAKERS,
                "away_team_id": CELTICS,
                "home_score": 110,
                "away_score": 100,
            }
        ],
    )
    base_stats = {
        "season": SEASON,
        "minutes": 240,
        "rebounds": 40,
        "offensive_rebounds": 10,
        "defensive_rebounds": 30,
        "assists": 20,
        "steals": 5,
        "blocks": 3,
        "turnovers": 10,
        "personal_fouls": 15,
        "fgm": 40,
        "fga": 80,
        "fg_pct": 0.5,
        "fg3m": 10,
        "fg3a": 30,
        "fg3_pct": 0.333,
        "ftm": 20,
        "fta": 25,
        "ft_pct": 0.8,
        "plus_minus": 10,
    }
    _write(
        root / SEASON / "team_game_stats.csv",
        [
            {**base_stats, "game_id": GAME_ID, "team_id": LAKERS, "is_home": True, "points": 110},
            {
                **base_stats,
                "game_id": GAME_ID,
                "team_id": CELTICS,
                "is_home": False,
                "points": 100,
                "plus_minus": -10,
            },
        ],
    )
    player_stats = {
        key: value for key, value in base_stats.items() if key not in {"minutes", "points"}
    }
    _write(
        root / SEASON / "player_game_stats.csv",
        [
            {
                **player_stats,
                "game_id": GAME_ID,
                "player_id": PLAYER_ONE,
                "team_id": LAKERS,
                "minutes": 35.0,
                "points": 30,
            },
            {
                **player_stats,
                "game_id": GAME_ID,
                "player_id": PLAYER_TWO,
                "team_id": CELTICS,
                "minutes": 34.0,
                "points": 25,
                "plus_minus": -10,
            },
        ],
    )


def matching_official_frames(
    dataset: lifecycle.SeasonDataset,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    team_columns = {local: official for official, local in official_verification.TEAM_STATS.items()}
    player_columns = {
        local: official for official, local in official_verification.PLAYER_STATS.items()
    }
    official_teams = (
        official_verification._local_team_totals(dataset.games, dataset.team_stats)
        .reset_index()
        .rename(columns={"team_id": "TEAM_ID", **team_columns})
    )
    official_players = (
        official_verification._local_player_totals(dataset.player_stats)
        .reset_index()
        .rename(columns={"player_id": "PLAYER_ID", **player_columns})
    )
    return official_teams, official_players


def write_passing_verification(root: Path) -> None:
    dataset = lifecycle.load_validated_dataset(root, SEASON)
    official_teams, official_players = matching_official_frames(dataset)
    paths = lifecycle.dataset_paths(root, SEASON)
    report = official_verification.build_report(
        season=SEASON,
        teams=dataset.teams,
        players=dataset.players,
        games=dataset.games,
        team_stats=dataset.team_stats,
        player_stats=dataset.player_stats,
        official_teams=official_teams,
        official_players=official_players,
        hashes=official_verification.dataset_hashes(root, paths),
    )
    official_verification.write_report(official_verification.report_path(root, SEASON), report)


@pytest.fixture
def valid_root(tmp_path: Path) -> Path:
    write_valid_dataset(tmp_path)
    write_passing_verification(tmp_path)
    return tmp_path


@pytest.fixture
def lifecycle_conn(client):
    del client
    conn = psycopg.connect(**get_db_config())
    conn.execute("SELECT 1")  # Outer transaction lets each test roll back committed savepoints.
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def test_manifest_records_source_hashes_counts_and_verifies(valid_root: Path) -> None:
    manifest = lifecycle.generate_manifest(valid_root, SEASON)

    assert manifest["schema_version"] == 2
    assert manifest["season"] == SEASON
    assert manifest["season_type"] == "Regular Season"
    assert manifest["generated_at"]
    assert manifest["source"]["season_type"] == "Regular Season"
    assert manifest["counts"] == {
        "teams": 2,
        "players": 2,
        "games": 1,
        "team_game_stats": 2,
        "player_game_stats": 2,
    }
    assert len(manifest["files"]) == 5
    assert manifest["official_verification"]["status"] == "passed"
    assert lifecycle.verify_manifest(valid_root, SEASON).counts == manifest["counts"]


def test_official_verification_uses_injected_aggregates_without_network(
    valid_root: Path,
) -> None:
    dataset = lifecycle.load_validated_dataset(valid_root, SEASON)
    official_frames = matching_official_frames(dataset)

    report = official_verification.run_verification(
        valid_root,
        SEASON,
        fetcher=lambda _season: official_frames,
    )

    assert report["status"] == "passed"
    assert report["mismatch_count"] == 0
    assert report["checks"]["teams"]["checked"] == 2
    assert report["checks"]["players"]["checked"] == 2


def test_official_verification_writes_failed_report_on_mismatch(valid_root: Path) -> None:
    dataset = lifecycle.load_validated_dataset(valid_root, SEASON)
    official_teams, official_players = matching_official_frames(dataset)
    official_players.loc[official_players["PLAYER_ID"] == PLAYER_ONE, "REB"] += 2

    with pytest.raises(official_verification.OfficialVerificationError, match="1 mismatches"):
        official_verification.run_verification(
            valid_root,
            SEASON,
            fetcher=lambda _season: (official_teams, official_players),
        )

    report = json.loads(official_verification.report_path(valid_root, SEASON).read_text())
    assert report["status"] == "failed"
    assert report["checks"]["players"]["mismatches"] == [
        {
            "id": PLAYER_ONE,
            "difference": -2,
            "local": 40,
            "name": "Player One",
            "official": 42,
            "stat": "rebounds",
            "tolerance": 1,
        }
    ]


def test_official_verification_reports_one_count_stat_corrections_as_warnings(
    valid_root: Path,
) -> None:
    dataset = lifecycle.load_validated_dataset(valid_root, SEASON)
    official_teams, official_players = matching_official_frames(dataset)
    official_players.loc[official_players["PLAYER_ID"] == PLAYER_ONE, "REB"] += 1

    report = official_verification.run_verification(
        valid_root,
        SEASON,
        fetcher=lambda _season: (official_teams, official_players),
    )

    assert report["status"] == "passed"
    assert report["difference_count"] == 1
    assert report["mismatch_count"] == 0
    assert report["checks"]["players"]["differences"][0]["tolerance"] == 1


def test_manifest_requires_passing_official_verification(valid_root: Path) -> None:
    official_verification.report_path(valid_root, SEASON).unlink()

    with pytest.raises(lifecycle.ManifestVerificationError, match="Missing required official"):
        lifecycle.generate_manifest(valid_root, SEASON)


def test_manifest_rejects_stale_official_verification(valid_root: Path) -> None:
    players_path = valid_root / "shared/players.csv"
    players_path.write_text(players_path.read_text().replace("Player One", "Player 1"))

    with pytest.raises(lifecycle.ManifestVerificationError, match="stale"):
        lifecycle.generate_manifest(valid_root, SEASON)


def test_manifest_rejects_verification_report_tampering(valid_root: Path) -> None:
    lifecycle.generate_manifest(valid_root, SEASON)
    path = official_verification.report_path(valid_root, SEASON)
    report = json.loads(path.read_text())
    report["generated_at"] = "2026-01-01T00:00:00+00:00"
    path.write_text(json.dumps(report))

    with pytest.raises(lifecycle.ManifestVerificationError, match="Checksum mismatch"):
        lifecycle.verify_manifest(valid_root, SEASON)


def test_manifest_rejects_checksum_tampering(valid_root: Path) -> None:
    lifecycle.generate_manifest(valid_root, SEASON)
    games_path = valid_root / SEASON / "games.csv"
    games_path.write_text(games_path.read_text().replace(",110,100", ",111,100"))

    with pytest.raises(lifecycle.ManifestVerificationError, match="Checksum mismatch"):
        lifecycle.verify_manifest(valid_root, SEASON)


def test_manifest_rejects_row_count_tampering(valid_root: Path) -> None:
    lifecycle.generate_manifest(valid_root, SEASON)
    path = lifecycle.manifest_path(valid_root, SEASON)
    manifest = json.loads(path.read_text())
    manifest["counts"]["games"] = 999
    path.write_text(json.dumps(manifest))

    with pytest.raises(lifecycle.ManifestVerificationError, match="aggregate counts"):
        lifecycle.verify_manifest(valid_root, SEASON)


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        (("season",), "2024-25"),
        (("season_type",), "Playoffs"),
        (("source", "season"), "2024-25"),
        (("source", "season_type"), "Playoffs"),
    ],
)
def test_manifest_rejects_wrong_season_or_scope(
    valid_root: Path, field_path: tuple[str, ...], value: str
) -> None:
    lifecycle.generate_manifest(valid_root, SEASON)
    path = lifecycle.manifest_path(valid_root, SEASON)
    manifest = json.loads(path.read_text())
    target = manifest
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = value
    path.write_text(json.dumps(manifest))

    with pytest.raises(lifecycle.ManifestVerificationError, match="season|scope|source|type"):
        lifecycle.verify_manifest(valid_root, SEASON)


def test_manifest_is_required_for_reverification(valid_root: Path) -> None:
    with pytest.raises(lifecycle.ManifestVerificationError, match="Missing required manifest"):
        lifecycle.verify_manifest(valid_root, SEASON)


@pytest.mark.parametrize(
    "season",
    ["2025", "2025-27", "../../2025-26", "2025-026", "abcd-ef"],
)
def test_invalid_or_unsafe_season_names_are_rejected(valid_root: Path, season: str) -> None:
    with pytest.raises(lifecycle.DatasetValidationError, match="Invalid season|following year"):
        lifecycle.load_validated_dataset(valid_root, season)


def test_validate_season_command_rejects_path_traversal() -> None:
    assert lifecycle.main(["validate-season", "--season", "../.."]) == 2


def test_extract_and_transform_reject_unsafe_seasons_before_work() -> None:
    for validator in (extract.validate_season_argument, transform.validate_season_argument):
        with pytest.raises(ValueError, match="safe consecutive-year"):
            validator("../..")
        validator(SEASON)


def test_make_guards_invalid_season_before_extract_and_has_no_clean_season_target() -> None:
    dry_run = subprocess.run(
        ["make", "-n", "extract", "SEASON=../.."],
        cwd=lifecycle.PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert dry_run.returncode == 0
    assert dry_run.stdout.index("validate-season") < dry_run.stdout.index("etl/extract.py")

    guarded = subprocess.run(
        ["make", "extract", "SEASON=../.."],
        cwd=lifecycle.PROJECT_ROOT,
        env={**os.environ, "UV_CACHE_DIR": "/tmp/nba-db-season-lifecycle-uv-cache"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert guarded.returncode != 0
    assert "Invalid season" in guarded.stderr
    assert "Fetching" not in guarded.stdout

    removed = subprocess.run(
        ["make", "-n", "clean-season", "SEASON=../.."],
        cwd=lifecycle.PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert removed.returncode != 0
    assert "No rule to make target" in removed.stderr


def test_season_build_verifies_official_totals_before_manifest_and_ci_stays_offline() -> None:
    dry_run = subprocess.run(
        ["make", "-n", "season-build", f"SEASON={SEASON}"],
        cwd=lifecycle.PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert dry_run.stdout.index("etl.official_verification") < dry_run.stdout.index(
        "season_lifecycle manifest"
    )

    workflow = (lifecycle.PROJECT_ROOT / ".github/workflows/ci.yml").read_text()
    assert "etl.official_verification" not in workflow
    assert "stats.nba.com" not in workflow


def test_missing_required_file_fails_closed_before_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connected = False
    schema_applied = False

    def unexpected_connect(**_kwargs):
        nonlocal connected
        connected = True

    def unexpected_schema(_conn):
        nonlocal schema_applied
        schema_applied = True

    monkeypatch.setattr(lifecycle.psycopg, "connect", unexpected_connect)
    monkeypatch.setattr(lifecycle, "apply_schema", unexpected_schema)
    result = lifecycle.main(["--clean-root", str(tmp_path), "load-local", "--season", SEASON])

    assert result == 2
    assert connected is False
    assert schema_applied is False


def test_local_load_verifies_guard_then_applies_schema_before_replace(
    valid_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle.generate_manifest(valid_root, SEASON)
    events: list[str] = []
    original_verify = lifecycle.verify_manifest

    def verify(root: Path, season: str):
        events.append("verify")
        return original_verify(root, season)

    class ConnectionContext:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setattr(lifecycle, "verify_manifest", verify)
    monkeypatch.setattr(
        lifecycle, "local_db_config", lambda: events.append("guard") or {"host": "localhost"}
    )
    monkeypatch.setattr(
        lifecycle.psycopg,
        "connect",
        lambda **_config: events.append("connect") or ConnectionContext(),
    )
    monkeypatch.setattr(lifecycle, "apply_schema", lambda _conn: events.append("schema"))
    monkeypatch.setattr(
        lifecycle,
        "replace_season",
        lambda _conn, _dataset, *, single_season: events.append(f"replace:{single_season}"),
    )

    result = lifecycle.main(["--clean-root", str(valid_root), "load-local", "--season", SEASON])

    assert result == 0
    assert events == ["verify", "guard", "connect", "schema", "replace:True"]


def test_local_load_guard_blocks_connection_and_schema(
    valid_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle.generate_manifest(valid_root, SEASON)
    monkeypatch.setenv("DATABASE_URL", "postgresql://owner:secret@db.example.com/nba")
    monkeypatch.setattr(
        lifecycle.psycopg,
        "connect",
        lambda **_config: pytest.fail("local guard must run before connecting"),
    )
    monkeypatch.setattr(
        lifecycle,
        "apply_schema",
        lambda _conn: pytest.fail("local guard must run before applying schema"),
    )

    result = lifecycle.main(["--clean-root", str(valid_root), "load-local", "--season", SEASON])

    assert result == 2


@pytest.mark.parametrize(
    ("filename", "mutation", "message"),
    [
        ("games.csv", lambda frame: frame.assign(id="225000001"), "002 regular-season"),
        ("games.csv", lambda frame: pd.concat([frame, frame]), "duplicate id"),
        (
            "team_game_stats.csv",
            lambda frame: frame.assign(season="2024-25"),
            "only season",
        ),
        (
            "player_game_stats.csv",
            lambda frame: frame.assign(team_id=999999),
            "teams absent",
        ),
    ],
)
def test_dataset_relationship_validation(
    valid_root: Path, filename: str, mutation, message: str
) -> None:
    path = valid_root / SEASON / filename
    mutation(pd.read_csv(path)).to_csv(path, index=False)

    with pytest.raises(lifecycle.DatasetValidationError, match=message):
        lifecycle.load_validated_dataset(valid_root, SEASON)


@pytest.mark.parametrize(
    ("filename", "key", "message"),
    [
        ("team_game_stats.csv", "game_id", "duplicate.*game_id, team_id"),
        ("player_game_stats.csv", "game_id", "duplicate.*game_id, player_id"),
    ],
)
def test_dataset_rejects_duplicate_composite_keys(
    valid_root: Path, filename: str, key: str, message: str
) -> None:
    path = valid_root / SEASON / filename
    frame = pd.read_csv(path, dtype={key: "string"})
    pd.concat([frame, frame.iloc[[0]]], ignore_index=True).to_csv(path, index=False)

    with pytest.raises(lifecycle.DatasetValidationError, match=message):
        lifecycle.load_validated_dataset(valid_root, SEASON)


def test_dataset_requires_both_participating_team_rows(valid_root: Path) -> None:
    path = valid_root / SEASON / "team_game_stats.csv"
    frame = pd.read_csv(path, dtype={"game_id": "string"})
    frame.iloc[[0]].to_csv(path, index=False)

    with pytest.raises(lifecycle.DatasetValidationError, match="exactly its two participating"):
        lifecycle.load_validated_dataset(valid_root, SEASON)


def test_dataset_allows_both_home_flags_false_for_neutral_site(valid_root: Path) -> None:
    path = valid_root / SEASON / "team_game_stats.csv"
    frame = pd.read_csv(path, dtype={"game_id": "string"})
    frame["is_home"] = False
    frame.to_csv(path, index=False)

    dataset = lifecycle.load_validated_dataset(valid_root, SEASON)

    assert dataset.team_stats["is_home"].tolist() == [False, False]


def test_dataset_rejects_score_mismatch(valid_root: Path) -> None:
    path = valid_root / SEASON / "team_game_stats.csv"
    frame = pd.read_csv(path, dtype={"game_id": "string"})
    frame.loc[frame["team_id"] == LAKERS, "points"] = 109
    frame.to_csv(path, index=False)

    with pytest.raises(lifecycle.DatasetValidationError, match="scores do not match"):
        lifecycle.load_validated_dataset(valid_root, SEASON)


def test_dataset_rejects_unknown_player(valid_root: Path) -> None:
    path = valid_root / SEASON / "player_game_stats.csv"
    frame = pd.read_csv(path, dtype={"game_id": "string"})
    frame.loc[0, "player_id"] = 999999
    frame.to_csv(path, index=False)

    with pytest.raises(lifecycle.DatasetValidationError, match="players absent"):
        lifecycle.load_validated_dataset(valid_root, SEASON)


def test_regular_season_dataset_rejects_playoff_game_ids(valid_root: Path) -> None:
    playoff_id = "0042500001"
    for filename, column in (
        ("games.csv", "id"),
        ("team_game_stats.csv", "game_id"),
        ("player_game_stats.csv", "game_id"),
    ):
        path = valid_root / SEASON / filename
        frame = pd.read_csv(path, dtype={column: "string"})
        frame[column] = playoff_id
        frame.to_csv(path, index=False)

    with pytest.raises(lifecycle.DatasetValidationError, match="regular.season|002"):
        lifecycle.load_validated_dataset(valid_root, SEASON)


@pytest.mark.parametrize(
    ("filename", "column", "value", "message"),
    [
        ("games.csv", "home_team_id", "not-a-number", "finite numeric"),
        ("games.csv", "home_score", 100.5, "integral"),
        ("team_game_stats.csv", "fg_pct", 1.2, "at most 1"),
        ("player_game_stats.csv", "points", -1, "at least 0"),
        ("player_game_stats.csv", "plus_minus", float("inf"), "finite numeric"),
        ("player_game_stats.csv", "player_id", 1001.5, "integral"),
        ("team_game_stats.csv", "minutes", 240.5, "integral"),
    ],
)
def test_dataset_rejects_invalid_numeric_values(
    valid_root: Path, filename: str, column: str, value, message: str
) -> None:
    path = valid_root / SEASON / filename
    dtype = {"id": "string"} if filename == "games.csv" else {"game_id": "string"}
    frame = pd.read_csv(path, dtype=dtype)
    frame[column] = frame[column].astype(object)
    frame.loc[0, column] = value
    frame.to_csv(path, index=False)

    with pytest.raises(lifecycle.DatasetValidationError, match=message):
        lifecycle.load_validated_dataset(valid_root, SEASON)


def test_dataset_rejects_makes_above_attempts(valid_root: Path) -> None:
    path = valid_root / SEASON / "team_game_stats.csv"
    frame = pd.read_csv(path, dtype={"game_id": "string"})
    frame.loc[0, "fgm"] = frame.loc[0, "fga"] + 1
    frame.to_csv(path, index=False)

    with pytest.raises(lifecycle.DatasetValidationError, match="fgm cannot exceed fga"):
        lifecycle.load_validated_dataset(valid_root, SEASON)


def test_nullable_schema_numerics_are_allowed_and_convert_to_python_none(
    valid_root: Path,
) -> None:
    nullable = ["minutes", "fg_pct", "fg3_pct", "ft_pct", "plus_minus"]
    for filename in ("team_game_stats.csv", "player_game_stats.csv"):
        path = valid_root / SEASON / filename
        frame = pd.read_csv(path, dtype={"game_id": "string"})
        frame.loc[0, nullable] = np.nan
        frame.to_csv(path, index=False)

    dataset = lifecycle.load_validated_dataset(valid_root, SEASON)

    for frame, columns in (
        (dataset.team_stats, lifecycle.TEAM_STATS_COLUMNS),
        (dataset.player_stats, lifecycle.PLAYER_STATS_COLUMNS),
    ):
        row = lifecycle._rows(frame.iloc[[0]], columns)[0]
        values = dict(zip(columns, row, strict=True))
        assert all(values[column] is None for column in nullable)
        assert not any(isinstance(value, np.generic) for value in row if value is not None)


def test_csv_parse_failures_become_validation_errors(valid_root: Path) -> None:
    (valid_root / SEASON / "games.csv").write_bytes(b"\xff\xfe\x00")

    with pytest.raises(lifecycle.DatasetValidationError, match="Could not parse games.csv"):
        lifecycle.load_validated_dataset(valid_root, SEASON)


def test_single_season_replace_prunes_other_seasons_and_verifies_counts(
    lifecycle_conn, valid_root: Path
) -> None:
    dataset = lifecycle.load_validated_dataset(valid_root, SEASON)

    lifecycle.replace_season(lifecycle_conn, dataset, single_season=True)

    with lifecycle_conn.cursor() as cur:
        cur.execute("SELECT id, games_count, players_count FROM seasons")
        assert cur.fetchall() == [(SEASON, 1, 2)]
        cur.execute("SELECT id FROM games")
        assert cur.fetchall() == [(GAME_ID,)]
        cur.execute("SELECT COUNT(*) FROM team_game_stats")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT COUNT(*) FROM player_game_stats")
        assert cur.fetchone()[0] == 2


def test_replace_rolls_back_deletes_and_shared_updates_on_failure(
    lifecycle_conn, valid_root: Path
) -> None:
    dataset = lifecycle.load_validated_dataset(valid_root, SEASON)
    dataset.teams.loc[dataset.teams["id"] == LAKERS, "full_name"] = "Must Roll Back"
    dataset.player_stats.loc[0, "team_id"] = 9999999999

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        lifecycle.replace_season(lifecycle_conn, dataset, single_season=True)

    with lifecycle_conn.cursor() as cur:
        cur.execute("SELECT id, games_count FROM seasons")
        assert cur.fetchall() == [("2024-25", 10)]
        cur.execute("SELECT COUNT(*) FROM games WHERE season = '2024-25'")
        assert cur.fetchone()[0] == 10
        cur.execute("SELECT full_name FROM teams WHERE id = %s", (LAKERS,))
        assert cur.fetchone()[0] == "Los Angeles Lakers"


def test_targeted_replace_removes_stale_target_rows_but_preserves_other_seasons(
    lifecycle_conn, valid_root: Path
) -> None:
    stale_game = "0022599999"
    with lifecycle_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO seasons (id, start_year, end_year) VALUES (%s, 2025, 2026)",
            (SEASON,),
        )
        cur.execute(
            """
            INSERT INTO games (
                id, game_date, season, home_team_id, away_team_id, home_score, away_score
            ) VALUES (%s, '2025-10-01', %s, %s, %s, 90, 80)
            """,
            (stale_game, SEASON, LAKERS, CELTICS),
        )
        cur.executemany(
            """
            INSERT INTO team_game_stats (game_id, team_id, season, is_home, points)
            VALUES (%s, %s, %s, %s, %s)
            """,
            [
                (stale_game, LAKERS, SEASON, True, 90),
                (stale_game, CELTICS, SEASON, False, 80),
            ],
        )

    lifecycle.replace_season(
        lifecycle_conn,
        lifecycle.load_validated_dataset(valid_root, SEASON),
        single_season=False,
    )

    with lifecycle_conn.cursor() as cur:
        cur.execute("SELECT id FROM seasons ORDER BY id")
        assert cur.fetchall() == [("2024-25",), (SEASON,)]
        cur.execute("SELECT id FROM games WHERE season = %s", (SEASON,))
        assert cur.fetchall() == [(GAME_ID,)]
        cur.execute("SELECT COUNT(*) FROM games WHERE season = '2024-25'")
        assert cur.fetchone()[0] == 10


def test_production_config_requires_explicit_nonlocal_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRODUCTION_DATABASE_URL", raising=False)
    with pytest.raises(lifecycle.PromotionSafetyError, match="PRODUCTION_DATABASE_URL"):
        lifecycle.production_db_config("production", SEASON, SEASON)

    monkeypatch.setenv("PRODUCTION_DATABASE_URL", "postgresql://user:secret@localhost/nba")
    with pytest.raises(lifecycle.PromotionSafetyError, match="local"):
        lifecycle.production_db_config("production", SEASON, SEASON)

    monkeypatch.setenv("PRODUCTION_DATABASE_URL", "postgresql://user:secret@db.example.com/nba")
    with pytest.raises(lifecycle.PromotionSafetyError, match="explicit target"):
        lifecycle.production_db_config("", SEASON, SEASON)
    with pytest.raises(lifecycle.PromotionSafetyError, match="confirmation"):
        lifecycle.production_db_config("production", SEASON, "2024-25")


def test_ordinary_database_url_cannot_authorize_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PRODUCTION_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://owner:secret@db.example.com/nba")

    with pytest.raises(lifecycle.PromotionSafetyError, match="PRODUCTION_DATABASE_URL"):
        lifecycle.production_db_config("production", SEASON, SEASON)


def test_production_config_preserves_secret_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "p@ss word"
    monkeypatch.setenv(
        "PRODUCTION_DATABASE_URL",
        "postgresql://owner:p%40ss%20word@db.example.com:5432/nba?sslmode=require",
    )

    config = lifecycle.production_db_config("production", SEASON, SEASON)

    assert config["host"] == "db.example.com"
    assert config["password"] == secret
    assert config["sslmode"] == "require"
    assert secret not in repr({key: value for key, value in config.items() if key != "password"})


@pytest.mark.parametrize(
    "config",
    [
        {"host": "/var/run/postgresql"},
        {"host": "db.example.com,localhost"},
        {"host": "db.example.com", "hostaddr": "127.0.0.1"},
        {"host": "db.example.com", "hostaddr": "203.0.113.4,::1"},
        {"hostaddr": "0.0.0.0"},
        {},
    ],
)
def test_production_routing_rejects_local_host_hostaddr_and_sockets(config: dict) -> None:
    assert lifecycle._route_is_unsafe(config) is True


def test_production_routing_accepts_remote_host_and_hostaddr() -> None:
    assert (
        lifecycle._route_is_unsafe({"host": "db.example.com", "hostaddr": "203.0.113.4"}) is False
    )


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://owner:secret@db.example.com/nba?hostaddr=127.0.0.1",
        "postgresql:///nba?host=%2Fvar%2Frun%2Fpostgresql",
        "postgresql://owner:secret@db.example.com,localhost/nba",
    ],
)
def test_production_config_rejects_unsafe_host_and_hostaddr_urls(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRODUCTION_DATABASE_URL", url)
    with pytest.raises(lifecycle.PromotionSafetyError, match="local|Unix-socket"):
        lifecycle.production_db_config("production", SEASON, SEASON)


def test_promotion_operation_lock_is_session_scoped_and_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Coordination:
        def execute(self, query, _params):
            events.append("unlock" if "unlock" in query else "lock")

        def close(self) -> None:
            events.append("close")

    def connect(**config):
        assert config["autocommit"] is True
        events.append("connect")
        return Coordination()

    monkeypatch.setattr(lifecycle.psycopg, "connect", connect)
    with lifecycle.promotion_operation_lock({"host": "db.example.com"}):
        events.append("backup-replace-smoke")

    assert events == ["connect", "lock", "backup-replace-smoke", "unlock", "close"]


def test_promotion_main_holds_lock_across_backup_replace_and_smoke(
    valid_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle.generate_manifest(valid_root, SEASON)
    events: list[str] = []

    @contextmanager
    def locked(_config):
        events.append("lock")
        yield
        events.append("unlock")

    class ReplacementConnection:
        def __enter__(self):
            events.append("replacement-connect")
            return self

        def __exit__(self, *_args) -> None:
            events.append("replacement-close")

    monkeypatch.setattr(lifecycle, "production_db_config", lambda *_args: {"host": "remote"})
    monkeypatch.setattr(lifecycle, "promotion_operation_lock", locked)
    monkeypatch.setattr(lifecycle, "create_backup", lambda *_args: events.append("backup"))
    monkeypatch.setattr(lifecycle.psycopg, "connect", lambda **_config: ReplacementConnection())
    monkeypatch.setattr(
        lifecycle,
        "replace_season",
        lambda *_args, **_kwargs: events.append("replace"),
    )
    monkeypatch.setattr(lifecycle, "verify_live_api", lambda *_args: events.append("smoke"))

    result = lifecycle.main(
        [
            "--clean-root",
            str(valid_root),
            "promote",
            "--season",
            SEASON,
            "--target",
            "production",
            "--confirm-season",
            SEASON,
            "--confirm-single-season",
            "DELETE OTHER SEASONS",
            "--backup-file",
            str(tmp_path / "backup.dump"),
            "--api-url",
            "https://api.example.com",
        ]
    )

    assert result == 0
    assert events == [
        "lock",
        "backup",
        "replacement-connect",
        "replace",
        "replacement-close",
        "smoke",
        "unlock",
    ]


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com",
        "https://user:secret@api.example.com",
        "api.example.com",
        "https:///missing-host",
    ],
)
def test_production_api_url_requires_credential_free_https(url: str) -> None:
    with pytest.raises(lifecycle.PromotionSafetyError, match="credential-free HTTPS"):
        lifecycle._production_api_url(url)


def test_local_load_refuses_any_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://owner:secret@db.example.com/nba")

    with pytest.raises(lifecycle.PromotionSafetyError, match="DATABASE_URL.*unset"):
        lifecycle.local_db_config()


def test_backup_is_real_and_passwords_are_not_in_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "backup.dump"
    monkeypatch.setenv("PRODUCTION_DATABASE_URL", "postgresql://owner:secret@db/nba")
    monkeypatch.setenv("DATABASE_URL", "postgresql://owner:other-secret@db/nba")

    def runner(command, **kwargs):
        assert "secret" not in " ".join(command)
        assert "tls-secret" not in " ".join(command)
        assert kwargs["env"]["PGPASSWORD"] == "secret"
        assert kwargs["env"]["PGSSLPASSWORD"] == "tls-secret"
        assert "PRODUCTION_DATABASE_URL" not in kwargs["env"]
        assert "DATABASE_URL" not in kwargs["env"]
        assert Path(command[command.index("--file") + 1]).stat().st_mode & 0o777 == 0o600
        Path(command[command.index("--file") + 1]).write_bytes(b"valid dump")
        return SimpleNamespace(returncode=0)

    lifecycle.create_backup(
        {
            "host": "db.example.com",
            "dbname": "nba",
            "user": "owner",
            "password": "secret",
            "sslpassword": "tls-secret",
        },
        output,
        runner,
    )

    assert output.read_bytes() == b"valid dump"
    assert output.stat().st_mode & 0o777 == 0o600


def test_backup_requires_existing_private_parent(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    public.chmod(0o755)
    with pytest.raises(lifecycle.PromotionSafetyError, match="group or other"):
        lifecycle.create_backup({"host": "db.example.com", "dbname": "nba"}, public / "backup.dump")
    with pytest.raises(lifecycle.PromotionSafetyError, match="existing"):
        lifecycle.create_backup(
            {"host": "db.example.com", "dbname": "nba"},
            tmp_path / "missing" / "backup.dump",
        )


def test_backup_failure_aborts_and_removes_partial_file(tmp_path: Path) -> None:
    output = tmp_path / "backup.dump"

    def runner(command, **_kwargs):
        Path(command[command.index("--file") + 1]).write_bytes(b"partial")
        return SimpleNamespace(returncode=1)

    with pytest.raises(lifecycle.PromotionSafetyError, match="did not create"):
        lifecycle.create_backup({"host": "db.example.com", "dbname": "nba"}, output, runner)
    assert not output.exists()
    assert not (tmp_path / "backup.dump.tmp").exists()


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.body


def smoke_response(url: str, *, listed_game_id: str = GAME_ID) -> FakeResponse:
    if url.endswith("/health"):
        return FakeResponse({"status": "healthy", "database": "connected"})
    if url.endswith("/api/seasons"):
        return FakeResponse([{"id": SEASON, "games_count": 1}])
    if url.endswith(f"/api/games/{GAME_ID}/boxscore"):
        return FakeResponse(
            {
                "game": {"id": GAME_ID},
                "home_team_stats": {},
                "away_team_stats": {},
                "home_players": [{"player_id": PLAYER_ONE}],
                "away_players": [{"player_id": PLAYER_TWO}],
            }
        )
    if url.endswith("/api/standings"):
        return FakeResponse(
            [
                {"season": SEASON, "team_id": LAKERS},
                {"season": SEASON, "team_id": CELTICS},
            ]
        )
    if url.endswith("/api/leaders/points"):
        return FakeResponse({"stat": "points", "season": SEASON, "data": []})
    return FakeResponse({"total": 1, "data": [{"id": listed_game_id}]})


def test_live_api_smoke_is_bounded_and_checks_counts(valid_root: Path) -> None:
    dataset = lifecycle.load_validated_dataset(valid_root, SEASON)
    calls: list[str] = []

    def get(url, **_kwargs):
        calls.append(url)
        return smoke_response(url)

    lifecycle.verify_live_api(
        "https://api.example.com/", dataset, get=get, attempts=1, sleep=lambda _seconds: None
    )

    assert len(calls) == 6
    assert calls[0] == "https://api.example.com/health"


def test_live_api_smoke_retries_transient_failures(valid_root: Path) -> None:
    dataset = lifecycle.load_validated_dataset(valid_root, SEASON)
    calls = 0
    sleeps: list[float] = []

    def get(url, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("temporary failure")
        return smoke_response(url)

    lifecycle.verify_live_api(
        "https://api.example.com",
        dataset,
        get=get,
        attempts=2,
        sleep=sleeps.append,
    )

    assert calls == 7
    assert sleeps == [2]


def test_live_api_smoke_failure_is_bounded(valid_root: Path) -> None:
    dataset = lifecycle.load_validated_dataset(valid_root, SEASON)
    calls = 0
    sleeps: list[float] = []

    def get(_url, **_kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse({"status": "unhealthy"})

    with pytest.raises(lifecycle.SeasonLifecycleError, match="failed after the database commit"):
        lifecycle.verify_live_api(
            "https://api.example.com",
            dataset,
            get=get,
            attempts=3,
            sleep=sleeps.append,
        )

    assert calls == 3
    assert sleeps == [2, 2]


def test_live_api_smoke_rejects_wrong_game_identity(valid_root: Path) -> None:
    dataset = lifecycle.load_validated_dataset(valid_root, SEASON)

    def get(url, **_kwargs):
        return smoke_response(url, listed_game_id="0022599999")

    with pytest.raises(
        lifecycle.SeasonLifecycleError, match="failed after the database commit"
    ) as exc_info:
        lifecycle.verify_live_api(
            "https://api.example.com",
            dataset,
            get=get,
            attempts=1,
            sleep=lambda _seconds: None,
        )

    assert exc_info.value.__cause__ is not None
    assert "games response" in str(exc_info.value.__cause__)
