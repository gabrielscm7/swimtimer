import re
from typing import Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

EventStatus = Literal["draft", "active", "finished"]
HeatType = Literal["maratona", "bateria"]
HeatStatus = Literal["scheduled", "ready_check", "active", "finished"]
LaneStatus = Literal["assigned", "ready", "active", "finished", "dq"]
ClassificationCriterion = Literal["lowest_time"]
MixedRanking = Literal["overall", "by_naipe", "both"]
# Exibicao publica dos nomes: completo ou "Maria S.".
PublicNameMode = Literal["full", "initials"]
# Atletas continuam apenas M/F; provas aceitam MISTO.
AthleteNaipe = Literal["M", "F"]
Naipe = Literal["M", "F", "MISTO"]

_NAIPE_ALIASES = {
    "M": "M",
    "MASC": "M",
    "MAS": "M",
    "MASCULINO": "M",
    "F": "F",
    "FEM": "F",
    "FEMININO": "F",
    "FEMININA": "F",
    "MISTO": "MISTO",
    "MISTA": "MISTO",
    "MIXTO": "MISTO",
    "MIXED": "MISTO",
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



def _reject_null(model: BaseModel, fields: tuple[str, ...]) -> BaseModel:
    """Rejeita null explicito em campos de coluna NOT NULL."""
    nulls = [
        name
        for name in fields
        if name in model.model_fields_set and getattr(model, name) is None
    ]
    if nulls:
        raise ValueError(f"campos_obrigatorios:{','.join(nulls)}")
    return model


def _trim_required_name(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
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

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value: object) -> object:
        return _trim_required_name(value)

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
    public_results_enabled: Optional[bool] = None
    public_name_mode: Optional[PublicNameMode] = None

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value: object) -> object:
        return _trim_required_name(value)

    @field_validator("pool_length_m")
    @classmethod
    def _validate_pool(cls, value: int | None) -> int | None:
        if value is not None and value not in (25, 50):
            raise ValueError("pool_length_m deve ser 25 ou 50")
        return value

    @model_validator(mode="after")
    def _required_fields(self) -> "EventUpdate":
        return _reject_null(
            self,
            (
                "name",
                "pool_length_m",
                "status",
                "public_results_enabled",
                "public_name_mode",
            ),
        )


class EventTheme(BaseModel):
    """Tema do front publico. Ausente no JSON = usa o padrao do sistema."""

    model_config = ConfigDict(extra="forbid")

    bg: str = "#0f1117"
    bg2: str = "#14161f"
    panel: str = "#1a1d27"
    text: str = "#e8eaf0"
    muted: str = "#6b7280"
    accent: str = "#00d4ff"
    accent_strong: str = "#00b0d6"
    bg_image_url: Optional[str] = None
    bg_opacity: float = Field(default=1.0, ge=0, le=1)
    bg_fit: Literal["cover", "contain", "center"] = "cover"
    bg_position: str = Field(default="center", min_length=1, max_length=40)
    logo_url: Optional[str] = None
    title_override: Optional[str] = Field(default=None, max_length=200)
    footer_text: Optional[str] = Field(default=None, max_length=300)
    show_team_logos: bool = True
    font_scale: float = Field(default=1.0, ge=0.8, le=1.4)

    @field_validator(
        "bg",
        "bg2",
        "panel",
        "text",
        "muted",
        "accent",
        "accent_strong",
    )
    @classmethod
    def _validate_color(cls, value: str) -> str:
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value or ""):
            raise ValueError("cor_invalida")
        return value.lower()

    @field_validator("bg_image_url", "logo_url")
    @classmethod
    def _validate_theme_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"/theme/[A-Za-z0-9._-]+", value):
            raise ValueError("url_invalida")
        return value

    @field_validator("bg_position")
    @classmethod
    def _validate_position(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9% .-]{1,40}", value or ""):
            raise ValueError("posicao_invalida")
        return value


class PresentationSlide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["prova", "bateria"]
    target_id: str = Field(min_length=1, max_length=80)


class PresentationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    rotation: bool = True
    slide_duration_s: int = Field(default=15, ge=5, le=60)
    show_next_prova: bool = True
    pinned_ref: Optional[str] = Field(default=None, max_length=100)
    slides: list[PresentationSlide] = Field(default_factory=list)


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    location: str | None = None
    date: str | None = None
    pool_length_m: int
    status: str
    public_results_enabled: bool = True
    public_name_mode: str = "full"
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
    mixed_ranking: MixedRanking = "both"
    consolidate_results: bool = True
    classification_criterion: ClassificationCriterion = "lowest_time"

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value: object) -> object:
        return _trim_required_name(value)

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
    mixed_ranking: Optional[MixedRanking] = None
    consolidate_results: Optional[bool] = None
    classification_criterion: Optional[ClassificationCriterion] = None

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value: object) -> object:
        return _trim_required_name(value)

    @field_validator("naipe", mode="before")
    @classmethod
    def _normalize_naipe(cls, value: object) -> object:
        return normalize_naipe(value)

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, value: object) -> object:
        return normalize_category(value)

    @model_validator(mode="after")
    def _required_fields(self) -> "ProvaUpdate":
        return _reject_null(
            self,
            (
                "name",
                "order_num",
                "mixed_ranking",
                "consolidate_results",
                "classification_criterion",
            ),
        )


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
    mixed_ranking: str = "both"
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
    naipe: str | None = None
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
    mixed_ranking: str = "both"
    is_provisional: bool
    standings: list[ClassificationEntry] = Field(default_factory=list)
    standings_by_naipe: dict[str, list[ClassificationEntry]] | None = None
    excluded: list[ClassificationEntry] = Field(default_factory=list)
    battery_results: list[dict] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Athlete
# --------------------------------------------------------------------------- #
class AthleteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    naipe: AthleteNaipe
    category: Optional[str] = Field(default=None, max_length=60)
    team_id: Optional[str] = None
    registration_code: Optional[str] = Field(default=None, max_length=40)

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


    @field_validator("registration_code", mode="before")
    @classmethod
    def _trim_registration_code(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
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
    naipe: Optional[AthleteNaipe] = None
    category: Optional[str] = Field(default=None, max_length=60)
    team_id: Optional[str] = None
    registration_code: Optional[str] = Field(default=None, max_length=40)
    force: bool = False
    override_reason: str | None = Field(default=None, max_length=500)

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


    @field_validator("registration_code", mode="before")
    @classmethod
    def _trim_registration_code(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
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
    registration_code: str | None = None
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

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value: object) -> object:
        return _trim_required_name(value)


class TeamUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value: object) -> object:
        return _trim_required_name(value)

    @model_validator(mode="after")
    def _required_fields(self) -> "TeamUpdate":
        return _reject_null(self, ("name",))


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

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value: object) -> object:
        return _trim_required_name(value)

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

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value: object) -> object:
        return _trim_required_name(value)

    @field_validator("distance_m")
    @classmethod
    def _validate_distance(cls, value: int | None) -> int | None:
        if value is not None and value not in (25, 50, 100, 200, 400, 800, 1500):
            raise ValueError("distance_m invalido")
        return value

    @model_validator(mode="after")
    def _required_fields(self) -> "HeatUpdate":
        return _reject_null(self, ("name", "order_num"))


class HeatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    prova_id: str
    name: str
    order_num: int
    event_seq: int | None = None
    prova_order_num: int | None = None
    prova_name: str | None = None
    heat_index_in_prova: int | None = None
    heats_in_prova: int | None = None
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
    force: bool = False
    override_reason: str | None = Field(default=None, max_length=500)


class LaneUpdate(BaseModel):
    participant_name: Optional[str] = Field(default=None, max_length=200)
    athlete_id: Optional[str] = None
    team_id: Optional[str] = None
    force: bool = False
    override_reason: str | None = Field(default=None, max_length=500)


class LaneActionRequest(BaseModel):
    """Corpo opcional de finish/lap: idempotencia e tempo do toque."""

    op_id: Optional[str] = Field(default=None, max_length=120)
    client_ts: Optional[float] = Field(default=None, ge=0)


class HeatLaneResponse(BaseModel):
    id: str
    heat_id: str
    lane_number: int
    naipe: str | None = None
    participant_name: str | None = None
    athlete_id: str | None = None
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
    naipe: str | None = None
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
