import asyncio
import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.locks import _theme_guard
from ..database import get_db
from ..models import (
    Athlete,
    Event,
    Heat,
    HeatLane,
    LapEvent,
    Prova,
    ResultSnapshot,
    Team,
)
from ..schemas import (
    EventCreate,
    EventTheme,
    EventUpdate,
    PresentationConfig,
)
from ..services import presentation, snapshots, themes
from ..services.backup import backup_service
from ..services.broadcast import (
    _broadcast_presentation,
    _broadcast_server_status,
    _broadcast_settings,
    _broadcast_theme,
)
from ..services.lookups import _get_event
from ..services.logos import _remove_logo_file, _sniff_image
from ..services.payloads import _event_payload, _results_tree_payload

router = APIRouter()


def _theme_from_event(event: Event) -> dict:
    return themes.normalize_theme(event.theme_json)


def _store_theme(event: Event, theme: dict) -> None:
    event.theme_json = themes.serialize_theme(theme)


def _validate_contrast(theme: dict) -> None:
    report = themes.theme_contrast_report(theme)
    if report["min"] < 3:
        raise HTTPException(status_code=422, detail="contraste_insuficiente")




async def _event_duplicate_warning(
    session: AsyncSession,
    *,
    name: str,
    date: str | None,
    exclude_id: str | None = None,
) -> list[str]:
    if not date:
        return []
    query = select(Event.id).where(
        func.lower(func.trim(Event.name)) == name.strip().lower(),
        Event.date == date,
    )
    if exclude_id is not None:
        query = query.where(Event.id != exclude_id)
    result = await session.execute(query.limit(1))
    if result.first() is None:
        return []
    return ["evento_mesmo_nome_data"]


