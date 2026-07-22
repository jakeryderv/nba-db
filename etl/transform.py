#!/usr/bin/env python3
"""
NBA Data Transform Script
Transforms raw JSON from nba_api into clean CSVs.

Input: data/raw/{season}/league_game_log_*.json and shot_chart.json
Output: data/clean/{season}/*.csv

Usage:
    python transform.py                    # Default season (2024-25)
    python transform.py --season 2023-24   # Specific season
"""

import argparse
import json
import os
import re

import pandas as pd

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BASE_RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
BASE_CLEAN_DIR = os.path.join(PROJECT_ROOT, "data", "clean")
DEFAULT_SEASON = "2024-25"
SEASON_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")


def validate_season_argument(season: str) -> None:
    match = SEASON_PATTERN.fullmatch(season)
    if not match or int(match.group(2)) != (int(match.group(1)) + 1) % 100:
        raise ValueError("season must use the safe consecutive-year format YYYY-YY")


def get_season_raw_dir(season):
    return os.path.join(BASE_RAW_DIR, season)


def get_season_clean_dir(season):
    return os.path.join(BASE_CLEAN_DIR, season)


def get_shared_raw_dir():
    return os.path.join(BASE_RAW_DIR, "shared")


def get_shared_clean_dir():
    return os.path.join(BASE_CLEAN_DIR, "shared")


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def load_json(filepath):
    with open(filepath) as f:
        return json.load(f)


def save_csv(df, filepath):
    df.to_csv(filepath, index=False)
    print(f"    Saved: {os.path.basename(filepath)} ({len(df)} rows)")


def resultset_to_df(data, index=0):
    """Convert NBA API resultSet to DataFrame."""
    rs = data["resultSets"][index]
    return pd.DataFrame(rs["rowSet"], columns=rs["headers"])


def transform_teams():
    """Transform static teams data."""
    print("\n=== Teams ===")
    shared_raw = get_shared_raw_dir()
    shared_clean = get_shared_clean_dir()
    ensure_dir(shared_clean)

    filepath = os.path.join(shared_raw, "teams.json")
    if not os.path.exists(filepath):
        print("  Skipping: teams.json not found")
        return

    teams = load_json(filepath)
    df = pd.DataFrame(teams)
    df = df.rename(
        columns={
            "id": "id",
            "full_name": "full_name",
            "abbreviation": "abbreviation",
            "nickname": "nickname",
            "city": "city",
            "state": "state",
            "year_founded": "year_founded",
        }
    )
    save_csv(df, os.path.join(shared_clean, "teams.csv"))


def transform_players():
    """Transform CommonAllPlayers data."""
    print("\n=== Players ===")
    shared_raw = get_shared_raw_dir()
    shared_clean = get_shared_clean_dir()
    ensure_dir(shared_clean)

    filepath = os.path.join(shared_raw, "players.json")
    if not os.path.exists(filepath):
        print("  Skipping: players.json not found")
        return

    data = load_json(filepath)
    df = resultset_to_df(data)

    # Parse DISPLAY_LAST_COMMA_FIRST (e.g., "Abdelnaby, Alaa") into first/last names
    def parse_name(name):
        if not name or "," not in name:
            return None, None
        parts = name.split(", ", 1)
        return parts[1] if len(parts) > 1 else None, parts[0]

    df["first_name"] = df["DISPLAY_LAST_COMMA_FIRST"].apply(lambda x: parse_name(x)[0])
    df["last_name"] = df["DISPLAY_LAST_COMMA_FIRST"].apply(lambda x: parse_name(x)[1])

    df = df.rename(
        columns={
            "PERSON_ID": "id",
            "DISPLAY_FIRST_LAST": "full_name",
            "ROSTERSTATUS": "is_active",
        }
    )
    df["is_active"] = df["is_active"] == 1
    df = df[["id", "full_name", "first_name", "last_name", "is_active"]]
    save_csv(df, os.path.join(shared_clean, "players.csv"))


def transform_games(season):
    """Transform LeagueGameLog (Teams) into games."""
    print("\n=== Games ===")
    season_raw = get_season_raw_dir(season)
    season_clean = get_season_clean_dir(season)
    ensure_dir(season_clean)

    filepath = os.path.join(season_raw, "league_game_log_teams.json")
    if not os.path.exists(filepath):
        print("  Skipping: league_game_log_teams.json not found")
        return

    data = load_json(filepath)
    df = resultset_to_df(data)

    # Each game appears twice (once per team), extract unique games
    # Parse matchup to get home/away: "MIL vs. CHI" = MIL home, "MIL @ CHI" = MIL away
    games = []
    seen = set()

    for _, row in df.iterrows():
        game_id = row["GAME_ID"]
        if game_id in seen:
            continue
        seen.add(game_id)

        matchup = row["MATCHUP"]
        team_abbr = row["TEAM_ABBREVIATION"]

        if " vs. " in matchup:
            # Home game for this team
            home_team = team_abbr
            away_team = matchup.split(" vs. ")[1]
        else:
            # Away game for this team
            away_team = team_abbr
            home_team = matchup.split(" @ ")[1]

        # Get scores from both rows for this game
        game_rows = df[df["GAME_ID"] == game_id]
        home_row = game_rows[game_rows["TEAM_ABBREVIATION"] == home_team].iloc[0]
        away_row = game_rows[game_rows["TEAM_ABBREVIATION"] == away_team].iloc[0]

        games.append(
            {
                "id": game_id,
                "game_date": row["GAME_DATE"],
                "season": season,
                "home_team_id": int(home_row["TEAM_ID"]),
                "away_team_id": int(away_row["TEAM_ID"]),
                "home_score": int(home_row["PTS"]),
                "away_score": int(away_row["PTS"]),
            }
        )

    games_columns = [
        "id",
        "game_date",
        "season",
        "home_team_id",
        "away_team_id",
        "home_score",
        "away_score",
    ]
    games_df = pd.DataFrame(games, columns=games_columns)
    save_csv(games_df, os.path.join(season_clean, "games.csv"))


