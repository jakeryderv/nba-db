"""The readiness contract, shared by the endpoint and the restore drill.

Readiness is the question the platform asks before sending traffic to a new
instance, so it is this product's operative definition of "this database can
serve". The restore drill asserts the same contract against a restored database,
which is only meaningful if both evaluate the same conditions from the same
code. A reimplementation would drift, and the drill would quietly end up proving
something adjacent to what production actually requires.

This module deliberately imports nothing from the web framework so the drill can
use it without constructing an application.
"""

from __future__ import annotations

from typing import Any

READINESS_SQL = """
SELECT s.id AS season, s.verification_status,
       s.games_count, s.players_count, s.shot_attempts_count,
       (SELECT COUNT(*) FROM games WHERE season = s.id) AS live_games,
       (SELECT COUNT(DISTINCT player_id)
        FROM player_game_stats WHERE season = s.id) AS live_players,
       (SELECT COUNT(*) FROM shot_attempts WHERE season = s.id) AS live_shots
FROM seasons s
WHERE s.id = %s
"""


def evaluate_readiness(cur: Any, season: str) -> dict[str, Any] | None:
    """Return the readiness payload, or None when the dataset is not ready.

    Comparing recorded counts against live counts is the point: the recorded
    counts come from the manifest at load time, so agreement means the data in
    the tables is the data that was verified, not merely that some data exists.

    The cursor must yield mapping rows.
    """
    cur.execute(READINESS_SQL, (season,))
    row = cur.fetchone()
    if (
        not row
        or row["verification_status"] != "passed"
        or row["games_count"] != row["live_games"]
        or row["players_count"] != row["live_players"]
        or row["shot_attempts_count"] != row["live_shots"]
    ):
        return None
    return {
        "status": "ready",
        "season": row["season"],
        "verification_status": row["verification_status"],
        "counts": {
            "games": row["live_games"],
            "players": row["live_players"],
            "shot_attempts": row["live_shots"],
        },
    }
