"""Offline extraction and transformation coverage for shot-location data."""

import json
from pathlib import Path

import pandas as pd
import pytest

from etl import extract, transform

SEASON = "2025-26"
GAME_ID = "0022500001"


def shot_response() -> dict:
    return {
        "resultSets": [
            {
                "name": "Shot_Chart_Detail",
                "headers": [
                    "GAME_ID",
                    "GAME_EVENT_ID",
                    "PLAYER_ID",
                    "TEAM_ID",
                    "PERIOD",
                    "MINUTES_REMAINING",
                    "SECONDS_REMAINING",
                    "ACTION_TYPE",
                    "SHOT_TYPE",
                    "SHOT_ZONE_BASIC",
                    "SHOT_ZONE_AREA",
                    "SHOT_ZONE_RANGE",
                    "SHOT_DISTANCE",
                    "LOC_X",
                    "LOC_Y",
                    "SHOT_MADE_FLAG",
                ],
                "rowSet": [
                    [
                        GAME_ID,
                        7,
                        2544,
                        1610612747,
                        1,
                        10,
                        42,
                        "Driving Layup Shot",
                        "2PT Field Goal",
                        "Restricted Area",
                        "Center(C)",
                        "Less Than 8 ft.",
                        2,
                        -12,
                        18,
                        1,
                    ]
                ],
            },
            {"name": "LeagueAverages", "headers": [], "rowSet": []},
        ]
    }


def test_extract_requests_bounded_team_shot_charts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []

    class Response:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def get_dict(self) -> dict:
            return shot_response()

    monkeypatch.setattr(extract, "BASE_DATA_DIR", str(tmp_path / "raw"))
    monkeypatch.setattr(extract, "ShotChartDetail", Response)
    monkeypatch.setattr(
        extract.teams,
        "get_teams",
        lambda: [{"id": 1610612747, "abbreviation": "LAL"}],
    )
    monkeypatch.setattr(extract.time, "sleep", lambda _seconds: None)

    extract.download_shot_chart(SEASON, force=True)

    assert calls == [
        {
            "team_id": 1610612747,
            "player_id": 0,
            "context_measure_simple": "FGA",
            "league_id": "00",
            "season_nullable": SEASON,
            "season_type_all_star": "Regular Season",
            "timeout": 120,
        }
    ]
    saved = json.loads((tmp_path / "raw" / SEASON / "shot_chart.json").read_text())
    assert saved["resultSets"][0]["rowSet"] == shot_response()["resultSets"][0]["rowSet"]


def test_extract_reuses_existing_shot_file_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "raw" / SEASON / "shot_chart.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    monkeypatch.setattr(extract, "BASE_DATA_DIR", str(tmp_path / "raw"))
    monkeypatch.setattr(
        extract,
        "ShotChartDetail",
        lambda **_kwargs: pytest.fail("cached extraction must not call the NBA endpoint"),
    )

    extract.download_shot_chart(SEASON)

    assert path.read_text() == "{}"


def test_transform_normalizes_shot_chart_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "raw" / SEASON / "shot_chart.json"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps(shot_response()))
    monkeypatch.setattr(transform, "BASE_RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setattr(transform, "BASE_CLEAN_DIR", str(tmp_path / "clean"))

    transform.transform_shot_attempts(SEASON)

    frame = pd.read_csv(
        tmp_path / "clean" / SEASON / "shot_attempts.csv", dtype={"game_id": "string"}
    )
    assert frame.to_dict("records") == [
        {
            "game_id": GAME_ID,
            "event_id": 7,
            "player_id": 2544,
            "team_id": 1610612747,
            "season": SEASON,
            "period": 1,
            "minutes_remaining": 10,
            "seconds_remaining": 42,
            "action_type": "Driving Layup Shot",
            "shot_type": "2PT Field Goal",
            "zone_basic": "Restricted Area",
            "zone_area": "Center(C)",
            "zone_range": "Less Than 8 ft.",
            "shot_distance": 2,
            "loc_x": -12,
            "loc_y": 18,
            "shot_made": True,
        }
    ]
