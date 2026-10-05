from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

EventStatus = Literal["draft", "active", "finished"]
HeatType = Literal["maratona", "bateria"]
HeatStatus = Literal["scheduled", "ready_check", "active", "finished"]
LaneStatus = Literal["assigned", "ready", "active", "finished", "dq"]


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
# Team
# --------------------------------------------------------------------------- #
class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    name: str


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
    team_id: Optional[str] = None


class HeatLaneConfigRequest(BaseModel):
    lanes: list[HeatLaneConfigItem]


class LaneUpdate(BaseModel):
    participant_name: Optional[str] = Field(default=None, max_length=200)
    team_id: Optional[str] = None


class HeatLaneResponse(BaseModel):
    id: str
    heat_id: str
    lane_number: int
    participant_name: str | None = None
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
