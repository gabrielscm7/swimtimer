from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database
from ..models import Heat, Prova
from ..ws_manager import ConnectionManager
from .payloads import _heat_lanes, _heat_payload, _prova_payload, _ready_payload

manager = ConnectionManager()


def _heat_state_message(heat_payload: dict) -> dict:
    return {
        "type": "heat_state",
        "scope": "heat",
        "heat_id": heat_payload["id"],
        "event_id": heat_payload.get("event_id"),
        "payload": heat_payload,
    }


def _ready_update_message(
    heat_id: str, ready_payload: dict, event_id: str | None = None
) -> dict:
    return {
        "type": "ready_update",
        "scope": "heat",
        "heat_id": heat_id,
        "event_id": event_id,
        "payload": ready_payload,
    }


def _prova_state_message(prova_payload: dict) -> dict:
    return {
        "type": "prova_state",
        "scope": "prova",
        "prova_id": prova_payload["id"],
        "event_id": prova_payload.get("event_id"),
        "payload": prova_payload,
    }


def _settings_updated_message(event_id: str, payload: dict) -> dict:
    return {
        "type": "settings_updated",
        "scope": "event",
        "event_id": event_id,
        "payload": payload,
    }


def _theme_updated_message(event_id: str, theme: dict) -> dict:
    return {
        "type": "theme_updated",
        "scope": "event",
        "event_id": event_id,
        "payload": theme,
    }


def _presentation_updated_message(event_id: str, payload: dict) -> dict:
    return {
        "type": "presentation_updated",
        "scope": "event",
        "event_id": event_id,
        "payload": payload,
    }


async def _broadcast_presentation(event_id: str, config: dict) -> None:
    await manager.broadcast(_presentation_updated_message(event_id, config))


async def _broadcast_theme(event_id: str, theme: dict) -> None:
    await manager.broadcast(_theme_updated_message(event_id, theme))


async def _broadcast_settings(event) -> None:
    manager.update_name_mode(event.id, event.public_name_mode)
    await manager.broadcast(
        _settings_updated_message(
            event.id,
            {"public_name_mode": event.public_name_mode},
        )
    )


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
    async with database.AsyncSessionLocal() as session:
        await manager.broadcast(await _server_status_message(session))


async def _broadcast_heat(session: AsyncSession, heat: Heat) -> None:
    await manager.broadcast(_heat_state_message(await _heat_payload(session, heat)))
    prova = await session.get(Prova, heat.prova_id)
    if prova is not None:
        await manager.broadcast(
            _prova_state_message(await _prova_payload(session, prova))
        )


async def _broadcast_ready(session: AsyncSession, heat: Heat) -> None:
    lanes = await _heat_lanes(session, heat.id)
    await manager.broadcast(
        _ready_update_message(
            heat.id, _ready_payload(lanes), heat.event_id
        )
    )
