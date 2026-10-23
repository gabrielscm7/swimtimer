"""Leituras derivadas de provas (grupos automáticos) — ADR-012.

O cadastro e a reordenação de prova não existem mais: a prova é criada,
renumerada e removida pelo serviço de baterias. Este router expõe apenas
consultas.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Prova
from ..services.lookups import _get_event, _get_prova
from ..services.payloads import (
    _classification_payload,
    _heat_payload,
    _prova_heats,
    _prova_payload,
    _prova_summary_payload,
    _provas_payload,
)

router = APIRouter()


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


@router.get("/api/provas/{prova_id}/heats")
async def list_heats_in_prova(
    prova_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_prova(session, prova_id)
    heats = await _prova_heats(session, prova_id)
    return [await _heat_payload(session, heat) for heat in heats]


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
