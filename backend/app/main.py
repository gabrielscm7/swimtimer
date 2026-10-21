import asyncio
import csv
import io
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook, load_workbook
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .classification import (
    build_classification,
    prova_status,
)
from .config import settings
from .database import AsyncSessionLocal, engine, get_db, init_db
from .models import Athlete, Event, Heat, HeatLane, LapEvent, Prova, Team
from .schemas import (
    AthleteCreate,
    AthleteImportResult,
    AthleteListResponse,
    AthleteResponse,
    AthleteUpdate,
    EventCreate,
    EventUpdate,
    HeatCreate,
    HeatUpdate,
    HeatLaneConfigRequest,
    LaneUpdate,
    OrderIdsRequest,
    ProvaCreate,
    ProvaUpdate,
    TeamCreate,
    TeamResponse,
    TeamUpdate,
    compute_speed,
    format_race_time,
    normalize_category,
    normalize_naipe,
)
from .ws_manager import ConnectionManager

START_TIME = time.time()
manager = ConnectionManager()

# Locks por prova: serializam as transições de estado de uma mesma bateria
# (finish/lap/dq/undo/start/abort/finish) evitando corridas de escrita no
# SQLite. O processo roda com um único worker uvicorn, então locks em memória
# são suficientes; a constraint única em lap_event é a rede de segurança.
_heat_locks: dict[str, asyncio.Lock] = {}
_heat_locks_guard = asyncio.Lock()


async def _get_heat_lock(heat_id: str) -> asyncio.Lock:
    async with _heat_locks_guard:
        lock = _heat_locks.get(heat_id)
        if lock is None:
            lock = asyncio.Lock()
            _heat_locks[heat_id] = lock
        return lock


@asynccontextmanager
async def _heat_guard(heat_id: str):
    lock = await _get_heat_lock(heat_id)
    async with lock:
        yield


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.logo_dir.mkdir(parents=True, exist_ok=True)
    await init_db()
    yield
    await engine.dispose()


app = FastAPI(title="SwimTimer", version="2.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def _get_event(session: AsyncSession, event_id: str) -> Event:
    event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="evento_nao_encontrado")
    return event


async def _get_heat(session: AsyncSession, heat_id: str) -> Heat:
    heat = await session.get(Heat, heat_id)
    if heat is None:
        raise HTTPException(status_code=404, detail="prova_nao_encontrada")
    return heat


async def _get_prova(session: AsyncSession, prova_id: str) -> Prova:
    prova = await session.get(Prova, prova_id)
    if prova is None:
        raise HTTPException(status_code=404, detail="prova_nao_encontrada")
    return prova


async def _get_lane(session: AsyncSession, lane_id: str) -> HeatLane:
    lane = await session.get(HeatLane, lane_id)
    if lane is None:
        raise HTTPException(status_code=404, detail="raia_nao_encontrada")
    return lane


async def _team_map(session: AsyncSession, event_id: str) -> dict[str, dict]:
    result = await session.execute(select(Team).where(Team.event_id == event_id))
    return {
        team.id: {"name": team.name, "logo_url": team.logo_url}
        for team in result.scalars().all()
    }


async def _team_athlete_counts(
    session: AsyncSession, event_id: str
) -> dict[str, int]:
    result = await session.execute(
        select(Athlete.team_id, func.count(Athlete.id))
        .where(Athlete.event_id == event_id, Athlete.team_id.is_not(None))
        .group_by(Athlete.team_id)
    )
    return {team_id: count for team_id, count in result.all()}


def _team_dict(team: Team, athlete_count: int = 0) -> dict:
    return {
        "id": team.id,
        "event_id": team.event_id,
        "name": team.name,
        "logo_url": team.logo_url,
        "athlete_count": athlete_count,
    }


def _lane_dict(
    lane: HeatLane,
    *,
    heat: Heat,
    pool_length_m: int,
    team_name: str | None,
    team_logo_url: str | None = None,
    athlete: Athlete | None = None,
    laps: int = 0,
    last_lap_at: float | None = None,
) -> dict:
    return {
        "id": lane.id,
        "heat_id": lane.heat_id,
        "lane_number": lane.lane_number,
        "participant_name": athlete.name if athlete else lane.participant_name,
        "athlete_id": lane.athlete_id,
        "naipe": athlete.naipe if athlete else None,
        "category": athlete.category if athlete else None,
        "team_id": lane.team_id,
        "team": team_name,
        "team_logo_url": team_logo_url,
        "status": lane.status,
        "finish_at": lane.finish_at,
        "race_time_ms": lane.race_time_ms,
        "race_time_display": format_race_time(lane.race_time_ms),
        "speed_ms": compute_speed(heat.distance_m, lane.race_time_ms),
        "laps": laps,
        "meters": laps * pool_length_m,
        "last_lap_at": last_lap_at,
    }


async def _lane_payload(
    session: AsyncSession, lane: HeatLane, heat: Heat
) -> dict:
    event = await session.get(Event, heat.event_id)
    athlete = (
        await session.get(Athlete, lane.athlete_id)
        if lane.athlete_id
        else None
    )
    team = await session.get(Team, lane.team_id) if lane.team_id else None
    return _lane_dict(
        lane,
        heat=heat,
        pool_length_m=event.pool_length_m if event else 0,
        team_name=team.name if team else None,
        team_logo_url=team.logo_url if team else None,
        athlete=athlete,
    )


async def _heats_payload(
    session: AsyncSession, heats: list[Heat]
) -> list[dict]:
    """Carrega raias, voltas e equipes de varias baterias em lote."""
    if not heats:
        return []

    event_ids = {heat.event_id for heat in heats}
    result = await session.execute(
        select(Event).where(Event.id.in_(event_ids))
    )
    events = {event.id: event for event in result.scalars().all()}

    result = await session.execute(
        select(Team).where(Team.event_id.in_(event_ids))
    )
    teams_by_event: dict[str, dict[str, dict]] = {}
    for team in result.scalars().all():
        teams_by_event.setdefault(team.event_id, {})[team.id] = {
            "name": team.name,
            "logo_url": team.logo_url,
        }

    heat_ids = [heat.id for heat in heats]
    result = await session.execute(
        select(HeatLane)
        .where(HeatLane.heat_id.in_(heat_ids))
        .order_by(HeatLane.heat_id, HeatLane.lane_number)
    )
    lanes_by_heat: dict[str, list[HeatLane]] = {}
    lane_ids: list[str] = []
    for lane in result.scalars().all():
        lanes_by_heat.setdefault(lane.heat_id, []).append(lane)
        lane_ids.append(lane.id)

    athlete_ids = {
        lane.athlete_id
        for lanes in lanes_by_heat.values()
        for lane in lanes
        if lane.athlete_id
    }
    athletes_by_id: dict[str, Athlete] = {}
    if athlete_ids:
        result = await session.execute(
            select(Athlete).where(Athlete.id.in_(athlete_ids))
        )
        athletes_by_id = {item.id: item for item in result.scalars().all()}

    lap_counts: dict[str, int] = {}
    last_laps: dict[str, float] = {}
    if lane_ids:
        rows = await session.execute(
            select(
                LapEvent.lane_id,
                func.count(LapEvent.id),
                func.max(LapEvent.recorded_at),
            )
            .where(LapEvent.lane_id.in_(lane_ids), LapEvent.is_undo.is_(False))
            .group_by(LapEvent.lane_id)
        )
        for lane_id, count, last in rows.all():
            lap_counts[lane_id] = count
            if last is not None:
                last_laps[lane_id] = last

    payloads: list[dict] = []
    for heat in heats:
        event = events.get(heat.event_id)
        pool_length_m = event.pool_length_m if event else 0
        team_map = teams_by_event.get(heat.event_id, {})
        lanes = lanes_by_heat.get(heat.id, [])
        payloads.append(
            {
                "id": heat.id,
                "event_id": heat.event_id,
                "prova_id": heat.prova_id,
                "name": heat.name,
                "order_num": heat.order_num,
                "heat_type": heat.heat_type,
                "distance_m": heat.distance_m,
                "duration_s": heat.duration_s,
                "status": heat.status,
                "started_at": heat.started_at,
                "finished_at": heat.finished_at,
                "heat_lanes": [
                    _lane_dict(
                        lane,
                        heat=heat,
                        pool_length_m=pool_length_m,
                        team_name=(team_map.get(lane.team_id) or {}).get("name")
                        if lane.team_id
                        else None,
                        team_logo_url=(
                            team_map.get(lane.team_id) or {}
                        ).get("logo_url")
                        if lane.team_id
                        else None,
                        athlete=athletes_by_id.get(lane.athlete_id)
                        if lane.athlete_id
                        else None,
                        laps=lap_counts.get(lane.id, 0),
                        last_lap_at=last_laps.get(lane.id),
                    )
                    for lane in lanes
                ],
            }
        )
    return payloads


