#!/usr/bin/env python3
"""
NBA Data Download Script
Downloads static team/player data and game logs from nba_api

Usage:
    python extract.py                    # Default season (2024-25)
    python extract.py --season 2023-24   # Specific season
"""

import argparse
import json
import os
import time

# Endpoints
from nba_api.stats.endpoints import (
    BoxScoreAdvancedV3,
    BoxScoreTraditionalV3,
    CommonAllPlayers,
    LeagueGameLog,
    PlayerGameLogs,
    ShotChartDetail,
)

# Static data
from nba_api.stats.static import teams

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BASE_DATA_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
DEFAULT_SEASON = "2024-25"
SEASON_TYPE = "Regular Season"
REQUEST_DELAY = 0.6  # Delay between API calls to avoid rate limiting


def get_season_dir(season):
    """Get the data directory for a specific season."""
    return os.path.join(BASE_DATA_DIR, season)


def get_shared_dir():
    """Get the shared data directory (teams, players)."""
    return os.path.join(BASE_DATA_DIR, "shared")


def ensure_dir(path):
    """Create directory if it doesn't exist."""
    os.makedirs(path, exist_ok=True)


def save_json(data, filepath):
    """Save data to JSON file atomically.

    Writes to a temp file first, then renames. This prevents corrupted
    files from interrupted downloads (empty or partial files).
    """
    temp_path = filepath + ".tmp"
    with open(temp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.rename(temp_path, filepath)  # Atomic on same filesystem
    print(f"  Saved: {filepath}")


def download_static_data(season):
    """Download teams (static) and players (live API) data."""
    print("\n=== Downloading Static Data ===")
    shared_dir = get_shared_dir()
    ensure_dir(shared_dir)

    # Teams (static is fine, rarely changes)
    teams_path = os.path.join(shared_dir, "teams.json")
    if os.path.exists(teams_path):
        print("  Skipping teams (already exists)")
        all_teams = json.load(open(teams_path))
    else:
        all_teams = teams.get_teams()
        save_json(all_teams, teams_path)
        print(f"  Found {len(all_teams)} teams")

    # Players (use live API to get all-time players)
    players_path = os.path.join(shared_dir, "players.json")
    if os.path.exists(players_path):
        print("  Skipping players (already exists)")
        players_data = json.load(open(players_path))
    else:
        print("  Fetching players from CommonAllPlayers API...")
        players_response = CommonAllPlayers(
            is_only_current_season=0,  # 0 = all players, 1 = current season only
            league_id="00",
            season=season,
        )
        players_data = players_response.get_dict()
        save_json(players_data, players_path)

        # Count players from response
        player_count = len(players_data.get("resultSets", [{}])[0].get("rowSet", []))
        print(f"  Found {player_count} players")
        time.sleep(REQUEST_DELAY)

    return all_teams, players_data


def download_league_game_log(season):
    """Download LeagueGameLog data."""
    print("\n=== Downloading LeagueGameLog ===")
    season_dir = get_season_dir(season)
    output_dir = os.path.join(season_dir, "LeagueGameLog")
    ensure_dir(output_dir)

    for player_or_team in ["T", "P"]:  # T=Team, P=Player
        label = "team" if player_or_team == "T" else "player"
        filepath = os.path.join(output_dir, f"league_game_log_{label}s.json")

        if os.path.exists(filepath):
            print(f"  Skipping {label} game logs (already exists)")
            continue

        print(f"  Fetching {label} game logs...")

        game_log = LeagueGameLog(
            season=season,
            season_type_all_star=SEASON_TYPE,
            player_or_team_abbreviation=player_or_team,
        )

        data = game_log.get_dict()
        save_json(data, filepath)
        time.sleep(REQUEST_DELAY)


def download_player_game_logs(season):
    """Download PlayerGameLogs data."""
    print("\n=== Downloading PlayerGameLogs ===")
    season_dir = get_season_dir(season)
    output_dir = os.path.join(season_dir, "PlayerGameLogs")
    ensure_dir(output_dir)

    filepath = os.path.join(output_dir, "player_game_logs.json")
    if os.path.exists(filepath):
        print("  Skipping player game logs (already exists)")
        return

    player_logs = PlayerGameLogs(
        season_nullable=season,
        season_type_nullable=SEASON_TYPE,
    )

    data = player_logs.get_dict()
    save_json(data, filepath)
    time.sleep(REQUEST_DELAY)


def get_game_ids_from_league_log(season):
    """Extract game IDs from saved league game log."""
    season_dir = get_season_dir(season)
    filepath = os.path.join(season_dir, "LeagueGameLog", "league_game_log_teams.json")

    if not os.path.exists(filepath):
        print("  League game log not found, downloading first...")
        download_league_game_log(season)

    with open(filepath) as f:
        data = json.load(f)

    # Extract unique game IDs
    headers = data["resultSets"][0]["headers"]
    rows = data["resultSets"][0]["rowSet"]
    game_id_idx = headers.index("GAME_ID")

    game_ids = list({row[game_id_idx] for row in rows})
    return sorted(game_ids)


def download_box_scores(season, game_ids, max_games=None):
    """Download BoxScoreTraditionalV3 and BoxScoreAdvancedV3 for games."""
    print("\n=== Downloading Box Scores ===")
    season_dir = get_season_dir(season)

    trad_dir = os.path.join(season_dir, "BoxScoreTraditionalV3")
    adv_dir = os.path.join(season_dir, "BoxScoreAdvancedV3")
    ensure_dir(trad_dir)
    ensure_dir(adv_dir)

    # Limit number of games to avoid too many requests
    games_to_fetch = game_ids[:max_games] if max_games else game_ids
    print(
        f"  Fetching box scores for {len(games_to_fetch)} games (limited from {len(game_ids)} total)..."
    )

    for i, game_id in enumerate(games_to_fetch):
        trad_path = os.path.join(trad_dir, f"{game_id}.json")
        adv_path = os.path.join(adv_dir, f"{game_id}.json")

        if os.path.exists(trad_path) and os.path.exists(adv_path):
            print(f"  [{i + 1}/{len(games_to_fetch)}] Skipping {game_id} (already exists)")
            continue

        print(f"  [{i + 1}/{len(games_to_fetch)}] Game {game_id}")

        try:
            # Traditional box score
            if not os.path.exists(trad_path):
                trad_box = BoxScoreTraditionalV3(game_id=game_id)
                save_json(trad_box.get_dict(), trad_path)
                time.sleep(REQUEST_DELAY)

            # Advanced box score
            if not os.path.exists(adv_path):
                adv_box = BoxScoreAdvancedV3(game_id=game_id)
                save_json(adv_box.get_dict(), adv_path)
                time.sleep(REQUEST_DELAY)

        except Exception as e:
            print(f"    Error fetching game {game_id}: {e}")
            continue


def download_shot_chart_detail(season, players_data, max_players=None):
    """Download ShotChartDetail for players."""
    print("\n=== Downloading ShotChartDetail ===")
    season_dir = get_season_dir(season)
    output_dir = os.path.join(season_dir, "ShotChartDetail")
    ensure_dir(output_dir)

    # Handle both old static format (list) and new API format (resultSets)
    if isinstance(players_data, list):
        # Old format: list of dicts
        all_players = players_data
        active_players = [p for p in all_players if p.get("is_active", False)]
    else:
        # New CommonAllPlayers format: extract from resultSets
        result_set = players_data.get("resultSets", [{}])[0]
        headers = result_set.get("headers", [])
        rows = result_set.get("rowSet", [])

        # Find column indices
        id_idx = headers.index("PERSON_ID") if "PERSON_ID" in headers else 0
        name_idx = headers.index("DISPLAY_FIRST_LAST") if "DISPLAY_FIRST_LAST" in headers else 1
        status_idx = headers.index("ROSTERSTATUS") if "ROSTERSTATUS" in headers else 2

        # Convert to list of dicts and filter active players (ROSTERSTATUS = 1)
        active_players = [
            {"id": row[id_idx], "full_name": row[name_idx]} for row in rows if row[status_idx] == 1
        ]

    players_to_fetch = active_players[:max_players] if max_players else active_players

    print(
        f"  Fetching shot charts for {len(players_to_fetch)} players (limited from {len(active_players)} active)..."
    )

    for i, player in enumerate(players_to_fetch):
        player_id = player["id"]
        player_name = player["full_name"]
        safe_name = player_name.replace(" ", "_").replace(".", "")
        filepath = os.path.join(output_dir, f"{player_id}_{safe_name}.json")

        if os.path.exists(filepath):
            print(f"  [{i + 1}/{len(players_to_fetch)}] Skipping {player_name} (already exists)")
            continue

        print(f"  [{i + 1}/{len(players_to_fetch)}] {player_name}")

        try:
            shot_chart = ShotChartDetail(
                team_id=0,  # 0 for all teams
                player_id=player_id,
                season_nullable=season,
                season_type_all_star=SEASON_TYPE,
                context_measure_simple="FGA",
            )

            data = shot_chart.get_dict()
            save_json(data, filepath)
            time.sleep(REQUEST_DELAY)

        except Exception as e:
            print(f"    Error fetching shot chart for {player_name}: {e}")
            continue


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Download NBA data from the NBA API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python extract.py                    # Download current season (2024-25)
    python extract.py --season 2023-24   # Download 2023-24 season
    python extract.py --season 2022-23 --max-games 100
        """,
    )
    parser.add_argument(
        "--season",
        default=DEFAULT_SEASON,
        help=f"Season to download (default: {DEFAULT_SEASON})",
    )
    parser.add_argument(
        "--max-games",
        type=int,
        default=None,
        help="Maximum number of games to download box scores for",
    )
    parser.add_argument(
        "--max-players",
        type=int,
        default=None,
        help="Maximum number of players to download shot charts for",
    )
    parser.add_argument(
        "--skip-shots",
        action="store_true",
        help="Skip downloading shot chart data",
    )
    return parser.parse_args()


def cleanup_temp_files(directory):
    """Remove any leftover .tmp files from interrupted downloads."""
    if not os.path.exists(directory):
        return 0
    count = 0
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if f.endswith(".tmp"):
                os.remove(os.path.join(root, f))
                count += 1
    return count


def main():
    args = parse_args()
    season = args.season
    season_dir = get_season_dir(season)

    print("=" * 50)
    print("NBA Data Download Script")
    print(f"Season: {season}")
    print(f"Data Directory: {season_dir}")
    print("=" * 50)

    # Clean up any leftover temp files from interrupted runs
    temp_cleaned = cleanup_temp_files(season_dir)
    temp_cleaned += cleanup_temp_files(get_shared_dir())
    if temp_cleaned > 0:
        print(f"\n  Cleaned up {temp_cleaned} incomplete download(s)")

    # Create directories
    ensure_dir(season_dir)

    # Download static/shared data
    all_teams, all_players = download_static_data(season)

    # Download league game log
    download_league_game_log(season)

    # Download player game logs
    download_player_game_logs(season)

    # Get game IDs for box scores
    game_ids = get_game_ids_from_league_log(season)
    print(f"\n  Found {len(game_ids)} unique games in season")

    # Download box scores
    download_box_scores(season, game_ids, max_games=args.max_games)

    # Download shot chart detail
    if not args.skip_shots:
        download_shot_chart_detail(season, all_players, max_players=args.max_players)
    else:
        print("\n=== Skipping ShotChartDetail (--skip-shots) ===")

    print("\n" + "=" * 50)
    print("Download complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
