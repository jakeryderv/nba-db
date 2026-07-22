"""NBA Database API - FastAPI Application."""

import csv
import io
import logging
import mimetypes
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from app.db import close_pool, get_cursor
from app.middleware import RequestPolicyMiddleware
from app.models import (
    DatasetCounts,
    DatasetStatus,
    GameBoxScore,
    GameDetail,
    GameList,
    HeadToHeadSummary,
    LeaderList,
    Player,
    PlayerComparison,
    PlayerGameLog,
    PlayerGameStats,
    PlayerGameStatsList,
    PlayerList,
    PlayerSeasonAvg,
    Season,
    ShotAttempt,
    ShotChart,
    ShotProfile,
    ShotProfileRow,
    ShotZoneSummary,
    StatLeader,
    Team,
    TeamComparison,
    TeamComparisonEntry,
    TeamGameStats,
    TeamGameStatsList,
    TeamPlayerSummary,
    TeamPlayerSummaryList,
    TeamSeasonSummary,
    TeamStanding,
    UsageEvent,
)
from app.shot_filters import HomeAway, ShotType, shot_query_parts
from nba_config import ALL_STAR_BREAK_END, DEFAULT_SEASON

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close_pool()


app = FastAPI(
    title="NBA Database API",
    description="API for querying NBA statistics.",
    version="2.0.0",
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)
app.add_middleware(RequestPolicyMiddleware)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

# Minimal container images do not always ship a MIME database. Keep static
# JavaScript responses consistent across Dagger, local, and production hosts.
mimetypes.add_type("text/javascript", ".js")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# === Web Interface ===


@app.get("/", response_class=HTMLResponse, tags=["UI"])
def home():
    html_file = TEMPLATES_DIR / "index.html"
    if not html_file.exists():
        raise HTTPException(status_code=404, detail="UI not found")
    return html_file.read_text()


# === Health ===


