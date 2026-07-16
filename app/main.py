"""NBA Database API - FastAPI Application."""

import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.db import close_pool, get_cursor
from app.models import (
    GameCreate,
    GameDetail,
    GameList,
    LeaderList,
    Player,
    PlayerCreate,
    PlayerGameStats,
    PlayerGameStatsCreate,
    PlayerGameStatsList,
    PlayerList,
    PlayerSeasonAvg,
    Season,
    StatLeader,
    Team,
    TeamGameStats,
    TeamGameStatsList,
    TeamStanding,
)


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
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}") from e


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
            conditions.append("full_name LIKE %s")
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


@app.post("/api/players", response_model=Player, tags=["Players"])
def create_player(player: PlayerCreate) -> Player:
    with get_cursor() as cur:
        cur.execute("SELECT id FROM players WHERE id = %s", (player.id,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail=f"Player with ID {player.id} already exists")

        cur.execute(
            """
            INSERT INTO players (id, full_name, first_name, last_name, is_active)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (player.id, player.full_name, player.first_name, player.last_name, player.is_active),
        )
        return Player(**player.model_dump())


@app.get("/api/players/{player_id}/stats", response_model=list[PlayerSeasonAvg], tags=["Players"])
def get_player_stats(player_id: int) -> list[PlayerSeasonAvg]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                pgs.player_id,
                p.full_name as player_name,
                pgs.season,
                COUNT(*) as games_played,
                ROUND(AVG(pgs.points), 1) as ppg,
                ROUND(AVG(pgs.rebounds), 1) as rpg,
                ROUND(AVG(pgs.assists), 1) as apg,
                ROUND(AVG(pgs.steals), 1) as spg,
                ROUND(AVG(pgs.blocks), 1) as bpg,
                ROUND(AVG(pgs.fg_pct), 3) as fg_pct,
                ROUND(AVG(pgs.fg3_pct), 3) as fg3_pct,
                ROUND(AVG(pgs.ft_pct), 3) as ft_pct
            FROM player_game_stats pgs
            JOIN players p ON pgs.player_id = p.id
            WHERE pgs.player_id = %s
            GROUP BY pgs.player_id, p.full_name, pgs.season
            ORDER BY pgs.season DESC
            """,
            (player_id,),
        )
        rows = cur.fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="No stats found for player")
        return [PlayerSeasonAvg(**row) for row in rows]


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


