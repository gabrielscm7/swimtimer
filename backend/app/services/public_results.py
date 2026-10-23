"""Payloads somente leitura para o publico (TV e pagina de resultados).

Nao expoem action_log, IPs, motivos internos nem nomes completos quando o
evento esta em `public_name_mode=initials`. O mascaramento acontece no
servidor, portanto os dados completos nunca saem destes endpoints.
"""

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Event, Prova, ResultSnapshot
from ..naming import mask_names
from .payloads import _classification_payload, _prova_heats
from .snapshots import latest_by_heat, snapshot_summary


def _badge(snapshot: ResultSnapshot | None) -> str:
    if snapshot is None:
        return "provisional"
    if snapshot.status in ("official", "corrected"):
        return snapshot.status
    return "provisional"


def _prova_badge(
    heats: list, latest: dict[str, ResultSnapshot]
) -> str:
    if not heats:
        return "provisional"
    badges = [_badge(latest.get(heat.id)) for heat in heats]
    if all(badge == "official" for badge in badges):
        return "official"
    if any(badge == "corrected" for badge in badges):
        return "corrected"
    return "provisional"


def _public_snapshot(snapshot: ResultSnapshot | None) -> dict | None:
    """Resumo do snapshot sem IP nem payload interno."""
    summary = snapshot_summary(snapshot)
    if summary is None:
        return None
    return {
        "revision": summary["revision"],
        "status": summary["status"],
        "created_at": summary["created_at"],
    }


async def _prova_public_payload(
    session: AsyncSession,
    prova: Prova,
    *,
    latest: dict[str, ResultSnapshot],
) -> dict:
    classification = await _classification_payload(session, prova)
    heats = await _prova_heats(session, prova.id)
    entries_by_heat = {
        item["heat_id"]: item["entries"]
        for item in classification["battery_results"]
    }
    heat_payloads = []
    for heat in heats:
        snapshot = latest.get(heat.id)
        heat_payloads.append(
            {
                "id": heat.id,
                "name": heat.name,
                "order_num": heat.order_num,
                "heat_type": heat.heat_type,
                "distance_m": heat.distance_m,
                "duration_s": heat.duration_s,
                "status": heat.status,
                "started_at": heat.started_at,
                "finished_at": heat.finished_at,
                "badge": _badge(snapshot),
                "result_snapshot": _public_snapshot(snapshot),
                "lanes": entries_by_heat.get(heat.id, []),
            }
        )
    return {
        "id": prova.id,
        "event_id": prova.event_id,
        "name": prova.name,
        "order_num": prova.order_num,
        "stroke": prova.stroke,
        "distance_m": prova.distance_m,
        "category": prova.category,
        "naipe": prova.naipe,
        "mixed_ranking": classification["mixed_ranking"],
        "consolidate_results": classification["consolidate_results"],
        "classification_criterion": classification["classification_criterion"],
        "status": classification["status"],
        "is_provisional": classification["is_provisional"],
        "badge": _prova_badge(heats, latest),
        "standings": classification["standings"],
        "standings_by_naipe": classification["standings_by_naipe"],
        "excluded": classification["excluded"],
        "heats": heat_payloads,
    }


def _event_header(event: Event) -> dict:
    return {
        "id": event.id,
        "name": event.name,
        "location": event.location,
        "date": event.date,
        "pool_length_m": event.pool_length_m,
        "status": event.status,
        "public_name_mode": event.public_name_mode,
    }


async def event_results_payload(session: AsyncSession, event: Event) -> dict:
    result = await session.execute(
        select(Prova).where(Prova.event_id == event.id).order_by(Prova.order_num)
    )
    provas = list(result.scalars().all())
    latest = await latest_by_heat(session, event.id)
    mode = event.public_name_mode
    provas_payload = [
        await _prova_public_payload(session, prova, latest=latest)
        for prova in provas
    ]
    return mask_names(
        {
            "event": _event_header(event),
            "provas": provas_payload,
        },
        mode,
    )


async def prova_public_payload(
    session: AsyncSession, prova: Prova, event: Event
) -> dict:
    latest = await latest_by_heat(session, event.id)
    payload = await _prova_public_payload(session, prova, latest=latest)
    return mask_names(
        {"event": _event_header(event), "prova": payload},
        event.public_name_mode,
    )


def etag_for(body: bytes) -> str:
    return '"' + hashlib.sha256(body).hexdigest() + '"'
