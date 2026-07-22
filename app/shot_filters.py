"""Validated SQL fragments shared by shot-chart and shot-profile endpoints."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import HTTPException

ShotType = Literal["2PT Field Goal", "3PT Field Goal"]
HomeAway = Literal["home", "away"]


def shot_query_parts(
    *,
    season: str,
    subject_column: str,
    subject_id: int,
    game_id: str | None,
    opponent_id: int | None,
    period: int | None,
    shot_type: ShotType | None,
    action_type: str | None,
    home_away: HomeAway | None,
    date_from: date | None,
    date_to: date | None,
    made: bool | None,
) -> tuple[str, list[object], str, list[object], str]:
    """Build parameterized subject and league-context predicates."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must not be after date_to")
    context_conditions = ["sa.season = %s"]
    context_params: list[object] = [season]
    for value, clause in (
        (game_id, "sa.game_id = %s"),
        (opponent_id, "opponent.id = %s"),
        (period, "sa.period = %s"),
        (shot_type, "sa.shot_type = %s"),
        (action_type, "sa.action_type = %s"),
        (date_from, "g.game_date >= %s"),
        (date_to, "g.game_date <= %s"),
    ):
        if value is not None:
            context_conditions.append(clause)
            context_params.append(value)
    if home_away == "home":
        context_conditions.append("g.home_team_id = sa.team_id")
    elif home_away == "away":
        context_conditions.append("g.away_team_id = sa.team_id")

    conditions = [*context_conditions, f"{subject_column} = %s"]
    params = [*context_params, subject_id]
    if made is not None:
        conditions.append("sa.shot_made = %s")
        params.append(made)
    joins = """
        FROM shot_attempts sa
        JOIN players p ON p.id = sa.player_id
        JOIN teams team ON team.id = sa.team_id
        JOIN games g ON g.id = sa.game_id
        JOIN teams opponent ON opponent.id = CASE
            WHEN g.home_team_id = sa.team_id THEN g.away_team_id ELSE g.home_team_id
        END
    """
    return (
        " AND ".join(conditions),
        params,
        " AND ".join(context_conditions),
        context_params,
        joins,
    )
