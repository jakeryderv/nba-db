#!/usr/bin/env python3
"""
NBA Database Data Quality Tests
Validates data integrity, completeness, and consistency.
"""

import os
import sys

import psycopg
from dotenv import load_dotenv

# Load environment variables
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from db.config import get_db_config

DB_CONFIG = get_db_config()


class TestResult:
    def __init__(self, name, passed, message=""):
        self.name = name
        self.passed = passed
        self.message = message


def get_connection():
    """Create database connection."""
    return psycopg.connect(**DB_CONFIG)


def run_query(conn, query):
    """Execute query and return results."""
    with conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchall()


def run_scalar(conn, query):
    """Execute query and return single value."""
    result = run_query(conn, query)
    return result[0][0] if result else None


# =============================================================================
# Row Count Tests
# =============================================================================


def test_teams_not_empty(conn):
    """Teams table should have 30 NBA teams."""
    count = run_scalar(conn, "SELECT COUNT(*) FROM teams")
    passed = count == 30
    return TestResult("Teams count", passed, f"Expected 30, got {count}")


def test_players_not_empty(conn):
    """Players table should have records."""
    count = run_scalar(conn, "SELECT COUNT(*) FROM players")
    passed = count > 0
    return TestResult("Players not empty", passed, f"Found {count} players")


def test_games_not_empty(conn):
    """Games table should have records."""
    count = run_scalar(conn, "SELECT COUNT(*) FROM games")
    passed = count > 0
    return TestResult("Games not empty", passed, f"Found {count} games")


def test_player_game_stats_not_empty(conn):
    """Player game stats should have records."""
    count = run_scalar(conn, "SELECT COUNT(*) FROM player_game_stats")
    passed = count > 0
    return TestResult("Player game stats not empty", passed, f"Found {count} player game stats")


def test_team_game_stats_not_empty(conn):
    """Team game stats should have records."""
    count = run_scalar(conn, "SELECT COUNT(*) FROM team_game_stats")
    passed = count > 0
    return TestResult("Team game stats not empty", passed, f"Found {count} team game stats")


def test_shot_attempts_not_empty(conn):
    """Shot attempts should be loaded for the active dataset."""
    count = run_scalar(conn, "SELECT COUNT(*) FROM shot_attempts")
    passed = count > 0
    return TestResult("Shot attempts not empty", passed, f"Found {count} shot attempts")


# =============================================================================
# Referential Integrity Tests
# =============================================================================


def test_games_reference_valid_teams(conn):
    """All games should reference valid teams."""
    orphan_home = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM games g
        LEFT JOIN teams t ON g.home_team_id = t.id
        WHERE t.id IS NULL
    """,
    )
    orphan_away = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM games g
        LEFT JOIN teams t ON g.away_team_id = t.id
        WHERE t.id IS NULL
    """,
    )
    total_orphans = orphan_home + orphan_away
    passed = total_orphans == 0
    return TestResult(
        "Games reference valid teams",
        passed,
        f"Found {total_orphans} games with invalid team references",
    )


def test_player_stats_reference_valid_players(conn):
    """All player stats should reference valid players."""
    orphan_count = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM player_game_stats pgs
        LEFT JOIN players p ON pgs.player_id = p.id
        WHERE p.id IS NULL
    """,
    )
    passed = orphan_count == 0
    return TestResult(
        "Player stats reference valid players",
        passed,
        f"Found {orphan_count} stats with invalid player references",
    )


def test_player_stats_reference_valid_games(conn):
    """All player stats should reference valid games."""
    orphan_count = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM player_game_stats pgs
        LEFT JOIN games g ON pgs.game_id = g.id
        WHERE g.id IS NULL
    """,
    )
    passed = orphan_count == 0
    return TestResult(
        "Player stats reference valid games",
        passed,
        f"Found {orphan_count} stats with invalid game references",
    )


# =============================================================================
# Data Consistency Tests
# =============================================================================


def test_game_scores_match_team_stats(conn):
    """Both game scores should match their corresponding team stats rows."""
    mismatch_count = run_scalar(
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
        WHERE tgs.points IS DISTINCT FROM expected.points
    """,
    )
    passed = mismatch_count == 0
    return TestResult(
        "Game scores match team stats",
        passed,
        f"Found {mismatch_count} mismatches" if mismatch_count else "All scores match",
    )


def test_two_teams_per_game(conn):
    """Each game should have exactly 2 team stats entries."""
    invalid_games = run_query(
        conn,
        """
        SELECT game_id, COUNT(*) as team_count
        FROM team_game_stats
        GROUP BY game_id
        HAVING COUNT(*) != 2
        LIMIT 5
    """,
    )
    passed = len(invalid_games) == 0
    return TestResult(
        "Two teams per game", passed, f"Found {len(invalid_games)} games without exactly 2 teams"
    )


def test_player_stats_reasonable_values(conn):
    """Player stats should have reasonable values (no negative points, etc)."""
    invalid_stats = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM player_game_stats
        WHERE points < 0 OR rebounds < 0 OR assists < 0
           OR points > 100 OR rebounds > 50 OR assists > 50
    """,
    )
    passed = invalid_stats == 0
    return TestResult(
        "Player stats reasonable values",
        passed,
        f"Found {invalid_stats} records with unreasonable values",
    )


