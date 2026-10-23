"""Ordenacao livre de baterias por evento (ADR-012)."""

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Heat
from .lookups import _validate_reorder_ids

ORDER_OFFSET = 100000


async def load_event_heats(
    session: AsyncSession, event_id: str
) -> list[Heat]:
    result = await session.execute(
        select(Heat)
        .where(Heat.event_id == event_id)
        .order_by(Heat.order_num)
    )
    return list(result.scalars().all())


def resolve_target_order(
    heats: list[Heat], request
) -> list[str]:
    """Converte o contrato (lista completa ou mover para posicao N)."""
    current = [heat.id for heat in heats]
    if request.ids is not None:
        _validate_reorder_ids(request.ids, set(current))
        return list(request.ids)

    if request.heat_id not in current:
        raise HTTPException(status_code=404, detail="bateria_nao_encontrada")
    position = min(int(request.position), len(current))
    ordered = [heat_id for heat_id in current if heat_id != request.heat_id]
    ordered.insert(max(position - 1, 0), request.heat_id)
    return ordered


def assert_anchored(heats: list[Heat], ordered_ids: list[str]) -> None:
    """Baterias fora de `scheduled` nao podem mudar de posicao."""
    for index, heat in enumerate(heats):
        if heat.status != "scheduled" and ordered_ids[index] != heat.id:
            raise HTTPException(status_code=409, detail="bateria_ancorada")


async def apply_order(
    session: AsyncSession, event_id: str, ordered_ids: list[str]
) -> None:
    await session.execute(
        update(Heat)
        .where(Heat.event_id == event_id)
        .values(order_num=Heat.order_num + ORDER_OFFSET),
        execution_options={"synchronize_session": False},
    )
    await session.flush()
    for index, heat_id in enumerate(ordered_ids, start=1):
        # populate_existing recarrega o valor deslocado pelo UPDATE em massa;
        # sem isso a atribuicao poderia ser um no-op sobre o valor em cache.
        heat = await session.get(Heat, heat_id, populate_existing=True)
        if heat is not None:
            heat.order_num = index
    await session.flush()


async def reorder_event_heats(
    session: AsyncSession, event_id: str, request
) -> list[Heat]:
    heats = await load_event_heats(session, event_id)
    ordered_ids = resolve_target_order(heats, request)
    assert_anchored(heats, ordered_ids)
    await apply_order(session, event_id, ordered_ids)
    return await load_event_heats(session, event_id)


async def place_new_heat(
    session: AsyncSession, event_id: str, heat: Heat, position: int | None
) -> None:
    """Insere uma bateria recem-criada na posicao pedida (opcional)."""
    heats = await load_event_heats(session, event_id)
    desired = [item.id for item in heats]
    if position is None or position >= len(desired):
        return
    desired.remove(heat.id)
    desired.insert(max(position - 1, 0), heat.id)
    assert_anchored(heats, desired)
    await apply_order(session, event_id, desired)


async def renumber_heats(session: AsyncSession, event_id: str) -> None:
    """Mantem `order_num` contiguo (1..N) apos exclusoes."""
    heats = await load_event_heats(session, event_id)
    ordered_ids = [heat.id for heat in heats]
    if all(
        heat.order_num == index
        for index, heat in enumerate(heats, start=1)
    ):
        return
    await apply_order(session, event_id, ordered_ids)


async def next_heat_order(session: AsyncSession, event_id: str) -> int:
    from sqlalchemy import func

    result = await session.execute(
        select(func.max(Heat.order_num)).where(Heat.event_id == event_id)
    )
    return int(result.scalar_one() or 0) + 1
