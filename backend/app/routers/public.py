import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Event, Prova
from ..services import public_results

router = APIRouter()


def _cached(request: Request, payload: dict) -> Response:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    etag = public_results.etag_for(body)
    headers = {"Cache-Control": "max-age=2", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


def _ensure_enabled(event: Event) -> None:
    if not event.public_results_enabled:
        raise HTTPException(
            status_code=404, detail="resultados_publicos_desativados"
        )


@router.get("/api/public/events/{event_id}/results")
async def public_event_results(
    event_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> Response:
    event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="evento_nao_encontrado")
    _ensure_enabled(event)
    return _cached(
        request, await public_results.event_results_payload(session, event)
    )


@router.get("/api/public/provas/{prova_id}")
async def public_prova_results(
    prova_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> Response:
    prova = await session.get(Prova, prova_id)
    if prova is None:
        raise HTTPException(status_code=404, detail="prova_nao_encontrada")
    event = await session.get(Event, prova.event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="evento_nao_encontrado")
    _ensure_enabled(event)
    return _cached(
        request, await public_results.prova_public_payload(session, prova, event)
    )
