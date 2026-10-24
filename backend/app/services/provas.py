"""Regras de grupo (prova) derivado das baterias — ADR-012.

A prova não é cadastrada: ela é encontrada/criada a partir dos atributos da
bateria (heat_type, stroke, distance_m, naipe, category). Baterias com
`classify_alone=True` recebem uma prova exclusiva. O nome da prova é sempre
gerado e as provas são renumeradas pela posição da primeira bateria no evento.
"""

from __future__ import annotations

import time

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import domain
from ..classification import effective_mixed_ranking
from ..models import Event, Heat, Prova, ResultSnapshot


# --------------------------------------------------------------------------- #
# Rotulos (reexportados para exports/sumula/presentation)
# --------------------------------------------------------------------------- #
stroke_label = domain.stroke_label
naipe_label = domain.naipe_label
category_label = domain.category_label
generate_prova_name = domain.generate_prova_name
is_legacy_incomplete = domain.is_legacy_incomplete


def prova_descriptor(prova: Prova) -> str:
    if prova.name:
        return prova.name
    return domain.generate_prova_name(
        heat_type=prova.format,
        stroke=prova.stroke,
        distance_m=prova.distance_m,
        naipe=prova.naipe,
        category=prova.category,
    )


def prova_label(prova: Prova) -> str:
    return f"PROVA {prova.order_num} · {prova_descriptor(prova)}"


def bateria_label(
    heat, prova: Prova | None = None, *, include_prova: bool = False
) -> str:
    index = getattr(heat, "heat_index_in_prova", None) or heat.order_num
    total = getattr(heat, "heats_in_prova", None)
    label = f"BATERIA {index}" + (f" de {total}" if total else "")
    name = (heat.name or "").strip()
    normalized = name.casefold()
    redundant = (
        not name
        or normalized in {str(index), f"bateria {index}", label.casefold()}
    )
    if not redundant:
        label = f"{label} · {name}"
    if include_prova and prova is not None:
        label = f"{label} · Prova {prova.order_num}"
    return label


# --------------------------------------------------------------------------- #
# Grupo
# --------------------------------------------------------------------------- #
def heat_group_values(heat: Heat) -> dict:
    return {
        "heat_type": heat.heat_type,
        "stroke": heat.stroke,
        "distance_m": heat.distance_m if heat.heat_type == "bateria" else None,
        "naipe": heat.naipe,
        "category": heat.category,
    }


def _prova_matches(prova: Prova, heat: Heat) -> bool:
    return domain.group_key(
        heat_type=prova.format,
        stroke=prova.stroke,
        distance_m=prova.distance_m,
        naipe=prova.naipe,
        category=prova.category,
    ) == domain.group_key(**heat_group_values(heat))


async def _prova_heat_count(
    session: AsyncSession, prova_id: str, *, exclude_heat_id: str | None = None
) -> int:
    query = select(func.count()).select_from(Heat).where(
        Heat.prova_id == prova_id
    )
    if exclude_heat_id is not None:
        query = query.where(Heat.id != exclude_heat_id)
    return int(await session.scalar(query) or 0)


async def _prova_has_snapshots(session: AsyncSession, prova_id: str) -> bool:
    count = await session.scalar(
        select(func.count())
        .select_from(ResultSnapshot)
        .where(ResultSnapshot.prova_id == prova_id)
    )
    return bool(count)


async def _dedicated_prova(
    session: AsyncSession, heat: Heat
) -> Prova | None:
    """Prova exclusiva da bateria (somente ela, isolada)."""
    if not heat.prova_id:
        return None
    prova = await session.get(Prova, heat.prova_id)
    if prova is None:
        return None
    if await _prova_heat_count(
        session, prova.id, exclude_heat_id=heat.id
    ):
        return None
    return prova


async def find_group_prova(
    session: AsyncSession, event_id: str, heat: Heat
) -> Prova | None:
    """Prova compartilhada existente com a mesma chave de grupo."""
    values = heat_group_values(heat)
    query = (
        select(Prova)
        .join(Heat, Heat.prova_id == Prova.id)
        .where(
            Prova.event_id == event_id,
            Prova.format == values["heat_type"],
            func.lower(func.trim(Prova.stroke))
            == (values["stroke"] or "").strip().lower(),
            Prova.distance_m == values["distance_m"],
            func.upper(func.trim(Prova.naipe))
            == (values["naipe"] or "").strip().upper(),
            func.lower(func.trim(Prova.category))
            == (values["category"] or "").strip().lower(),
            Heat.classify_alone.is_(False),
        )
        .order_by(Prova.order_num)
        .limit(1)
    )
    result = await session.execute(query)
    return result.scalars().first()