@app.get("/health", tags=["Health"])
def health_check() -> dict:
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
        return {"status": "healthy", "database": "connected"}
    except Exception as exc:
        logger.exception("Database health check failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@app.get("/ready", tags=["Health"])
def readiness_check() -> dict:
    """Confirm that the verified default dataset is complete and queryable."""
    try:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT s.id AS season, s.verification_status,
                       s.games_count, s.players_count, s.shot_attempts_count,
                       (SELECT COUNT(*) FROM games WHERE season = s.id) AS live_games,
                       (SELECT COUNT(DISTINCT player_id)
                        FROM player_game_stats WHERE season = s.id) AS live_players,
                       (SELECT COUNT(*) FROM shot_attempts WHERE season = s.id) AS live_shots
                FROM seasons s
                WHERE s.id = %s
                """,
                (DEFAULT_SEASON,),
            )
            row = cur.fetchone()
        if (
            not row
            or row["verification_status"] != "passed"
            or row["games_count"] != row["live_games"]
            or row["players_count"] != row["live_players"]
            or row["shot_attempts_count"] != row["live_shots"]
        ):
            raise HTTPException(status_code=503, detail="Verified dataset is not ready")
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
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Readiness check failed")
        raise HTTPException(status_code=503, detail="Readiness check failed") from exc


# === Seasons ===


@app.get("/api/seasons", response_model=list[Season], tags=["Seasons"])
def list_seasons() -> list[Season]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM seasons ORDER BY id DESC")
        return [Season(**row) for row in cur.fetchall()]


@app.get("/api/dataset-status", response_model=DatasetStatus, tags=["Seasons"])
def get_dataset_status(
    season: str = Query(DEFAULT_SEASON, description="Season"),
) -> DatasetStatus:
    """Return public freshness, verification, and row-count metadata."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                s.id AS season,
                s.loaded_at,
                s.manifest_generated_at,
                s.verified_at,
                s.verification_status,
                s.manifest_sha256,
                s.games_count AS games,
                s.players_count AS players,
                (SELECT COUNT(*) FROM team_game_stats WHERE season = s.id)
                    AS team_game_stats,
                (SELECT COUNT(*) FROM player_game_stats WHERE season = s.id)
                    AS player_game_stats,
                (SELECT COUNT(*) FROM shot_attempts WHERE season = s.id)
                    AS shot_attempts
            FROM seasons s
            WHERE s.id = %s
            """,
            (season,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Dataset not found")
        count_keys = (
            "games",
            "players",
            "team_game_stats",
            "player_game_stats",
            "shot_attempts",
        )
        return DatasetStatus(
            season=row["season"],
            season_type="Regular Season",
            is_default=row["season"] == DEFAULT_SEASON,
            loaded_at=row["loaded_at"],
            manifest_generated_at=row["manifest_generated_at"],
            verified_at=row["verified_at"],
            verification_status=row["verification_status"],
            manifest_sha256=(row["manifest_sha256"].strip() if row["manifest_sha256"] else None),
            counts=DatasetCounts(**{key: row[key] for key in count_keys}),
        )


@app.post("/api/telemetry", status_code=204, tags=["Operations"])
def record_usage(event: UsageEvent) -> Response:
    """Record an anonymous, allowlisted product event in structured service logs."""
    logger.info("Usage event=%s view=%s", event.event, event.view)
    return Response(status_code=204)


# === Teams ===


@app.get("/api/teams", response_model=list[Team], tags=["Teams"])
def list_teams() -> list[Team]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM teams ORDER BY full_name")
        return [Team(**row) for row in cur.fetchall()]


@app.get("/api/teams/{team_id}", response_model=Team, tags=["Teams"])
def get_team(team_id: int) -> Team:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM teams WHERE id = %s", (team_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Team not found")
        return Team(**row)


@app.get("/api/teams/{team_id}/stats", response_model=TeamSeasonSummary, tags=["Teams"])
def get_team_season_stats(
    team_id: int, season: str = Query(DEFAULT_SEASON, description="Season")
) -> TeamSeasonSummary:
    with get_cursor() as cur:
        cur.execute(
            """
            WITH team_games AS (
                SELECT
                    g.id,
                    g.game_date,
                    g.home_team_id = %s AS is_home,
                    CASE WHEN g.home_team_id = %s THEN g.home_score ELSE g.away_score END
                        AS team_score,
                    CASE WHEN g.home_team_id = %s THEN g.away_score ELSE g.home_score END
                        AS opponent_score
                FROM games g
                WHERE g.season = %s
                  AND (g.home_team_id = %s OR g.away_team_id = %s)
            ), ranked_games AS (
                SELECT *, ROW_NUMBER() OVER (ORDER BY game_date DESC NULLS LAST, id DESC) AS recency
                FROM team_games
            )
            SELECT
                %s AS team_id,
                %s AS season,
                COUNT(*) AS games_played,
                COUNT(*) FILTER (WHERE tg.team_score > tg.opponent_score) AS wins,
                COUNT(*) FILTER (WHERE tg.team_score < tg.opponent_score) AS losses,
                ROUND(
                    COUNT(*) FILTER (WHERE tg.team_score > tg.opponent_score)::NUMERIC
                    / NULLIF(COUNT(*), 0), 3
                ) AS win_pct,
                COUNT(*) FILTER (
                    WHERE tg.is_home AND tg.team_score > tg.opponent_score
                ) AS home_wins,
                COUNT(*) FILTER (
                    WHERE tg.is_home AND tg.team_score < tg.opponent_score
                ) AS home_losses,
                COUNT(*) FILTER (
                    WHERE NOT tg.is_home AND tg.team_score > tg.opponent_score
                ) AS away_wins,
                COUNT(*) FILTER (
                    WHERE NOT tg.is_home AND tg.team_score < tg.opponent_score
                ) AS away_losses,
                ROUND(AVG(tgs.points), 1) AS ppg,
                ROUND(AVG(otgs.points), 1) AS opponent_ppg,
                ROUND(AVG(tg.team_score - tg.opponent_score), 1) AS point_diff,
                COUNT(*) FILTER (
                    WHERE tg.recency <= 10 AND tg.team_score > tg.opponent_score
                ) AS last_10_wins,
                COUNT(*) FILTER (
                    WHERE tg.recency <= 10 AND tg.team_score < tg.opponent_score
                ) AS last_10_losses,
                ROUND(AVG(tgs.rebounds), 1) AS rpg,
                ROUND(AVG(tgs.assists), 1) AS apg,
                ROUND(AVG(tgs.steals), 1) AS spg,
                ROUND(AVG(tgs.blocks), 1) AS bpg,
                ROUND(SUM(tgs.fgm)::NUMERIC / NULLIF(SUM(tgs.fga), 0), 3) AS fg_pct,
                ROUND(SUM(tgs.fg3m)::NUMERIC / NULLIF(SUM(tgs.fg3a), 0), 3) AS fg3_pct,
                ROUND(SUM(tgs.ftm)::NUMERIC / NULLIF(SUM(tgs.fta), 0), 3) AS ft_pct,
                ROUND(
                    (SUM(tgs.fgm) + 0.5 * SUM(tgs.fg3m))::NUMERIC
                    / NULLIF(SUM(tgs.fga), 0), 3
                ) AS efg_pct
            FROM ranked_games tg
            JOIN team_game_stats tgs ON tgs.game_id = tg.id AND tgs.team_id = %s
            JOIN team_game_stats otgs ON otgs.game_id = tg.id AND otgs.team_id <> %s
            """,
            (
                team_id,
                team_id,
                team_id,
                season,
                team_id,
                team_id,
                team_id,
                season,
                team_id,
                team_id,
            ),
        )
        row = cur.fetchone()
        if not row or row["games_played"] == 0:
            raise HTTPException(status_code=404, detail="No team stats found")
        return TeamSeasonSummary(**row)


@app.get(
    "/api/teams/{team_id}/players",
    response_model=TeamPlayerSummaryList,
    tags=["Teams"],
)
def get_team_players(
    team_id: int,
    season: str = Query(DEFAULT_SEASON, description="Season"),
    limit: int = Query(15, ge=1, le=50),
) -> TeamPlayerSummaryList:
    with get_cursor() as cur:
        cur.execute("SELECT 1 FROM teams WHERE id = %s", (team_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Team not found")

        cur.execute(
            """
            SELECT
                pgs.player_id,
                p.full_name AS player_name,
                COUNT(*) AS games_played,
                ROUND(AVG(pgs.minutes), 1) AS mpg,
                ROUND(AVG(pgs.points), 1) AS ppg,
                ROUND(AVG(pgs.rebounds), 1) AS rpg,
                ROUND(AVG(pgs.assists), 1) AS apg,
                ROUND(AVG(pgs.steals), 1) AS spg,
                ROUND(AVG(pgs.blocks), 1) AS bpg
            FROM player_game_stats pgs
            JOIN players p ON p.id = pgs.player_id
            WHERE pgs.team_id = %s AND pgs.season = %s AND pgs.minutes IS NOT NULL
            GROUP BY pgs.player_id, p.full_name
            ORDER BY ppg DESC, games_played DESC, p.full_name
            LIMIT %s
            """,
            (team_id, season, limit),
        )
        players = [TeamPlayerSummary(**row) for row in cur.fetchall()]
        return TeamPlayerSummaryList(team_id=team_id, season=season, data=players)


# === Players ===


@app.get("/api/players", response_model=PlayerList, tags=["Players"])
def list_players(
    search: str | None = Query(None, description="Search by name"),
    active: bool | None = Query(None, description="Filter by active status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PlayerList:
    with get_cursor() as cur:
        conditions = []
        params: list = []

        if search:
            conditions.append("full_name ILIKE %s")
            params.append(f"%{search}%")
        if active is not None:
            conditions.append("is_active = %s")
            params.append(active)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cur.execute(f"SELECT COUNT(*) as count FROM players {where_clause}", params)
        total = cur.fetchone()["count"]

        cur.execute(
            f"SELECT * FROM players {where_clause} ORDER BY full_name LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        players = [Player(**row) for row in cur.fetchall()]

        return PlayerList(data=players, total=total, limit=limit, offset=offset)


@app.get("/api/players/{player_id}", response_model=Player, tags=["Players"])
def get_player(player_id: int) -> Player:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM players WHERE id = %s", (player_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Player not found")
        return Player(**row)


@app.get("/api/players/{player_id}/stats", response_model=list[PlayerSeasonAvg], tags=["Players"])
def get_player_stats(player_id: int) -> list[PlayerSeasonAvg]:
    with get_cursor() as cur:
        cur.execute(
            """
            WITH latest_team AS (
                SELECT DISTINCT ON (pgs.season)
                    pgs.season,
                    pgs.team_id,
                    t.abbreviation AS team_abbr
                FROM player_game_stats pgs
                JOIN games g ON g.id = pgs.game_id
                JOIN teams t ON t.id = pgs.team_id
                WHERE pgs.player_id = %s AND pgs.minutes IS NOT NULL
                ORDER BY pgs.season, g.game_date DESC NULLS LAST, g.id DESC
            )
            SELECT
                pgs.player_id,
                p.full_name AS player_name,
                pgs.season,
                lt.team_id,
                lt.team_abbr,
                COUNT(*) AS games_played,
                ROUND(AVG(pgs.minutes), 1) AS mpg,
                ROUND(AVG(pgs.points), 1) AS ppg,
                ROUND(AVG(pgs.rebounds), 1) AS rpg,
                ROUND(AVG(pgs.assists), 1) AS apg,
                ROUND(AVG(pgs.steals), 1) AS spg,
                ROUND(AVG(pgs.blocks), 1) AS bpg,
                ROUND(SUM(pgs.fgm)::NUMERIC / NULLIF(SUM(pgs.fga), 0), 3) AS fg_pct,
                ROUND(SUM(pgs.fg3m)::NUMERIC / NULLIF(SUM(pgs.fg3a), 0), 3) AS fg3_pct,
                ROUND(SUM(pgs.ftm)::NUMERIC / NULLIF(SUM(pgs.fta), 0), 3) AS ft_pct
            FROM player_game_stats pgs
            JOIN players p ON pgs.player_id = p.id
            JOIN latest_team lt ON lt.season = pgs.season
            WHERE pgs.player_id = %s AND pgs.minutes IS NOT NULL
            GROUP BY pgs.player_id, p.full_name, pgs.season, lt.team_id, lt.team_abbr
            ORDER BY pgs.season DESC
            """,
            (player_id, player_id),
        )
        rows = cur.fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="No stats found for player")
        return [PlayerSeasonAvg(**row) for row in rows]


@app.get("/api/players/{player_id}/games", response_model=PlayerGameLog, tags=["Players"])
def get_player_games(
    player_id: int,
    season: str = Query(DEFAULT_SEASON, description="Season"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PlayerGameLog:
    with get_cursor() as cur:
        cur.execute("SELECT 1 FROM players WHERE id = %s", (player_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Player not found")

        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM player_game_stats
            WHERE player_id = %s AND season = %s AND minutes IS NOT NULL
            """,
            (player_id, season),
        )
        total = cur.fetchone()["count"]

        cur.execute(
            """
            SELECT
                pgs.*,
                p.full_name AS player_name,
                team.abbreviation AS team_abbr,
                g.game_date,
                opponent.id AS opponent_id,
                opponent.full_name AS opponent_name,
                opponent.abbreviation AS opponent_abbr,
                g.home_team_id = pgs.team_id AS is_home,
                CASE
                    WHEN (g.home_team_id = pgs.team_id AND g.home_score > g.away_score)
                      OR (g.away_team_id = pgs.team_id AND g.away_score > g.home_score)
                    THEN 'W' ELSE 'L'
                END AS result,
                CASE WHEN g.home_team_id = pgs.team_id THEN g.home_score ELSE g.away_score END
                    AS team_score,
                CASE WHEN g.home_team_id = pgs.team_id THEN g.away_score ELSE g.home_score END
                    AS opponent_score
            FROM player_game_stats pgs
            JOIN players p ON p.id = pgs.player_id
            JOIN games g ON g.id = pgs.game_id
            JOIN teams team ON team.id = pgs.team_id
            JOIN teams opponent ON opponent.id = CASE
                WHEN g.home_team_id = pgs.team_id THEN g.away_team_id ELSE g.home_team_id
            END
            WHERE pgs.player_id = %s AND pgs.season = %s AND pgs.minutes IS NOT NULL
            ORDER BY g.game_date DESC NULLS LAST, g.id DESC
            LIMIT %s OFFSET %s
            """,
            (player_id, season, limit, offset),
        )
        return PlayerGameLog(data=cur.fetchall(), total=total, limit=limit, offset=offset)