def transform_team_game_stats(season):
    """Transform LeagueGameLog (Teams) into team_game_stats."""
    print("\n=== Team Game Stats ===")
    season_raw = get_season_raw_dir(season)
    season_clean = get_season_clean_dir(season)
    ensure_dir(season_clean)

    filepath = os.path.join(season_raw, "league_game_log_teams.json")
    if not os.path.exists(filepath):
        print("  Skipping: league_game_log_teams.json not found")
        return

    data = load_json(filepath)
    df = resultset_to_df(data)

    # Determine if home or away
    df["is_home"] = df["MATCHUP"].str.contains(" vs. ")

    df = df.rename(
        columns={
            "GAME_ID": "game_id",
            "TEAM_ID": "team_id",
            "MIN": "minutes",
            "FGM": "fgm",
            "FGA": "fga",
            "FG_PCT": "fg_pct",
            "FG3M": "fg3m",
            "FG3A": "fg3a",
            "FG3_PCT": "fg3_pct",
            "FTM": "ftm",
            "FTA": "fta",
            "FT_PCT": "ft_pct",
            "OREB": "offensive_rebounds",
            "DREB": "defensive_rebounds",
            "REB": "rebounds",
            "AST": "assists",
            "STL": "steals",
            "BLK": "blocks",
            "TOV": "turnovers",
            "PF": "personal_fouls",
            "PTS": "points",
            "PLUS_MINUS": "plus_minus",
        }
    )

    df["season"] = season

    columns = [
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
    df = df[columns]
    save_csv(df, os.path.join(season_clean, "team_game_stats.csv"))


def transform_player_game_stats(season):
    """Transform LeagueGameLog (Players) into player_game_stats."""
    print("\n=== Player Game Stats ===")
    season_raw = get_season_raw_dir(season)
    season_clean = get_season_clean_dir(season)
    ensure_dir(season_clean)

    filepath = os.path.join(season_raw, "league_game_log_players.json")
    if not os.path.exists(filepath):
        print("  Skipping: league_game_log_players.json not found")
        return

    data = load_json(filepath)
    df = resultset_to_df(data)

    df = df.rename(
        columns={
            "GAME_ID": "game_id",
            "PLAYER_ID": "player_id",
            "TEAM_ID": "team_id",
            "MIN": "minutes",
            "FGM": "fgm",
            "FGA": "fga",
            "FG_PCT": "fg_pct",
            "FG3M": "fg3m",
            "FG3A": "fg3a",
            "FG3_PCT": "fg3_pct",
            "FTM": "ftm",
            "FTA": "fta",
            "FT_PCT": "ft_pct",
            "OREB": "offensive_rebounds",
            "DREB": "defensive_rebounds",
            "REB": "rebounds",
            "AST": "assists",
            "STL": "steals",
            "BLK": "blocks",
            "TOV": "turnovers",
            "PF": "personal_fouls",
            "PTS": "points",
            "PLUS_MINUS": "plus_minus",
        }
    )

    df["season"] = season

    columns = [
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
    df = df[columns]
    save_csv(df, os.path.join(season_clean, "player_game_stats.csv"))


def transform_shot_attempts(season):
    """Transform ShotChartDetail into one normalized row per field-goal attempt."""
    print("\n=== Shot Attempts ===")
    season_raw = get_season_raw_dir(season)
    season_clean = get_season_clean_dir(season)
    ensure_dir(season_clean)

    filepath = os.path.join(season_raw, "shot_chart.json")
    if not os.path.exists(filepath):
        print("  Skipping: shot_chart.json not found")
        return

    data = load_json(filepath)
    df = resultset_to_df(data)
    df = df.rename(
        columns={
            "GAME_ID": "game_id",
            "GAME_EVENT_ID": "event_id",
            "PLAYER_ID": "player_id",
            "TEAM_ID": "team_id",
            "PERIOD": "period",
            "MINUTES_REMAINING": "minutes_remaining",
            "SECONDS_REMAINING": "seconds_remaining",
            "ACTION_TYPE": "action_type",
            "SHOT_TYPE": "shot_type",
            "SHOT_ZONE_BASIC": "zone_basic",
            "SHOT_ZONE_AREA": "zone_area",
            "SHOT_ZONE_RANGE": "zone_range",
            "SHOT_DISTANCE": "shot_distance",
            "LOC_X": "loc_x",
            "LOC_Y": "loc_y",
            "SHOT_MADE_FLAG": "shot_made",
        }
    )
    df["season"] = season
    df["shot_made"] = df["shot_made"] == 1
    columns = [
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
    save_csv(df[columns], os.path.join(season_clean, "shot_attempts.csv"))


def main():
    parser = argparse.ArgumentParser(description="Transform NBA data")
    parser.add_argument(
        "--season", default=DEFAULT_SEASON, help=f"Season (default: {DEFAULT_SEASON})"
    )
    args = parser.parse_args()

    season = args.season
    try:
        validate_season_argument(season)
    except ValueError as exc:
        parser.error(str(exc))
    print("=" * 50)
    print(f"NBA Data Transform - Season {season}")
    print("=" * 50)

    transform_teams()
    transform_players()
    transform_games(season)
    transform_team_game_stats(season)
    transform_player_game_stats(season)
    transform_shot_attempts(season)

    print("\n" + "=" * 50)
    print("Transform complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
