#!/usr/bin/env python3
"""
NBA Data Extract Script
Downloads team, player, game, and shot-location data from nba_api.

Endpoints used:
- teams.get_teams() - Static team data
- CommonAllPlayers - All players
- LeagueGameLog (Teams) - Games with scores, dates, team stats
- LeagueGameLog (Players) - Player game stats
- ShotChartDetail - League-wide shot attempts and court locations

Usage:
    python extract.py                    # Verified product default
    python extract.py --season 2025-26   # Explicit season
"""

import argparse
import json
import os
import re
import sys
import time

from nba_api.stats.endpoints import CommonAllPlayers, LeagueGameLog, ShotChartDetail
from nba_api.stats.static import teams

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from nba_config import DEFAULT_SEASON  # noqa: E402

BASE_DATA_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
SEASON_TYPE = "Regular Season"
REQUEST_DELAY = 0.6
SEASON_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")


def validate_season_argument(season: str) -> None:
    match = SEASON_PATTERN.fullmatch(season)
    if not match or int(match.group(2)) != (int(match.group(1)) + 1) % 100:
        raise ValueError("season must use the safe consecutive-year format YYYY-YY")


def get_season_dir(season):
    return os.path.join(BASE_DATA_DIR, season)


def get_shared_dir():
    return os.path.join(BASE_DATA_DIR, "shared")


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def save_json(data, filepath):
    temp_path = filepath + ".tmp"
    with open(temp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.rename(temp_path, filepath)
    print(f"    Saved: {os.path.basename(filepath)}")


def download_teams(force=False):
    """Download static team data."""
    print("\n=== Teams ===")
    shared_dir = get_shared_dir()
    ensure_dir(shared_dir)

    filepath = os.path.join(shared_dir, "teams.json")
    if os.path.exists(filepath) and not force:
        print("  Skipping (exists)")
        return

    data = teams.get_teams()
    save_json(data, filepath)
    print(f"  Found {len(data)} teams")


def download_players(season, force=False):
    """Download all players from CommonAllPlayers."""
    print("\n=== Players ===")
    shared_dir = get_shared_dir()
    ensure_dir(shared_dir)

    filepath = os.path.join(shared_dir, "players.json")
    if os.path.exists(filepath) and not force:
        print("  Skipping (exists)")
        return

    response = CommonAllPlayers(
        is_only_current_season=0,
        league_id="00",
        season=season,
    )
    data = response.get_dict()
    save_json(data, filepath)

    count = len(data.get("resultSets", [{}])[0].get("rowSet", []))
    print(f"  Found {count} players")
    time.sleep(REQUEST_DELAY)


def download_league_game_log(season, force=False):
    """Download LeagueGameLog for teams and players."""
    print("\n=== LeagueGameLog ===")
    season_dir = get_season_dir(season)
    ensure_dir(season_dir)

    for player_or_team, label in [("T", "teams"), ("P", "players")]:
        filepath = os.path.join(season_dir, f"league_game_log_{label}.json")

        if os.path.exists(filepath) and not force:
            print(f"  Skipping {label} (exists)")
            continue

        print(f"  Fetching {label}...")
        response = LeagueGameLog(
            season=season,
            season_type_all_star=SEASON_TYPE,
            player_or_team_abbreviation=player_or_team,
        )
        data = response.get_dict()
        save_json(data, filepath)

        count = len(data.get("resultSets", [{}])[0].get("rowSet", []))
        print(f"  Found {count} {label} game records")
        time.sleep(REQUEST_DELAY)


def download_shot_chart(season, force=False):
    """Download every regular-season attempt through bounded per-team queries."""
    print("\n=== ShotChartDetail ===")
    season_dir = get_season_dir(season)
    ensure_dir(season_dir)
    filepath = os.path.join(season_dir, "shot_chart.json")

    if os.path.exists(filepath) and not force:
        print("  Skipping shots (exists)")
        return

    # A team_id=0 league query is silently capped at 102,400 rows. Team-sized
    # responses remain comfortably below that limit, and each attempt belongs
    # to exactly one team, so combining all 30 responses is complete and unique.
    team_rows = sorted(teams.get_teams(), key=lambda team: team["id"])
    combined_headers = None
    combined_rows = []
    for index, team in enumerate(team_rows, start=1):
        team_id = int(team["id"])
        print(f"  Fetching {team['abbreviation']} ({index}/{len(team_rows)})...")
        response = ShotChartDetail(
            team_id=team_id,
            player_id=0,
            context_measure_simple="FGA",
            league_id="00",
            season_nullable=season,
            season_type_all_star=SEASON_TYPE,
            timeout=120,
        )
        data = response.get_dict()
        result_sets = data.get("resultSets", [])
        if not result_sets:
            raise RuntimeError(f"ShotChartDetail returned no result set for team {team_id}")
        detail = result_sets[0]
        headers = detail.get("headers", [])
        rows = detail.get("rowSet", [])
        if not headers or not rows:
            raise RuntimeError(f"ShotChartDetail returned no attempts for team {team_id}")
        if combined_headers is None:
            combined_headers = headers
        elif headers != combined_headers:
            raise RuntimeError("ShotChartDetail headers changed between team responses")
        team_id_index = headers.index("TEAM_ID")
        if any(int(row[team_id_index]) != team_id for row in rows):
            raise RuntimeError(f"ShotChartDetail mixed team IDs for team {team_id}")
        combined_rows.extend(rows)
        if index < len(team_rows):
            time.sleep(REQUEST_DELAY)

    output = {
        "resultSets": [
            {
                "name": "Shot_Chart_Detail",
                "headers": combined_headers,
                "rowSet": combined_rows,
            }
        ]
    }
    save_json(output, filepath)
    print(f"  Found {len(combined_rows)} shot attempts across {len(team_rows)} teams")


def main():
    parser = argparse.ArgumentParser(description="Download NBA data")
    parser.add_argument(
        "--season", default=DEFAULT_SEASON, help=f"Season (default: {DEFAULT_SEASON})"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download files even if they already exist",
    )
    args = parser.parse_args()

    season = args.season
    try:
        validate_season_argument(season)
    except ValueError as exc:
        parser.error(str(exc))
    print("=" * 50)
    print(f"NBA Data Extract - Season {season}")
    print("=" * 50)

    download_teams(force=args.force)
    download_players(season, force=args.force)
    download_league_game_log(season, force=args.force)
    download_shot_chart(season, force=args.force)

    print("\n" + "=" * 50)
    print("Extract complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
