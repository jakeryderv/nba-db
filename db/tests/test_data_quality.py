#!/usr/bin/env python3
"""Data-quality checks for a loaded, manifested season.

These assert properties of real data rather than of the application, so they run
against a database that holds a manifested season -- the restore drill's restored
production backup, or an operator's local load. They are deliberately excluded
from the application suite, whose fixture seeds two teams and ten games.

Checks are season-scoped. An unscoped count silently mixes seasons once a
database holds more than one, and the reconciliation checks would then compare
one season's recorded provenance against every season's rows.
"""

from __future__ import annotations

from typing import Any

import psycopg


def run_query(conn: psycopg.Connection, query: str, params: tuple = ()) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def run_scalar(conn: psycopg.Connection, query: str, params: tuple = ()) -> Any:
    result = run_query(conn, query, params)
    return result[0][0] if result else None


# =============================================================================
# Provenance
#
# The manifest system exists to guarantee these. Nothing checked them after a
# load, so the entire provenance story was untested surface.
# =============================================================================


def test_season_row_exists(conn, season) -> None:
    exists = run_scalar(conn, "SELECT COUNT(*) FROM seasons WHERE id = %s", (season,))
    assert exists == 1, f"Expected exactly one row for {season}, found {exists}"


def test_verification_status_passed(conn, season) -> None:
    status = run_scalar(conn, "SELECT verification_status FROM seasons WHERE id = %s", (season,))
    assert status == "passed", f"{season} verification status is {status!r}, not 'passed'"


def test_manifest_digest_recorded(conn, season) -> None:
    digest = run_scalar(conn, "SELECT manifest_sha256 FROM seasons WHERE id = %s", (season,))
    assert digest, f"{season} carries no manifest digest"
    assert len(digest) == 64, f"{season} manifest digest is not a SHA-256: {digest!r}"


def test_recorded_game_count_reconciles(conn, season) -> None:
    recorded = run_scalar(conn, "SELECT games_count FROM seasons WHERE id = %s", (season,))
    live = run_scalar(conn, "SELECT COUNT(*) FROM games WHERE season = %s", (season,))
    assert recorded == live, f"{season} records {recorded} games but holds {live}"


def test_recorded_player_count_reconciles(conn, season) -> None:
    recorded = run_scalar(conn, "SELECT players_count FROM seasons WHERE id = %s", (season,))
    live = run_scalar(
        conn,
        "SELECT COUNT(DISTINCT player_id) FROM player_game_stats WHERE season = %s",
        (season,),
    )
    assert recorded == live, f"{season} records {recorded} participating players but holds {live}"


def test_recorded_shot_count_reconciles(conn, season) -> None:
    recorded = run_scalar(conn, "SELECT shot_attempts_count FROM seasons WHERE id = %s", (season,))
    live = run_scalar(conn, "SELECT COUNT(*) FROM shot_attempts WHERE season = %s", (season,))
    assert recorded == live, f"{season} records {recorded} shot attempts but holds {live}"


# =============================================================================
# Row counts
# =============================================================================


def test_teams_not_empty(conn) -> None:
    count = run_scalar(conn, "SELECT COUNT(*) FROM teams")
    assert count == 30, f"Expected 30 NBA teams, found {count}"


def test_players_not_empty(conn) -> None:
    count = run_scalar(conn, "SELECT COUNT(*) FROM players")
    assert count > 0, "Players table is empty"


def test_games_not_empty(conn, season) -> None:
    count = run_scalar(conn, "SELECT COUNT(*) FROM games WHERE season = %s", (season,))
    assert count > 0, f"No games loaded for {season}"


def test_player_game_stats_not_empty(conn, season) -> None:
    count = run_scalar(conn, "SELECT COUNT(*) FROM player_game_stats WHERE season = %s", (season,))
    assert count > 0, f"No player game stats loaded for {season}"


def test_team_game_stats_not_empty(conn, season) -> None:
    count = run_scalar(conn, "SELECT COUNT(*) FROM team_game_stats WHERE season = %s", (season,))
    assert count > 0, f"No team game stats loaded for {season}"


def test_shot_attempts_not_empty(conn, season) -> None:
    count = run_scalar(conn, "SELECT COUNT(*) FROM shot_attempts WHERE season = %s", (season,))
    assert count > 0, f"No shot attempts loaded for {season}"


