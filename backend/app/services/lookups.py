from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Event, Heat, HeatLane, Prova


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


def _validate_reorder_ids(ids: list[str], known: set[str]) -> None:
    """Exige o conjunto completo de IDs, sem duplicatas ou itens externos."""
    if len(ids) != len(set(ids)) or set(ids) != known:
        raise HTTPException(status_code=400, detail="ordem_ids_invalidos")
