import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.locks import _heat_guard
from ..database import get_db
from ..models import Heat, HeatLane, LapEvent, Prova
from ..schemas import OrderIdsRequest, ProvaCreate, ProvaUpdate
from ..services.broadcast import (
    _broadcast_server_status,
    _prova_state_message,
    manager,
)
from ..services.lookups import _get_event, _get_prova, _validate_reorder_ids
from ..services.payloads import (
    _classification_payload,
    _prova_heats,
    _prova_payload,
    _prova_summary_payload,
    _provas_payload,
    _sync_prova_status,
)

router = APIRouter()


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
        mixed_ranking=payload.mixed_ranking,
        consolidate_results=payload.consolidate_results,
        classification_criterion=payload.classification_criterion,
        status="scheduled",
        created_at=time.time(),
    )
    session.add(prova)
    return prova


@router.post("/api/events/{event_id}/provas", status_code=201)
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


@router.get("/api/events/{event_id}/provas")
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


@router.get("/api/provas/{prova_id}")
async def get_prova(
    prova_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    prova = await _get_prova(session, prova_id)
    return await _prova_payload(session, prova)


@router.patch("/api/provas/{prova_id}")
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


@router.put("/api/events/{event_id}/provas/order")
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


@router.delete("/api/provas/{prova_id}", status_code=204)
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


@router.get("/api/provas/{prova_id}/classification")
async def get_prova_classification(
    prova_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    prova = await _get_prova(session, prova_id)
    return await _classification_payload(session, prova)


@router.get("/api/provas/{prova_id}/summary")
async def get_prova_summary(
    prova_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    prova = await _get_prova(session, prova_id)
    return await _prova_summary_payload(session, prova)
