#!/usr/bin/env python3
"""
NBA Data Extract Script
Downloads team, player, and game data from nba_api.

Endpoints used:
- teams.get_teams() - Static team data
- CommonAllPlayers - All players
- LeagueGameLog (Teams) - Games with scores, dates, team stats
- LeagueGameLog (Players) - Player game stats

Usage:
    python extract.py                    # Default season (2024-25)
    python extract.py --season 2023-24   # Specific season
"""

import argparse
import json
import os
import re
import time

from nba_api.stats.endpoints import CommonAllPlayers, LeagueGameLog
from nba_api.stats.static import teams

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BASE_DATA_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
DEFAULT_SEASON = "2024-25"
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

    print("\n" + "=" * 50)
    print("Extract complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
