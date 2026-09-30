from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CompetitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    duration_s: int = Field(gt=0)
    meters_lap: int
    event_type: Literal["maratona", "bateria"] = "maratona"
    distance_m: Optional[int] = 25

    @field_validator("meters_lap")
    @classmethod
    def _validate_meters_lap(cls, value: int) -> int:
        if value not in (25, 50):
            raise ValueError("meters_lap deve ser 25 ou 50")
        return value


class CompetitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: str
    duration_s: int
    meters_lap: int
    event_type: str = "maratona"
    distance_m: int | None = None
    started_at: float | None = None
    finished_at: float | None = None
    created_at: float


class TeamCreate(BaseModel):
    competition_id: str
    name: str = Field(min_length=1, max_length=200)


class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    competition_id: str
    name: str


class LaneResponse(BaseModel):
    id: str
    competition_id: str
    number: int
    team_id: str | None = None
    team: str | None = None
    laps: int = 0
    meters: int = 0
    status: str = "waiting"
    last_lap_at: float | None = None
    participant_name: str | None = None
    finish_at: float | None = None
    race_time_ms: int | None = None
    speed_ms: float | None = None


class LaneAssign(BaseModel):
    team_id: str | None = None
    participant_name: str | None = None


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


class ResetRequest(BaseModel):
    password: str


class WSMessage(BaseModel):
    type: str
    payload: dict = Field(default_factory=dict)
