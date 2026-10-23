"""Validacoes de inscricao de atletas em baterias.

Regras (ADR-009, que revoga o "aviso visual, sem bloqueio" do ADR-007):

- naipe do atleta incompativel com a prova (`422 naipe_incompativel`),
  exceto prova MISTO ou com naipe nao definido;
- categoria incompativel quando a prova define categoria
  (`422 categoria_incompativel`) — atleta sem categoria tambem bloqueia;
- atleta ja inscrito em outra bateria da MESMA prova
  (`409 atleta_duplicado_na_prova: <bateria>`);
- atleta duas vezes na mesma bateria (`409 atleta_duplicado_na_bateria`);
- atleta alocado em bateria ready_check/active de OUTRA prova
  (`409 atleta_em_outra_bateria_ativa`).

O supervisor pode autorizar uma excecao com `force=true` +
`override_reason` e o header `X-Operator-Pin`. A excecao fica registrada no
`action_log`; sem OPERATOR_PIN configurado o override e sempre negado.
"""
import time
from collections import Counter
from secrets import compare_digest

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..domain import is_free_category
from ..models import Athlete, Heat, HeatLane
from .lane_actions import _client_ip, _log_action

_OVERRIDE_CODES = {
    "naipe_incompativel": 422,
    "categoria_incompativel": 422,
    "atleta_duplicado_na_prova": 409,
    "atleta_duplicado_na_bateria": 409,
    "atleta_em_outra_bateria_ativa": 409,
    "atleta_com_resultado": 409,
}

_ACTIVE_HEAT_STATUSES = ("ready_check", "active")


def _violation(code: str, **extra: object) -> dict:
    return {"code": code, **extra}


def _violation_detail(violation: dict) -> str:
    code = violation["code"]
    if code == "atleta_duplicado_na_prova":
        return f"{code}: {violation.get('heat_name') or 'outra bateria'}"
    return code


def check_override(
    request: Request | None,
    force: bool,
    override_reason: str | None,
) -> None:
    """Valida o override exclusivo do supervisor (nunca aberto a todos)."""
    if not force:
        return
    if not override_reason or not override_reason.strip():
        raise HTTPException(
            status_code=422, detail="override_reason_obrigatorio"
        )
    pin = settings.OPERATOR_PIN
    if not pin:
        raise HTTPException(
            status_code=403, detail="override_requer_pin_do_supervisor"
        )
    provided = request.headers.get("X-Operator-Pin") if request else None
    if not provided or not compare_digest(provided, pin):
        raise HTTPException(
            status_code=403, detail="pin_do_supervisor_invalido"
        )


def raise_violations(violations: list[dict]) -> None:
    first = violations[0]
    raise HTTPException(
        status_code=_OVERRIDE_CODES[first["code"]],
        detail=_violation_detail(first),
    )


async def _athletes_by_id(
    session: AsyncSession, ids: set[str]
) -> dict[str, Athlete]:
    if not ids:
        return {}
    result = await session.execute(
        select(Athlete).where(Athlete.id.in_(ids))
    )
    return {athlete.id: athlete for athlete in result.scalars().all()}


async def _other_assignments(
    session: AsyncSession,
    athlete_ids: set[str],
    *,
    exclude_heat_id: str,
) -> list[tuple[HeatLane, Heat]]:
    if not athlete_ids:
        return []
    result = await session.execute(
        select(HeatLane, Heat)
        .join(Heat, HeatLane.heat_id == Heat.id)
        .where(HeatLane.athlete_id.in_(athlete_ids))
    )
    return [
        (lane, heat)
        for lane, heat in result.all()
        if heat.id != exclude_heat_id
    ]


def _check_naipe(athlete: Athlete, heat: Heat) -> dict | None:
    if not heat.naipe or heat.naipe.upper() == "MISTO":
        return None
    if athlete.naipe.upper() != heat.naipe.upper():
        return _violation(
            "naipe_incompativel",
            athlete_id=athlete.id,
            heat_id=heat.id,
            athlete_naipe=athlete.naipe,
            prova_naipe=heat.naipe,
        )
    return None


def _check_categoria(athlete: Athlete, heat: Heat) -> dict | None:
    # Sem categoria (legado) ou categoria "livre" aceitam qualquer atleta.
    if not heat.category or is_free_category(heat.category):
        return None
    athlete_category = (athlete.category or "").strip().lower()
    if athlete_category != heat.category.strip().lower():
        return _violation(
            "categoria_incompativel",
            athlete_id=athlete.id,
            heat_id=heat.id,
            athlete_category=athlete.category,
            prova_category=heat.category,
        )
    return None


def athlete_eligible(athlete: Athlete, heat: Heat) -> bool:
    """Naipe/categoria do atleta compativeis com a bateria (ADR-012)."""
    return (
        _check_naipe(athlete, heat) is None
        and _check_categoria(athlete, heat) is None
    )


