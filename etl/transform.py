#!/usr/bin/env python3
"""
NBA Data Transform Script
Transforms raw JSON data into clean CSVs for database loading.

Usage:
    python transform.py                    # Default season (2024-25)
    python transform.py --season 2023-24   # Specific season
"""

import argparse
import json
import os
from glob import glob

import pandas as pd

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BASE_RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
BASE_CLEAN_DIR = os.path.join(PROJECT_ROOT, "data", "clean")
DEFAULT_SEASON = "2024-25"


def get_season_raw_dir(season):
    """Get the raw data directory for a specific season."""
    return os.path.join(BASE_RAW_DIR, season)


def get_season_clean_dir(season):
    """Get the clean data directory for a specific season."""
    return os.path.join(BASE_CLEAN_DIR, season)


def get_shared_raw_dir():
    """Get the shared raw data directory."""
    return os.path.join(BASE_RAW_DIR, "shared")


def get_shared_clean_dir():
    """Get the shared clean data directory."""
    return os.path.join(BASE_CLEAN_DIR, "shared")


def ensure_dir(path):
    """Create directory if it doesn't exist."""
    os.makedirs(path, exist_ok=True)


def load_json(filepath):
    """Load JSON file."""
    with open(filepath) as f:
        return json.load(f)


def save_csv(df, filepath):
    """Save DataFrame to CSV."""
    df.to_csv(filepath, index=False)
    print(f"  Saved: {filepath} ({len(df)} rows)")


def transform_teams():
    """Transform teams.json to teams.csv."""
    print("\n=== Transforming Teams ===")
    shared_raw = get_shared_raw_dir()
    shared_clean = get_shared_clean_dir()
    ensure_dir(shared_clean)

    filepath = os.path.join(shared_raw, "teams.json")

    if not os.path.exists(filepath):
        print("  Skipping: teams.json not found")
        return

    teams = load_json(filepath)
    df = pd.DataFrame(teams)
    save_csv(df, os.path.join(shared_clean, "teams.csv"))


def transform_players():
    """Transform players.json to players.csv."""
    print("\n=== Transforming Players ===")
    shared_raw = get_shared_raw_dir()
    shared_clean = get_shared_clean_dir()
    ensure_dir(shared_clean)

    filepath = os.path.join(shared_raw, "players.json")

    if not os.path.exists(filepath):
        print("  Skipping: players.json not found")
        return

    data = load_json(filepath)

    # Handle both old static format (list of dicts) and new API format (resultSets)
    if isinstance(data, list):
        # Old static format: [{"id": ..., "full_name": ..., ...}, ...]
        df = pd.DataFrame(data)
    else:
        # New CommonAllPlayers API format: {"resultSets": [{"headers": [...], "rowSet": [...]}]}
        result_set = data.get("resultSets", [{}])[0]
        headers = result_set.get("headers", [])
        rows = result_set.get("rowSet", [])
        df = pd.DataFrame(rows, columns=headers)

        # Map CommonAllPlayers columns to expected output format
        df = df.rename(
            columns={
                "PERSON_ID": "id",
                "DISPLAY_FIRST_LAST": "full_name",
            }
        )

        # Extract first/last name from DISPLAY_FIRST_LAST
        df["first_name"] = df["full_name"].apply(
            lambda x: x.split(" ")[0] if isinstance(x, str) else ""
        )
        df["last_name"] = df["full_name"].apply(
            lambda x: " ".join(x.split(" ")[1:]) if isinstance(x, str) else ""
        )

        # ROSTERSTATUS: 1 = active, 0 = inactive
        df["is_active"] = df["ROSTERSTATUS"].apply(lambda x: x == 1)

        # Select only needed columns
        df = df[["id", "full_name", "first_name", "last_name", "is_active"]]

    save_csv(df, os.path.join(shared_clean, "players.csv"))


def transform_box_scores(season):
    """Transform BoxScoreTraditionalV3 and BoxScoreAdvancedV3 into games, player_box_scores, and team_box_scores CSVs."""
    print("\n=== Transforming Box Scores ===")

    season_raw = get_season_raw_dir(season)
    season_clean = get_season_clean_dir(season)
    ensure_dir(season_clean)

    trad_dir = os.path.join(season_raw, "BoxScoreTraditionalV3")
    adv_dir = os.path.join(season_raw, "BoxScoreAdvancedV3")

    trad_files = glob(os.path.join(trad_dir, "*.json"))

    if not trad_files:
        print("  Skipping: No box score files found")
        return

    print(f"  Processing {len(trad_files)} box score files...")

    games = []
    player_stats = []
    team_stats = []

    for trad_file in trad_files:
        game_id = os.path.basename(trad_file).replace(".json", "")
        adv_file = os.path.join(adv_dir, f"{game_id}.json")

        trad_data = load_json(trad_file)
        adv_data = load_json(adv_file) if os.path.exists(adv_file) else None

        # Extract game info from traditional box score
        game_info = extract_game_info(game_id, trad_data)
        if game_info:
            games.append(game_info)

        # Extract player stats
        player_rows = extract_player_stats(game_id, trad_data, adv_data)
        player_stats.extend(player_rows)

        # Extract team stats
        team_rows = extract_team_stats(game_id, trad_data, adv_data)
        team_stats.extend(team_rows)

    # Save CSVs
    if games:
        df_games = pd.DataFrame(games)
        df_games["season"] = season
        save_csv(df_games, os.path.join(season_clean, "games.csv"))

    if player_stats:
        df_players = pd.DataFrame(player_stats)
        df_players["season"] = season
        save_csv(df_players, os.path.join(season_clean, "player_box_scores.csv"))

    if team_stats:
        df_teams = pd.DataFrame(team_stats)
        df_teams["season"] = season
        save_csv(df_teams, os.path.join(season_clean, "team_box_scores.csv"))