# =============================================================================
# Referential integrity
# =============================================================================


def test_games_reference_valid_teams(conn, season) -> None:
    orphans = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM games g
        LEFT JOIN teams home ON g.home_team_id = home.id
        LEFT JOIN teams away ON g.away_team_id = away.id
        WHERE g.season = %s AND (home.id IS NULL OR away.id IS NULL)
        """,
        (season,),
    )
    assert orphans == 0, f"Found {orphans} games referencing unknown teams"


def test_player_stats_reference_valid_players(conn, season) -> None:
    orphans = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM player_game_stats pgs
        LEFT JOIN players p ON pgs.player_id = p.id
        WHERE pgs.season = %s AND p.id IS NULL
        """,
        (season,),
    )
    assert orphans == 0, f"Found {orphans} player stats referencing unknown players"


def test_player_stats_reference_valid_games(conn, season) -> None:
    orphans = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM player_game_stats pgs
        LEFT JOIN games g ON pgs.game_id = g.id
        WHERE pgs.season = %s AND g.id IS NULL
        """,
        (season,),
    )
    assert orphans == 0, f"Found {orphans} player stats referencing unknown games"


def test_shot_attempts_reference_valid_games(conn, season) -> None:
    orphans = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM shot_attempts sa
        LEFT JOIN games g ON sa.game_id = g.id
        WHERE sa.season = %s AND g.id IS NULL
        """,
        (season,),
    )
    assert orphans == 0, f"Found {orphans} shot attempts referencing unknown games"


# =============================================================================
# Uniqueness
# =============================================================================

NATURAL_KEYS = {
    "shot_attempts": "game_id, event_id",
    "player_game_stats": "game_id, player_id",
    "team_game_stats": "game_id, team_id",
}


def test_natural_keys_are_enforced_by_constraints(conn) -> None:
    """Assert the uniqueness constraints exist, rather than scanning for duplicates.

    Every natural key here is backed by a primary key or unique constraint, so a
    duplicate row cannot be inserted -- a GROUP BY ... HAVING COUNT(*) > 1 scan
    over 219k rows would be testing PostgreSQL, not the data, and could never
    fail. What can actually happen is a migration dropping a constraint, which
    this catches directly and in constant time.
    """
    rows = run_query(
        conn,
        """
        SELECT c.conrelid::regclass::text AS table_name,
               string_agg(a.attname, ', ' ORDER BY k.ord) AS columns
        FROM pg_constraint c
        CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
        WHERE c.contype IN ('p', 'u')
          AND c.conrelid::regclass::text = ANY(%s)
        GROUP BY c.oid, c.conrelid
        """,
        (list(NATURAL_KEYS),),
    )
    enforced = {(table, columns) for table, columns in rows}
    missing = [
        f"{table} ({columns})"
        for table, columns in NATURAL_KEYS.items()
        if (table, columns) not in enforced
    ]
    assert not missing, f"Natural keys no longer enforced by a constraint: {missing}"


# =============================================================================
# Consistency
# =============================================================================


def test_game_dates_fall_within_the_season(conn, season) -> None:
    """A season labelled 2025-26 cannot contain games from another year.

    A mislabelled or misparsed date is invisible to count reconciliation, which
    only asks how many rows there are, not whether they belong.
    """
    start_year = int(season.split("-")[0])
    outside = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM games
        WHERE season = %s
          AND (game_date < make_date(%s, 8, 1) OR game_date >= make_date(%s, 8, 1))
        """,
        (season, start_year, start_year + 1),
    )
    assert outside == 0, f"Found {outside} games dated outside the {season} season window"


def test_game_dates_are_present(conn, season) -> None:
    missing = run_scalar(
        conn,
        "SELECT COUNT(*) FROM games WHERE season = %s AND game_date IS NULL",
        (season,),
    )
    assert missing == 0, f"Found {missing} games with no date"


def test_game_scores_match_team_stats(conn, season) -> None:
    mismatches = run_scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM games g
        CROSS JOIN LATERAL (
            VALUES
                (g.home_team_id, g.home_score),
                (g.away_team_id, g.away_score)
        ) AS expected(team_id, points)
        LEFT JOIN team_game_stats tgs
            ON tgs.game_id = g.id AND tgs.team_id = expected.team_id
        WHERE g.season = %s AND tgs.points IS DISTINCT FROM expected.points
        """,
        (season,),
    )
    assert mismatches == 0, f"Found {mismatches} game scores disagreeing with team stats"