@app.post("/api/games", response_model=GameDetail, tags=["Games"])
def create_game(game: GameCreate) -> GameDetail:
    with get_cursor() as cur:
        cur.execute("SELECT id FROM games WHERE id = %s", (game.id,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail=f"Game with ID {game.id} already exists")

        cur.execute("SELECT id FROM teams WHERE id = %s", (game.home_team_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=400, detail=f"Home team with ID {game.home_team_id} not found")

        cur.execute("SELECT id FROM teams WHERE id = %s", (game.away_team_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=400, detail=f"Away team with ID {game.away_team_id} not found")

        cur.execute(
            """
            INSERT INTO games (id, game_date, season, home_team_id, away_team_id, home_score, away_score)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (game.id, game.game_date, game.season, game.home_team_id, game.away_team_id, game.home_score, game.away_score),
        )

        cur.execute(
            """
            SELECT g.*, ht.full_name as home_team, at.full_name as away_team
            FROM games g
            JOIN teams ht ON g.home_team_id = ht.id
            JOIN teams at ON g.away_team_id = at.id
            WHERE g.id = %s
            """,
            (game.id,),
        )
        return GameDetail(**cur.fetchone())


@app.get("/api/games/{game_id}/boxscore", tags=["Games"])
def get_game_boxscore(game_id: str) -> dict:
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

        return {
            "game": GameDetail(**game),
            "home_players": [PlayerGameStats(**p) for p in player_stats if p["team_id"] == game["home_team_id"]],
            "away_players": [PlayerGameStats(**p) for p in player_stats if p["team_id"] == game["away_team_id"]],
            "home_team_stats": next((TeamGameStats(**t) for t in team_stats if t["team_id"] == game["home_team_id"]), None),
            "away_team_stats": next((TeamGameStats(**t) for t in team_stats if t["team_id"] == game["away_team_id"]), None),
        }


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


@app.post("/api/player-game-stats", response_model=PlayerGameStats, tags=["Box Scores"])
def create_player_game_stats(stats: PlayerGameStatsCreate) -> PlayerGameStats:
    with get_cursor() as cur:
        cur.execute("SELECT id FROM games WHERE id = %s", (stats.game_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=400, detail=f"Game with ID {stats.game_id} not found")

        cur.execute("SELECT id FROM players WHERE id = %s", (stats.player_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=400, detail=f"Player with ID {stats.player_id} not found")

        cur.execute("SELECT id FROM teams WHERE id = %s", (stats.team_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=400, detail=f"Team with ID {stats.team_id} not found")

        cur.execute(
            "SELECT id FROM player_game_stats WHERE game_id = %s AND player_id = %s",
            (stats.game_id, stats.player_id),
        )
        if cur.fetchone():
            raise HTTPException(status_code=400, detail=f"Stats for player {stats.player_id} in game {stats.game_id} already exist")

        cur.execute(
            """
            INSERT INTO player_game_stats (
                game_id, player_id, team_id, season, minutes, points, rebounds,
                assists, steals, blocks, turnovers, personal_fouls,
                fgm, fga, fg_pct, fg3m, fg3a, fg3_pct, ftm, fta, ft_pct, plus_minus
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                stats.game_id, stats.player_id, stats.team_id, stats.season, stats.minutes,
                stats.points, stats.rebounds, stats.assists, stats.steals, stats.blocks,
                stats.turnovers, stats.personal_fouls, stats.fgm, stats.fga, stats.fg_pct,
                stats.fg3m, stats.fg3a, stats.fg3_pct, stats.ftm, stats.fta, stats.ft_pct,
                stats.plus_minus,
            ),
        )

        cur.execute(
            """
            SELECT pgs.*, p.full_name as player_name, t.abbreviation as team_abbr
            FROM player_game_stats pgs
            JOIN players p ON pgs.player_id = p.id
            JOIN teams t ON pgs.team_id = t.id
            WHERE pgs.game_id = %s AND pgs.player_id = %s
            """,
            (stats.game_id, stats.player_id),
        )
        return PlayerGameStats(**cur.fetchone())


# === Leaders ===


StatCategory = Literal["points", "rebounds", "assists", "steals", "blocks"]


@app.get("/api/leaders/{stat}", response_model=LeaderList, tags=["Leaders"])
def get_leaders(
    stat: StatCategory,
    season: str = Query(..., description="Season (required)"),
    limit: int = Query(10, ge=1, le=50),
) -> LeaderList:
    stat_column = {"points": "points", "rebounds": "rebounds", "assists": "assists", "steals": "steals", "blocks": "blocks"}[stat]

    with get_cursor() as cur:
        cur.execute(
            f"""
            WITH player_stats AS (
                SELECT
                    pgs.player_id,
                    COUNT(*) as games_played,
                    ROUND(AVG(pgs.{stat_column}), 1) as value,
                    MAX(pgs.game_id) as last_game_id
                FROM player_game_stats pgs
                WHERE pgs.season = %s
                GROUP BY pgs.player_id
                HAVING COUNT(*) >= 10
            ),
            player_last_team AS (
                SELECT pgs.player_id, t.abbreviation as team_abbr
                FROM player_game_stats pgs
                JOIN teams t ON pgs.team_id = t.id
                WHERE pgs.season = %s
                  AND pgs.game_id = (
                      SELECT MAX(pgs2.game_id)
                      FROM player_game_stats pgs2
                      WHERE pgs2.player_id = pgs.player_id AND pgs2.season = %s
                  )
                GROUP BY pgs.player_id, t.abbreviation
            )
            SELECT
                ps.player_id,
                p.full_name as player_name,
                plt.team_abbr,
                ps.games_played,
                ps.value
            FROM player_stats ps
            JOIN players p ON ps.player_id = p.id
            JOIN player_last_team plt ON ps.player_id = plt.player_id
            ORDER BY ps.value DESC
            LIMIT %s
            """,
            (season, season, season, limit),
        )
        rows = cur.fetchall()

        leaders = [StatLeader(rank=i + 1, **row) for i, row in enumerate(rows)]
        return LeaderList(stat=stat, season=season, data=leaders)


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
            ORDER BY wins DESC
            """,
            (season, season),
        )
        rows = cur.fetchall()
        return [
            TeamStanding(**row, win_pct=round(row["wins"] / (row["wins"] + row["losses"]), 3) if row["wins"] + row["losses"] > 0 else 0)
            for row in rows
        ]


# === ETL Pipeline ===


class ETLRequest(BaseModel):
    seasons: list[str]
    extract: bool = True
    transform: bool = True
    load: bool = True


class ETLSeasonResult(BaseModel):
    season: str
    success: bool
    steps_completed: list[str]
    errors: list[str]


class ETLResponse(BaseModel):
    success: bool
    message: str
    results: list[ETLSeasonResult]


PROJECT_ROOT = Path(__file__).parent.parent


def run_etl_step(step: str, season: str) -> tuple[bool, str]:
    """Run a single ETL step and return (success, message)."""
    script_path = PROJECT_ROOT / "etl" / f"{step}.py"
    if not script_path.exists():
        return False, f"Script not found: {script_path}"

    try:
        result = subprocess.run(
            [sys.executable, str(script_path), "--season", season],
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            return False, f"{step} failed: {error_msg}"
        return True, f"{step} completed successfully"
    except subprocess.TimeoutExpired:
        return False, f"{step} timed out after 10 minutes"
    except Exception as e:
        return False, f"{step} error: {str(e)}"


@app.post("/api/etl", response_model=ETLResponse, tags=["ETL"])
def run_etl_pipeline(request: ETLRequest) -> ETLResponse:
    """Run the ETL pipeline to load one or more complete NBA seasons."""
    import re

    # Validate all seasons
    if not request.seasons:
        raise HTTPException(status_code=400, detail="At least one season must be specified")

    for season in request.seasons:
        if not re.match(r"^\d{4}-\d{2}$", season):
            raise HTTPException(status_code=400, detail=f"Invalid season format: {season}. Use YYYY-YY (e.g., 2024-25)")

    steps_to_run = []
    if request.extract:
        steps_to_run.append("extract")
    if request.transform:
        steps_to_run.append("transform")
    if request.load:
        steps_to_run.append("load")

    if not steps_to_run:
        raise HTTPException(status_code=400, detail="At least one ETL step must be selected")

    results = []
    all_success = True

    for season in request.seasons:
        steps_completed = []
        errors = []

        for step in steps_to_run:
            success, message = run_etl_step(step, season)
            if success:
                steps_completed.append(step)
            else:
                errors.append(message)
                break  # Stop on first error for this season

        season_success = len(errors) == 0 and len(steps_completed) == len(steps_to_run)
        if not season_success:
            all_success = False

        results.append(ETLSeasonResult(
            season=season,
            success=season_success,
            steps_completed=steps_completed,
            errors=errors,
        ))

    successful_count = sum(1 for r in results if r.success)
    total_count = len(results)

    if all_success:
        message = f"All {total_count} season(s) loaded successfully"
    elif successful_count > 0:
        message = f"{successful_count} of {total_count} season(s) loaded successfully"
    else:
        message = "ETL pipeline failed for all seasons"

    return ETLResponse(
        success=all_success,
        message=message,
        results=results,
    )


# === Query Demo ===


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    success: bool
    columns: list[str]
    rows: list[dict]
    row_count: int
    execution_time_ms: float
    error: str | None = None


@app.post("/api/query", response_model=QueryResponse, tags=["Demo"])
def execute_query(request: QueryRequest) -> QueryResponse:
    """Execute a read-only SQL query for demo purposes."""
    import time

    query = request.query.strip()

    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # Security: Only allow SELECT queries
    query_upper = query.upper()
    if not query_upper.startswith("SELECT"):
        raise HTTPException(status_code=400, detail="Only SELECT queries are allowed")

    # Block dangerous keywords
    dangerous_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE"]
    for keyword in dangerous_keywords:
        if keyword in query_upper:
            raise HTTPException(status_code=400, detail=f"Query contains forbidden keyword: {keyword}")

    start_time = time.time()

    try:
        with get_cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description] if cur.description else []

            execution_time = (time.time() - start_time) * 1000

            return QueryResponse(
                success=True,
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_time_ms=round(execution_time, 2),
            )
    except Exception as e:
        execution_time = (time.time() - start_time) * 1000
        return QueryResponse(
            success=False,
            columns=[],
            rows=[],
            row_count=0,
            execution_time_ms=round(execution_time, 2),
            error=str(e),
        )