# === Shot charts ===


def _shot_subject(player_id: int | None, team_id: int | None) -> tuple[str, int, str, str]:
    if (player_id is None) == (team_id is None):
        raise HTTPException(status_code=422, detail="Provide exactly one player_id or team_id")
    if player_id is not None:
        return "player", player_id, "sa.player_id", "players"
    assert team_id is not None
    return "team", team_id, "sa.team_id", "teams"


@app.get("/api/shot-chart/players", response_model=list[Player], tags=["Shot Charts"])
def list_shot_chart_players(
    season: str = Query(DEFAULT_SEASON, description="Season"),
) -> list[Player]:
    """List only players who have shot attempts in the selected season."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT p.*
            FROM players p
            WHERE EXISTS (
                SELECT 1 FROM shot_attempts sa
                WHERE sa.player_id = p.id AND sa.season = %s
            )
            ORDER BY p.full_name, p.id
            """,
            (season,),
        )
        return [Player(**row) for row in cur.fetchall()]


@app.get("/api/shot-chart/action-types", response_model=list[str], tags=["Shot Charts"])
def list_shot_action_types(
    season: str = Query(DEFAULT_SEASON, description="Season"),
) -> list[str]:
    """List action types present in the verified season."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT action_type
            FROM shot_attempts
            WHERE season = %s
            ORDER BY action_type
            """,
            (season,),
        )
        return [row["action_type"] for row in cur.fetchall()]


