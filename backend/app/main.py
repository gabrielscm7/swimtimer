import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import AsyncSessionLocal, engine, get_db, init_db
from .models import Event, Heat, HeatLane, LapEvent, Team
from .schemas import (
    EventCreate,
    EventUpdate,
    HeatCreate,
    HeatUpdate,
    HeatLaneConfigRequest,
    LaneUpdate,
    TeamCreate,
    compute_speed,
    format_race_time,
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
    await init_db()
    yield
    await engine.dispose()


app = FastAPI(title="SwimTimer", version="2.0.0", lifespan=lifespan)

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


async def _get_lane(session: AsyncSession, lane_id: str) -> HeatLane:
    lane = await session.get(HeatLane, lane_id)
    if lane is None:
        raise HTTPException(status_code=404, detail="raia_nao_encontrada")
    return lane


async def _team_names(session: AsyncSession, event_id: str) -> dict[str, str]:
    result = await session.execute(select(Team).where(Team.event_id == event_id))
    return {team.id: team.name for team in result.scalars().all()}


def _lane_dict(
    lane: HeatLane,
    *,
    heat: Heat,
    pool_length_m: int,
    team_name: str | None,
    laps: int = 0,
    last_lap_at: float | None = None,
) -> dict:
    return {
        "id": lane.id,
        "heat_id": lane.heat_id,
        "lane_number": lane.lane_number,
        "participant_name": lane.participant_name,
        "team_id": lane.team_id,
        "team": team_name,
        "status": lane.status,
        "finish_at": lane.finish_at,
        "race_time_ms": lane.race_time_ms,
        "race_time_display": format_race_time(lane.race_time_ms),
        "speed_ms": compute_speed(heat.distance_m, lane.race_time_ms),
        "laps": laps,
        "meters": laps * pool_length_m,
        "last_lap_at": last_lap_at,
    }


async def _heat_payload(session: AsyncSession, heat: Heat) -> dict:
    event = await session.get(Event, heat.event_id)
    pool_length_m = event.pool_length_m if event else 0
    team_map = await _team_names(session, heat.event_id)

    result = await session.execute(
        select(HeatLane)
        .where(HeatLane.heat_id == heat.id)
        .order_by(HeatLane.lane_number)
    )
    lanes = result.scalars().all()
    lane_ids = [lane.id for lane in lanes]

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

    return {
        "id": heat.id,
        "event_id": heat.event_id,
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
                team_name=team_map.get(lane.team_id) if lane.team_id else None,
                laps=lap_counts.get(lane.id, 0),
                last_lap_at=last_laps.get(lane.id),
            )
            for lane in lanes
        ],
    }


async def _event_payload(
    session: AsyncSession, event: Event, *, include_teams: bool = False
) -> dict:
    result = await session.execute(
        select(Heat).where(Heat.event_id == event.id).order_by(Heat.order_num)
    )
    heats = result.scalars().all()
    payload = {
        "id": event.id,
        "name": event.name,
        "location": event.location,
        "date": event.date,
        "pool_length_m": event.pool_length_m,
        "status": event.status,
        "created_at": event.created_at,
        "heats": [await _heat_payload(session, heat) for heat in heats],
    }
    if include_teams:
        result = await session.execute(
            select(Team).where(Team.event_id == event.id).order_by(Team.name)
        )
        payload["teams"] = [
            {"id": team.id, "event_id": team.event_id, "name": team.name}
            for team in result.scalars().all()
        ]
    return payload


def _participant_lanes(lanes: list[HeatLane]) -> list[HeatLane]:
    return [lane for lane in lanes if lane.participant_name or lane.team_id]


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


async def _broadcast_ready(session: AsyncSession, heat: Heat) -> None:
    lanes = await _heat_lanes(session, heat.id)
    await manager.broadcast(_ready_update_message(heat.id, _ready_payload(lanes)))


async def _maybe_finish_heat(session: AsyncSession, heat: Heat) -> bool:
    await session.flush()
    lanes = await _heat_lanes(session, heat.id)
    participants = _participant_lanes(lanes)
    if participants and all(
        lane.status in ("finished", "dq") for lane in participants
    ):
        heat.status = "finished"
        heat.finished_at = time.time()
        return True
    return False


# --------------------------------------------------------------------------- #
# Eventos
# --------------------------------------------------------------------------- #
@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": "2.0.0"}


@app.get("/api/status")
async def server_status(session: AsyncSession = Depends(get_db)) -> dict:
    return {
        "uptime": time.time() - START_TIME,
        "connected_clients": manager.count,
        "active_heats": await _active_heat_count(session),
    }


@app.get("/api/events")
async def list_events(session: AsyncSession = Depends(get_db)) -> list[dict]:
    result = await session.execute(
        select(Event).order_by(Event.created_at.desc())
    )
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
    await session.execute(delete(Heat).where(Heat.event_id == event_id))
    await session.execute(delete(Team).where(Team.event_id == event_id))
    await session.delete(event)
    await session.commit()
    await _broadcast_server_status()


# --------------------------------------------------------------------------- #
# Equipes
# --------------------------------------------------------------------------- #
@app.post("/api/events/{event_id}/teams", status_code=201)
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
    return {"id": team.id, "event_id": team.event_id, "name": team.name}