@router.get("/api/events")
async def list_events(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = (
        select(Event)
        .order_by(Event.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
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
        default_lane_count=payload.default_lane_count,
        status="draft",
        created_at=time.time(),
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    await _broadcast_server_status()
    payload = await _event_payload(session, event, include_teams=True)
    warnings = await _event_duplicate_warning(
        session, name=event.name, date=event.date
    )
    if warnings:
        payload["warnings"] = warnings
    return payload


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
    data = payload.model_dump(exclude_unset=True)
    if (
        "pool_length_m" in data
        and data["pool_length_m"] != event.pool_length_m
    ):
        started = await session.scalar(
            select(func.count())
            .select_from(Heat)
            .where(
                Heat.event_id == event_id,
                Heat.status != "scheduled",
            )
        )
        if started:
            raise HTTPException(
                status_code=409, detail="evento_ja_iniciado"
            )
    previous_status = event.status
    previous_name_mode = event.public_name_mode
    for field, value in data.items():
        setattr(event, field, value)
    await session.commit()
    await session.refresh(event)
    if previous_name_mode != event.public_name_mode:
        await _broadcast_settings(event)
    if previous_status != "finished" and event.status == "finished":
        await backup_service.backup_now(event.id, kind="final")
    payload = await _event_payload(session, event, include_teams=True)
    warnings = await _event_duplicate_warning(
        session,
        name=event.name,
        date=event.date,
        exclude_id=event.id,
    )
    if warnings:
        payload["warnings"] = warnings
    return payload


@router.get("/api/events/{event_id}/presentation")
async def get_event_presentation(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    event = await _get_event(session, event_id)
    config = presentation.normalize_presentation(event.presentation_json)
    return await presentation.hydrate_presentation(session, event, config)


@router.put("/api/events/{event_id}/presentation")
async def update_event_presentation(
    event_id: str,
    payload: PresentationConfig,
    session: AsyncSession = Depends(get_db),
) -> dict:
    event = await _get_event(session, event_id)
    config = presentation.normalize_presentation(payload.model_dump())
    error = await presentation.validate_targets(session, event.id, config)
    if error is not None:
        raise HTTPException(status_code=422, detail=error)
    event.presentation_json = presentation.serialize_presentation(config)
    await session.commit()
    await session.refresh(event)
    await _broadcast_presentation(event.id, config)
    return await presentation.hydrate_presentation(session, event, config)


@router.get("/api/events/{event_id}/results")
async def event_results_tree(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    event = await _get_event(session, event_id)
    return await _results_tree_payload(session, event)


@router.get("/api/events/{event_id}/theme")
async def get_event_theme(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    event = await _get_event(session, event_id)
    return _theme_from_event(event)


@router.put("/api/events/{event_id}/theme")
async def update_event_theme(
    event_id: str,
    payload: EventTheme,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _theme_guard(event_id):
        event = await _get_event(session, event_id)
        theme = payload.model_dump()
        _validate_contrast(theme)
        previous = _theme_from_event(event)
        reference_error = themes.validate_theme_references(
            theme,
            event.id,
            themes.referenced_theme_urls(previous),
        )
        if reference_error is not None:
            raise HTTPException(status_code=422, detail=reference_error)
        _store_theme(event, theme)
        await session.commit()
        await session.refresh(event)

        themes.remove_unreferenced_theme_files(previous, theme, event.id)
        await _broadcast_theme(event.id, theme)
        return theme


@router.post("/api/events/{event_id}/theme/image")
async def upload_theme_image(
    event_id: str,
    kind: Literal["background", "logo"] = Query(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
) -> dict:
    data = await file.read(settings.MAX_THEME_IMAGE_BYTES + 1)
    if len(data) > settings.MAX_THEME_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="arquivo_muito_grande")
    if not data:
        raise HTTPException(status_code=400, detail="arquivo_vazio")

    signature = _sniff_image(data)
    if signature is None:
        raise HTTPException(status_code=415, detail="imagem_formato_invalido")
    extension, _mime = signature

    dimensions = themes.image_dimensions(data)
    if dimensions is None:
        raise HTTPException(status_code=415, detail="imagem_formato_invalido")
    width, height = dimensions
    if width <= 0 or height <= 0:
        raise HTTPException(status_code=415, detail="imagem_formato_invalido")
    if (
        width > settings.MAX_THEME_IMAGE_PX
        or height > settings.MAX_THEME_IMAGE_PX
    ):
        raise HTTPException(status_code=413, detail="imagem_muito_grande")

    async with _theme_guard(event_id):
        event = await _get_event(session, event_id)
        settings.theme_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{event.id}-{kind}-{uuid.uuid4()}.{extension}"
        destination = settings.theme_dir / filename
        try:
            await asyncio.to_thread(destination.write_bytes, data)
        except Exception:
            await asyncio.to_thread(
                themes.remove_theme_file,
                f"/theme/{filename}",
                event.id,
            )
            raise

        field = "bg_image_url" if kind == "background" else "logo_url"
        previous = _theme_from_event(event)
        theme = dict(previous)
        theme[field] = f"/theme/{filename}"
        _store_theme(event, theme)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            await asyncio.to_thread(
                themes.remove_theme_file,
                f"/theme/{filename}",
                event.id,
            )
            raise
        await session.refresh(event)

        themes.remove_unreferenced_theme_files(previous, theme, event.id)
        await _broadcast_theme(event.id, theme)
        return theme


@router.delete("/api/events/{event_id}/theme/image")
async def delete_theme_image(
    event_id: str,
    kind: Literal["background", "logo"] = Query(...),
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _theme_guard(event_id):
        event = await _get_event(session, event_id)
        previous = _theme_from_event(event)
        theme = dict(previous)
        field = "bg_image_url" if kind == "background" else "logo_url"
        theme[field] = None
        _store_theme(event, theme)
        await session.commit()
        await session.refresh(event)

        themes.remove_unreferenced_theme_files(previous, theme, event.id)
        await _broadcast_theme(event.id, theme)
        return theme


@router.get("/api/events/{event_id}/audit/verify")
async def audit_verify(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    await _get_event(session, event_id)
    return await snapshots.verify_event(session, event_id)


@router.delete("/api/events/{event_id}", status_code=204)
async def delete_event(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    async with _theme_guard(event_id):
        event = await _get_event(session, event_id)
        theme = _theme_from_event(event)
        result = await session.execute(
            select(Team.logo_url).where(Team.event_id == event_id)
        )
        logo_urls = [url for url in result.scalars().all() if url]
        result = await session.execute(
            select(func.count())
            .select_from(ResultSnapshot)
            .where(ResultSnapshot.event_id == event_id)
        )
        if int(result.scalar_one()):
            raise HTTPException(
                status_code=409, detail="evento_possui_resultados"
            )
        started = await session.scalar(
            select(func.count())
            .select_from(Heat)
            .where(
                Heat.event_id == event_id,
                Heat.status != "scheduled",
            )
        )
        if started:
            raise HTTPException(
                status_code=409, detail="evento_com_baterias_iniciadas"
            )
        if event.status != "draft":
            raise HTTPException(status_code=409, detail="evento_nao_esta_draft")
        heat_ids = select(Heat.id).where(Heat.event_id == event_id)
        lane_ids = select(HeatLane.id).where(HeatLane.heat_id.in_(heat_ids))
        await session.execute(
            delete(LapEvent).where(LapEvent.lane_id.in_(lane_ids))
        )
        await session.execute(
            delete(HeatLane).where(HeatLane.heat_id.in_(heat_ids))
        )
        await session.execute(
            delete(Athlete).where(Athlete.event_id == event_id)
        )
        await session.execute(delete(Heat).where(Heat.event_id == event_id))
        await session.execute(delete(Prova).where(Prova.event_id == event_id))
        await session.execute(delete(Team).where(Team.event_id == event_id))
        await session.delete(event)
        await session.commit()
        themes.remove_theme_files(theme, event_id)
        for logo_url in logo_urls:
            _remove_logo_file(logo_url)
        await _broadcast_server_status()
