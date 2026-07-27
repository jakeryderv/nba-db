#!/usr/bin/env python3
"""Data-quality checks for a loaded, manifested season.

These are production logic, not tests. Three callers run them: the pytest file
under `db/tests/`, the restore drill through that file, and the promotion path,
which calls them directly on its own connection inside the replacement
transaction so a dataset that fails them is rolled back rather than committed.

That last caller is why they live here. A pytest fixture opens its own
connection, and an uncommitted transaction is invisible to every connection but
the one that opened it -- so the promotion could not reuse checks that could only
be reached through a fixture.

Checks are season-scoped. An unscoped count silently mixes seasons once a
database holds more than one, and the reconciliation checks would then compare
one season's recorded provenance against every season's rows.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
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


def check_season_row_exists(conn, season) -> None:
    exists = run_scalar(conn, "SELECT COUNT(*) FROM seasons WHERE id = %s", (season,))
    assert exists == 1, f"Expected exactly one row for {season}, found {exists}"


def check_verification_status_passed(conn, season) -> None:
    status = run_scalar(conn, "SELECT verification_status FROM seasons WHERE id = %s", (season,))
    assert status == "passed", f"{season} verification status is {status!r}, not 'passed'"


def check_manifest_digest_recorded(conn, season) -> None:
    digest = run_scalar(conn, "SELECT manifest_sha256 FROM seasons WHERE id = %s", (season,))
    assert digest, f"{season} carries no manifest digest"
    assert len(digest) == 64, f"{season} manifest digest is not a SHA-256: {digest!r}"


def check_recorded_game_count_reconciles(conn, season) -> None:
    recorded = run_scalar(conn, "SELECT games_count FROM seasons WHERE id = %s", (season,))
    live = run_scalar(conn, "SELECT COUNT(*) FROM games WHERE season = %s", (season,))
    assert recorded == live, f"{season} records {recorded} games but holds {live}"


def check_recorded_player_count_reconciles(conn, season) -> None:
    recorded = run_scalar(conn, "SELECT players_count FROM seasons WHERE id = %s", (season,))
    live = run_scalar(
        conn,
        "SELECT COUNT(DISTINCT player_id) FROM player_game_stats WHERE season = %s",
        (season,),
    )
    assert recorded == live, f"{season} records {recorded} participating players but holds {live}"


def check_recorded_shot_count_reconciles(conn, season) -> None:
    recorded = run_scalar(conn, "SELECT shot_attempts_count FROM seasons WHERE id = %s", (season,))
    live = run_scalar(conn, "SELECT COUNT(*) FROM shot_attempts WHERE season = %s", (season,))
    assert recorded == live, f"{season} records {recorded} shot attempts but holds {live}"


# =============================================================================
# Row counts
# =============================================================================


def check_teams_not_empty(conn) -> None:
    count = run_scalar(conn, "SELECT COUNT(*) FROM teams")
    assert count == 30, f"Expected 30 NBA teams, found {count}"


def check_players_not_empty(conn) -> None:
    count = run_scalar(conn, "SELECT COUNT(*) FROM players")
    assert count > 0, "Players table is empty"


def check_games_not_empty(conn, season) -> None:
    count = run_scalar(conn, "SELECT COUNT(*) FROM games WHERE season = %s", (season,))
    assert count > 0, f"No games loaded for {season}"


def check_player_game_stats_not_empty(conn, season) -> None:
    count = run_scalar(conn, "SELECT COUNT(*) FROM player_game_stats WHERE season = %s", (season,))
    assert count > 0, f"No player game stats loaded for {season}"


def check_team_game_stats_not_empty(conn, season) -> None:
    count = run_scalar(conn, "SELECT COUNT(*) FROM team_game_stats WHERE season = %s", (season,))
    assert count > 0, f"No team game stats loaded for {season}"


def check_shot_attempts_not_empty(conn, season) -> None:
    count = run_scalar(conn, "SELECT COUNT(*) FROM shot_attempts WHERE season = %s", (season,))
    assert count > 0, f"No shot attempts loaded for {season}"


# =============================================================================
# Referential integrity
# =============================================================================


def check_games_reference_valid_teams(conn, season) -> None:
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


def check_player_stats_reference_valid_players(conn, season) -> None:
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


def check_player_stats_reference_valid_games(conn, season) -> None:
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


def check_shot_attempts_reference_valid_games(conn, season) -> None:
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


def check_natural_keys_are_enforced_by_constraints(conn) -> None:
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


def check_game_dates_fall_within_the_season(conn, season) -> None:
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


def check_game_dates_are_present(conn, season) -> None:
    missing = run_scalar(
        conn,
        "SELECT COUNT(*) FROM games WHERE season = %s AND game_date IS NULL",
        (season,),
    )
    assert missing == 0, f"Found {missing} games with no date"


def check_game_scores_match_team_stats(conn, season) -> None:
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


def check_two_teams_per_game(conn, season) -> None:
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


def check_player_stats_reasonable_values(conn, season) -> None:
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


def check_shooting_percentages_valid(conn, season) -> None:
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


def check_shot_totals_match_player_game_stats(conn, season) -> None:
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


def check_active_players_have_stats(conn) -> None:
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


def check_all_teams_have_games(conn, season) -> None:
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


class DataQualityError(RuntimeError):
    """Raised when loaded data fails one or more quality checks."""


def all_checks() -> list[tuple[str, Callable]]:
    """Every check in this module, discovered rather than listed.

    An explicit list is one edit away from silently omitting a new check, which
    is the failure mode this whole area keeps producing. Discovery means adding a
    `check_` function is enough to have it run everywhere.
    """
    return sorted(
        (name, value)
        for name, value in globals().items()
        if name.startswith("check_") and inspect.isfunction(value)
    )


def run_all_checks(conn: psycopg.Connection, season: str) -> list[str]:
    """Run every check against one connection; raise once with all failures.

    Collects rather than stopping at the first failure: an operator deciding
    whether to abandon a promotion needs the whole picture, not the
    alphabetically first symptom.

    Takes the caller's connection deliberately. Run inside an open transaction it
    sees uncommitted rows, which is what lets a promotion verify data before
    making it visible.
    """
    failures: list[str] = []
    names: list[str] = []
    for name, check in all_checks():
        names.append(name)
        arguments = (conn, season) if "season" in inspect.signature(check).parameters else (conn,)
        try:
            check(*arguments)
        except AssertionError as exc:
            failures.append(f"{name}: {exc}")
    if failures:
        raise DataQualityError(
            f"{len(failures)} of {len(names)} data-quality checks failed:\n  "
            + "\n  ".join(failures)
        )
    return names
