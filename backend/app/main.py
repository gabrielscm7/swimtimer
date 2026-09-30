import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import AsyncSessionLocal, engine, get_db, init_db
from .models import Competition, LapEvent, Lane, Team
from .schemas import (
    CompetitionCreate,
    CompetitionResponse,
    FinishResponse,
    LaneAssign,
    LaneResponse,
    LapEventResponse,
    ResetRequest,
    TeamCreate,
    TeamResponse,
)
from .timer import CompetitionTimer
from .ws_manager import ConnectionManager

manager = ConnectionManager()
timer = CompetitionTimer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    if timer.is_running:
        await timer.pause()
    await engine.dispose()


app = FastAPI(title="SwimTimer", version="1.0.0", lifespan=lifespan)

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
async def _current_competition(session: AsyncSession) -> Competition | None:
    result = await session.execute(
        select(Competition)
        .where(Competition.status == "active")
        .order_by(Competition.created_at.desc())
    )
    competition = result.scalars().first()
    if competition is not None:
        return competition
    result = await session.execute(
        select(Competition).order_by(Competition.created_at.desc())
    )
    return result.scalars().first()


def _compute_speed(distance_m: int | None, race_time_ms: int | None) -> float | None:
    if not distance_m or not race_time_ms or race_time_ms <= 0:
        return None
    return round(distance_m * 1000 / race_time_ms, 2)


def _format_race_time(race_time_ms: int) -> str:
    ms = max(0, int(race_time_ms))
    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    centis = (ms % 1000) // 10
    return f"{minutes:02d}:{seconds:02d}.{centis:02d}"


async def _build_state(session: AsyncSession) -> dict:
    competition = await _current_competition(session)
    if competition is None:
        return {
            "type": "state",
            "competition": None,
            "lanes": [],
            "timer": timer.get_state(),
        }

    result = await session.execute(
        select(Lane)
        .where(Lane.competition_id == competition.id)
        .order_by(Lane.number)
    )
    lanes = result.scalars().all()

    las_result = await session.execute(
        select(LapEvent.lane_id, func.max(LapEvent.recorded_at))
        .join(Lane, Lane.id == LapEvent.lane_id)
        .where(
            Lane.competition_id == competition.id,
            LapEvent.is_undo.is_(False),
        )
        .group_by(LapEvent.lane_id)
    )
    last_lap_map = {lane_id: recorded for lane_id, recorded in las_result.all()}

    teams_result = await session.execute(
        select(Team).where(Team.competition_id == competition.id).order_by(Team.name)
    )
    teams = teams_result.scalars().all()
    team_map = {team.id: team.name for team in teams}

    lane_list = []
    for lane in lanes:
        speed_ms = _compute_speed(competition.distance_m, lane.race_time_ms)
        lane_list.append(
            {
                "id": lane.id,
                "number": lane.number,
                "team_id": lane.team_id,
                "team": team_map.get(lane.team_id) if lane.team_id else None,
                "laps": lane.laps,
                "meters": lane.laps * competition.meters_lap,
                "status": lane.status,
                "last_lap_at": last_lap_map.get(lane.id),
                "participant_name": lane.participant_name,
                "finish_at": lane.finish_at,
                "race_time_ms": lane.race_time_ms,
                "speed_ms": speed_ms,
            }
        )

    return {
        "type": "state",
        "competition": {
            "id": competition.id,
            "name": competition.name,
            "status": competition.status,
            "started_at": competition.started_at,
            "finished_at": competition.finished_at,
            "duration_s": competition.duration_s,
            "meters_lap": competition.meters_lap,
            "event_type": competition.event_type,
            "distance_m": competition.distance_m,
        },
        "lanes": lane_list,
        "teams": [{"id": team.id, "name": team.name} for team in teams],
        "timer": timer.get_state(),
    }


async def _broadcast_state(session: AsyncSession) -> None:
    await manager.broadcast(await _build_state(session))


