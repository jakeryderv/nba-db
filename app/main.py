"""NBA Database API - FastAPI Application."""

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Query

from app.db import close_pool, get_cursor
from app.models import (
    GameDetail,
    GameList,
    LeaderList,
    Player,
    PlayerGameStats,
    PlayerList,
    PlayerSeasonAvg,
    Season,
    ShootingZoneStats,
    Shot,
    ShotList,
    StatLeader,
    Team,
    TeamGameStats,
    TeamStanding,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - cleanup on shutdown."""
    yield
    close_pool()


app = FastAPI(
    title="NBA Database API",
    description="API for querying NBA statistics including players, games, and box scores.",
    version="1.0.0",
    lifespan=lifespan,
)


# === Health Check ===


@app.get("/health", tags=["Health"])
def health_check() -> dict:
    """Check API and database health."""
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}") from e


# === Seasons ===


@app.get("/api/seasons", response_model=list[Season], tags=["Seasons"])
def list_seasons() -> list[Season]:
    """List all loaded seasons."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM seasons ORDER BY id DESC")
        return [Season(**row) for row in cur.fetchall()]


# === Teams ===


@app.get("/api/teams", response_model=list[Team], tags=["Teams"])
def list_teams() -> list[Team]:
    """List all NBA teams."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM teams ORDER BY full_name")
        return [Team(**row) for row in cur.fetchall()]


@app.get("/api/teams/{team_id}", response_model=Team, tags=["Teams"])
def get_team(team_id: int) -> Team:
    """Get a specific team by ID."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM teams WHERE id = %s", (team_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Team not found")
        return Team(**row)


@app.get("/api/teams/{team_id}/standings", response_model=list[TeamStanding], tags=["Teams"])
def get_team_standings(team_id: int, season: str | None = None) -> list[TeamStanding]:
    """Get team standings (wins/losses) by season."""
    with get_cursor() as cur:
        query = """
            SELECT
                t.id as team_id,
                t.full_name as team_name,
                t.abbreviation,
                g.season,
                SUM(CASE
                    WHEN (g.home_team_id = t.id AND g.home_score > g.away_score)
                      OR (g.away_team_id = t.id AND g.away_score > g.home_score)
                    THEN 1 ELSE 0
                END) as wins,
                SUM(CASE
                    WHEN (g.home_team_id = t.id AND g.home_score < g.away_score)
                      OR (g.away_team_id = t.id AND g.away_score < g.home_score)
                    THEN 1 ELSE 0
                END) as losses
            FROM teams t
            JOIN games g ON t.id = g.home_team_id OR t.id = g.away_team_id
            WHERE t.id = %s
        """
        params: list = [team_id]
        if season:
            query += " AND g.season = %s"
            params.append(season)
        query += " GROUP BY t.id, t.full_name, t.abbreviation, g.season ORDER BY g.season DESC"

        cur.execute(query, params)
        rows = cur.fetchall()
        return [
            TeamStanding(**row, win_pct=round(row["wins"] / (row["wins"] + row["losses"]), 3))
            for row in rows
            if row["wins"] + row["losses"] > 0
        ]


# === Players ===


@app.get("/api/players", response_model=PlayerList, tags=["Players"])
def list_players(
    search: str | None = Query(None, description="Search by name"),
    active: bool | None = Query(None, description="Filter by active status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PlayerList:
    """List players with optional filters."""
    with get_cursor() as cur:
        # Build query
        conditions = []
        params: list = []

        if search:
            conditions.append("full_name ILIKE %s")
            params.append(f"%{search}%")
        if active is not None:
            conditions.append("is_active = %s")
            params.append(active)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Get total count
        cur.execute(f"SELECT COUNT(*) as count FROM players {where_clause}", params)
        total = cur.fetchone()["count"]

        # Get paginated results
        cur.execute(
            f"SELECT * FROM players {where_clause} ORDER BY full_name LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        players = [Player(**row) for row in cur.fetchall()]

        return PlayerList(data=players, total=total, limit=limit, offset=offset)


@app.get("/api/players/{player_id}", response_model=Player, tags=["Players"])
def get_player(player_id: int) -> Player:
    """Get a specific player by ID."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM players WHERE id = %s", (player_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Player not found")
        return Player(**row)


@app.get("/api/players/{player_id}/stats", response_model=list[PlayerSeasonAvg], tags=["Players"])
def get_player_stats(player_id: int) -> list[PlayerSeasonAvg]:
    """Get player season averages."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                pgs.player_id,
                p.full_name as player_name,
                pgs.season,
                COUNT(*) as games_played,
                ROUND(AVG(pgs.points)::numeric, 1) as ppg,
                ROUND(AVG(pgs.rebounds)::numeric, 1) as rpg,
                ROUND(AVG(pgs.assists)::numeric, 1) as apg,
                ROUND(AVG(pgs.steals)::numeric, 1) as spg,
                ROUND(AVG(pgs.blocks)::numeric, 1) as bpg,
                ROUND(AVG(pgs.fg_pct)::numeric, 3) as fg_pct,
                ROUND(AVG(pgs.fg3_pct)::numeric, 3) as fg3_pct,
                ROUND(AVG(pgs.ft_pct)::numeric, 3) as ft_pct
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


@app.get("/api/players/{player_id}/games", response_model=list[PlayerGameStats], tags=["Players"])
def get_player_games(
    player_id: int,
    season: str | None = Query(None, description="Filter by season"),
    limit: int = Query(50, ge=1, le=100),
) -> list[PlayerGameStats]:
    """Get player game logs."""
    with get_cursor() as cur:
        query = """
            SELECT
                pgs.game_id, pgs.player_id, p.full_name as player_name,
                pgs.team_id, t.abbreviation as team_abbr, pgs.season,
                pgs.position, pgs.starter, pgs.minutes::text as minutes,
                pgs.points, pgs.rebounds, pgs.offensive_rebounds, pgs.defensive_rebounds,
                pgs.assists, pgs.steals, pgs.blocks, pgs.turnovers, pgs.personal_fouls,
                pgs.fgm, pgs.fga, pgs.fg_pct, pgs.fg3m, pgs.fg3a, pgs.fg3_pct,
                pgs.ftm, pgs.fta, pgs.ft_pct, pgs.plus_minus,
                pgs.offensive_rating, pgs.defensive_rating, pgs.net_rating,
                pgs.ast_pct, pgs.ast_ratio, pgs.reb_pct, pgs.ts_pct, pgs.usg_pct, pgs.pace, pgs.pie
            FROM player_game_stats pgs
            JOIN players p ON pgs.player_id = p.id
            JOIN teams t ON pgs.team_id = t.id
            WHERE pgs.player_id = %s
        """
        params: list = [player_id]
        if season:
            query += " AND pgs.season = %s"
            params.append(season)
        query += " ORDER BY pgs.game_id DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        return [PlayerGameStats(**row) for row in cur.fetchall()]


# === Games ===


@app.get("/api/games", response_model=GameList, tags=["Games"])
def list_games(
    season: str | None = Query(None, description="Filter by season"),
    team_id: int | None = Query(None, description="Filter by team"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> GameList:
    """List games with optional filters."""
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

        # Get total
        cur.execute(f"SELECT COUNT(*) as count FROM games g {where_clause}", params)
        total = cur.fetchone()["count"]

        # Get games with team names
        cur.execute(
            f"""
            SELECT g.*,
                   ht.full_name as home_team,
                   at.full_name as away_team
            FROM games g
            JOIN teams ht ON g.home_team_id = ht.id
            JOIN teams at ON g.away_team_id = at.id
            {where_clause}
            ORDER BY g.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        games = [GameDetail(**row) for row in cur.fetchall()]

        return GameList(data=games, total=total, limit=limit, offset=offset)


@app.get("/api/games/{game_id}", response_model=GameDetail, tags=["Games"])
def get_game(game_id: str) -> GameDetail:
    """Get a specific game by ID."""
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
    """Get full box score for a game."""
    with get_cursor() as cur:
        # Get game info
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

        # Get player stats
        cur.execute(
            """
            SELECT
                pgs.*, p.full_name as player_name, t.abbreviation as team_abbr,
                pgs.minutes::text as minutes
            FROM player_game_stats pgs
            JOIN players p ON pgs.player_id = p.id
            JOIN teams t ON pgs.team_id = t.id
            WHERE pgs.game_id = %s
            ORDER BY t.id, pgs.starter DESC, pgs.points DESC
            """,
            (game_id,),
        )
        player_stats = cur.fetchall()

        # Get team stats
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
            "home_players": [
                PlayerGameStats(**p) for p in player_stats if p["team_id"] == game["home_team_id"]
            ],
            "away_players": [
                PlayerGameStats(**p) for p in player_stats if p["team_id"] == game["away_team_id"]
            ],
            "home_team_stats": next(
                (TeamGameStats(**t) for t in team_stats if t["team_id"] == game["home_team_id"]),
                None,
            ),
            "away_team_stats": next(
                (TeamGameStats(**t) for t in team_stats if t["team_id"] == game["away_team_id"]),
                None,
            ),
        }


# === Leaders ===


StatCategory = Literal["points", "rebounds", "assists", "steals", "blocks"]


@app.get("/api/leaders/{stat}", response_model=LeaderList, tags=["Leaders"])
def get_leaders(
    stat: StatCategory,
    season: str = Query(..., description="Season (required)"),
    limit: int = Query(10, ge=1, le=50),
) -> LeaderList:
    """Get league leaders for a stat category."""
    # Map stat to column
    stat_column = {
        "points": "points",
        "rebounds": "rebounds",
        "assists": "assists",
        "steals": "steals",
        "blocks": "blocks",
    }[stat]

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                p.id as player_id,
                p.full_name as player_name,
                t.abbreviation as team_abbr,
                COUNT(*) as games_played,
                ROUND(AVG(pgs.{stat_column})::numeric, 1) as value
            FROM player_game_stats pgs
            JOIN players p ON pgs.player_id = p.id
            JOIN teams t ON pgs.team_id = t.id
            WHERE pgs.season = %s
            GROUP BY p.id, p.full_name, t.abbreviation
            HAVING COUNT(*) >= 10
            ORDER BY value DESC
            LIMIT %s
            """,
            (season, limit),
        )
        rows = cur.fetchall()

        leaders = [StatLeader(rank=i + 1, **row) for i, row in enumerate(rows)]
        return LeaderList(stat=stat, season=season, data=leaders)


# === Standings ===


@app.get("/api/standings", response_model=list[TeamStanding], tags=["Standings"])
def get_standings(season: str = Query(..., description="Season (required)")) -> list[TeamStanding]:
    """Get league standings for a season."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                t.id as team_id,
                t.full_name as team_name,
                t.abbreviation,
                %s as season,
                SUM(CASE
                    WHEN (g.home_team_id = t.id AND g.home_score > g.away_score)
                      OR (g.away_team_id = t.id AND g.away_score > g.home_score)
                    THEN 1 ELSE 0
                END) as wins,
                SUM(CASE
                    WHEN (g.home_team_id = t.id AND g.home_score < g.away_score)
                      OR (g.away_team_id = t.id AND g.away_score < g.home_score)
                    THEN 1 ELSE 0
                END) as losses
            FROM teams t
            JOIN games g ON (t.id = g.home_team_id OR t.id = g.away_team_id) AND g.season = %s
            GROUP BY t.id, t.full_name, t.abbreviation
            ORDER BY wins DESC, losses ASC
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


# === Shots ===


@app.get("/api/players/{player_id}/shots", response_model=ShotList, tags=["Shots"])
def get_player_shots(
    player_id: int,
    season: str | None = Query(None, description="Filter by season"),
    game_id: str | None = Query(None, description="Filter by game"),
    made: bool | None = Query(None, description="Filter by made/missed"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> ShotList:
    """Get shot chart data for a player."""
    with get_cursor() as cur:
        conditions = ["s.player_id = %s"]
        params: list = [player_id]

        if season:
            conditions.append("s.season = %s")
            params.append(season)
        if game_id:
            conditions.append("s.game_id = %s")
            params.append(game_id)
        if made is not None:
            conditions.append("s.shot_made = %s")
            params.append(made)

        where_clause = f"WHERE {' AND '.join(conditions)}"

        # Get total count
        cur.execute(f"SELECT COUNT(*) as count FROM shots s {where_clause}", params)
        total = cur.fetchone()["count"]

        # Get shots
        cur.execute(
            f"""
            SELECT s.*, p.full_name as player_name, t.abbreviation as team_abbr
            FROM shots s
            JOIN players p ON s.player_id = p.id
            JOIN teams t ON s.team_id = t.id
            {where_clause}
            ORDER BY s.game_id DESC, s.period, (12 - s.minutes_remaining) * 60 + (60 - s.seconds_remaining)
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        shots = [Shot(**row) for row in cur.fetchall()]

        return ShotList(data=shots, total=total, limit=limit, offset=offset)


@app.get("/api/players/{player_id}/shooting-zones", response_model=list[ShootingZoneStats], tags=["Shots"])
def get_player_shooting_zones(
    player_id: int,
    season: str | None = Query(None, description="Filter by season"),
) -> list[ShootingZoneStats]:
    """Get shooting stats by zone for a player."""
    with get_cursor() as cur:
        query = """
            SELECT
                shot_zone_basic as zone,
                SUM(CASE WHEN shot_made THEN 1 ELSE 0 END) as fgm,
                COUNT(*) as fga,
                ROUND(SUM(CASE WHEN shot_made THEN 1 ELSE 0 END)::numeric / COUNT(*), 3) as fg_pct
            FROM shots
            WHERE player_id = %s
        """
        params: list = [player_id]
        if season:
            query += " AND season = %s"
            params.append(season)
        query += " GROUP BY shot_zone_basic ORDER BY fga DESC"

        cur.execute(query, params)
        return [ShootingZoneStats(**row) for row in cur.fetchall()]


@app.get("/api/games/{game_id}/shots", response_model=ShotList, tags=["Shots"])
def get_game_shots(
    game_id: str,
    team_id: int | None = Query(None, description="Filter by team"),
    player_id: int | None = Query(None, description="Filter by player"),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> ShotList:
    """Get all shots from a game."""
    with get_cursor() as cur:
        conditions = ["s.game_id = %s"]
        params: list = [game_id]

        if team_id:
            conditions.append("s.team_id = %s")
            params.append(team_id)
        if player_id:
            conditions.append("s.player_id = %s")
            params.append(player_id)

        where_clause = f"WHERE {' AND '.join(conditions)}"

        # Get total count
        cur.execute(f"SELECT COUNT(*) as count FROM shots s {where_clause}", params)
        total = cur.fetchone()["count"]

        # Get shots
        cur.execute(
            f"""
            SELECT s.*, p.full_name as player_name, t.abbreviation as team_abbr
            FROM shots s
            JOIN players p ON s.player_id = p.id
            JOIN teams t ON s.team_id = t.id
            {where_clause}
            ORDER BY s.period, (12 - s.minutes_remaining) * 60 + (60 - s.seconds_remaining)
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        shots = [Shot(**row) for row in cur.fetchall()]

        return ShotList(data=shots, total=total, limit=limit, offset=offset)