async def _heat_payload(session: AsyncSession, heat: Heat) -> dict:
    payloads = await _heats_payload(session, [heat])
    return payloads[0]


async def _prova_heats(session: AsyncSession, prova_id: str) -> list[Heat]:
    result = await session.execute(
        select(Heat)
        .where(Heat.prova_id == prova_id)
        .order_by(Heat.order_num)
    )
    return list(result.scalars().all())


async def _provas_payload(
    session: AsyncSession,
    provas: list[Prova],
    *,
    include_heats: bool = True,
) -> list[dict]:
    if not provas:
        return []
    event_id = provas[0].event_id
    result = await session.execute(
        select(Heat)
        .where(Heat.event_id == event_id)
        .order_by(Heat.order_num)
    )
    heats = list(result.scalars().all())
    heat_payloads = await _heats_payload(session, heats) if include_heats else []
    payload_by_heat = {payload["id"]: payload for payload in heat_payloads}
    heats_by_prova: dict[str, list[Heat]] = {}
    for heat in heats:
        heats_by_prova.setdefault(heat.prova_id, []).append(heat)

    payloads = []
    for prova in provas:
        prova_heats = sorted(
            heats_by_prova.get(prova.id, []),
            key=lambda heat: heat.order_num,
        )
        payloads.append(
            {
                "id": prova.id,
                "event_id": prova.event_id,
                "name": prova.name,
                "order_num": prova.order_num,
                "stroke": prova.stroke,
                "distance_m": prova.distance_m,
                "category": prova.category,
                "naipe": prova.naipe,
                "consolidate_results": prova.consolidate_results,
                "classification_criterion": prova.classification_criterion,
                "status": prova_status([heat.status for heat in prova_heats]),
                "created_at": prova.created_at,
                "heat_count": len(prova_heats),
                "heat_orders": [heat.order_num for heat in prova_heats],
                "heats": [
                    payload_by_heat[heat.id]
                    for heat in prova_heats
                    if heat.id in payload_by_heat
                ],
            }
        )
    return payloads


async def _prova_payload(
    session: AsyncSession, prova: Prova, *, include_heats: bool = True
) -> dict:
    payloads = await _provas_payload(
        session, [prova], include_heats=include_heats
    )
    return payloads[0]


async def _classification_payload(
    session: AsyncSession, prova: Prova
) -> dict:
    heats = await _prova_heats(session, prova.id)
    heat_ids = [heat.id for heat in heats]
    lane_map: dict[str, list[HeatLane]] = {heat_id: [] for heat_id in heat_ids}
    if heat_ids:
        result = await session.execute(
            select(HeatLane)
            .where(HeatLane.heat_id.in_(heat_ids))
            .order_by(HeatLane.lane_number)
        )
        for lane in result.scalars().all():
            lane_map[lane.heat_id].append(lane)

    event = await session.get(Event, prova.event_id)
    team_map = await _team_map(session, prova.event_id)
    heat_dicts = [
        {
            "id": heat.id,
            "name": heat.name,
            "order_num": heat.order_num,
            "status": heat.status,
            "distance_m": heat.distance_m,
            "lanes": [
                {
                    "id": lane.id,
                    "lane_number": lane.lane_number,
                    "participant_name": lane.participant_name,
                    "team_id": lane.team_id,
                    "status": lane.status,
                    "race_time_ms": lane.race_time_ms,
                }
                for lane in lane_map.get(heat.id, [])
            ],
        }
        for heat in heats
    ]
    classification = build_classification(
        consolidate_results=prova.consolidate_results,
        heats=heat_dicts,
        team_map=team_map,
        pool_distance_m=event.pool_length_m if event else None,
    )
    return {
        "prova_id": prova.id,
        "name": prova.name,
        "naipe": prova.naipe,
        "category": prova.category,
        "status": classification["status"],
        "consolidate_results": prova.consolidate_results,
        "classification_criterion": prova.classification_criterion,
        "is_provisional": classification["is_provisional"],
        "standings": classification["standings"],
        "excluded": classification["excluded"],
        "battery_results": classification["battery_results"],
    }


async def _sync_prova_status(session: AsyncSession, prova_id: str) -> None:
    prova = await session.get(Prova, prova_id)
    if prova is None:
        return
    result = await session.execute(
        select(Heat.status).where(Heat.prova_id == prova_id)
    )
    prova.status = prova_status(list(result.scalars().all()))


async def _event_payload(
    session: AsyncSession, event: Event, *, include_teams: bool = False
) -> dict:
    result = await session.execute(
        select(Heat)
        .join(Prova, Heat.prova_id == Prova.id)
        .where(Heat.event_id == event.id)
        .order_by(Prova.order_num, Heat.order_num)
    )
    heats = result.scalars().all()
    result = await session.execute(
        select(Prova)
        .where(Prova.event_id == event.id)
        .order_by(Prova.order_num)
    )
    provas = result.scalars().all()
    payload = {
        "id": event.id,
        "name": event.name,
        "location": event.location,
        "date": event.date,
        "pool_length_m": event.pool_length_m,
        "status": event.status,
        "created_at": event.created_at,
        "provas": [
            {
                "id": prova.id,
                "event_id": prova.event_id,
                "name": prova.name,
                "order_num": prova.order_num,
                "stroke": prova.stroke,
                "distance_m": prova.distance_m,
                "category": prova.category,
                "naipe": prova.naipe,
                "consolidate_results": prova.consolidate_results,
                "classification_criterion": prova.classification_criterion,
                "status": prova.status,
                "heat_count": sum(
                    1 for heat in heats if heat.prova_id == prova.id
                ),
            }
            for prova in provas
        ],
        "heats": await _heats_payload(session, heats),
    }
    if include_teams:
        result = await session.execute(
            select(Team).where(Team.event_id == event.id).order_by(Team.name)
        )
        counts = await _team_athlete_counts(session, event.id)
        payload["teams"] = [
            _team_dict(team, counts.get(team.id, 0))
            for team in result.scalars().all()
        ]
    return payload


def _participant_lanes(lanes: list[HeatLane]) -> list[HeatLane]:
    return [
        lane
        for lane in lanes
        if lane.participant_name or lane.athlete_id or lane.team_id
    ]


async def _heat_lanes(session: AsyncSession, heat_id: str) -> list[HeatLane]:
    result = await session.execute(
        select(HeatLane)
        .where(HeatLane.heat_id == heat_id)
        .order_by(HeatLane.lane_number)
    )
    return list(result.scalars().all())


def _ready_payload(lanes: list[HeatLane]) -> dict:
    participants = _participant_lanes(lanes)
    ready = [lane.lane_number for lane in participants if lane.status == "ready"]
    pending = [lane.lane_number for lane in participants if lane.status != "ready"]
    return {
        "lanes_ready": ready,
        "lanes_pending": pending,
        "all_ready": bool(participants) and not pending,
    }