async def check_heat_inscricao(
    session: AsyncSession,
    *,
    heat: Heat,
    final_athlete_ids: list[str],
) -> list[dict]:
    """Valida o estado FINAL da bateria (apos aplicar o payload)."""
    violations: list[dict] = []
    counts = Counter(
        athlete_id for athlete_id in final_athlete_ids if athlete_id
    )
    if not counts:
        return violations

    athletes = await _athletes_by_id(session, set(counts))

    # 1. Naipe / categoria de cada atleta inscrito.
    # Atleta de outro evento fica para a checagem 404 do endpoint.
    for athlete_id in counts:
        athlete = athletes.get(athlete_id)
        if athlete is None or athlete.event_id != heat.event_id:
            continue
        mismatch = _check_naipe(athlete, heat) or _check_categoria(
            athlete, heat
        )
        if mismatch:
            violations.append(mismatch)

    assignments = await _other_assignments(
        session, set(counts), exclude_heat_id=heat.id
    )

    # 2. Ja inscrito em outra bateria do MESMO grupo (prova).
    for lane, other_heat in assignments:
        if other_heat.prova_id == heat.prova_id:
            violations.append(
                _violation(
                    "atleta_duplicado_na_prova",
                    athlete_id=lane.athlete_id,
                    heat_id=other_heat.id,
                    heat_name=other_heat.name,
                )
            )

    # 3. Duas vezes na mesma bateria.
    if any(count > 1 for count in counts.values()):
        violations.append(_violation("atleta_duplicado_na_bateria"))

    # 4. Alocado em bateria ativa/ready_check de OUTRO grupo.
    for lane, other_heat in assignments:
        if (
            other_heat.prova_id != heat.prova_id
            and other_heat.status in _ACTIVE_HEAT_STATUSES
        ):
            violations.append(
                _violation(
                    "atleta_em_outra_bateria_ativa",
                    athlete_id=lane.athlete_id,
                    heat_id=other_heat.id,
                    heat_name=other_heat.name,
                )
            )

    return violations


async def check_athlete_update(
    session: AsyncSession,
    *,
    athlete: Athlete,
    naipe: str,
    category: str | None,
) -> list[dict]:
    """Valida naipe/categoria novos contra as raias ja ocupadas pelo atleta."""
    result = await session.execute(
        select(HeatLane, Heat)
        .join(Heat, HeatLane.heat_id == Heat.id)
        .where(HeatLane.athlete_id == athlete.id)
    )
    violations: list[dict] = []
    changed = naipe != athlete.naipe or category != athlete.category
    for _lane, heat in result.all():
        if changed and heat.status == "finished":
            violations.append(
                _violation(
                    "atleta_com_resultado",
                    athlete_id=athlete.id,
                    heat_id=heat.id,
                    heat_name=heat.name,
                )
            )
        if heat.naipe and heat.naipe != "MISTO" and naipe != heat.naipe:
            violations.append(
                _violation(
                    "naipe_incompativel",
                    athlete_id=athlete.id,
                    heat_id=heat.id,
                    athlete_naipe=naipe,
                    prova_naipe=heat.naipe,
                )
            )
        elif (
            heat.category
            and not is_free_category(heat.category)
            and (category or "").strip().lower()
            != heat.category.strip().lower()
        ):
            violations.append(
                _violation(
                    "categoria_incompativel",
                    athlete_id=athlete.id,
                    heat_id=heat.id,
                    athlete_category=category,
                    prova_category=heat.category,
                )
            )
    return violations


def _log_override(
    session: AsyncSession,
    *,
    request: Request | None,
    event_id: str | None,
    heat_id: str | None,
    lane_id: str | None,
    override_reason: str | None,
    violations: list[dict],
) -> None:
    now = time.time()
    _log_action(
        session,
        action="override_inscricao",
        received_at=now,
        effective_ts=now,
        event_id=event_id,
        heat_id=heat_id,
        lane_id=lane_id,
        source_ip=_client_ip(request),
        payload={
            "reason": (override_reason or "").strip(),
            "violations": [violation["code"] for violation in violations],
            "athlete_ids": sorted(
                {
                    violation["athlete_id"]
                    for violation in violations
                    if violation.get("athlete_id")
                }
            ),
        },
    )


async def enforce_heat_inscricao(
    session: AsyncSession,
    *,
    heat: Heat,
    final_athlete_ids: list[str],
    force: bool,
    override_reason: str | None,
    request: Request | None,
    lane_id: str | None = None,
) -> None:
    check_override(request, force, override_reason)
    violations = await check_heat_inscricao(
        session, heat=heat, final_athlete_ids=final_athlete_ids
    )
    if violations and not force:
        raise_violations(violations)
    if force:
        _log_override(
            session,
            request=request,
            event_id=heat.event_id,
            heat_id=heat.id,
            lane_id=lane_id,
            override_reason=override_reason,
            violations=violations,
        )


async def enforce_athlete_update(
    session: AsyncSession,
    *,
    athlete: Athlete,
    naipe: str,
    category: str | None,
    force: bool,
    override_reason: str | None,
    request: Request | None,
) -> None:
    check_override(request, force, override_reason)
    violations = await check_athlete_update(
        session, athlete=athlete, naipe=naipe, category=category
    )
    if violations and not force:
        raise_violations(violations)
    if force:
        _log_override(
            session,
            request=request,
            event_id=athlete.event_id,
            heat_id=None,
            lane_id=None,
            override_reason=override_reason,
            violations=violations,
        )