@app.get("/api/shot-chart/games", response_model=list[GameDetail], tags=["Shot Charts"])
def list_shot_chart_games(
    season: str = Query(DEFAULT_SEASON, description="Season"),
    player_id: int | None = Query(None, description="Player subject"),
    team_id: int | None = Query(None, description="Team subject"),
) -> list[GameDetail]:
    """List games containing shot attempts for exactly one player or team."""
    if (player_id is None) == (team_id is None):
        raise HTTPException(status_code=422, detail="Provide exactly one player_id or team_id")

    subject_column = "sa.player_id" if player_id is not None else "sa.team_id"
    subject_id = player_id if player_id is not None else team_id
    subject_type = "player" if player_id is not None else "team"
    entity_table = "players" if player_id is not None else "teams"
    with get_cursor() as cur:
        cur.execute(f"SELECT 1 FROM {entity_table} WHERE id = %s", (subject_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"{subject_type.title()} not found")
        cur.execute(
            f"""
            SELECT g.*, home.full_name AS home_team, away.full_name AS away_team
            FROM games g
            JOIN teams home ON home.id = g.home_team_id
            JOIN teams away ON away.id = g.away_team_id
            WHERE g.season = %s
              AND EXISTS (
                  SELECT 1 FROM shot_attempts sa
                  WHERE sa.game_id = g.id AND {subject_column} = %s
              )
            ORDER BY g.game_date DESC NULLS LAST, g.id DESC
            """,
            (season, subject_id),
        )
        return [GameDetail(**row) for row in cur.fetchall()]


@app.get("/api/shot-chart.csv", tags=["Shot Charts"])
def export_shot_chart_csv(
    season: str = Query(DEFAULT_SEASON, description="Season"),
    player_id: int | None = Query(None),
    team_id: int | None = Query(None),
    game_id: str | None = Query(None),
    opponent_id: int | None = Query(None),
    period: int | None = Query(None, ge=1, le=20),
    made: bool | None = Query(None),
    shot_type: Annotated[ShotType | None, Query()] = None,
    action_type: str | None = Query(None, max_length=100),
    home_away: Annotated[HomeAway | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> Response:
    """Download every matching attempt for one player or team as CSV."""
    subject_type, subject_id, subject_column, entity_table = _shot_subject(player_id, team_id)
    where_clause, params, _, _, joins = shot_query_parts(
        season=season,
        subject_column=subject_column,
        subject_id=subject_id,
        game_id=game_id,
        opponent_id=opponent_id,
        period=period,
        shot_type=shot_type,
        action_type=action_type,
        home_away=home_away,
        date_from=date_from,
        date_to=date_to,
        made=made,
    )
    with get_cursor() as cur:
        cur.execute(f"SELECT 1 FROM {entity_table} WHERE id = %s", (subject_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"{subject_type.title()} not found")
        cur.execute(
            f"""
            SELECT g.game_date, sa.game_id, sa.event_id, sa.player_id,
                   p.full_name AS player_name, sa.team_id, team.abbreviation AS team_abbr,
                   opponent.id AS opponent_id, opponent.abbreviation AS opponent_abbr,
                   sa.season, sa.period, sa.minutes_remaining, sa.seconds_remaining,
                   sa.action_type, sa.shot_type, sa.zone_basic, sa.zone_area,
                   sa.zone_range, sa.shot_distance, sa.loc_x, sa.loc_y, sa.shot_made
            {joins}
            WHERE {where_clause}
            ORDER BY g.game_date, sa.game_id, sa.event_id
            LIMIT 20001
            """,
            params,
        )
        rows = cur.fetchall()
    if len(rows) > 20000:
        raise HTTPException(status_code=413, detail="CSV export exceeds the 20,000-row limit")
    output = io.StringIO()
    fieldnames = (
        list(rows[0])
        if rows
        else [
            "game_date",
            "game_id",
            "event_id",
            "player_id",
            "player_name",
            "team_id",
            "team_abbr",
            "opponent_id",
            "opponent_abbr",
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
    )
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    filename = f"{season}-{subject_type}-{subject_id}-shots.csv"
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/shot-chart", response_model=ShotChart, tags=["Shot Charts"])
def get_shot_chart(
    season: str = Query(DEFAULT_SEASON, description="Season"),
    player_id: int | None = Query(None, description="Player subject"),
    team_id: int | None = Query(None, description="Team subject"),
    game_id: str | None = Query(None),
    opponent_id: int | None = Query(None),
    period: int | None = Query(None, ge=1, le=20),
    made: bool | None = Query(None),
    shot_type: Annotated[ShotType | None, Query()] = None,
    action_type: str | None = Query(None, max_length=100),
    home_away: Annotated[HomeAway | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    max_points: int = Query(2500, ge=100, le=10000),
) -> ShotChart:
    """Return bounded shot locations plus complete zone aggregates for one subject."""
    subject_type, subject_id, subject_column, entity_table = _shot_subject(player_id, team_id)
    where_clause, params, context_where_clause, context_params, joins = shot_query_parts(
        season=season,
        subject_column=subject_column,
        subject_id=subject_id,
        game_id=game_id,
        opponent_id=opponent_id,
        period=period,
        shot_type=shot_type,
        action_type=action_type,
        home_away=home_away,
        date_from=date_from,
        date_to=date_to,
        made=made,
    )
    with get_cursor() as cur:
        cur.execute(f"SELECT 1 FROM {entity_table} WHERE id = %s", (subject_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"{subject_type.title()} not found")

        cur.execute(
            f"""
            SELECT COUNT(*) AS attempts,
                   COUNT(*) FILTER (WHERE sa.shot_made) AS makes,
                   COALESCE(SUM(
                       CASE WHEN sa.shot_made
                           THEN CASE WHEN sa.shot_type = '3PT Field Goal' THEN 3 ELSE 2 END
                           ELSE 0
                       END
                   ), 0) AS points,
                   ROUND(
                       COUNT(*) FILTER (WHERE sa.shot_made)::NUMERIC
                       / NULLIF(COUNT(*), 0), 3
                   ) AS fg_pct,
                   ROUND(
                       SUM(
                           CASE WHEN sa.shot_made
                               THEN CASE WHEN sa.shot_type = '3PT Field Goal' THEN 3 ELSE 2 END
                               ELSE 0
                           END
                       )::NUMERIC / NULLIF(COUNT(*), 0), 3
                   ) AS points_per_shot
            {joins}
            WHERE {where_clause}
            """,
            params,
        )
        summary = cur.fetchone()

        league_fg_pct = None
        if made is None:
            cur.execute(
                f"""
                SELECT ROUND(
                    COUNT(*) FILTER (WHERE sa.shot_made)::NUMERIC
                    / NULLIF(COUNT(*), 0), 3
                ) AS fg_pct
                {joins}
                WHERE {context_where_clause}
                """,
                context_params,
            )
            league_fg_pct = cur.fetchone()["fg_pct"]

        cur.execute(
            f"""
            SELECT sa.*, p.full_name AS player_name, team.abbreviation AS team_abbr,
                   opponent.id AS opponent_id, opponent.abbreviation AS opponent_abbr
            {joins}
            WHERE {where_clause}
            ORDER BY md5(sa.game_id || ':' || sa.event_id::TEXT)
            LIMIT %s
            """,
            [*params, max_points],
        )
        attempts = [ShotAttempt(**row) for row in cur.fetchall()]

        cur.execute(
            f"""
            SELECT sa.zone_basic, sa.zone_area, sa.zone_range,
                   COUNT(*) AS attempts,
                   COUNT(*) FILTER (WHERE sa.shot_made) AS makes,
                   COALESCE(SUM(
                       CASE WHEN sa.shot_made
                           THEN CASE WHEN sa.shot_type = '3PT Field Goal' THEN 3 ELSE 2 END
                           ELSE 0
                       END
                   ), 0) AS points,
                   ROUND(
                       COUNT(*) FILTER (WHERE sa.shot_made)::NUMERIC
                       / NULLIF(COUNT(*), 0), 3
                   ) AS fg_pct,
                   ROUND(
                       SUM(
                           CASE WHEN sa.shot_made
                               THEN CASE WHEN sa.shot_type = '3PT Field Goal' THEN 3 ELSE 2 END
                               ELSE 0
                           END
                       )::NUMERIC / NULLIF(COUNT(*), 0), 3
                   ) AS points_per_shot
            {joins}
            WHERE {where_clause}
            GROUP BY sa.zone_basic, sa.zone_area, sa.zone_range
            ORDER BY attempts DESC, sa.zone_basic, sa.zone_area, sa.zone_range
            """,
            params,
        )
        zone_rows = cur.fetchall()

        league_zones: dict[tuple[str, str, str], float | None] = {}
        if made is None:
            cur.execute(
                f"""
                SELECT sa.zone_basic, sa.zone_area, sa.zone_range,
                       ROUND(
                           COUNT(*) FILTER (WHERE sa.shot_made)::NUMERIC
                           / NULLIF(COUNT(*), 0), 3
                       ) AS fg_pct
                {joins}
                WHERE {context_where_clause}
                GROUP BY sa.zone_basic, sa.zone_area, sa.zone_range
                """,
                context_params,
            )
            league_zones = {
                (row["zone_basic"], row["zone_area"], row["zone_range"]): (
                    float(row["fg_pct"]) if row["fg_pct"] is not None else None
                )
                for row in cur.fetchall()
            }

    total = summary["attempts"]
    zones = []
    for row in zone_rows:
        key = (row["zone_basic"], row["zone_area"], row["zone_range"])
        zone_league_fg_pct = league_zones.get(key)
        zone_fg_pct = row["fg_pct"]
        zones.append(
            ShotZoneSummary(
                **row,
                frequency=round(row["attempts"] / total, 3) if total else 0,
                league_fg_pct=zone_league_fg_pct,
                fg_pct_vs_league=(
                    round(float(zone_fg_pct) - float(zone_league_fg_pct), 3)
                    if zone_fg_pct is not None and zone_league_fg_pct is not None
                    else None
                ),
            )
        )
    fg_pct_vs_league = (
        round(float(summary["fg_pct"]) - float(league_fg_pct), 3)
        if summary["fg_pct"] is not None and league_fg_pct is not None
        else None
    )
    return ShotChart(
        season=season,
        subject_type=subject_type,
        subject_id=subject_id,
        attempts=total,
        makes=summary["makes"],
        fg_pct=summary["fg_pct"],
        points=summary["points"],
        points_per_shot=summary["points_per_shot"],
        league_fg_pct=league_fg_pct,
        fg_pct_vs_league=fg_pct_vs_league,
        truncated=total > len(attempts),
        data=attempts,
        zones=zones,
    )


@app.get("/api/shot-profile", response_model=ShotProfile, tags=["Shot Charts"])
def get_shot_profile(
    season: str = Query(DEFAULT_SEASON, description="Season"),
    player_id: int | None = Query(None, description="Player subject"),
    team_id: int | None = Query(None, description="Team subject"),
    game_id: str | None = Query(None),
    opponent_id: int | None = Query(None),
    period: int | None = Query(None, ge=1, le=20),
    made: bool | None = Query(None),
    shot_type: Annotated[ShotType | None, Query()] = None,
    action_type: str | None = Query(None, max_length=100),
    home_away: Annotated[HomeAway | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> ShotProfile:
    """Summarize one subject by normalized area and within-season splits."""
    subject_type, subject_id, subject_column, entity_table = _shot_subject(player_id, team_id)
    where_clause, params, _, _, joins = shot_query_parts(
        season=season,
        subject_column=subject_column,
        subject_id=subject_id,
        game_id=game_id,
        opponent_id=opponent_id,
        period=period,
        shot_type=shot_type,
        action_type=action_type,
        home_away=home_away,
        date_from=date_from,
        date_to=date_to,
        made=made,
    )
    break_end = ALL_STAR_BREAK_END.get(season)
    if break_end is None:
        try:
            break_end = date(int(season[:4]) + 1, 2, 16)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Invalid season") from None

    with get_cursor() as cur:
        cur.execute(f"SELECT 1 FROM {entity_table} WHERE id = %s", (subject_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"{subject_type.title()} not found")
        cur.execute(
            f"""
            WITH filtered AS MATERIALIZED (
                SELECT sa.shot_made, sa.shot_type, g.game_date,
                       opponent.full_name AS opponent_name,
                       CASE WHEN g.home_team_id = sa.team_id THEN 'Home' ELSE 'Away' END
                           AS venue,
                       CASE
                           WHEN sa.zone_basic = 'Restricted Area' THEN 'Rim'
                           WHEN sa.zone_basic = 'In The Paint (Non-RA)' THEN 'Paint'
                           WHEN sa.zone_basic = 'Mid-Range' THEN 'Midrange'
                           WHEN sa.zone_basic IN ('Left Corner 3', 'Right Corner 3')
                               THEN 'Corner 3'
                           WHEN sa.zone_basic = 'Above the Break 3' THEN 'Above the Break 3'
                           ELSE sa.zone_basic
                       END AS normalized_zone
                {joins}
                WHERE {where_clause}
            ), dimension_rows AS (
                SELECT 'zone' AS dimension, normalized_zone AS label,
                       CASE normalized_zone
                           WHEN 'Rim' THEN '1'
                           WHEN 'Paint' THEN '2'
                           WHEN 'Midrange' THEN '3'
                           WHEN 'Corner 3' THEN '4'
                           WHEN 'Above the Break 3' THEN '5'
                           ELSE '9' || normalized_zone
                       END AS sort_key, shot_made, shot_type
                FROM filtered
                UNION ALL
                SELECT 'venue', venue, CASE venue WHEN 'Home' THEN '1' ELSE '2' END,
                       shot_made, shot_type
                FROM filtered
                UNION ALL
                SELECT 'month', TO_CHAR(game_date, 'Mon YYYY'), TO_CHAR(game_date, 'YYYY-MM'),
                       shot_made, shot_type
                FROM filtered
                UNION ALL
                SELECT 'opponent', opponent_name, opponent_name, shot_made, shot_type
                FROM filtered
                UNION ALL
                SELECT 'season_phase',
                       CASE WHEN game_date < %s THEN 'Pre All-Star' ELSE 'Post All-Star' END,
                       CASE WHEN game_date < %s THEN '1' ELSE '2' END,
                       shot_made, shot_type
                FROM filtered
            )
            SELECT dimension, label, sort_key,
                   COUNT(*) AS attempts,
                   COUNT(*) FILTER (WHERE shot_made) AS makes,
                   COALESCE(SUM(
                       CASE WHEN shot_made
                           THEN CASE WHEN shot_type = '3PT Field Goal' THEN 3 ELSE 2 END
                           ELSE 0
                       END
                   ), 0) AS points,
                   ROUND(
                       COUNT(*) FILTER (WHERE shot_made)::NUMERIC / NULLIF(COUNT(*), 0), 3
                   ) AS fg_pct,
                   ROUND(
                       COUNT(*)::NUMERIC
                       / NULLIF(SUM(COUNT(*)) OVER (PARTITION BY dimension), 0), 3
                   ) AS frequency,
                   ROUND(
                       SUM(
                           CASE WHEN shot_made
                               THEN CASE WHEN shot_type = '3PT Field Goal' THEN 3 ELSE 2 END
                               ELSE 0
                           END
                       )::NUMERIC / NULLIF(COUNT(*), 0), 3
                   ) AS points_per_shot,
                   ROUND(
                       (
                           COUNT(*) FILTER (WHERE shot_made)
                           + 0.5 * COUNT(*) FILTER (
                               WHERE shot_made AND shot_type = '3PT Field Goal'
                           )
                       )::NUMERIC / NULLIF(COUNT(*), 0), 3
                   ) AS efg_pct
            FROM dimension_rows
            GROUP BY dimension, label, sort_key
            ORDER BY dimension, sort_key, label
            """,
            [*params, break_end, break_end],
        )
        raw_rows = cur.fetchall()

    grouped: dict[str, list[ShotProfileRow]] = {
        "zone": [],
        "venue": [],
        "month": [],
        "opponent": [],
        "season_phase": [],
    }
    for raw in raw_rows:
        grouped[raw["dimension"]].append(
            ShotProfileRow(
                **{
                    key: value
                    for key, value in raw.items()
                    if key != "dimension" and key != "sort_key"
                }
            )
        )

    zones = grouped["zone"]
    total_attempts = sum(zone.attempts for zone in zones)
    minimum_attempts = max(10, round(total_attempts * 0.02))
    eligible = [zone for zone in zones if zone.attempts >= minimum_attempts]
    best_area = max(eligible, key=lambda row: row.points_per_shot or 0) if eligible else None
    lowest_area = (
        min(eligible, key=lambda row: row.points_per_shot or 0) if len(eligible) > 1 else None
    )
    return ShotProfile(
        season=season,
        subject_type=subject_type,
        subject_id=subject_id,
        zones=zones,
        venue_splits=grouped["venue"],
        month_splits=grouped["month"],
        opponent_splits=grouped["opponent"],
        season_phase_splits=grouped["season_phase"],
        best_area=best_area,
        lowest_area=lowest_area,
    )


# === Comparisons ===


def _comparison_pair(values: list[int], label: str) -> tuple[int, int]:
    if len(values) != 2 or values[0] == values[1]:
        raise HTTPException(status_code=422, detail=f"Provide exactly two distinct {label}")
    return values[0], values[1]


@app.get("/api/comparisons/players", response_model=PlayerComparison, tags=["Comparisons"])
def compare_players(
    player_ids: Annotated[list[int], Query(description="Exactly two distinct player IDs")],
    season: Annotated[str, Query(description="Season")] = DEFAULT_SEASON,
) -> PlayerComparison:
    first_id, second_id = _comparison_pair(player_ids, "player IDs")
    compared: list[PlayerSeasonAvg] = []
    for player_id in (first_id, second_id):
        season_stats = next(
            (row for row in get_player_stats(player_id) if row.season == season), None
        )
        if season_stats is None:
            raise HTTPException(status_code=404, detail="Player has no stats for this season")
        compared.append(season_stats)
    return PlayerComparison(season=season, data=compared)


@app.get("/api/comparisons/teams", response_model=TeamComparison, tags=["Comparisons"])
def compare_teams(
    team_ids: Annotated[list[int], Query(description="Exactly two distinct team IDs")],
    season: Annotated[str, Query(description="Season")] = DEFAULT_SEASON,
) -> TeamComparison:
    first_id, second_id = _comparison_pair(team_ids, "team IDs")
    entries = [
        TeamComparisonEntry(team=get_team(team_id), stats=get_team_season_stats(team_id, season))
        for team_id in (first_id, second_id)
    ]

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS games_played,
                COUNT(*) FILTER (
                    WHERE (home_team_id = %s AND home_score > away_score)
                       OR (away_team_id = %s AND away_score > home_score)
                ) AS first_team_wins,
                COUNT(*) FILTER (
                    WHERE (home_team_id = %s AND home_score > away_score)
                       OR (away_team_id = %s AND away_score > home_score)
                ) AS second_team_wins,
                COALESCE(ROUND(AVG(
                    CASE WHEN home_team_id = %s THEN home_score ELSE away_score END
                ), 1), 0) AS first_team_ppg,
                COALESCE(ROUND(AVG(
                    CASE WHEN home_team_id = %s THEN home_score ELSE away_score END
                ), 1), 0) AS second_team_ppg
            FROM games
            WHERE season = %s
              AND ((home_team_id = %s AND away_team_id = %s)
                OR (home_team_id = %s AND away_team_id = %s))
            """,
            (
                first_id,
                first_id,
                second_id,
                second_id,
                first_id,
                second_id,
                season,
                first_id,
                second_id,
                second_id,
                first_id,
            ),
        )
        head_to_head = HeadToHeadSummary(**cur.fetchone())

    return TeamComparison(season=season, data=entries, head_to_head=head_to_head)


# === Games ===


@app.get("/api/games", response_model=GameList, tags=["Games"])
def list_games(
    season: str = Query(DEFAULT_SEASON, description="Filter by season"),
    team_id: int | None = Query(None, description="Filter by team"),
    sort: str = Query("desc", description="Sort by date: 'asc' or 'desc'"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> GameList:
    with get_cursor() as cur:
        conditions = []
        params: list = []

        if season:
            conditions.append("g.season = %s")
            params.append(season)
        if team_id:
            conditions.append("(g.home_team_id = %s OR g.away_team_id = %s)")
            params.extend([team_id, team_id])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order_dir = "ASC" if sort == "asc" else "DESC"

        cur.execute(f"SELECT COUNT(*) as count FROM games g {where_clause}", params)
        total = cur.fetchone()["count"]

        cur.execute(
            f"""
            SELECT g.*, ht.full_name as home_team, at.full_name as away_team
            FROM games g
            JOIN teams ht ON g.home_team_id = ht.id
            JOIN teams at ON g.away_team_id = at.id
            {where_clause}
            ORDER BY g.game_date {order_dir}, g.id {order_dir}
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        games = [GameDetail(**row) for row in cur.fetchall()]

        return GameList(data=games, total=total, limit=limit, offset=offset)


@app.get("/api/games/{game_id}", response_model=GameDetail, tags=["Games"])
def get_game(game_id: str) -> GameDetail:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT g.*, ht.full_name as home_team, at.full_name as away_team
            FROM games g
            JOIN teams ht ON g.home_team_id = ht.id
            JOIN teams at ON g.away_team_id = at.id
            WHERE g.id = %s
            """,
            (game_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Game not found")
        return GameDetail(**row)


@app.get("/api/games/{game_id}/boxscore", response_model=GameBoxScore, tags=["Games"])
def get_game_boxscore(game_id: str) -> GameBoxScore:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT g.*, ht.full_name as home_team, at.full_name as away_team
            FROM games g
            JOIN teams ht ON g.home_team_id = ht.id
            JOIN teams at ON g.away_team_id = at.id
            WHERE g.id = %s
            """,
            (game_id,),
        )
        game = cur.fetchone()
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")

        cur.execute(
            """
            SELECT pgs.*, p.full_name as player_name, t.abbreviation as team_abbr
            FROM player_game_stats pgs
            JOIN players p ON pgs.player_id = p.id
            JOIN teams t ON pgs.team_id = t.id
            WHERE pgs.game_id = %s
            ORDER BY t.id, pgs.points DESC
            """,
            (game_id,),
        )
        player_stats = cur.fetchall()

        cur.execute(
            """
            SELECT tgs.*, t.abbreviation as team_abbr
            FROM team_game_stats tgs
            JOIN teams t ON tgs.team_id = t.id
            WHERE tgs.game_id = %s
            """,
            (game_id,),
        )
        team_stats = cur.fetchall()

        return GameBoxScore(
            game=GameDetail(**game),
            home_players=[
                PlayerGameStats(**p) for p in player_stats if p["team_id"] == game["home_team_id"]
            ],
            away_players=[
                PlayerGameStats(**p) for p in player_stats if p["team_id"] == game["away_team_id"]
            ],
            home_team_stats=next(
                (TeamGameStats(**t) for t in team_stats if t["team_id"] == game["home_team_id"]),
                None,
            ),
            away_team_stats=next(
                (TeamGameStats(**t) for t in team_stats if t["team_id"] == game["away_team_id"]),
                None,
            ),
        )


# === Box Score Lists ===


@app.get("/api/team-game-stats", response_model=TeamGameStatsList, tags=["Box Scores"])
def list_team_game_stats(
    season: str = Query(DEFAULT_SEASON, description="Season"),
    team_id: int | None = Query(None, description="Filter by team"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> TeamGameStatsList:
    with get_cursor() as cur:
        conditions = ["tgs.season = %s"]
        params: list = [season]

        if team_id:
            conditions.append("tgs.team_id = %s")
            params.append(team_id)

        where_clause = f"WHERE {' AND '.join(conditions)}"

        cur.execute(f"SELECT COUNT(*) as count FROM team_game_stats tgs {where_clause}", params)
        total = cur.fetchone()["count"]

        cur.execute(
            f"""
            SELECT tgs.*, t.abbreviation as team_abbr
            FROM team_game_stats tgs
            JOIN teams t ON tgs.team_id = t.id
            {where_clause}
            ORDER BY tgs.game_id DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        stats = [TeamGameStats(**row) for row in cur.fetchall()]

        return TeamGameStatsList(data=stats, total=total, limit=limit, offset=offset)


@app.get("/api/player-game-stats", response_model=PlayerGameStatsList, tags=["Box Scores"])
def list_player_game_stats(
    season: str = Query(DEFAULT_SEASON, description="Season"),
    player_id: int | None = Query(None, description="Filter by player"),
    team_id: int | None = Query(None, description="Filter by team"),
    game_id: str | None = Query(None, description="Filter by game"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PlayerGameStatsList:
    with get_cursor() as cur:
        conditions = ["pgs.season = %s"]
        params: list = [season]

        if player_id:
            conditions.append("pgs.player_id = %s")
            params.append(player_id)
        if team_id:
            conditions.append("pgs.team_id = %s")
            params.append(team_id)
        if game_id:
            conditions.append("pgs.game_id = %s")
            params.append(game_id)

        where_clause = f"WHERE {' AND '.join(conditions)}"

        cur.execute(f"SELECT COUNT(*) as count FROM player_game_stats pgs {where_clause}", params)
        total = cur.fetchone()["count"]

        cur.execute(
            f"""
            SELECT pgs.*, p.full_name as player_name, t.abbreviation as team_abbr
            FROM player_game_stats pgs
            JOIN players p ON pgs.player_id = p.id
            JOIN teams t ON pgs.team_id = t.id
            {where_clause}
            ORDER BY pgs.game_id DESC, pgs.points DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        stats = [PlayerGameStats(**row) for row in cur.fetchall()]

        return PlayerGameStatsList(data=stats, total=total, limit=limit, offset=offset)


# === Leaders ===


StatCategory = Literal["points", "rebounds", "assists", "steals", "blocks"]


@app.get("/api/leaders/{stat}", response_model=LeaderList, tags=["Leaders"])
def get_leaders(
    stat: StatCategory,
    season: str = Query(DEFAULT_SEASON, description="Season"),
    limit: int = Query(10, ge=1, le=50),
) -> LeaderList:
    stat_column = {
        "points": "points",
        "rebounds": "rebounds",
        "assists": "assists",
        "steals": "steals",
        "blocks": "blocks",
    }[stat]

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(CEIL(MAX(games_played) * 0.7), 0)::INTEGER AS minimum_games
            FROM (
                SELECT team_id, COUNT(*) AS games_played
                FROM team_game_stats
                WHERE season = %s
                GROUP BY team_id
            ) team_seasons
            """,
            (season,),
        )
        minimum_games = cur.fetchone()["minimum_games"]
        cur.execute(
            f"""
            WITH player_stats AS (
                SELECT
                    pgs.player_id,
                    COUNT(*) AS games_played,
                    ROUND(AVG(pgs.{stat_column}), 1) AS value
                FROM player_game_stats pgs
                WHERE pgs.season = %s AND pgs.minutes IS NOT NULL
                GROUP BY pgs.player_id
                HAVING COUNT(*) >= %s
            ),
            player_last_team AS (
                SELECT DISTINCT ON (pgs.player_id)
                    pgs.player_id, t.abbreviation AS team_abbr
                FROM player_game_stats pgs
                JOIN games g ON g.id = pgs.game_id
                JOIN teams t ON pgs.team_id = t.id
                WHERE pgs.season = %s AND pgs.minutes IS NOT NULL
                ORDER BY pgs.player_id, g.game_date DESC NULLS LAST, g.id DESC
            )
            SELECT
                RANK() OVER (ORDER BY ps.value DESC) AS rank,
                ps.player_id,
                p.full_name AS player_name,
                plt.team_abbr,
                ps.games_played,
                ps.value
            FROM player_stats ps
            JOIN players p ON ps.player_id = p.id
            JOIN player_last_team plt ON ps.player_id = plt.player_id
            ORDER BY ps.value DESC, ps.games_played DESC, p.full_name, ps.player_id
            LIMIT %s
            """,
            (season, minimum_games, season, limit),
        )
        rows = cur.fetchall()

        leaders = [StatLeader(**row) for row in rows]
        return LeaderList(
            stat=stat,
            season=season,
            minimum_games=minimum_games,
            data=leaders,
        )


# === Standings ===


@app.get("/api/standings", response_model=list[TeamStanding], tags=["Standings"])
def get_standings(season: str = Query(DEFAULT_SEASON, description="Season")) -> list[TeamStanding]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                t.id as team_id,
                t.full_name as team_name,
                t.abbreviation,
                %s as season,
                SUM(CASE WHEN (g.home_team_id = t.id AND g.home_score > g.away_score)
                          OR (g.away_team_id = t.id AND g.away_score > g.home_score) THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN (g.home_team_id = t.id AND g.home_score < g.away_score)
                          OR (g.away_team_id = t.id AND g.away_score < g.home_score) THEN 1 ELSE 0 END) as losses
            FROM teams t
            JOIN games g ON (t.id = g.home_team_id OR t.id = g.away_team_id) AND g.season = %s
            GROUP BY t.id, t.full_name, t.abbreviation
            ORDER BY wins DESC, losses ASC, t.full_name, t.id
            """,
            (season, season),
        )
        rows = cur.fetchall()
        return [
            TeamStanding(
                **row,
                win_pct=round(row["wins"] / (row["wins"] + row["losses"]), 3)
                if row["wins"] + row["losses"] > 0
                else 0,
            )
            for row in rows
        ]
