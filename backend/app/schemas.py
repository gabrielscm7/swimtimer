from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

EventStatus = Literal["draft", "active", "finished"]
HeatType = Literal["maratona", "bateria"]
HeatStatus = Literal["scheduled", "ready_check", "active", "finished"]
LaneStatus = Literal["assigned", "ready", "active", "finished", "dq"]
ClassificationCriterion = Literal["lowest_time"]
Naipe = Literal["M", "F"]

_NAIPE_ALIASES = {
    "M": "M",
    "MASC": "M",
    "MAS": "M",
    "MASCULINO": "M",
    "F": "F",
    "FEM": "F",
    "FEMININO": "F",
    "FEMININA": "F",
}


def normalize_naipe(value: object) -> object:
    if isinstance(value, str):
        return _NAIPE_ALIASES.get(value.strip().upper(), value.strip().upper())
    return value


def normalize_category(value: object) -> object:
    if isinstance(value, str):
        cleaned = value.strip().upper()
        return cleaned or None
    return value



def format_race_time(race_time_ms: int | None) -> str | None:
    if race_time_ms is None:
        return None
    ms = max(0, int(race_time_ms))
    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    centis = (ms % 1000) // 10
    return f"{minutes:02d}:{seconds:02d}.{centis:02d}"


def compute_speed(distance_m: int | None, race_time_ms: int | None) -> float | None:
    if not distance_m or not race_time_ms or race_time_ms <= 0:
        return None
    return round(distance_m / (race_time_ms / 1000), 2)


# --------------------------------------------------------------------------- #
# Event
# --------------------------------------------------------------------------- #
class EventCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    location: Optional[str] = Field(default=None, max_length=200)
    date: Optional[str] = Field(default=None, max_length=40)
    pool_length_m: int = 25

    @field_validator("pool_length_m")
    @classmethod
    def _validate_pool(cls, value: int) -> int:
        if value not in (25, 50):
            raise ValueError("pool_length_m deve ser 25 ou 50")
        return value


class EventUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    location: Optional[str] = Field(default=None, max_length=200)
    date: Optional[str] = Field(default=None, max_length=40)
    pool_length_m: Optional[int] = None
    status: Optional[EventStatus] = None

    @field_validator("pool_length_m")
    @classmethod
    def _validate_pool(cls, value: int | None) -> int | None:
        if value is not None and value not in (25, 50):
            raise ValueError("pool_length_m deve ser 25 ou 50")
        return value


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    location: str | None = None
    date: str | None = None
    pool_length_m: int
    status: str
    created_at: float
    heats: list["HeatResponse"] = Field(default_factory=list)


class EventDetailResponse(EventResponse):
    teams: list["TeamResponse"] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Prova
# --------------------------------------------------------------------------- #
class ProvaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    order_num: Optional[int] = Field(default=None, ge=1)
    stroke: Optional[str] = Field(default=None, max_length=60)
    distance_m: Optional[int] = Field(default=None, gt=0)
    category: Optional[str] = Field(default=None, max_length=60)
    naipe: Optional[Naipe] = None
    consolidate_results: bool = True
    classification_criterion: ClassificationCriterion = "lowest_time"

    @field_validator("naipe", mode="before")
    @classmethod
    def _normalize_naipe(cls, value: object) -> object:
        return normalize_naipe(value)

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, value: object) -> object:
        return normalize_category(value)


class ProvaUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    order_num: Optional[int] = Field(default=None, ge=1)
    stroke: Optional[str] = Field(default=None, max_length=60)
    distance_m: Optional[int] = Field(default=None, gt=0)
    category: Optional[str] = Field(default=None, max_length=60)
    naipe: Optional[Naipe] = None
    consolidate_results: Optional[bool] = None
    classification_criterion: Optional[ClassificationCriterion] = None

    @field_validator("naipe", mode="before")
    @classmethod
    def _normalize_naipe(cls, value: object) -> object:
        return normalize_naipe(value)

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, value: object) -> object:
        return normalize_category(value)


class OrderIdsRequest(BaseModel):
    """Lista completa de IDs na nova ordem (1..N)."""

    ids: list[str] = Field(default_factory=list, max_length=1000)


class ProvaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    name: str
    order_num: int
    stroke: str | None = None
    distance_m: int | None = None
    category: str | None = None
    naipe: str | None = None
    consolidate_results: bool = True
    classification_criterion: str = "lowest_time"
    status: str
    created_at: float
    heats: list["HeatResponse"] = Field(default_factory=list)


class ClassificationEntry(BaseModel):
    position: int | None = None
    lane_id: str
    heat_id: str
    heat_name: str
    heat_order_num: int
    lane_number: int
    participant_name: str | None = None
    team_id: str | None = None
    team_name: str | None = None
    team_logo_url: str | None = None
    race_time_ms: int | None = None
    race_time_display: str | None = None
    status: str
    classification_status: str
    tied: bool = False