def extract_game_info(game_id, trad_data):
    """Extract game-level info from box score."""
    try:
        # Game info is typically in the boxScoreTraditional response
        box_score = trad_data.get("boxScoreTraditional", trad_data)

        game_info = {"game_id": game_id}

        # Try to get game metadata
        if "gameId" in box_score:
            game_info["game_id"] = box_score["gameId"]

        # Extract team info to get home/away
        if "homeTeam" in box_score:
            home = box_score["homeTeam"]
            game_info["home_team_id"] = home.get("teamId")
            game_info["home_team_tricode"] = home.get("teamTricode")
            game_info["home_score"] = home.get("statistics", {}).get("points")

        if "awayTeam" in box_score:
            away = box_score["awayTeam"]
            game_info["away_team_id"] = away.get("teamId")
            game_info["away_team_tricode"] = away.get("teamTricode")
            game_info["away_score"] = away.get("statistics", {}).get("points")

        return game_info
    except Exception as e:
        print(f"    Error extracting game info for {game_id}: {e}")
        return None


def extract_player_stats(game_id, trad_data, adv_data):
    """Extract player-level stats from box scores."""
    rows = []

    try:
        box_score = trad_data.get("boxScoreTraditional", trad_data)
        adv_box = adv_data.get("boxScoreAdvanced", adv_data) if adv_data else None

        # Build lookup for advanced stats by player_id
        adv_lookup = {}
        if adv_box:
            for team_key in ["homeTeam", "awayTeam"]:
                if team_key in adv_box and "players" in adv_box[team_key]:
                    for player in adv_box[team_key]["players"]:
                        pid = player.get("personId")
                        if pid:
                            adv_lookup[pid] = player.get("statistics", {})

        # Process traditional stats
        for team_key in ["homeTeam", "awayTeam"]:
            if team_key not in box_score:
                continue

            team_data = box_score[team_key]
            team_id = team_data.get("teamId")
            team_tricode = team_data.get("teamTricode")

            if "players" not in team_data:
                continue

            for player in team_data["players"]:
                player_id = player.get("personId")
                stats = player.get("statistics", {})

                row = {
                    "game_id": game_id,
                    "player_id": player_id,
                    "team_id": team_id,
                    "team_tricode": team_tricode,
                    "name": player.get("name"),
                    "position": player.get("position"),
                    "starter": player.get("starter"),
                    # Traditional stats
                    "minutes": stats.get("minutes"),
                    "points": stats.get("points"),
                    "rebounds": stats.get("reboundsTotal"),
                    "offensive_rebounds": stats.get("reboundsOffensive"),
                    "defensive_rebounds": stats.get("reboundsDefensive"),
                    "assists": stats.get("assists"),
                    "steals": stats.get("steals"),
                    "blocks": stats.get("blocks"),
                    "turnovers": stats.get("turnovers"),
                    "personal_fouls": stats.get("foulsPersonal"),
                    "fgm": stats.get("fieldGoalsMade"),
                    "fga": stats.get("fieldGoalsAttempted"),
                    "fg_pct": stats.get("fieldGoalsPercentage"),
                    "fg3m": stats.get("threePointersMade"),
                    "fg3a": stats.get("threePointersAttempted"),
                    "fg3_pct": stats.get("threePointersPercentage"),
                    "ftm": stats.get("freeThrowsMade"),
                    "fta": stats.get("freeThrowsAttempted"),
                    "ft_pct": stats.get("freeThrowsPercentage"),
                    "plus_minus": stats.get("plusMinusPoints"),
                }

                # Merge advanced stats if available
                if player_id in adv_lookup:
                    adv_stats = adv_lookup[player_id]
                    row.update(
                        {
                            "offensive_rating": adv_stats.get("offensiveRating"),
                            "defensive_rating": adv_stats.get("defensiveRating"),
                            "net_rating": adv_stats.get("netRating"),
                            "ast_pct": adv_stats.get("assistPercentage"),
                            "ast_ratio": adv_stats.get("assistRatio"),
                            "reb_pct": adv_stats.get("reboundPercentage"),
                            "ts_pct": adv_stats.get("trueShootingPercentage"),
                            "usg_pct": adv_stats.get("usagePercentage"),
                            "pace": adv_stats.get("pace"),
                            "pie": adv_stats.get("pie"),
                        }
                    )

                rows.append(row)

    except Exception as e:
        print(f"    Error extracting player stats for {game_id}: {e}")

    return rows