async def _broadcast_lap(session: AsyncSession, lane: Lane) -> None:
    competition = await session.get(Competition, lane.competition_id)
    team_name = None
    if lane.team_id:
        team = await session.get(Team, lane.team_id)
        team_name = team.name if team else None
    meters = lane.laps * competition.meters_lap if competition else lane.laps
    await manager.broadcast(
        {
            "type": "lap",
            "lane_id": lane.id,
            "lane_number": lane.number,
            "team": team_name,
            "laps": lane.laps,
            "meters": meters,
        }
    )


async def _register_lap(
    session: AsyncSession, lane_id: str
) -> tuple[LapEvent | None, str | None]:
    lane = await session.get(Lane, lane_id)
    if lane is None:
        return None, "lane_nao_encontrada"
    lane.laps += 1
    if lane.status == "waiting":
        lane.status = "active"
    event = LapEvent(
        lane_id=lane.id,
        lap_number=lane.laps,
        recorded_at=time.time(),
        is_undo=False,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    await session.refresh(lane)
    return event, None


async def _undo_last_lap(
    session: AsyncSession, lane_id: str, window_s: float = 30.0
) -> tuple[LapEvent | None, str | None]:
    lane = await session.get(Lane, lane_id)
    if lane is None:
        return None, "lane_nao_encontrada"
    result = await session.execute(
        select(LapEvent)
        .where(LapEvent.lane_id == lane_id, LapEvent.is_undo.is_(False))
        .order_by(LapEvent.recorded_at.desc())
        .limit(1)
    )
    event = result.scalars().first()
    if event is None:
        return None, "nenhum_lap"
    if time.time() - event.recorded_at >= window_s:
        return None, "fora_do_prazo"
    event.is_undo = True
    if lane.laps > 0:
        lane.laps -= 1
    await session.commit()
    await session.refresh(lane)
    return event, None


async def _register_finish(
    session: AsyncSession, lane_id: str
) -> tuple[FinishResponse | None, str | None]:
    lane = await session.get(Lane, lane_id)
    if lane is None:
        return None, "lane_nao_encontrada"
    competition = await session.get(Competition, lane.competition_id)
    if competition is None:
        return None, "competicao_nao_encontrada"
    if competition.event_type != "bateria":
        return None, "nao_e_bateria"
    if lane.finish_at is not None:
        return None, "ja_finalizou"
    if competition.status != "active":
        return None, "competicao_nao_ativa"
    if competition.started_at is None:
        return None, "competicao_nao_iniciada"

    finish_at = time.time()
    race_time_ms = int((finish_at - competition.started_at) * 1000)
    lane.finish_at = finish_at
    lane.race_time_ms = race_time_ms
    lane.status = "finished"

    result = await session.execute(
        select(Lane).where(
            Lane.competition_id == competition.id,
            Lane.participant_name.isnot(None),
        )
    )
    participants = result.scalars().all()
    all_finished = bool(participants) and all(
        participant.finish_at is not None for participant in participants
    )
    if all_finished:
        competition.status = "finished"
        competition.finished_at = time.time()

    await session.commit()
    await session.refresh(lane)

    if all_finished:
        await timer.pause()

    team_name = None
    if lane.team_id:
        team = await session.get(Team, lane.team_id)
        team_name = team.name if team else None

    response = FinishResponse(
        lane_id=lane.id,
        lane_number=lane.number,
        participant_name=lane.participant_name,
        team_name=team_name,
        race_time_ms=race_time_ms,
        race_time_display=_format_race_time(race_time_ms),
        speed_ms=_compute_speed(competition.distance_m, race_time_ms) or 0.0,
    )
    return response, None


async def _reset_competition(session: AsyncSession, competition: Competition) -> None:
    lane_ids = select(Lane.id).where(Lane.competition_id == competition.id)
    await session.execute(delete(LapEvent).where(LapEvent.lane_id.in_(lane_ids)))
    await session.execute(
        update(Lane)
        .where(Lane.competition_id == competition.id)
        .values(
            laps=0,
            status="waiting",
            finish_at=None,
            race_time_ms=None,
        )
    )
    competition.status = "draft"
    competition.started_at = None
    competition.finished_at = None
    await session.commit()
    await timer.reset()


# --------------------------------------------------------------------------- #
# REST API
# --------------------------------------------------------------------------- #
@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/competition/current")
async def get_current_competition(
    session: AsyncSession = Depends(get_db),
) -> dict:
    return await _build_state(session)


@app.post(
    "/api/competition",
    response_model=CompetitionResponse,
    status_code=201,
)
async def create_competition(
    payload: CompetitionCreate,
    session: AsyncSession = Depends(get_db),
) -> Competition:
    competition = Competition(
        name=payload.name,
        status="draft",
        duration_s=payload.duration_s,
        meters_lap=payload.meters_lap,
        event_type=payload.event_type,
        distance_m=payload.distance_m,
        created_at=time.time(),
    )
    session.add(competition)
    await session.flush()
    for number in range(1, 9):
        session.add(
            Lane(
                competition_id=competition.id,
                number=number,
                laps=0,
                status="waiting",
            )
        )
    await session.commit()
    await session.refresh(competition)
    await _broadcast_state(session)
    return competition


@app.post("/api/competition/{competition_id}/start")
async def start_competition(
    competition_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    competition = await session.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(status_code=404, detail="competicao_nao_encontrada")
    if competition.started_at is None:
        competition.started_at = time.time()
    competition.status = "active"
    await session.execute(
        update(Lane)
        .where(Lane.competition_id == competition.id)
        .values(status="active")
    )
    await session.commit()
    await session.refresh(competition)
    await timer.start(competition.id, competition.duration_s, manager)
    await _broadcast_state(session)
    return {
        "status": "started",
        "competition_id": competition.id,
        "timer": timer.get_state(),
    }


@app.post("/api/competition/{competition_id}/reset")
async def reset_competition(
    competition_id: str,
    payload: ResetRequest,
    session: AsyncSession = Depends(get_db),
) -> dict:
    if payload.password != settings.RESET_PASSWORD:
        raise HTTPException(status_code=403, detail="senha_invalida")
    competition = await session.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(status_code=404, detail="competicao_nao_encontrada")
    await _reset_competition(session, competition)
    await _broadcast_state(session)
    return {"status": "reset", "competition_id": competition.id}


@app.post("/api/team", response_model=TeamResponse, status_code=201)
async def create_team(
    payload: TeamCreate,
    session: AsyncSession = Depends(get_db),
) -> Team:
    competition = await session.get(Competition, payload.competition_id)
    if competition is None:
        raise HTTPException(status_code=404, detail="competicao_nao_encontrada")
    team = Team(competition_id=payload.competition_id, name=payload.name)
    session.add(team)
    await session.commit()
    await session.refresh(team)
    await _broadcast_state(session)
    return team


@app.post("/api/lane/{lane_id}/assign", response_model=LaneResponse)
async def assign_lane(
    lane_id: str,
    payload: LaneAssign,
    session: AsyncSession = Depends(get_db),
) -> LaneResponse:
    lane = await session.get(Lane, lane_id)
    if lane is None:
        raise HTTPException(status_code=404, detail="raia_nao_encontrada")
    team_name = None
    if payload.team_id is not None:
        team = await session.get(Team, payload.team_id)
        if team is None:
            raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
        team_name = team.name
    lane.team_id = payload.team_id
    lane.participant_name = payload.participant_name
    await session.commit()
    await session.refresh(lane)
    competition = await session.get(Competition, lane.competition_id)
    meters = lane.laps * competition.meters_lap if competition else 0
    await _broadcast_state(session)
    return LaneResponse(
        id=lane.id,
        competition_id=lane.competition_id,
        number=lane.number,
        team_id=lane.team_id,
        team=team_name,
        laps=lane.laps,
        meters=meters,
        status=lane.status,
        participant_name=lane.participant_name,
        finish_at=lane.finish_at,
        race_time_ms=lane.race_time_ms,
        speed_ms=_compute_speed(
            competition.distance_m if competition else None, lane.race_time_ms
        ),
    )


@app.post("/api/lane/{lane_id}/lap", response_model=LapEventResponse)
async def register_lap_endpoint(
    lane_id: str,
    session: AsyncSession = Depends(get_db),
) -> LapEvent:
    event, error = await _register_lap(session, lane_id)
    if error is not None:
        raise HTTPException(status_code=404, detail=error)
    lane = await session.get(Lane, lane_id)
    await _broadcast_lap(session, lane)
    await _broadcast_state(session)
    return event


@app.post("/api/lane/{lane_id}/finish", response_model=FinishResponse)
async def finish_lane_endpoint(
    lane_id: str,
    session: AsyncSession = Depends(get_db),
) -> FinishResponse:
    response, error = await _register_finish(session, lane_id)
    if error is not None:
        if error in ("lane_nao_encontrada", "competicao_nao_encontrada"):
            status_code = 404
        elif error == "ja_finalizou":
            status_code = 409
        else:
            status_code = 400
        raise HTTPException(status_code=status_code, detail=error)
    await _broadcast_state(session)
    return response


@app.delete("/api/lane/{lane_id}/lap/last")
async def undo_last_lap_endpoint(
    lane_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    event, error = await _undo_last_lap(session, lane_id)
    if error == "lane_nao_encontrada":
        raise HTTPException(status_code=404, detail=error)
    if error == "nenhum_lap":
        raise HTTPException(status_code=404, detail=error)
    if error == "fora_do_prazo":
        raise HTTPException(status_code=400, detail=error)
    lane = await session.get(Lane, lane_id)
    await _broadcast_state(session)
    return {"status": "undone", "lane_id": lane.id, "laps": lane.laps}


# --------------------------------------------------------------------------- #
# WebSocket
# --------------------------------------------------------------------------- #
async def _dispatch(data: dict, session: AsyncSession, websocket: WebSocket) -> None:
    message_type = data.get("type")

    if message_type == "lap":
        lane_id = data.get("lane_id")
        if not lane_id:
            await manager.send_to(websocket, {"type": "error", "message": "lane_id_ausente"})
            return
        _event, error = await _register_lap(session, lane_id)
        if error is not None:
            await manager.send_to(websocket, {"type": "error", "message": error})
            return
        lane = await session.get(Lane, lane_id)
        await _broadcast_lap(session, lane)
        await _broadcast_state(session)

    elif message_type == "finish":
        lane_id = data.get("lane_id")
        if not lane_id:
            await manager.send_to(websocket, {"type": "error", "message": "lane_id_ausente"})
            return
        _response, error = await _register_finish(session, lane_id)
        if error is not None:
            await manager.send_to(websocket, {"type": "error", "message": error})
            return
        await _broadcast_state(session)

    elif message_type == "undo":
        lane_id = data.get("lane_id")
        if not lane_id:
            await manager.send_to(websocket, {"type": "error", "message": "lane_id_ausente"})
            return
        _event, error = await _undo_last_lap(session, lane_id)
        if error is not None:
            await manager.send_to(websocket, {"type": "error", "message": error})
            return
        await _broadcast_state(session)

    elif message_type == "timer_start":
        competition = await _current_competition(session)
        if competition is None:
            await manager.send_to(websocket, {"type": "error", "message": "sem_competicao"})
            return
        if competition.started_at is None:
            competition.started_at = time.time()
        competition.status = "active"
        await session.execute(
            update(Lane)
            .where(Lane.competition_id == competition.id)
            .values(status="active")
        )
        await session.commit()
        await timer.start(competition.id, competition.duration_s, manager)
        await _broadcast_state(session)

    elif message_type == "timer_pause":
        await timer.pause()
        await _broadcast_state(session)

    elif message_type == "timer_reset":
        competition = await _current_competition(session)
        if competition is None:
            await manager.send_to(websocket, {"type": "error", "message": "sem_competicao"})
            return
        if data.get("password") != settings.RESET_PASSWORD:
            await manager.send_to(websocket, {"type": "error", "message": "senha_invalida"})
            return
        await _reset_competition(session, competition)
        await _broadcast_state(session)

    else:
        await manager.send_to(
            websocket,
            {"type": "error", "message": "tipo_desconhecido"},
        )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        async with AsyncSessionLocal() as session:
            await manager.send_to(websocket, await _build_state(session))
        while True:
            data = await websocket.receive_json()
            async with AsyncSessionLocal() as session:
                await _dispatch(data, session, websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


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
