"""Pydantic models for API responses."""

import math
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, model_serializer


def clean_nan(value: Any) -> Any:
    """Convert NaN/Inf floats to None for JSON compatibility."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


class NaNSafeModel(BaseModel):
    """Base model that handles NaN values in serialization."""

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        data = handler(self)
        return {k: clean_nan(v) for k, v in data.items()}

# === Base Models ===


class Team(BaseModel):
    """Team information."""

    id: int
    full_name: str
    abbreviation: str
    nickname: str
    city: str
    state: str
    year_founded: int


class Player(BaseModel):
    """Player information."""

    id: int
    full_name: str
    first_name: str
    last_name: str
    is_active: bool


class Season(BaseModel):
    """Season metadata."""

    id: str
    start_year: int
    end_year: int
    games_count: int
    players_count: int
    shots_count: int
    loaded_at: datetime


# === Game Models ===


class Game(BaseModel):
    """Game summary."""

    id: str
    home_team_id: int
    away_team_id: int
    home_score: int
    away_score: int
    season: str
    game_date: date | None = None


class GameDetail(Game):
    """Game with team names."""

    home_team: str
    away_team: str


# === Stats Models ===


class PlayerGameStats(NaNSafeModel):
    """Player stats for a single game."""

    game_id: str
    player_id: int
    player_name: str | None = None
    team_id: int
    team_abbr: str | None = None
    season: str | None = None
    position: str | None = None
    starter: bool | None = None
    minutes: str | None = None

    # Traditional stats
    points: int
    rebounds: int
    offensive_rebounds: int = 0
    defensive_rebounds: int = 0
    assists: int
    steals: int
    blocks: int
    turnovers: int
    personal_fouls: int = 0

    # Shooting stats
    fgm: int
    fga: int
    fg_pct: float | None = None
    fg3m: int
    fg3a: int
    fg3_pct: float | None = None
    ftm: int
    fta: int
    ft_pct: float | None = None

    # Plus/minus
    plus_minus: float | None = None

    # Advanced stats
    offensive_rating: float | None = None
    defensive_rating: float | None = None
    net_rating: float | None = None
    ast_pct: float | None = None
    ast_ratio: float | None = None
    reb_pct: float | None = None
    ts_pct: float | None = None
    usg_pct: float | None = None
    pace: float | None = None
    pie: float | None = None


class PlayerSeasonAvg(BaseModel):
    """Player season averages."""

    player_id: int
    player_name: str
    team_id: int | None = None
    team_abbr: str | None = None
    season: str
    games_played: int
    ppg: float
    rpg: float
    apg: float
    spg: float
    bpg: float
    fg_pct: float | None = None
    fg3_pct: float | None = None
    ft_pct: float | None = None


class TeamGameStats(NaNSafeModel):
    """Team stats for a single game."""

    game_id: str
    team_id: int
    team_abbr: str | None = None
    is_home: bool
    season: str | None = None

    # Traditional stats
    points: int
    rebounds: int
    offensive_rebounds: int = 0
    defensive_rebounds: int = 0
    assists: int
    steals: int
    blocks: int
    turnovers: int
    personal_fouls: int = 0

    # Shooting stats
    fgm: int
    fga: int
    fg_pct: float | None = None
    fg3m: int
    fg3a: int
    fg3_pct: float | None = None
    ftm: int = 0
    fta: int = 0
    ft_pct: float | None = None

    # Advanced stats
    offensive_rating: float | None = None
    defensive_rating: float | None = None
    net_rating: float | None = None
    pace: float | None = None
    pie: float | None = None


class TeamStanding(BaseModel):
    """Team standings."""

    team_id: int
    team_name: str
    abbreviation: str
    season: str
    wins: int
    losses: int
    win_pct: float


# === List Response Models ===


class PaginatedResponse(BaseModel):
    """Paginated response wrapper."""

    total: int
    limit: int
    offset: int


# === Shot Models ===


class Shot(BaseModel):
    """Shot chart detail."""

    id: int
    game_id: str
    game_event_id: int
    player_id: int
    player_name: str | None = None
    team_id: int
    team_abbr: str | None = None
    season: str

    # Shot timing
    period: int
    minutes_remaining: int
    seconds_remaining: int

    # Shot description
    event_type: str  # 'Made Shot' or 'Missed Shot'
    action_type: str  # 'Jump Shot', 'Layup', etc.
    shot_type: str  # '2PT Field Goal' or '3PT Field Goal'

    # Shot location zones
    shot_zone_basic: str | None = None
    shot_zone_area: str | None = None
    shot_zone_range: str | None = None
    shot_distance: int | None = None

    # Court coordinates
    loc_x: int
    loc_y: int

    # Result
    shot_made: bool

    # Game context
    game_date: date | None = None
    home_team: str | None = None
    away_team: str | None = None


class ShotList(PaginatedResponse):
    """List of shots."""

    data: list[Shot]


class ShootingZoneStats(BaseModel):
    """Shooting stats by zone."""

    zone: str
    fgm: int
    fga: int
    fg_pct: float


# === Leader Models ===


class StatLeader(BaseModel):
    """League leader in a stat category."""

    rank: int
    player_id: int
    player_name: str
    team_abbr: str | None = None
    value: float
    games_played: int


class PlayerList(PaginatedResponse):
    """List of players."""

    data: list[Player]


class GameList(PaginatedResponse):
    """List of games."""

    data: list[GameDetail]


class LeaderList(BaseModel):
    """List of stat leaders."""

    stat: str
    season: str
    data: list[StatLeader]
