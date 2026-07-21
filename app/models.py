"""Pydantic models for API responses."""

from datetime import date, datetime

from pydantic import BaseModel

# === Base Models ===


class Team(BaseModel):
    id: int
    full_name: str
    abbreviation: str
    nickname: str
    city: str
    state: str
    year_founded: int


class Player(BaseModel):
    id: int
    full_name: str
    first_name: str | None
    last_name: str | None
    is_active: bool


class Season(BaseModel):
    id: str
    start_year: int
    end_year: int
    games_count: int
    players_count: int
    loaded_at: datetime


# === Game Models ===


class Game(BaseModel):
    id: str
    home_team_id: int
    away_team_id: int
    home_score: int
    away_score: int
    season: str
    game_date: date | None = None


class GameDetail(Game):
    home_team: str
    away_team: str


# === Stats Models ===


class PlayerGameStats(BaseModel):
    game_id: str
    player_id: int
    player_name: str | None = None
    team_id: int
    team_abbr: str | None = None
    season: str | None = None
    minutes: float | None = None
    points: int
    rebounds: int
    offensive_rebounds: int = 0
    defensive_rebounds: int = 0
    assists: int
    steals: int
    blocks: int
    turnovers: int
    personal_fouls: int = 0
    fgm: int
    fga: int
    fg_pct: float | None = None
    fg3m: int
    fg3a: int
    fg3_pct: float | None = None
    ftm: int
    fta: int
    ft_pct: float | None = None
    plus_minus: float | None = None


class PlayerSeasonAvg(BaseModel):
    player_id: int
    player_name: str
    season: str
    team_id: int
    team_abbr: str
    games_played: int
    mpg: float | None = None
    ppg: float
    rpg: float
    apg: float
    spg: float
    bpg: float
    fg_pct: float | None = None
    fg3_pct: float | None = None
    ft_pct: float | None = None


class TeamGameStats(BaseModel):
    game_id: str
    team_id: int
    team_abbr: str | None = None
    is_home: bool
    season: str | None = None
    minutes: int | None = None
    points: int
    rebounds: int
    offensive_rebounds: int = 0
    defensive_rebounds: int = 0
    assists: int
    steals: int
    blocks: int
    turnovers: int
    personal_fouls: int = 0
    fgm: int
    fga: int
    fg_pct: float | None = None
    fg3m: int
    fg3a: int
    fg3_pct: float | None = None
    ftm: int = 0
    fta: int = 0
    ft_pct: float | None = None
    plus_minus: float | None = None


class TeamStanding(BaseModel):
    team_id: int
    team_name: str
    abbreviation: str
    season: str
    wins: int
    losses: int
    win_pct: float


class TeamSeasonSummary(BaseModel):
    team_id: int
    season: str
    games_played: int
    wins: int
    losses: int
    win_pct: float
    home_wins: int
    home_losses: int
    away_wins: int
    away_losses: int
    ppg: float
    opponent_ppg: float
    rpg: float
    apg: float
    spg: float
    bpg: float
    fg_pct: float | None = None
    fg3_pct: float | None = None
    ft_pct: float | None = None


class TeamPlayerSummary(BaseModel):
    player_id: int
    player_name: str
    games_played: int
    mpg: float | None = None
    ppg: float
    rpg: float
    apg: float
    spg: float
    bpg: float


class PlayerGameLogEntry(PlayerGameStats):
    game_date: date | None = None
    opponent_id: int
    opponent_name: str
    opponent_abbr: str
    is_home: bool
    result: str
    team_score: int
    opponent_score: int


# === List Response Models ===


class PaginatedResponse(BaseModel):
    total: int
    limit: int
    offset: int


class PlayerList(PaginatedResponse):
    data: list[Player]


class GameList(PaginatedResponse):
    data: list[GameDetail]


class TeamGameStatsList(PaginatedResponse):
    data: list[TeamGameStats]


class PlayerGameStatsList(PaginatedResponse):
    data: list[PlayerGameStats]


class PlayerGameLog(PaginatedResponse):
    data: list[PlayerGameLogEntry]


class TeamPlayerSummaryList(BaseModel):
    team_id: int
    season: str
    data: list[TeamPlayerSummary]


class GameBoxScore(BaseModel):
    game: GameDetail
    home_players: list[PlayerGameStats]
    away_players: list[PlayerGameStats]
    home_team_stats: TeamGameStats | None
    away_team_stats: TeamGameStats | None


# === Leader Models ===


class StatLeader(BaseModel):
    rank: int
    player_id: int
    player_name: str
    team_abbr: str | None = None
    value: float
    games_played: int


class LeaderList(BaseModel):
    stat: str
    season: str
    data: list[StatLeader]