@app.get("/api/events/{event_id}/teams")
async def list_teams(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_event(session, event_id)
    result = await session.execute(
        select(Team).where(Team.event_id == event_id).order_by(Team.name)
    )
    return [
        {"id": team.id, "event_id": team.event_id, "name": team.name}
        for team in result.scalars().all()
    ]


@app.delete("/api/teams/{team_id}", status_code=204)
async def delete_team(
    team_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
    await session.execute(
        update(HeatLane)
        .where(HeatLane.team_id == team_id)
        .values(team_id=None)
    )
    await session.delete(team)
    await session.commit()


# --------------------------------------------------------------------------- #
# Provas (heats)
# --------------------------------------------------------------------------- #
@app.post("/api/events/{event_id}/heats", status_code=201)
async def create_heat(
    event_id: str,
    payload: HeatCreate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    if payload.heat_type == "bateria" and payload.distance_m is None:
        raise HTTPException(status_code=400, detail="distance_m_obrigatorio")
    if payload.heat_type == "maratona" and payload.duration_s is None:
        raise HTTPException(status_code=400, detail="duration_s_obrigatorio")

    async with _heat_guard(f"event:{event_id}"):
        session.expire_all()
        await _get_event(session, event_id)
        if payload.order_num is not None:
            order_num = payload.order_num
            result = await session.execute(
                select(Heat.id).where(
                    Heat.event_id == event_id, Heat.order_num == order_num
                )
            )
            if result.first() is not None:
                raise HTTPException(
                    status_code=400, detail="order_num_duplicado"
                )
        else:
            result = await session.execute(
                select(func.max(Heat.order_num)).where(Heat.event_id == event_id)
            )
            current = result.scalar_one()
            order_num = (current or 0) + 1

        heat = Heat(
            event_id=event_id,
            name=payload.name,
            order_num=order_num,
            heat_type=payload.heat_type,
            distance_m=payload.distance_m,
            duration_s=payload.duration_s,
            status="scheduled",
        )
        session.add(heat)
        await session.commit()
        await session.refresh(heat)

    await _broadcast_server_status()
    return await _heat_payload(session, heat)


@app.get("/api/events/{event_id}/heats")
async def list_heats(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_event(session, event_id)
    result = await session.execute(
        select(Heat).where(Heat.event_id == event_id).order_by(Heat.order_num)
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
    if heat.status not in ("scheduled", "ready_check"):
        raise HTTPException(status_code=409, detail="prova_ja_iniciada")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(heat, field, value)
    await session.commit()
    await session.refresh(heat)
    await _broadcast_heat(session, heat)
    return await _heat_payload(session, heat)


@app.delete("/api/heats/{heat_id}", status_code=204)
async def delete_heat(
    heat_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    heat = await _get_heat(session, heat_id)
    if heat.status != "scheduled":
        raise HTTPException(status_code=409, detail="prova_nao_esta_scheduled")
    lane_ids = select(HeatLane.id).where(HeatLane.heat_id == heat_id)
    await session.execute(delete(LapEvent).where(LapEvent.lane_id.in_(lane_ids)))
    await session.execute(delete(HeatLane).where(HeatLane.heat_id == heat_id))
    await session.delete(heat)
    await session.commit()
    await _broadcast_server_status()


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
        await session.commit()
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        await _broadcast_server_status()
        return await _heat_payload(session, heat)


@app.post("/api/heats/{heat_id}/finish")
@app.post("/api/heats/{heat_id}/finish-marathon")
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
            if item.team_id is not None:
                team = await session.get(Team, item.team_id)
                if team is None or team.event_id != heat.event_id:
                    raise HTTPException(
                        status_code=404, detail="equipe_nao_encontrada"
                    )
            lane = existing.get(item.lane_number)
            if lane is None:
                lane = HeatLane(
                    heat_id=heat.id,
                    lane_number=item.lane_number,
                    participant_name=item.participant_name,
                    team_id=item.team_id,
                    status="assigned",
                )
                session.add(lane)
            else:
                lane.participant_name = item.participant_name
                lane.team_id = item.team_id
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
        event = await session.get(Event, heat.event_id)
        team = await session.get(Team, lane.team_id) if lane.team_id else None
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        return _lane_dict(
            lane,
            heat=heat,
            pool_length_m=event.pool_length_m if event else 0,
            team_name=team.name if team else None,
        )


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
        event = await session.get(Event, heat.event_id)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        return _lane_dict(
            lane,
            heat=heat,
            pool_length_m=event.pool_length_m if event else 0,
            team_name=None,
        )


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
        event = await session.get(Event, heat.event_id)
        await _broadcast_heat(session, heat)
        if all_finished:
            await _broadcast_server_status()
        return _lane_dict(
            lane,
            heat=heat,
            pool_length_m=event.pool_length_m,
            team_name=None,
        )


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
            for heat in result.scalars().all():
                await manager.send_to(
                    websocket,
                    _heat_state_message(await _heat_payload(session, heat)),
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
_frontend_dir = settings.frontend_dir
if _frontend_dir.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_frontend_dir), html=True),
        name="frontend",
    )