class ClassificationResponse(BaseModel):
    prova_id: str
    name: str
    status: str
    consolidate_results: bool
    classification_criterion: str
    is_provisional: bool
    standings: list[ClassificationEntry] = Field(default_factory=list)
    excluded: list[ClassificationEntry] = Field(default_factory=list)
    battery_results: list[dict] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Athlete
# --------------------------------------------------------------------------- #
class AthleteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    naipe: Naipe
    category: Optional[str] = Field(default=None, max_length=60)
    team_id: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("naipe", mode="before")
    @classmethod
    def _normalize_naipe(cls, value: object) -> object:
        return normalize_naipe(value)

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, value: object) -> object:
        return normalize_category(value)


class AthleteUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    naipe: Optional[Naipe] = None
    category: Optional[str] = Field(default=None, max_length=60)
    team_id: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("naipe", mode="before")
    @classmethod
    def _normalize_naipe(cls, value: object) -> object:
        return normalize_naipe(value)

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, value: object) -> object:
        return normalize_category(value)


class AthleteResponse(BaseModel):
    id: str
    event_id: str
    team_id: str | None = None
    name: str
    naipe: str
    category: str | None = None
    created_at: float
    updated_at: float | None = None
    team_name: str | None = None
    team_logo_url: str | None = None


class AthleteImportError(BaseModel):
    line: int
    field: str | None = None
    message: str


class AthleteImportResult(BaseModel):
    created_athletes: int
    created_teams: int
    skipped: int
    errors: list[AthleteImportError] = Field(default_factory=list)


class AthleteListResponse(BaseModel):
    items: list[AthleteResponse]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# Team
# --------------------------------------------------------------------------- #
class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TeamUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)


class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    name: str
    logo_url: str | None = None
    athlete_count: int = 0


# --------------------------------------------------------------------------- #
# Heat
# --------------------------------------------------------------------------- #
class HeatCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    order_num: Optional[int] = Field(default=None, ge=1)
    heat_type: HeatType = "maratona"
    distance_m: Optional[int] = Field(default=None, gt=0)
    duration_s: Optional[int] = Field(default=None, gt=0)

    @field_validator("distance_m")
    @classmethod
    def _validate_distance(cls, value: int | None) -> int | None:
        if value is not None and value not in (25, 50, 100, 200, 400, 800, 1500):
            raise ValueError("distance_m invalido")
        return value


class HeatUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    order_num: Optional[int] = Field(default=None, ge=1)
    distance_m: Optional[int] = Field(default=None, gt=0)
    duration_s: Optional[int] = Field(default=None, gt=0)


class HeatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    prova_id: str
    name: str
    order_num: int
    heat_type: str
    distance_m: int | None = None
    duration_s: int | None = None
    status: str
    started_at: float | None = None
    finished_at: float | None = None
    heat_lanes: list["HeatLaneResponse"] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# HeatLane
# --------------------------------------------------------------------------- #
class HeatLaneConfigItem(BaseModel):
    lane_number: int = Field(ge=1, le=8)
    participant_name: Optional[str] = Field(default=None, max_length=200)
    athlete_id: Optional[str] = None
    team_id: Optional[str] = None


class HeatLaneConfigRequest(BaseModel):
    lanes: list[HeatLaneConfigItem]


class LaneUpdate(BaseModel):
    participant_name: Optional[str] = Field(default=None, max_length=200)
    athlete_id: Optional[str] = None
    team_id: Optional[str] = None


class LaneActionRequest(BaseModel):
    """Corpo opcional de finish/lap: idempotencia e tempo do toque."""

    op_id: Optional[str] = Field(default=None, max_length=120)
    client_ts: Optional[float] = Field(default=None, ge=0)


class HeatLaneResponse(BaseModel):
    id: str
    heat_id: str
    lane_number: int
    participant_name: str | None = None
    athlete_id: str | None = None
    naipe: str | None = None
    category: str | None = None
    team_id: str | None = None
    team: str | None = None
    status: str
    finish_at: float | None = None
    race_time_ms: int | None = None
    race_time_display: str | None = None
    speed_ms: float | None = None
    laps: int = 0
    meters: int = 0
    last_lap_at: float | None = None


class FinishResponse(BaseModel):
    lane_id: str
    lane_number: int
    participant_name: str | None = None
    team_name: str | None = None
    race_time_ms: int
    race_time_display: str
    speed_ms: float


class LapEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    lane_id: str
    lap_number: int
    recorded_at: float
    is_undo: bool = False


# --------------------------------------------------------------------------- #
# Status / WebSocket
# --------------------------------------------------------------------------- #
class StatusResponse(BaseModel):
    uptime: float
    connected_clients: int
    active_heats: int


class WSMessage(BaseModel):
    type: str
    scope: str | None = None
    heat_id: str | None = None
    payload: dict = Field(default_factory=dict)


EventDetailResponse.model_rebuild()
HeatResponse.model_rebuild()
ProvaResponse.model_rebuild()