def test_shooting_percentages_valid(conn):
    """Shooting percentages should be between 0 and 1."""
    invalid_pct = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM player_game_stats
        WHERE (fg_pct IS NOT NULL AND (fg_pct < 0 OR fg_pct > 1))
           OR (fg3_pct IS NOT NULL AND (fg3_pct < 0 OR fg3_pct > 1))
           OR (ft_pct IS NOT NULL AND (ft_pct < 0 OR ft_pct > 1))
    """,
    )
    passed = invalid_pct == 0
    return TestResult(
        "Shooting percentages valid",
        passed,
        f"Found {invalid_pct} records with invalid percentages",
    )


def test_shot_totals_match_player_game_stats(conn):
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
            GROUP BY game_id, player_id
        )
        SELECT COUNT(*)
        FROM player_game_stats pgs
        FULL OUTER JOIN shot_totals shots
          ON shots.game_id = pgs.game_id AND shots.player_id = pgs.player_id
        WHERE pgs.game_id IS NULL
           OR (shots.game_id IS NOT NULL AND pgs.team_id IS DISTINCT FROM shots.team_id)
           OR ABS(pgs.fga - COALESCE(shots.fga, 0)) > 1
           OR pgs.fgm IS DISTINCT FROM COALESCE(shots.fgm, 0)
           OR ABS(pgs.fg3a - COALESCE(shots.fg3a, 0)) > 1
           OR pgs.fg3m IS DISTINCT FROM COALESCE(shots.fg3m, 0)
        """,
    )
    passed = mismatches == 0
    return TestResult(
        "Shot totals satisfy player game stats correction policy",
        passed,
        f"Found {mismatches} player-game mismatches"
        if mismatches
        else "All shot totals satisfy the correction policy",
    )


# =============================================================================
# Completeness Tests
# =============================================================================


def test_active_players_have_stats(conn):
    """Active players should have some game stats (sample check)."""
    active_without_stats = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM players p
        WHERE p.is_active = true
        AND NOT EXISTS (
            SELECT 1 FROM player_game_stats pgs
            WHERE pgs.player_id = p.id
        )
    """,
    )
    active_total = run_scalar(conn, "SELECT COUNT(*) FROM players WHERE is_active = true")
    # Allow some active players without stats (injured, end of bench)
    threshold = active_total * 0.5 if active_total else 0
    passed = active_without_stats < threshold
    return TestResult(
        "Active players have stats",
        passed,
        f"{active_without_stats}/{active_total} active players without stats",
    )


def test_all_teams_have_games(conn):
    """All teams should have at least one game."""
    teams_without_games = run_scalar(
        conn,
        """
        SELECT COUNT(*) FROM teams t
        WHERE NOT EXISTS (
            SELECT 1 FROM games g
            WHERE g.home_team_id = t.id OR g.away_team_id = t.id
        )
    """,
    )
    passed = teams_without_games == 0
    return TestResult(
        "All teams have games", passed, f"Found {teams_without_games} teams without games"
    )


# =============================================================================
# Test Runner
# =============================================================================


def run_all_tests():
    """Run all data quality tests."""
    print("=" * 60)
    print("NBA Database Data Quality Tests")
    print("=" * 60)

    try:
        conn = get_connection()
        print(f"\nConnected to {DB_CONFIG['dbname']}@{DB_CONFIG['host']}\n")
    except Exception as e:
        print(f"\nError connecting to database: {e}")
        print("Make sure PostgreSQL is running and credentials are correct")
        sys.exit(1)

    tests = [
        # Row count tests
        test_teams_not_empty,
        test_players_not_empty,
        test_games_not_empty,
        test_player_game_stats_not_empty,
        test_team_game_stats_not_empty,
        test_shot_attempts_not_empty,
        # Referential integrity tests
        test_games_reference_valid_teams,
        test_player_stats_reference_valid_players,
        test_player_stats_reference_valid_games,
        # Data consistency tests
        test_game_scores_match_team_stats,
        test_two_teams_per_game,
        test_player_stats_reasonable_values,
        test_shooting_percentages_valid,
        test_shot_totals_match_player_game_stats,
        # Completeness tests
        test_active_players_have_stats,
        test_all_teams_have_games,
    ]

    results = []
    for test_func in tests:
        try:
            result = test_func(conn)
            results.append(result)
            status = "PASS" if result.passed else "FAIL"
            print(f"[{status}] {result.name}: {result.message}")
        except Exception as e:
            results.append(TestResult(test_func.__name__, False, str(e)))
            print(f"[ERROR] {test_func.__name__}: {e}")

    conn.close()

    # Summary
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {len(results)} total")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