def test_two_teams_per_game(conn, season) -> None:
    invalid = run_query(
        conn,
        """
        SELECT game_id, COUNT(*) AS team_count
        FROM team_game_stats
        WHERE season = %s
        GROUP BY game_id
        HAVING COUNT(*) != 2
        LIMIT 5
        """,
        (season,),
    )
    assert not invalid, f"Games without exactly two team rows: {invalid}"


def test_player_stats_reasonable_values(conn, season) -> None:
    invalid = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM player_game_stats
        WHERE season = %s
          AND (points < 0 OR rebounds < 0 OR assists < 0
               OR points > 100 OR rebounds > 50 OR assists > 50)
        """,
        (season,),
    )
    assert invalid == 0, f"Found {invalid} player stat rows outside plausible ranges"


def test_shooting_percentages_valid(conn, season) -> None:
    invalid = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM player_game_stats
        WHERE season = %s
          AND ((fg_pct IS NOT NULL AND (fg_pct < 0 OR fg_pct > 1))
               OR (fg3_pct IS NOT NULL AND (fg3_pct < 0 OR fg3_pct > 1))
               OR (ft_pct IS NOT NULL AND (ft_pct < 0 OR ft_pct > 1)))
        """,
        (season,),
    )
    assert invalid == 0, f"Found {invalid} rows with percentages outside 0-1"


def test_shot_totals_match_player_game_stats(conn, season) -> None:
    """Shot detail must reconcile to each player-game FG and 3PT total."""
    mismatches = run_scalar(
        conn,
        """
        WITH shot_totals AS (
            SELECT
                game_id,
                player_id,
                MIN(team_id) AS team_id,
                COUNT(*) AS fga,
                COUNT(*) FILTER (WHERE shot_made) AS fgm,
                COUNT(*) FILTER (WHERE shot_type = '3PT Field Goal') AS fg3a,
                COUNT(*) FILTER (
                    WHERE shot_type = '3PT Field Goal' AND shot_made
                ) AS fg3m
            FROM shot_attempts
            WHERE season = %s
            GROUP BY game_id, player_id
        ),
        season_stats AS (
            SELECT * FROM player_game_stats WHERE season = %s
        )
        SELECT COUNT(*)
        FROM season_stats pgs
        FULL OUTER JOIN shot_totals shots
          ON shots.game_id = pgs.game_id AND shots.player_id = pgs.player_id
        WHERE pgs.game_id IS NULL
           OR (shots.game_id IS NOT NULL AND pgs.team_id IS DISTINCT FROM shots.team_id)
           OR ABS(pgs.fga - COALESCE(shots.fga, 0)) > 1
           OR pgs.fgm IS DISTINCT FROM COALESCE(shots.fgm, 0)
           OR ABS(pgs.fg3a - COALESCE(shots.fg3a, 0)) > 1
           OR pgs.fg3m IS DISTINCT FROM COALESCE(shots.fg3m, 0)
        """,
        (season, season),
    )
    assert mismatches == 0, f"Found {mismatches} player-games where shot detail does not reconcile"


# =============================================================================
# Completeness
# =============================================================================


def test_active_players_have_stats(conn) -> None:
    """Most active players should appear in the loaded season."""
    without_stats = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM players p
        WHERE p.is_active = true
          AND NOT EXISTS (SELECT 1 FROM player_game_stats pgs WHERE pgs.player_id = p.id)
        """,
    )
    total = run_scalar(conn, "SELECT COUNT(*) FROM players WHERE is_active = true")
    threshold = total * 0.5 if total else 0
    assert without_stats < threshold, (
        f"{without_stats}/{total} active players have no stats, over the 50% tolerance"
    )


def test_all_teams_have_games(conn, season) -> None:
    without_games = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM teams t
        WHERE NOT EXISTS (
            SELECT 1 FROM games g
            WHERE g.season = %s AND (g.home_team_id = t.id OR g.away_team_id = t.id)
        )
        """,
        (season,),
    )
    assert without_games == 0, f"Found {without_games} teams with no games in {season}"
