import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Athlete, Event, Heat, HeatLane, LapEvent, Prova, Team
from ..schemas import EventCreate, EventUpdate
from ..services.broadcast import _broadcast_server_status
from ..services.lookups import _get_event
from ..services.payloads import _event_payload

router = APIRouter()


@router.get("/api/events")
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


@router.post("/api/events", status_code=201)
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


@router.get("/api/events/{event_id}")
async def get_event(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    event = await _get_event(session, event_id)
    return await _event_payload(session, event, include_teams=True)


@router.patch("/api/events/{event_id}")
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


@router.delete("/api/events/{event_id}", status_code=204)
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
