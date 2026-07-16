"""NBA Database API - FastAPI Application."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.db import close_pool, get_cursor
from app.models import (
    GameDetail,
    GameList,
    LeaderList,
    Player,
    PlayerGameStats,
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

