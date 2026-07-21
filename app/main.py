"""NBA Database API - FastAPI Application."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.db import close_pool, get_cursor
from app.models import (
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
)

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

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.method == "GET" and response.status_code < 400:
        if request.url.path == "/health":
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path == "/":
            response.headers["Cache-Control"] = "no-cache"
        elif request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=3600, must-revalidate"
        elif request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = (
                "public, max-age=300, stale-while-revalidate=3600"
            )
    return response


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


# === Seasons ===


@app.get("/api/seasons", response_model=list[Season], tags=["Seasons"])
def list_seasons() -> list[Season]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM seasons ORDER BY id DESC")
        return [Season(**row) for row in cur.fetchall()]


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
    team_id: int, season: str = Query(..., description="Season (required)")
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
    season: str = Query(..., description="Season (required)"),
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
    season: str = Query(..., description="Season (required)"),
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


# === Comparisons ===


def _comparison_pair(values: list[int], label: str) -> tuple[int, int]:
    if len(values) != 2 or values[0] == values[1]:
        raise HTTPException(status_code=422, detail=f"Provide exactly two distinct {label}")
    return values[0], values[1]


@app.get("/api/comparisons/players", response_model=PlayerComparison, tags=["Comparisons"])
def compare_players(
    player_ids: Annotated[list[int], Query(description="Exactly two distinct player IDs")],
    season: Annotated[str, Query(description="Season (required)")],
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
    season: Annotated[str, Query(description="Season (required)")],
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
    season: str | None = Query(None, description="Filter by season"),
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
    season: str = Query(..., description="Season (required)"),
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
    season: str = Query(..., description="Season (required)"),
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
    season: str = Query(..., description="Season (required)"),
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
def get_standings(season: str = Query(..., description="Season (required)")) -> list[TeamStanding]:
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