def _heat_state_message(heat_payload: dict) -> dict:
    return {
        "type": "heat_state",
        "scope": "heat",
        "heat_id": heat_payload["id"],
        "payload": heat_payload,
    }


def _ready_update_message(heat_id: str, ready_payload: dict) -> dict:
    return {
        "type": "ready_update",
        "scope": "heat",
        "heat_id": heat_id,
        "payload": ready_payload,
    }


def _prova_state_message(prova_payload: dict) -> dict:
    return {
        "type": "prova_state",
        "scope": "prova",
        "prova_id": prova_payload["id"],
        "payload": prova_payload,
    }


async def _active_heat_count(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Heat)
        .where(Heat.status == "active")
    )
    return int(result.scalar_one())


async def _server_status_message(session: AsyncSession) -> dict:
    return {
        "type": "server_status",
        "scope": "home",
        "payload": {
            "connected": manager.count,
            "active_heats": await _active_heat_count(session),
        },
    }


async def _broadcast_server_status() -> None:
    async with AsyncSessionLocal() as session:
        await manager.broadcast(await _server_status_message(session))


async def _broadcast_heat(session: AsyncSession, heat: Heat) -> None:
    await manager.broadcast(_heat_state_message(await _heat_payload(session, heat)))
    prova = await session.get(Prova, heat.prova_id)
    if prova is not None:
        await manager.broadcast(
            _prova_state_message(await _prova_payload(session, prova))
        )


async def _broadcast_ready(session: AsyncSession, heat: Heat) -> None:
    lanes = await _heat_lanes(session, heat.id)
    await manager.broadcast(_ready_update_message(heat.id, _ready_payload(lanes)))


async def _maybe_finish_heat(session: AsyncSession, heat: Heat) -> bool:
    await session.flush()
    lanes = await _heat_lanes(session, heat.id)
    participants = _participant_lanes(lanes)
    finished = False
    if participants and all(
        lane.status in ("finished", "dq") for lane in participants
    ):
        heat.status = "finished"
        heat.finished_at = time.time()
        finished = True
    await _sync_prova_status(session, heat.prova_id)
    return finished


# --------------------------------------------------------------------------- #
# Eventos
# --------------------------------------------------------------------------- #
@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": "2.3.0"}


@app.get("/api/status")
async def server_status(session: AsyncSession = Depends(get_db)) -> dict:
    return {
        "uptime": time.time() - START_TIME,
        "connected_clients": manager.count,
        "active_heats": await _active_heat_count(session),
    }