async def _new_prova(session: AsyncSession, event: Event, heat: Heat) -> Prova:
    values = heat_group_values(heat)
    next_order = int(
        await session.scalar(
            select(func.max(Prova.order_num)).where(
                Prova.event_id == event.id
            )
        )
        or 0
    ) + 1
    prova = Prova(
        event_id=event.id,
        name=domain.generate_prova_name(
            heat_type=values["heat_type"],
            stroke=values["stroke"],
            distance_m=values["distance_m"],
            naipe=values["naipe"],
            category=values["category"],
            duration_s=heat.duration_s,
        ),
        order_num=next_order,
        format=values["heat_type"],
        stroke=values["stroke"],
        distance_m=values["distance_m"],
        naipe=values["naipe"],
        category=values["category"],
        classification_criterion="lowest_time",
        status="scheduled",
        created_at=time.time(),
    )
    session.add(prova)
    await session.flush()
    return prova


async def resolve_group(
    session: AsyncSession, event: Event, heat: Heat
) -> Prova:
    """Encontra/cria a prova correta para o estado atual da bateria."""
    if heat.classify_alone:
        current = await _dedicated_prova(session, heat)
        if current is not None:
            return current
        return await _new_prova(session, event, heat)

    existing = await find_group_prova(session, event.id, heat)
    if existing is not None:
        return existing
    return await _new_prova(session, event, heat)


async def sync_prova_from_group(
    session: AsyncSession, prova: Prova
) -> None:
    """Espelha atributos do grupo na prova e regenera o nome."""
    result = await session.execute(
        select(Heat).where(Heat.prova_id == prova.id).order_by(Heat.order_num)
    )
    heats = list(result.scalars().all())
    if not heats:
        return
    first = heats[0]
    values = heat_group_values(first)
    prova.format = values["heat_type"]
    prova.stroke = values["stroke"]
    prova.distance_m = values["distance_m"]
    prova.naipe = values["naipe"]
    prova.category = values["category"]
    duration_s = None
    if values["heat_type"] == "maratona":
        durations = {heat.duration_s for heat in heats}
        if len(durations) == 1:
            duration_s = durations.pop()
    prova.name = domain.generate_prova_name(
        heat_type=values["heat_type"],
        stroke=values["stroke"],
        distance_m=values["distance_m"],
        naipe=values["naipe"],
        category=values["category"],
        duration_s=duration_s,
    )


async def renumber_provas(session: AsyncSession, event_id: str) -> None:
    """Renumera 1..N pela menor order_num de bateria de cada prova."""
    result = await session.execute(
        select(Prova.id, func.min(Heat.order_num))
        .outerjoin(Heat, Heat.prova_id == Prova.id)
        .where(Prova.event_id == event_id)
        .group_by(Prova.id)
    )
    rows = result.all()
    ordered = sorted(
        rows, key=lambda row: (row[1] is None, row[1] or 0, row[0])
    )
    await session.execute(
        update(Prova)
        .where(Prova.event_id == event_id)
        .values(order_num=Prova.order_num + 100000),
        execution_options={"synchronize_session": False},
    )
    await session.flush()
    for index, (prova_id, _min_order) in enumerate(ordered, start=1):
        prova = await session.get(Prova, prova_id, populate_existing=True)
        if prova is not None:
            prova.order_num = index
    await session.flush()


async def remove_prova_if_empty(
    session: AsyncSession, prova_id: str | None
) -> bool:
    """Remove prova sem baterias e sem snapshots (ADR-012)."""
    if not prova_id:
        return False
    prova = await session.get(Prova, prova_id)
    if prova is None:
        return False
    if await _prova_heat_count(session, prova.id):
        return False
    if await _prova_has_snapshots(session, prova.id):
        return False
    event = await session.get(Event, prova.event_id)
    await session.delete(prova)
    await session.flush()
    if event is not None:
        from . import presentation  # import tardio evita ciclo

        event.presentation_json = presentation.serialize_presentation(
            presentation.remove_refs(
                event.presentation_json, {f"prova:{prova_id}"}
            )
        )
    return True


async def attach_heat_to_group(
    session: AsyncSession, event: Event, heat: Heat
) -> tuple[Prova, str | None]:
    """Define `heat.prova_id` e sincroniza o nome. Retorna (prova, old_id)."""
    old_prova_id = heat.prova_id
    prova = await resolve_group(session, event, heat)
    heat.prova_id = prova.id
    await session.flush()
    await sync_prova_from_group(session, prova)
    return prova, old_prova_id


async def group_heats(
    session: AsyncSession, prova_id: str
) -> list[Heat]:
    result = await session.execute(
        select(Heat)
        .where(Heat.prova_id == prova_id)
        .order_by(Heat.order_num)
    )
    return list(result.scalars().all())


def group_mixed_ranking(prova: Prova) -> str:
    """Regra unica: MISTO exibe geral + por naipe; demais apenas geral."""
    return effective_mixed_ranking(prova.naipe, "both")


async def assert_group_invariant(
    session: AsyncSession, prova_id: str
) -> None:
    heats = await group_heats(session, prova_id)
    if not heats:
        return
    first_key = domain.group_key(**heat_group_values(heats[0]))
    for heat in heats[1:]:
        if domain.group_key(**heat_group_values(heat)) != first_key:
            raise HTTPException(
                status_code=409, detail="prova_com_grupos_diferentes"
            )
