import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.locks import _heat_guard
from ..database import get_db
from ..models import Athlete, Heat, HeatLane, LapEvent, Prova, Team
from ..schemas import (
    HeatCreate,
    HeatLaneConfigRequest,
    HeatUpdate,
    OrderIdsRequest,
)
from ..services.broadcast import (
    _broadcast_heat,
    _broadcast_ready,
    _broadcast_server_status,
    _prova_state_message,
    manager,
)
from ..services.lane_actions import (
    _anchor_heat,
    _client_ip,
    _drop_anchor,
    _log_action,
)
from ..services.lookups import (
    _get_event,
    _get_heat,
    _get_prova,
    _validate_reorder_ids,
)
from ..services.payloads import (
    _heat_lanes,
    _heat_payload,
    _participant_lanes,
    _prova_heats,
    _prova_payload,
    _sync_prova_status,
)

router = APIRouter()


@router.post("/api/provas/{prova_id}/heats", status_code=201)
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


@router.get("/api/provas/{prova_id}/heats")
async def list_heats_in_prova(
    prova_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_prova(session, prova_id)
    heats = await _prova_heats(session, prova_id)
    return [await _heat_payload(session, heat) for heat in heats]


@router.get("/api/events/{event_id}/heats")
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


@router.patch("/api/heats/{heat_id}")
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


@router.put("/api/provas/{prova_id}/heats/order")
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


@router.delete("/api/heats/{heat_id}", status_code=204)
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


@router.post("/api/heats/{heat_id}/open-ready-check")
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


@router.post("/api/heats/{heat_id}/start")
async def start_heat(
    heat_id: str,
    request: Request,
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

        started_at = time.time()
        heat.status = "active"
        heat.started_at = started_at
        heat.finished_at = None
        for lane in participants:
            lane.status = "active"
        _anchor_heat(heat)
        _log_action(
            session,
            action="start",
            received_at=started_at,
            effective_ts=started_at,
            event_id=heat.event_id,
            heat_id=heat.id,
            source_ip=_client_ip(request),
        )
        await _sync_prova_status(session, heat.prova_id)
        await session.commit()
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        await _broadcast_server_status()
        return await _heat_payload(session, heat)


@router.post("/api/heats/{heat_id}/abort")
async def abort_heat(
    heat_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status not in ("ready_check", "active"):
            raise HTTPException(status_code=409, detail="prova_nao_esta_ativa")
        now = time.time()
        heat.status = "scheduled"
        heat.started_at = None
        heat.finished_at = None
        _drop_anchor(heat.id)
        result = await session.execute(
            update(HeatLane)
            .where(HeatLane.heat_id == heat.id, HeatLane.status == "active")
            .values(status="ready")
        )
        _log_action(
            session,
            action="abort",
            received_at=now,
            effective_ts=now,
            event_id=heat.event_id,
            heat_id=heat.id,
            source_ip=_client_ip(request),
        )
        await _sync_prova_status(session, heat.prova_id)
        await session.commit()
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        await _broadcast_server_status()
        return await _heat_payload(session, heat)


@router.post("/api/heats/{heat_id}/finish")
async def finish_heat(
    heat_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status == "finished":
            return await _heat_payload(session, heat)
        if heat.status == "scheduled":
            raise HTTPException(status_code=409, detail="prova_nao_iniciada")
        now = time.time()
        heat.status = "finished"
        heat.finished_at = now
        _drop_anchor(heat.id)
        _log_action(
            session,
            action="finish_heat",
            received_at=now,
            effective_ts=now,
            event_id=heat.event_id,
            heat_id=heat.id,
            source_ip=_client_ip(request),
        )
        await _sync_prova_status(session, heat.prova_id)
        await session.commit()
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        await _broadcast_server_status()
        return await _heat_payload(session, heat)


@router.post("/api/heats/{heat_id}/lanes")
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
