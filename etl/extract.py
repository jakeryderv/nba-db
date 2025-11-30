#!/usr/bin/env python3
"""
NBA Data Download Script
Downloads static team/player data and game logs from nba_api
"""

import os
import json
import time
from datetime import datetime

# Static data
from nba_api.stats.static import teams

# Endpoints
from nba_api.stats.endpoints import (
    CommonAllPlayers,
    LeagueGameLog,
    PlayerGameLogs,
    BoxScoreTraditionalV3,
    BoxScoreAdvancedV3,
    ShotChartDetail,
)

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
SEASON = "2024-25"
SEASON_TYPE = "Regular Season"
REQUEST_DELAY = 0.6  # Delay between API calls to avoid rate limiting


def ensure_dir(path):
    """Create directory if it doesn't exist."""
    os.makedirs(path, exist_ok=True)


def save_json(data, filepath):
    """Save data to JSON file."""
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved: {filepath}")


def download_static_data():
    """Download teams (static) and players (live API) data."""
    print("\n=== Downloading Static Data ===")

    # Teams (static is fine, rarely changes)
    all_teams = teams.get_teams()
    save_json(all_teams, os.path.join(DATA_DIR, "teams.json"))
    print(f"  Found {len(all_teams)} teams")

    # Players (use live API to get current roster)
    print("  Fetching players from CommonAllPlayers API...")
    players_response = CommonAllPlayers(
        is_only_current_season=0,  # 0 = all players, 1 = current season only
        league_id="00",
        season=SEASON,
    )
    players_data = players_response.get_dict()
    save_json(players_data, os.path.join(DATA_DIR, "players.json"))

    # Count players from response
    player_count = len(players_data.get("resultSets", [{}])[0].get("rowSet", []))
    print(f"  Found {player_count} players")
    time.sleep(REQUEST_DELAY)

    return all_teams, players_data


def download_league_game_log():
    """Download LeagueGameLog data."""
    print("\n=== Downloading LeagueGameLog ===")
    output_dir = os.path.join(DATA_DIR, "LeagueGameLog")
    ensure_dir(output_dir)

    for player_or_team in ["T", "P"]:  # T=Team, P=Player
        label = "team" if player_or_team == "T" else "player"
        filepath = os.path.join(output_dir, f"league_game_log_{label}s_{SEASON}.json")

        if os.path.exists(filepath):
            print(f"  Skipping {label} game logs (already exists)")
            continue

        print(f"  Fetching {label} game logs...")

        game_log = LeagueGameLog(
            season=SEASON,
            season_type_all_star=SEASON_TYPE,
            player_or_team_abbreviation=player_or_team,
        )

        data = game_log.get_dict()
        save_json(data, filepath)
        time.sleep(REQUEST_DELAY)


def download_player_game_logs():
    """Download PlayerGameLogs data."""
    print("\n=== Downloading PlayerGameLogs ===")
    output_dir = os.path.join(DATA_DIR, "PlayerGameLogs")
    ensure_dir(output_dir)

    filepath = os.path.join(output_dir, f"player_game_logs_{SEASON}.json")
    if os.path.exists(filepath):
        print("  Skipping player game logs (already exists)")
        return

    player_logs = PlayerGameLogs(
        season_nullable=SEASON,
        season_type_nullable=SEASON_TYPE,
    )

    data = player_logs.get_dict()
    save_json(data, filepath)
    time.sleep(REQUEST_DELAY)


def get_game_ids_from_league_log():
    """Extract game IDs from saved league game log."""
    filepath = os.path.join(
        DATA_DIR, "LeagueGameLog", f"league_game_log_teams_{SEASON}.json"
    )

    if not os.path.exists(filepath):
        print("  League game log not found, downloading first...")
        download_league_game_log()

    with open(filepath) as f:
        data = json.load(f)

    # Extract unique game IDs
    headers = data["resultSets"][0]["headers"]
    rows = data["resultSets"][0]["rowSet"]
    game_id_idx = headers.index("GAME_ID")

    game_ids = list(set(row[game_id_idx] for row in rows))
    return sorted(game_ids)


def download_box_scores(game_ids, max_games=50):
    """Download BoxScoreTraditionalV3 and BoxScoreAdvancedV3 for games."""
    print("\n=== Downloading Box Scores ===")

    trad_dir = os.path.join(DATA_DIR, "BoxScoreTraditionalV3")
    adv_dir = os.path.join(DATA_DIR, "BoxScoreAdvancedV3")
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
            print(
                f"  [{i + 1}/{len(games_to_fetch)}] Skipping {game_id} (already exists)"
            )
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


def download_shot_chart_detail(players_data, max_players=25):
    """Download ShotChartDetail for players."""
    print("\n=== Downloading ShotChartDetail ===")
    output_dir = os.path.join(DATA_DIR, "ShotChartDetail")
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
            {"id": row[id_idx], "full_name": row[name_idx]}
            for row in rows
            if row[status_idx] == 1
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
            print(
                f"  [{i + 1}/{len(players_to_fetch)}] Skipping {player_name} (already exists)"
            )
            continue

        print(f"  [{i + 1}/{len(players_to_fetch)}] {player_name}")

        try:
            shot_chart = ShotChartDetail(
                team_id=0,  # 0 for all teams
                player_id=player_id,
                season_nullable=SEASON,
                season_type_all_star=SEASON_TYPE,
                context_measure_simple="FGA",
            )

            data = shot_chart.get_dict()
            save_json(data, filepath)
            time.sleep(REQUEST_DELAY)

        except Exception as e:
            print(f"    Error fetching shot chart for {player_name}: {e}")
            continue


def main():
    print("=" * 50)
    print("NBA Data Download Script")
    print(f"Season: {SEASON}")
    print(f"Data Directory: {DATA_DIR}")
    print("=" * 50)

    # Create base data directory
    ensure_dir(DATA_DIR)

    # Download static data
    all_teams, all_players = download_static_data()

    # Download league game log
    download_league_game_log()

    # Download player game logs
    download_player_game_logs()

    # Get game IDs for box scores
    game_ids = get_game_ids_from_league_log()
    print(f"\n  Found {len(game_ids)} unique games in season")

    # Download box scores (limited to avoid rate limiting)
    download_box_scores(game_ids, max_games=None)

    # Download shot chart detail (limited to avoid rate limiting)
    download_shot_chart_detail(all_players, max_players=None)

    print("\n" + "=" * 50)
    print("Download complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
