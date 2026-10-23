import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import LaneActionError
from ..core.locks import _heat_guard
from ..database import get_db
from ..models import Athlete, LapEvent, Team
from ..schemas import LaneActionRequest, LaneUpdate
from ..services.broadcast import (
    _broadcast_heat,
    _broadcast_ready,
    _broadcast_server_status,
)
from ..services.lane_actions import (
    _client_ip,
    _do_finish,
    _do_lap,
    _log_action,
    _maybe_finish_heat,
)
from ..services.lookups import _get_heat, _get_lane
from ..services.payloads import _lane_payload

router = APIRouter()


@router.patch("/api/lanes/{lane_id}")
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


@router.post("/api/lanes/{lane_id}/ready")
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


@router.post("/api/lanes/{lane_id}/finish")
async def lane_finish(
    lane_id: str,
    request: Request,
    payload: LaneActionRequest | None = None,
    session: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await _do_finish(
            session,
            lane_id,
            op_id=payload.op_id if payload else None,
            client_ts=payload.client_ts if payload else None,
            source_ip=_client_ip(request),
        )
    except LaneActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/api/lanes/{lane_id}/lap")
async def lane_lap(
    lane_id: str,
    request: Request,
    payload: LaneActionRequest | None = None,
    session: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await _do_lap(
            session,
            lane_id,
            op_id=payload.op_id if payload else None,
            client_ts=payload.client_ts if payload else None,
            source_ip=_client_ip(request),
        )
    except LaneActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/api/lanes/{lane_id}/dq")
async def lane_dq(
    lane_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    lane = await _get_lane(session, lane_id)
    async with _heat_guard(lane.heat_id):
        session.expire_all()
        lane = await _get_lane(session, lane_id)
        heat = await _get_heat(session, lane.heat_id)
        if heat.status != "active":
            raise HTTPException(status_code=400, detail="prova_nao_ativa")
        now = time.time()
        lane.status = "dq"
        all_finished = await _maybe_finish_heat(session, heat)
        _log_action(
            session,
            action="dq",
            received_at=now,
            effective_ts=now,
            event_id=heat.event_id,
            heat_id=heat.id,
            lane_id=lane.id,
            source_ip=_client_ip(request),
        )
        await session.commit()
        await session.refresh(lane)
        await _broadcast_heat(session, heat)
        if all_finished:
            await _broadcast_server_status()
        return await _lane_payload(session, lane, heat)


@router.delete("/api/lanes/{lane_id}/lap/last")
async def undo_last_lap(
    lane_id: str,
    request: Request,
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
        now = time.time()
        if now - event.recorded_at >= 30.0:
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
        _log_action(
            session,
            action="undo_lap",
            received_at=now,
            effective_ts=now,
            event_id=heat.event_id,
            heat_id=heat.id,
            lane_id=lane.id,
            source_ip=_client_ip(request),
            payload={
                "lap_event_id": event.id,
                "lap_number": event.lap_number,
                "recorded_at": event.recorded_at,
            },
        )
        await session.commit()
        await _broadcast_heat(session, heat)
        return {"status": "undone", "lane_id": lane.id}