def extract_team_stats(game_id, trad_data, adv_data):
    """Extract team-level stats from box scores."""
    rows = []

    try:
        box_score = trad_data.get("boxScoreTraditional", trad_data)
        adv_box = adv_data.get("boxScoreAdvanced", adv_data) if adv_data else None

        # Build lookup for advanced team stats
        adv_lookup = {}
        if adv_box:
            for team_key in ["homeTeam", "awayTeam"]:
                if team_key in adv_box:
                    team_data = adv_box[team_key]
                    tid = team_data.get("teamId")
                    if tid:
                        adv_lookup[tid] = team_data.get("statistics", {})

        for team_key in ["homeTeam", "awayTeam"]:
            if team_key not in box_score:
                continue

            team_data = box_score[team_key]
            team_id = team_data.get("teamId")
            stats = team_data.get("statistics", {})

            row = {
                "game_id": game_id,
                "team_id": team_id,
                "team_tricode": team_data.get("teamTricode"),
                "is_home": team_key == "homeTeam",
                # Traditional stats
                "points": stats.get("points"),
                "rebounds": stats.get("reboundsTotal"),
                "offensive_rebounds": stats.get("reboundsOffensive"),
                "defensive_rebounds": stats.get("reboundsDefensive"),
                "assists": stats.get("assists"),
                "steals": stats.get("steals"),
                "blocks": stats.get("blocks"),
                "turnovers": stats.get("turnovers"),
                "personal_fouls": stats.get("foulsPersonal"),
                "fgm": stats.get("fieldGoalsMade"),
                "fga": stats.get("fieldGoalsAttempted"),
                "fg_pct": stats.get("fieldGoalsPercentage"),
                "fg3m": stats.get("threePointersMade"),
                "fg3a": stats.get("threePointersAttempted"),
                "fg3_pct": stats.get("threePointersPercentage"),
                "ftm": stats.get("freeThrowsMade"),
                "fta": stats.get("freeThrowsAttempted"),
                "ft_pct": stats.get("freeThrowsPercentage"),
            }

            # Merge advanced stats if available
            if team_id in adv_lookup:
                adv_stats = adv_lookup[team_id]
                row.update(
                    {
                        "offensive_rating": adv_stats.get("offensiveRating"),
                        "defensive_rating": adv_stats.get("defensiveRating"),
                        "net_rating": adv_stats.get("netRating"),
                        "pace": adv_stats.get("pace"),
                        "pie": adv_stats.get("pie"),
                    }
                )

            rows.append(row)

    except Exception as e:
        print(f"    Error extracting team stats for {game_id}: {e}")

    return rows


def transform_shots(season):
    """Transform ShotChartDetail files into shots.csv."""
    print("\n=== Transforming Shot Charts ===")

    season_raw = get_season_raw_dir(season)
    season_clean = get_season_clean_dir(season)
    ensure_dir(season_clean)

    shot_dir = os.path.join(season_raw, "ShotChartDetail")
    shot_files = glob(os.path.join(shot_dir, "*.json"))

    if not shot_files:
        print("  Skipping: No shot chart files found")
        return

    print(f"  Processing {len(shot_files)} shot chart files...")

    all_shots = []

    for shot_file in shot_files:
        data = load_json(shot_file)

        # Shot data is in resultSets
        result_sets = data.get("resultSets", [])

        for result_set in result_sets:
            if result_set.get("name") == "Shot_Chart_Detail":
                headers = result_set.get("headers", [])
                rows = result_set.get("rowSet", [])

                for row in rows:
                    shot = dict(zip(headers, row, strict=False))
                    all_shots.append(shot)

    if all_shots:
        df = pd.DataFrame(all_shots)
        df["season"] = season
        # Rename columns to snake_case
        df.columns = [c.lower() for c in df.columns]
        save_csv(df, os.path.join(season_clean, "shots.csv"))


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Transform raw NBA data into clean CSVs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python transform.py                    # Transform current season (2024-25)
    python transform.py --season 2023-24   # Transform 2023-24 season
        """,
    )
    parser.add_argument(
        "--season",
        default=DEFAULT_SEASON,
        help=f"Season to transform (default: {DEFAULT_SEASON})",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    season = args.season

    season_raw = get_season_raw_dir(season)
    season_clean = get_season_clean_dir(season)

    print("=" * 50)
    print("NBA Data Transform Script")
    print(f"Season: {season}")
    print(f"Raw Directory: {season_raw}")
    print(f"Clean Directory: {season_clean}")
    print("=" * 50)

    # Create clean directories
    ensure_dir(season_clean)
    ensure_dir(get_shared_clean_dir())

    # Transform shared dimension tables (teams, players)
    transform_teams()
    transform_players()

    # Transform season-specific fact tables
    transform_box_scores(season)
    transform_shots(season)

    print("\n" + "=" * 50)
    print("Transform complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