@app.get("/api/events")
async def list_events(
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = select(Event).order_by(Event.created_at.desc()).offset(offset)
    if limit is not None:
        query = query.limit(limit)
    result = await session.execute(query)
    return [
        await _event_payload(session, event, include_teams=True)
        for event in result.scalars().all()
    ]


@app.post("/api/events", status_code=201)
async def create_event(
    payload: EventCreate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    event = Event(
        name=payload.name,
        location=payload.location,
        date=payload.date,
        pool_length_m=payload.pool_length_m,
        status="draft",
        created_at=time.time(),
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    await _broadcast_server_status()
    return await _event_payload(session, event, include_teams=True)


@app.get("/api/events/{event_id}")
async def get_event(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    event = await _get_event(session, event_id)
    return await _event_payload(session, event, include_teams=True)


@app.patch("/api/events/{event_id}")
async def update_event(
    event_id: str,
    payload: EventUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    event = await _get_event(session, event_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(event, field, value)
    await session.commit()
    await session.refresh(event)
    return await _event_payload(session, event, include_teams=True)


@app.delete("/api/events/{event_id}", status_code=204)
async def delete_event(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    event = await _get_event(session, event_id)
    if event.status != "draft":
        raise HTTPException(status_code=409, detail="evento_nao_esta_draft")
    heat_ids = select(Heat.id).where(Heat.event_id == event_id)
    lane_ids = select(HeatLane.id).where(HeatLane.heat_id.in_(heat_ids))
    await session.execute(delete(LapEvent).where(LapEvent.lane_id.in_(lane_ids)))
    await session.execute(delete(HeatLane).where(HeatLane.heat_id.in_(heat_ids)))
    await session.execute(delete(Athlete).where(Athlete.event_id == event_id))
    await session.execute(delete(Heat).where(Heat.event_id == event_id))
    await session.execute(delete(Prova).where(Prova.event_id == event_id))
    await session.execute(delete(Team).where(Team.event_id == event_id))
    await session.delete(event)
    await session.commit()
    await _broadcast_server_status()


# --------------------------------------------------------------------------- #
# Equipes
# --------------------------------------------------------------------------- #
@app.post(
    "/api/events/{event_id}/teams",
    status_code=201,
    response_model=TeamResponse,
)
async def create_team(
    event_id: str,
    payload: TeamCreate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    await _get_event(session, event_id)
    team = Team(event_id=event_id, name=payload.name)
    session.add(team)
    await session.commit()
    await session.refresh(team)
    return _team_dict(team)


@app.get("/api/events/{event_id}/teams", response_model=list[TeamResponse])
async def list_teams(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_event(session, event_id)
    result = await session.execute(
        select(Team).where(Team.event_id == event_id).order_by(Team.name)
    )
    counts = await _team_athlete_counts(session, event_id)
    return [
        _team_dict(team, counts.get(team.id, 0))
        for team in result.scalars().all()
    ]


@app.patch("/api/teams/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: str,
    payload: TeamUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(team, field, value)
    await session.commit()
    await session.refresh(team)
    count = await session.scalar(
        select(func.count())
        .select_from(Athlete)
        .where(Athlete.team_id == team.id)
    )
    return _team_dict(team, int(count or 0))


def _sniff_image(data: bytes) -> tuple[str, str] | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if (
        len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):
        return "webp", "image/webp"
    return None


def _logo_path_from_url(url: str | None) -> Path | None:
    if not url or not url.startswith("/logos/"):
        return None
    name = url[len("/logos/"):]
    if "/" in name or "\\" in name or name in ("", ".", ".."):
        return None
    return settings.logo_dir / name


def _remove_logo_file(url: str | None) -> None:
    path = _logo_path_from_url(url)
    if path is None:
        return
    try:
        if path.parent == settings.logo_dir:
            path.unlink(missing_ok=True)
    except OSError:
        pass


@app.post("/api/teams/{team_id}/logo")
async def upload_team_logo(
    team_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
) -> dict:
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="equipe_nao_encontrada")

    data = await file.read(settings.MAX_LOGO_BYTES + 1)
    if len(data) > settings.MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail="arquivo_muito_grande")
    if not data:
        raise HTTPException(status_code=400, detail="arquivo_vazio")
    signature = _sniff_image(data)
    if signature is None:
        raise HTTPException(status_code=415, detail="formato_invalido")
    extension, _mime = signature

    settings.logo_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}.{extension}"
    destination = settings.logo_dir / filename
    destination.write_bytes(data)

    old_url = team.logo_url
    team.logo_url = f"/logos/{filename}"
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        destination.unlink(missing_ok=True)
        raise
    await session.refresh(team)
    if old_url != team.logo_url:
        _remove_logo_file(old_url)
    return _team_dict(team)


@app.delete("/api/teams/{team_id}/logo")
async def delete_team_logo(
    team_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
    old_url = team.logo_url
    team.logo_url = None
    await session.commit()
    await session.refresh(team)
    _remove_logo_file(old_url)
    return _team_dict(team)


@app.delete("/api/teams/{team_id}", status_code=204)
async def delete_team(
    team_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
    usage = await session.scalar(
        select(func.count())
        .select_from(HeatLane)
        .where(HeatLane.team_id == team_id)
    )
    athletes = await session.scalar(
        select(func.count())
        .select_from(Athlete)
        .where(Athlete.team_id == team_id)
    )
    if usage or athletes:
        raise HTTPException(status_code=409, detail="equipe_em_uso")
    await session.delete(team)
    await session.commit()


# --------------------------------------------------------------------------- #
# Atletas
# --------------------------------------------------------------------------- #
def _athlete_dict(athlete: Athlete, team: Team | None = None) -> dict:
    return {
        "id": athlete.id,
        "event_id": athlete.event_id,
        "team_id": athlete.team_id,
        "name": athlete.name,
        "naipe": athlete.naipe,
        "category": athlete.category,
        "created_at": athlete.created_at,
        "updated_at": athlete.updated_at,
        "team_name": team.name if team else None,
        "team_logo_url": team.logo_url if team else None,
    }


async def _get_athlete(session: AsyncSession, athlete_id: str) -> Athlete:
    athlete = await session.get(Athlete, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=404, detail="atleta_nao_encontrado")
    return athlete


def _validate_reorder_ids(ids: list[str], known: set[str]) -> None:
    """Exige o conjunto completo de IDs, sem duplicatas ou itens externos."""
    if len(ids) != len(set(ids)) or set(ids) != known:
        raise HTTPException(status_code=400, detail="ordem_ids_invalidos")


async def _validate_athlete_team(
    session: AsyncSession, event_id: str, team_id: str | None
) -> Team | None:
    if team_id is None:
        return None
    team = await session.get(Team, team_id)
    if team is None or team.event_id != event_id:
        raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
    return team


async def _broadcast_athletes_changed(event_id: str) -> None:
    await manager.broadcast(
        {
            "type": "athletes_changed",
            "scope": "event",
            "payload": {"event_id": event_id},
        }
    )


async def _athlete_duplicate_exists(
    session: AsyncSession,
    event_id: str,
    name: str,
    team_id: str | None,
    *,
    exclude_id: str | None = None,
) -> bool:
    query = (
        select(func.count())
        .select_from(Athlete)
        .where(
            Athlete.event_id == event_id,
            func.lower(Athlete.name) == name.lower(),
            func.coalesce(Athlete.team_id, "") == (team_id or ""),
        )
    )
    if exclude_id is not None:
        query = query.where(Athlete.id != exclude_id)
    return bool(await session.scalar(query))


@app.post(
    "/api/events/{event_id}/athletes",
    status_code=201,
    response_model=AthleteResponse,
)
async def create_athlete(
    event_id: str,
    payload: AthleteCreate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    await _get_event(session, event_id)
    team = await _validate_athlete_team(session, event_id, payload.team_id)
    if await _athlete_duplicate_exists(
        session, event_id, payload.name, payload.team_id
    ):
        raise HTTPException(status_code=409, detail="atleta_duplicado")

    athlete = Athlete(
        event_id=event_id,
        team_id=payload.team_id,
        name=payload.name,
        naipe=payload.naipe,
        category=payload.category,
        created_at=time.time(),
    )
    session.add(athlete)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="atleta_duplicado")
    await session.refresh(athlete)
    await _broadcast_athletes_changed(event_id)
    return _athlete_dict(athlete, team)


@app.get(
    "/api/events/{event_id}/athletes",
    response_model=AthleteListResponse,
)
async def list_athletes(
    event_id: str,
    q: str | None = Query(default=None, max_length=120),
    team_id: str | None = Query(default=None),
    naipe: str | None = Query(default=None),
    category: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> dict:
    await _get_event(session, event_id)
    conditions = [Athlete.event_id == event_id]

    if q and q.strip():
        conditions.append(Athlete.name.ilike(f"%{q.strip()}%"))
    if team_id:
        conditions.append(Athlete.team_id == team_id)
    if naipe:
        normalized = normalize_naipe(naipe)
        if normalized not in ("M", "F"):
            raise HTTPException(status_code=400, detail="naipe_invalido")
        conditions.append(Athlete.naipe == normalized)
    if category:
        conditions.append(
            Athlete.category == normalize_category(category)
        )

    total = await session.scalar(
        select(func.count()).select_from(Athlete).where(*conditions)
    )
    result = await session.execute(
        select(Athlete)
        .where(*conditions)
        .order_by(Athlete.name, Athlete.id)
        .limit(limit)
        .offset(offset)
    )
    athletes = list(result.scalars().all())

    team_ids = {athlete.team_id for athlete in athletes if athlete.team_id}
    teams: dict[str, Team] = {}
    if team_ids:
        result = await session.execute(
            select(Team).where(Team.id.in_(team_ids))
        )
        teams = {team.id: team for team in result.scalars().all()}

    return {
        "items": [
            _athlete_dict(athlete, teams.get(athlete.team_id))
            for athlete in athletes
        ],
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/athletes/{athlete_id}", response_model=AthleteResponse)
async def get_athlete(
    athlete_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    athlete = await _get_athlete(session, athlete_id)
    team = await session.get(Team, athlete.team_id) if athlete.team_id else None
    return _athlete_dict(athlete, team)


@app.patch("/api/athletes/{athlete_id}", response_model=AthleteResponse)
async def update_athlete(
    athlete_id: str,
    payload: AthleteUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    athlete = await _get_athlete(session, athlete_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and not data["name"]:
        raise HTTPException(status_code=422, detail="nome_obrigatorio")

    if "team_id" in data:
        await _validate_athlete_team(
            session, athlete.event_id, data["team_id"]
        )

    new_name = data.get("name", athlete.name)
    new_team_id = data["team_id"] if "team_id" in data else athlete.team_id
    if "name" in data or "team_id" in data:
        if await _athlete_duplicate_exists(
            session,
            athlete.event_id,
            new_name,
            new_team_id,
            exclude_id=athlete.id,
        ):
            raise HTTPException(status_code=409, detail="atleta_duplicado")

    for field, value in data.items():
        setattr(athlete, field, value)
    athlete.updated_at = time.time()

    # Mantem a copia desnormalizada das raias em sincronia para os clientes
    # (fiscal/supervisor/publico) que leem participant_name diretamente.
    await session.execute(
        update(HeatLane)
        .where(HeatLane.athlete_id == athlete.id)
        .values(participant_name=athlete.name, team_id=athlete.team_id)
    )
    await session.commit()
    await session.refresh(athlete)
    team = await session.get(Team, athlete.team_id) if athlete.team_id else None
    await _broadcast_athletes_changed(athlete.event_id)
    return _athlete_dict(athlete, team)


@app.delete("/api/athletes/{athlete_id}", status_code=204)
async def delete_athlete(
    athlete_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    athlete = await _get_athlete(session, athlete_id)
    usage = await session.scalar(
        select(func.count())
        .select_from(HeatLane)
        .where(HeatLane.athlete_id == athlete.id)
    )
    if usage:
        raise HTTPException(status_code=409, detail="atleta_em_uso")
    event_id = athlete.event_id
    await session.delete(athlete)
    await session.commit()
    await _broadcast_athletes_changed(event_id)


# ---------------- Importacao / exportacao de planilhas ---------------- #
_IMPORT_COLUMNS = ("NOME", "EQUIPE", "NAIPE", "CATEGORIA")


def _strip_accents(value: str) -> str:
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )


def _normalize_header(value: object) -> str:
    if value is None:
        return ""
    return _strip_accents(str(value)).strip().upper()


def _parse_csv_rows(data: bytes) -> list[list[object]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    return [row for row in reader]


def _parse_xlsx_rows(data: bytes) -> list[list[object]]:
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        sheet = workbook.active
        if sheet is None:
            return []
        return [list(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


def _detect_header(rows: list[list[object]]) -> tuple[int, dict[str, int]]:
    for index, row in enumerate(rows[:20]):
        headers = [_normalize_header(cell) for cell in row]
        if "NOME" in headers:
            return index, {
                header: position
                for position, header in enumerate(headers)
                if header
            }
    raise HTTPException(status_code=400, detail="planilha_sem_cabecalho")


def _cell(row: list[object], position: int | None) -> str:
    if position is None or position >= len(row) or row[position] is None:
        return ""
    return str(row[position]).strip()


@app.post(
    "/api/events/{event_id}/athletes/import",
    response_model=AthleteImportResult,
)
async def import_athletes(
    event_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
) -> dict:
    await _get_event(session, event_id)

    filename = (file.filename or "").lower()
    if filename.endswith(".xlsx"):
        fmt = "xlsx"
    elif filename.endswith(".csv") or filename.endswith(".txt"):
        fmt = "csv"
    else:
        raise HTTPException(status_code=415, detail="formato_invalido")

    data = await file.read(settings.MAX_IMPORT_BYTES + 1)
    if len(data) > settings.MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="arquivo_muito_grande")
    if not data:
        raise HTTPException(status_code=400, detail="arquivo_vazio")
    if fmt == "xlsx" and not data.startswith(b"PK\x03\x04"):
        raise HTTPException(status_code=415, detail="formato_invalido")

    if fmt == "xlsx":
        try:
            rows = _parse_xlsx_rows(data)
        except Exception:
            raise HTTPException(
                status_code=400, detail="planilha_invalida"
            )
    else:
        rows = _parse_csv_rows(data)

    header_index, header_map = _detect_header(rows)
    missing = [
        column for column in _IMPORT_COLUMNS if column not in header_map
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"colunas_obrigatorias:{','.join(missing)}",
        )

    data_rows = len(rows) - header_index - 1
    if data_rows > settings.MAX_IMPORT_ROWS:
        raise HTTPException(status_code=413, detail="planilha_muito_grande")

    result = await session.execute(
        select(Team).where(Team.event_id == event_id)
    )
    teams_by_key = {
        team.name.casefold(): team for team in result.scalars().all()
    }
    result = await session.execute(
        select(Athlete.name, Athlete.team_id).where(
            Athlete.event_id == event_id
        )
    )
    existing_keys = {
        (name.casefold(), team_id or "") for name, team_id in result.all()
    }

    errors: list[dict] = []
    pending: list[Athlete] = []
    created_teams = 0
    skipped = 0
    now = time.time()

    name_col = header_map["NOME"]
    team_col = header_map["EQUIPE"]
    naipe_col = header_map["NAIPE"]
    category_col = header_map["CATEGORIA"]

    for index, row in enumerate(rows):
        if index <= header_index:
            continue
        line = index + 1

        name = _cell(row, name_col)
        team_name = _cell(row, team_col)
        naipe_raw = _cell(row, naipe_col)
        category_raw = _cell(row, category_col)

        if not name and not team_name and not naipe_raw and not category_raw:
            skipped += 1
            continue
        if not name:
            errors.append(
                {"line": line, "field": "nome", "message": "nome_obrigatorio"}
            )
            continue
        naipe = normalize_naipe(naipe_raw)
        if naipe not in ("M", "F"):
            errors.append(
                {"line": line, "field": "naipe", "message": "naipe_invalido"}
            )
            continue

        team_id: str | None = None
        if team_name:
            key = team_name.casefold()
            team = teams_by_key.get(key)
            if team is None:
                team = Team(event_id=event_id, name=team_name)
                session.add(team)
                await session.flush()
                teams_by_key[key] = team
                created_teams += 1
            team_id = team.id

        duplicate_key = (name.casefold(), team_id or "")
        if duplicate_key in existing_keys:
            errors.append(
                {"line": line, "field": "nome", "message": "atleta_duplicado"}
            )
            continue
        existing_keys.add(duplicate_key)

        pending.append(
            Athlete(
                event_id=event_id,
                team_id=team_id,
                name=name,
                naipe=naipe,
                category=normalize_category(category_raw),
                created_at=now,
            )
        )

    session.add_all(pending)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="importacao_conflito")

    await _broadcast_athletes_changed(event_id)
    return {
        "created_athletes": len(pending),
        "created_teams": created_teams,
        "skipped": skipped,
        "errors": errors,
    }


def _attachment_response(
    content: bytes, filename: str, media_type: str
) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@app.get("/api/events/{event_id}/athletes/import-template")
async def download_athletes_template(
    event_id: str,
    format: str = Query(default="csv", pattern="^(csv|xlsx)$"),
    session: AsyncSession = Depends(get_db),
) -> Response:
    await _get_event(session, event_id)
    if format == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(list(_IMPORT_COLUMNS))
        sheet.append(["Maria Silva", "Equipe A", "F", "SUB-12"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        return _attachment_response(
            buffer.getvalue(),
            "modelo_atletas.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    return _attachment_response(
        ("\ufeff" + ",".join(_IMPORT_COLUMNS) + "\n"
         "Maria Silva,Equipe A,F,SUB-12\n").encode("utf-8"),
        "modelo_atletas.csv",
        "text/csv; charset=utf-8",
    )


@app.get("/api/events/{event_id}/athletes/export")
async def export_athletes(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> Response:
    await _get_event(session, event_id)
    result = await session.execute(
        select(Athlete, Team.name)
        .outerjoin(Team, Athlete.team_id == Team.id)
        .where(Athlete.event_id == event_id)
        .order_by(Athlete.name)
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_IMPORT_COLUMNS)
    for athlete, team_name in result.all():
        writer.writerow(
            [
                athlete.name,
                team_name or "",
                athlete.naipe,
                athlete.category or "",
            ]
        )
    return _attachment_response(
        ("\ufeff" + buffer.getvalue()).encode("utf-8"),
        "atletas.csv",
        "text/csv; charset=utf-8",
    )


# --------------------------------------------------------------------------- #
# Provas
# --------------------------------------------------------------------------- #
async def _next_prova_order(session: AsyncSession, event_id: str) -> int:
    result = await session.execute(
        select(func.max(Prova.order_num)).where(Prova.event_id == event_id)
    )
    return int(result.scalar_one() or 0) + 1


async def _create_prova_record(
    session: AsyncSession, event_id: str, payload: ProvaCreate
) -> Prova:
    if payload.order_num is not None:
        order_num = payload.order_num
        result = await session.execute(
            select(Prova.id).where(
                Prova.event_id == event_id, Prova.order_num == order_num
            )
        )
        if result.first() is not None:
            raise HTTPException(status_code=400, detail="order_num_duplicado")
    else:
        order_num = await _next_prova_order(session, event_id)

    prova = Prova(
        event_id=event_id,
        name=payload.name,
        order_num=order_num,
        stroke=payload.stroke,
        distance_m=payload.distance_m,
        category=payload.category,
        naipe=payload.naipe,
        consolidate_results=payload.consolidate_results,
        classification_criterion=payload.classification_criterion,
        status="scheduled",
        created_at=time.time(),
    )
    session.add(prova)
    return prova


@app.post("/api/events/{event_id}/provas", status_code=201)
async def create_prova(
    event_id: str,
    payload: ProvaCreate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _heat_guard(f"event:{event_id}"):
        session.expire_all()
        await _get_event(session, event_id)
        prova = await _create_prova_record(session, event_id, payload)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=400, detail="order_num_duplicado")
        await session.refresh(prova)
    await _broadcast_server_status()
    return await _prova_payload(session, prova)


@app.get("/api/events/{event_id}/provas")
async def list_provas(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_event(session, event_id)
    result = await session.execute(
        select(Prova)
        .where(Prova.event_id == event_id)
        .order_by(Prova.order_num)
    )
    return await _provas_payload(
        session, list(result.scalars().all()), include_heats=True
    )


@app.get("/api/provas/{prova_id}")
async def get_prova(
    prova_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    prova = await _get_prova(session, prova_id)
    return await _prova_payload(session, prova)


@app.patch("/api/provas/{prova_id}")
async def update_prova(
    prova_id: str,
    payload: ProvaUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    prova = await _get_prova(session, prova_id)
    async with _heat_guard(f"event:{prova.event_id}"):
        session.expire_all()
        prova = await _get_prova(session, prova_id)
        heats = await _prova_heats(session, prova.id)
        started = any(heat.status != "scheduled" for heat in heats)
        data = payload.model_dump(exclude_unset=True)
        operational = {
            "order_num",
            "consolidate_results",
            "classification_criterion",
            "distance_m",
        }
        if started and operational & set(data):
            raise HTTPException(status_code=409, detail="prova_ja_iniciada")

        new_order = data.get("order_num")
        if new_order is not None and new_order != prova.order_num:
            result = await session.execute(
                select(Prova.id).where(
                    Prova.event_id == prova.event_id,
                    Prova.order_num == new_order,
                    Prova.id != prova.id,
                )
            )
            if result.first() is not None:
                raise HTTPException(
                    status_code=400, detail="order_num_duplicado"
                )
        for field, value in data.items():
            setattr(prova, field, value)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=400, detail="order_num_duplicado")
        await session.refresh(prova)
        await _sync_prova_status(session, prova.id)
        await session.commit()
        await session.refresh(prova)
        payload_out = await _prova_payload(session, prova)
    await manager.broadcast(_prova_state_message(payload_out))
    return payload_out


@app.put("/api/events/{event_id}/provas/order")
async def reorder_provas(
    event_id: str,
    payload: OrderIdsRequest,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Reordena todas as provas do evento em uma unica transacao."""
    async with _heat_guard(f"event:{event_id}"):
        session.expire_all()
        await _get_event(session, event_id)
        result = await session.execute(
            select(Prova).where(Prova.event_id == event_id)
        )
        provas = list(result.scalars().all())
        _validate_reorder_ids(payload.ids, {prova.id for prova in provas})
        if any(prova.status != "scheduled" for prova in provas):
            raise HTTPException(status_code=409, detail="prova_ja_iniciada")

        # Desloca temporariamente para liberar 1..N sem violar o indice unico.
        offset = 100000
        await session.execute(
            update(Prova)
            .where(Prova.event_id == event_id)
            .values(order_num=Prova.order_num + offset),
            execution_options={"synchronize_session": False},
        )
        session.expire_all()
        for index, prova_id in enumerate(payload.ids):
            prova = await session.get(Prova, prova_id)
            prova.order_num = index + 1
        await session.commit()

        result = await session.execute(
            select(Prova)
            .where(Prova.event_id == event_id)
            .order_by(Prova.order_num)
        )
        provas = list(result.scalars().all())
        payloads = await _provas_payload(
            session, provas, include_heats=True
        )

    for prova_payload in payloads:
        await manager.broadcast(_prova_state_message(prova_payload))
    return payloads


@app.delete("/api/provas/{prova_id}", status_code=204)
async def delete_prova(
    prova_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    prova = await _get_prova(session, prova_id)
    async with _heat_guard(f"event:{prova.event_id}"):
        session.expire_all()
        prova = await _get_prova(session, prova_id)
        heats = await _prova_heats(session, prova.id)
        if any(heat.status != "scheduled" for heat in heats):
            raise HTTPException(
                status_code=409, detail="prova_possui_baterias_iniciadas"
            )
        heat_ids = [heat.id for heat in heats]
        if heat_ids:
            lane_ids = select(HeatLane.id).where(
                HeatLane.heat_id.in_(heat_ids)
            )
            await session.execute(
                delete(LapEvent).where(LapEvent.lane_id.in_(lane_ids))
            )
            await session.execute(
                delete(HeatLane).where(HeatLane.heat_id.in_(heat_ids))
            )
            await session.execute(delete(Heat).where(Heat.id.in_(heat_ids)))
        await session.delete(prova)
        await session.commit()
    await _broadcast_server_status()


@app.get("/api/provas/{prova_id}/classification")
async def get_prova_classification(
    prova_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    prova = await _get_prova(session, prova_id)
    return await _classification_payload(session, prova)


@app.post("/api/provas/{prova_id}/heats", status_code=201)
async def create_heat_in_prova(
    prova_id: str,
    payload: HeatCreate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    if payload.heat_type == "bateria" and payload.distance_m is None:
        raise HTTPException(status_code=400, detail="distance_m_obrigatorio")
    if payload.heat_type == "maratona" and payload.duration_s is None:
        raise HTTPException(status_code=400, detail="duration_s_obrigatorio")

    async with _heat_guard(f"prova:{prova_id}"):
        session.expire_all()
        prova = await _get_prova(session, prova_id)
        if payload.order_num is not None:
            order_num = payload.order_num
            result = await session.execute(
                select(Heat.id).where(
                    Heat.prova_id == prova_id,
                    Heat.order_num == order_num,
                )
            )
            if result.first() is not None:
                raise HTTPException(
                    status_code=400, detail="order_num_duplicado"
                )
        else:
            result = await session.execute(
                select(func.max(Heat.order_num)).where(
                    Heat.prova_id == prova_id
                )
            )
            order_num = int(result.scalar_one() or 0) + 1

        heat = Heat(
            event_id=prova.event_id,
            prova_id=prova_id,
            name=payload.name,
            order_num=order_num,
            heat_type=payload.heat_type,
            distance_m=payload.distance_m,
            duration_s=payload.duration_s,
            status="scheduled",
        )
        session.add(heat)
        await _sync_prova_status(session, prova_id)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=400, detail="order_num_duplicado")
        await session.refresh(heat)
        await session.refresh(prova)

    await _broadcast_server_status()
    await manager.broadcast(
        _prova_state_message(await _prova_payload(session, prova))
    )
    return await _heat_payload(session, heat)


@app.get("/api/provas/{prova_id}/heats")
async def list_heats_in_prova(
    prova_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_prova(session, prova_id)
    heats = await _prova_heats(session, prova_id)
    return [await _heat_payload(session, heat) for heat in heats]


# --------------------------------------------------------------------------- #
# Baterias (heats)
# --------------------------------------------------------------------------- #
@app.get("/api/events/{event_id}/heats")
async def list_heats(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_event(session, event_id)
    result = await session.execute(
        select(Heat)
        .join(Prova, Heat.prova_id == Prova.id)
        .where(Heat.event_id == event_id)
        .order_by(Prova.order_num, Heat.order_num)
    )
    return [
        await _heat_payload(session, heat)
        for heat in result.scalars().all()
    ]


@app.patch("/api/heats/{heat_id}")
async def update_heat(
    heat_id: str,
    payload: HeatUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    heat = await _get_heat(session, heat_id)
    async with _heat_guard(f"prova:{heat.prova_id}"):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status not in ("scheduled", "ready_check"):
            raise HTTPException(status_code=409, detail="prova_ja_iniciada")
        data = payload.model_dump(exclude_unset=True)
        new_order = data.get("order_num")
        if new_order is not None and new_order != heat.order_num:
            result = await session.execute(
                select(Heat.id).where(
                    Heat.prova_id == heat.prova_id,
                    Heat.order_num == new_order,
                    Heat.id != heat.id,
                )
            )
            if result.first() is not None:
                raise HTTPException(
                    status_code=400, detail="order_num_duplicado"
                )
        for field, value in data.items():
            setattr(heat, field, value)
        await _sync_prova_status(session, heat.prova_id)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=400, detail="order_num_duplicado")
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        return await _heat_payload(session, heat)


@app.put("/api/provas/{prova_id}/heats/order")
async def reorder_heats(
    prova_id: str,
    payload: OrderIdsRequest,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Reordena todas as baterias de uma prova em uma unica transacao."""
    async with _heat_guard(f"prova:{prova_id}"):
        session.expire_all()
        prova = await _get_prova(session, prova_id)
        result = await session.execute(
            select(Heat).where(Heat.prova_id == prova_id)
        )
        heats = list(result.scalars().all())
        _validate_reorder_ids(payload.ids, {heat.id for heat in heats})
        if any(
            heat.status not in ("scheduled", "ready_check")
            for heat in heats
        ):
            raise HTTPException(status_code=409, detail="prova_ja_iniciada")

        offset = 100000
        await session.execute(
            update(Heat)
            .where(Heat.prova_id == prova_id)
            .values(order_num=Heat.order_num + offset),
            execution_options={"synchronize_session": False},
        )
        session.expire_all()
        for index, heat_id in enumerate(payload.ids):
            heat = await session.get(Heat, heat_id)
            heat.order_num = index + 1
        await session.commit()

        await session.refresh(prova)
        payload_out = await _prova_payload(session, prova)

    await manager.broadcast(_prova_state_message(payload_out))
    return payload_out["heats"]


@app.delete("/api/heats/{heat_id}", status_code=204)
async def delete_heat(
    heat_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    heat = await _get_heat(session, heat_id)
    prova_id = heat.prova_id
    async with _heat_guard(f"prova:{prova_id}"):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status != "scheduled":
            raise HTTPException(
                status_code=409, detail="prova_nao_esta_scheduled"
            )
        lane_ids = select(HeatLane.id).where(HeatLane.heat_id == heat_id)
        await session.execute(
            delete(LapEvent).where(LapEvent.lane_id.in_(lane_ids))
        )
        await session.execute(
            delete(HeatLane).where(HeatLane.heat_id == heat_id)
        )
        await session.delete(heat)
        await session.flush()
        await _sync_prova_status(session, prova_id)
        await session.commit()
        prova = await session.get(Prova, prova_id)
        payload_out = (
            _prova_state_message(await _prova_payload(session, prova))
            if prova is not None
            else None
        )
    await _broadcast_server_status()
    if payload_out is not None:
        await manager.broadcast(payload_out)


@app.post("/api/heats/{heat_id}/open-ready-check")
async def open_ready_check(
    heat_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status not in ("scheduled", "ready_check"):
            raise HTTPException(status_code=409, detail="prova_nao_esta_scheduled")
        heat.status = "ready_check"
        await _sync_prova_status(session, heat.prova_id)
        await session.commit()
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        return await _heat_payload(session, heat)


@app.post("/api/heats/{heat_id}/start")
async def start_heat(
    heat_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        direct_start = heat.status == "scheduled" and heat.heat_type == "maratona"
        if heat.status != "ready_check" and not direct_start:
            raise HTTPException(
                status_code=400, detail="prova_nao_esta_em_ready_check"
            )

        lanes = await _heat_lanes(session, heat.id)
        participants = _participant_lanes(lanes)
        if not participants:
            raise HTTPException(status_code=400, detail="sem_participantes")
        if not direct_start:
            pending = [
                lane.lane_number for lane in participants if lane.status != "ready"
            ]
            if pending:
                listed = ", ".join(str(number) for number in pending)
                raise HTTPException(
                    status_code=400, detail=f"raias_pendentes: {listed}"
                )

        heat.status = "active"
        heat.started_at = time.time()
        heat.finished_at = None
        for lane in participants:
            lane.status = "active"
        await _sync_prova_status(session, heat.prova_id)
        await session.commit()
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        await _broadcast_server_status()
        return await _heat_payload(session, heat)


@app.post("/api/heats/{heat_id}/abort")
async def abort_heat(
    heat_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status not in ("ready_check", "active"):
            raise HTTPException(status_code=409, detail="prova_nao_esta_ativa")
        heat.status = "scheduled"
        heat.started_at = None
        heat.finished_at = None
        result = await session.execute(
            update(HeatLane)
            .where(HeatLane.heat_id == heat.id, HeatLane.status == "active")
            .values(status="ready")
        )
        await _sync_prova_status(session, heat.prova_id)
        await session.commit()
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        await _broadcast_server_status()
        return await _heat_payload(session, heat)


@app.post("/api/heats/{heat_id}/finish")
async def finish_heat(
    heat_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status == "finished":
            return await _heat_payload(session, heat)
        if heat.status == "scheduled":
            raise HTTPException(status_code=409, detail="prova_nao_iniciada")
        heat.status = "finished"
        heat.finished_at = time.time()
        await _sync_prova_status(session, heat.prova_id)
        await session.commit()
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        await _broadcast_server_status()
        return await _heat_payload(session, heat)


# --------------------------------------------------------------------------- #
# Raias
# --------------------------------------------------------------------------- #
@app.post("/api/heats/{heat_id}/lanes")
async def configure_lanes(
    heat_id: str,
    payload: HeatLaneConfigRequest,
    session: AsyncSession = Depends(get_db),
) -> dict:
    numbers = [item.lane_number for item in payload.lanes]
    if len(numbers) != len(set(numbers)):
        raise HTTPException(status_code=400, detail="raias_duplicadas")

    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status not in ("scheduled", "ready_check"):
            raise HTTPException(status_code=409, detail="prova_ja_iniciada")

        existing = {
            lane.lane_number: lane for lane in await _heat_lanes(session, heat.id)
        }
        for item in payload.lanes:
            athlete = None
            if item.athlete_id is not None:
                athlete = await session.get(Athlete, item.athlete_id)
                if athlete is None or athlete.event_id != heat.event_id:
                    raise HTTPException(
                        status_code=404, detail="atleta_nao_encontrado"
                    )
            else:
                if item.team_id is not None:
                    team = await session.get(Team, item.team_id)
                    if team is None or team.event_id != heat.event_id:
                        raise HTTPException(
                            status_code=404, detail="equipe_nao_encontrada"
                        )
            participant_name = (
                athlete.name if athlete else item.participant_name
            )
            team_id = athlete.team_id if athlete else item.team_id
            lane = existing.get(item.lane_number)
            if lane is None:
                lane = HeatLane(
                    heat_id=heat.id,
                    lane_number=item.lane_number,
                    participant_name=participant_name,
                    athlete_id=item.athlete_id,
                    team_id=team_id,
                    status="assigned",
                )
                session.add(lane)
            else:
                lane.participant_name = participant_name
                lane.athlete_id = item.athlete_id
                lane.team_id = team_id
                lane.status = "assigned"
        await session.commit()
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        return await _heat_payload(session, heat)


@app.patch("/api/lanes/{lane_id}")
async def update_lane(
    lane_id: str,
    payload: LaneUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    lane = await _get_lane(session, lane_id)
    async with _heat_guard(lane.heat_id):
        session.expire_all()
        lane = await _get_lane(session, lane_id)
        heat = await _get_heat(session, lane.heat_id)
        if heat.status not in ("scheduled", "ready_check"):
            raise HTTPException(status_code=409, detail="prova_ja_iniciada")
        data = payload.model_dump(exclude_unset=True)
        if data.get("athlete_id") is not None:
            athlete = await session.get(Athlete, data["athlete_id"])
            if athlete is None or athlete.event_id != heat.event_id:
                raise HTTPException(
                    status_code=404, detail="atleta_nao_encontrado"
                )
            data["participant_name"] = athlete.name
            data["team_id"] = athlete.team_id
        if data.get("team_id") is not None:
            team = await session.get(Team, data["team_id"])
            if team is None or team.event_id != heat.event_id:
                raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
        for field, value in data.items():
            setattr(lane, field, value)
        if data:
            lane.status = "assigned"
        await session.commit()
        await session.refresh(lane)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        return await _lane_payload(session, lane, heat)


@app.post("/api/lanes/{lane_id}/ready")
async def lane_ready(
    lane_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    lane = await _get_lane(session, lane_id)
    async with _heat_guard(lane.heat_id):
        session.expire_all()
        lane = await _get_lane(session, lane_id)
        heat = await _get_heat(session, lane.heat_id)
        if heat.status != "ready_check":
            raise HTTPException(
                status_code=400, detail="prova_nao_esta_em_ready_check"
            )
        lane.status = "ready"
        await session.commit()
        await session.refresh(lane)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        return await _lane_payload(session, lane, heat)


class LaneActionError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


async def _do_finish(session: AsyncSession, lane_id: str) -> dict:
    lane = await session.get(HeatLane, lane_id)
    if lane is None:
        raise LaneActionError(404, "raia_nao_encontrada")
    heat_id = lane.heat_id

    async with _heat_guard(heat_id):
        session.expire_all()
        lane = await session.get(HeatLane, lane_id)
        if lane is None:
            raise LaneActionError(404, "raia_nao_encontrada")
        heat = await session.get(Heat, heat_id)
        if heat is None:
            raise LaneActionError(404, "prova_nao_encontrada")
        if heat.heat_type != "bateria":
            raise LaneActionError(400, "nao_e_bateria")
        if lane.finish_at is not None:
            raise LaneActionError(409, "ja_finalizou")
        if heat.status != "active":
            raise LaneActionError(400, "prova_nao_ativa")
        if heat.started_at is None:
            raise LaneActionError(400, "prova_nao_iniciada")

        finish_at = time.time()
        lane.finish_at = finish_at
        lane.race_time_ms = int((finish_at - heat.started_at) * 1000)
        lane.status = "finished"
        all_finished = await _maybe_finish_heat(session, heat)
        await session.commit()
        await session.refresh(lane)

        team_name = None
        if lane.team_id:
            team = await session.get(Team, lane.team_id)
            team_name = team.name if team else None

        await _broadcast_heat(session, heat)
        if all_finished:
            await _broadcast_server_status()

        return {
            "lane_id": lane.id,
            "lane_number": lane.lane_number,
            "participant_name": lane.participant_name,
            "team_name": team_name,
            "race_time_ms": lane.race_time_ms,
            "race_time_display": format_race_time(lane.race_time_ms),
            "speed_ms": compute_speed(heat.distance_m, lane.race_time_ms) or 0.0,
        }


async def _do_lap(session: AsyncSession, lane_id: str) -> dict:
    lane = await session.get(HeatLane, lane_id)
    if lane is None:
        raise LaneActionError(404, "raia_nao_encontrada")
    heat_id = lane.heat_id

    async with _heat_guard(heat_id):
        session.expire_all()
        lane = await session.get(HeatLane, lane_id)
        if lane is None:
            raise LaneActionError(404, "raia_nao_encontrada")
        heat = await session.get(Heat, heat_id)
        if heat is None:
            raise LaneActionError(404, "prova_nao_encontrada")
        if heat.heat_type != "maratona":
            raise LaneActionError(400, "nao_e_maratona")
        if heat.status != "active":
            raise LaneActionError(400, "prova_nao_ativa")

        result = await session.execute(
            select(func.max(LapEvent.lap_number)).where(
                LapEvent.lane_id == lane.id
            )
        )
        current = result.scalar_one()
        lap_number = int(current or 0) + 1
        event = LapEvent(
            lane_id=lane.id,
            lap_number=lap_number,
            recorded_at=time.time(),
            is_undo=False,
        )
        session.add(event)
        if lane.status in ("assigned", "ready"):
            lane.status = "active"
        await session.commit()
        await session.refresh(event)
        await _broadcast_heat(session, heat)
        return {
            "id": event.id,
            "lane_id": event.lane_id,
            "lap_number": event.lap_number,
            "recorded_at": event.recorded_at,
            "is_undo": event.is_undo,
        }


@app.post("/api/lanes/{lane_id}/finish")
async def lane_finish(
    lane_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await _do_finish(session, lane_id)
    except LaneActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@app.post("/api/lanes/{lane_id}/lap")
async def lane_lap(
    lane_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await _do_lap(session, lane_id)
    except LaneActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@app.post("/api/lanes/{lane_id}/dq")
async def lane_dq(
    lane_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    lane = await _get_lane(session, lane_id)
    async with _heat_guard(lane.heat_id):
        session.expire_all()
        lane = await _get_lane(session, lane_id)
        heat = await _get_heat(session, lane.heat_id)
        if heat.status != "active":
            raise HTTPException(status_code=400, detail="prova_nao_ativa")
        lane.status = "dq"
        all_finished = await _maybe_finish_heat(session, heat)
        await session.commit()
        await session.refresh(lane)
        await _broadcast_heat(session, heat)
        if all_finished:
            await _broadcast_server_status()
        return await _lane_payload(session, lane, heat)


@app.delete("/api/lanes/{lane_id}/lap/last")
async def undo_last_lap(
    lane_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    lane = await _get_lane(session, lane_id)
    async with _heat_guard(lane.heat_id):
        session.expire_all()
        lane = await _get_lane(session, lane_id)
        heat = await _get_heat(session, lane.heat_id)
        result = await session.execute(
            select(LapEvent)
            .where(LapEvent.lane_id == lane_id, LapEvent.is_undo.is_(False))
            .order_by(LapEvent.recorded_at.desc())
            .limit(1)
        )
        event = result.scalars().first()
        if event is None:
            raise HTTPException(status_code=404, detail="nenhum_lap")
        if time.time() - event.recorded_at >= 30.0:
            raise HTTPException(status_code=400, detail="fora_do_prazo")
        event.is_undo = True
        if lane.status == "active":
            result = await session.execute(
                select(func.count(LapEvent.id)).where(
                    LapEvent.lane_id == lane.id, LapEvent.is_undo.is_(False)
                )
            )
            if int(result.scalar_one()) == 0:
                lane.status = "assigned"
        await session.commit()
        await _broadcast_heat(session, heat)
        return {"status": "undone", "lane_id": lane.id}


# --------------------------------------------------------------------------- #
# WebSocket (broadcast global com escopos)
# --------------------------------------------------------------------------- #
async def _handle_ws_message(data: dict, websocket: WebSocket) -> None:
    message_type = data.get("type")
    if message_type == "finish":
        handler = _do_finish
    elif message_type == "lap":
        handler = _do_lap
    else:
        return
    lane_id = data.get("lane_id")
    if not lane_id:
        await manager.send_to(
            websocket, {"type": "error", "message": "lane_id_ausente"}
        )
        return
    async with AsyncSessionLocal() as session:
        try:
            await handler(session, lane_id)
        except LaneActionError as exc:
            await manager.send_to(
                websocket,
                {"type": "error", "message": exc.detail, "lane_id": lane_id},
            )
        except Exception:
            await manager.send_to(
                websocket,
                {"type": "error", "message": "erro_interno", "lane_id": lane_id},
            )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        await _broadcast_server_status()
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Heat)
                .where(Heat.status.in_(("ready_check", "active")))
                .order_by(Heat.order_num)
            )
            active_heats = list(result.scalars().all())
            for heat in active_heats:
                await manager.send_to(
                    websocket,
                    _heat_state_message(await _heat_payload(session, heat)),
                )
            seen_provas: set[str] = set()
            for heat in active_heats:
                if heat.prova_id in seen_provas:
                    continue
                seen_provas.add(heat.prova_id)
                prova = await session.get(Prova, heat.prova_id)
                if prova is not None:
                    await manager.send_to(
                        websocket,
                        _prova_state_message(
                            await _prova_payload(session, prova)
                        ),
                    )
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                raise
            except Exception:
                await manager.send_to(
                    websocket, {"type": "error", "message": "mensagem_invalida"}
                )
                continue
            try:
                await _handle_ws_message(data, websocket)
            except Exception:
                await manager.send_to(
                    websocket, {"type": "error", "message": "erro_interno"}
                )
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await _broadcast_server_status()
    except Exception:
        manager.disconnect(websocket)
        await _broadcast_server_status()


# --------------------------------------------------------------------------- #
# Frontend estático (montado por último para não capturar /api e /ws)
# --------------------------------------------------------------------------- #
settings.logo_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/logos",
    StaticFiles(directory=str(settings.logo_dir)),
    name="logos",
)

_frontend_dir = settings.frontend_dir
if _frontend_dir.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_frontend_dir), html=True),
        name="frontend",
    )
