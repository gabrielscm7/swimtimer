import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.locks import _heat_guard
from ..database import get_db
from ..models import Athlete, Event, Heat, HeatLane, LapEvent, Prova, Team
from ..schemas import (
    HeatCreate,
    HeatLaneConfigRequest,
    HeatOrderRequest,
    HeatUpdate,
)
from ..services import presentation
from ..services import provas as prova_rules
from ..services import snapshots
from ..services.backup import backup_service
from ..services.broadcast import (
    _broadcast_heat,
    _broadcast_ready,
    _broadcast_server_status,
    _prova_state_message,
    manager,
)
from ..services.heat_order import (
    next_heat_order,
    place_new_heat,
    renumber_heats,
    reorder_event_heats,
)
from ..services.inscricao import (
    athlete_eligible,
    check_override,
    enforce_heat_inscricao,
)
from ..services.lane_actions import (
    _anchor_heat,
    _client_ip,
    _drop_anchor,
    _log_action,
)
from ..services.lookups import _get_event, _get_heat
from ..services.payloads import (
    _heat_lanes,
    _heat_payload,
    _participant_lanes,
    _prova_payload,
    _sync_event_status,
    _sync_prova_status,
)

router = APIRouter()


async def _broadcast_provas(session: AsyncSession, prova_ids: set[str]) -> None:
    for prova_id in prova_ids:
        prova = await session.get(Prova, prova_id)
        if prova is None:
            continue
        await manager.broadcast(
            _prova_state_message(await _prova_payload(session, prova))
        )


@router.post("/api/events/{event_id}/heats", status_code=201)
async def create_heat(
    event_id: str,
    payload: HeatCreate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Cria uma bateria; a prova do grupo é criada automaticamente."""
    async with _heat_guard(f"event:{event_id}"):
        session.expire_all()
        event = await _get_event(session, event_id)
        order_num = await next_heat_order(session, event_id)
        values = {
            "event_id": event_id,
            "name": payload.name or "",
            "order_num": order_num,
            "heat_type": payload.heat_type,
            "stroke": payload.stroke,
            "naipe": payload.naipe,
            "category": payload.category,
            "classify_alone": payload.classify_alone,
            "lane_count": payload.lane_count or event.default_lane_count,
            "distance_m": (
                payload.distance_m if payload.heat_type == "bateria" else None
            ),
            "duration_s": (
                payload.duration_s if payload.heat_type == "maratona" else None
            ),
            "status": "scheduled",
        }
        # Resolve o grupo antes de persistir a bateria (prova_id e NOT NULL/FK).
        transient = Heat(**values)
        prova = await prova_rules.resolve_group(session, event, transient)
        heat = Heat(prova_id=prova.id, **values)
        session.add(heat)
        await session.flush()
        await prova_rules.sync_prova_from_group(session, prova)
        if payload.order_num is not None:
            await place_new_heat(session, event_id, heat, payload.order_num)
        await prova_rules.renumber_provas(session, event_id)
        await _sync_prova_status(session, prova.id)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(
                status_code=400, detail="order_num_duplicado"
            )
        await session.refresh(heat)
        await session.refresh(prova)
        changed, _became_finished = await _sync_event_status(
            session, heat.event_id
        )
        if changed:
            await session.commit()
        payload_out = await _heat_payload(session, heat)
        prova_payload = await _prova_payload(session, prova)

    await _broadcast_server_status()
    await manager.broadcast(_prova_state_message(prova_payload))
    return payload_out


@router.get("/api/events/{event_id}/heats")
async def list_heats(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_event(session, event_id)
    result = await session.execute(
        select(Heat)
        .where(Heat.event_id == event_id)
        .order_by(Heat.order_num)
    )
    return [
        await _heat_payload(session, heat)
        for heat in result.scalars().all()
    ]


@router.get("/api/heats/{heat_id}")
async def get_heat(
    heat_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    heat = await _get_heat(session, heat_id)
    payload = await _heat_payload(session, heat)
    payload["result_snapshot"] = snapshots.snapshot_summary(
        await snapshots.latest_for_heat(session, heat.id)
    )
    return payload


@router.get("/api/heats/{heat_id}/snapshots")
async def list_heat_snapshots(
    heat_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    heat = await _get_heat(session, heat_id)
    rows = await snapshots.list_for_heat(session, heat.id)
    return [snapshots.snapshot_summary(row) for row in rows]


@router.get("/api/heats/{heat_id}/eligible-athletes")
async def eligible_athletes(
    heat_id: str,
    team_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Atletas elegíveis da equipe, marcando os já alocados no grupo."""
    heat = await _get_heat(session, heat_id)
    team = await session.get(Team, team_id)
    if team is None or team.event_id != heat.event_id:
        raise HTTPException(status_code=404, detail="equipe_nao_encontrada")

    result = await session.execute(
        select(Athlete)
        .where(
            Athlete.event_id == heat.event_id,
            Athlete.team_id == team_id,
        )
        .order_by(Athlete.name)
    )
    athlete_rows = list(result.scalars().all())

    allocated: dict[str, Heat] = {}
    result = await session.execute(
        select(HeatLane.athlete_id, Heat)
        .join(Heat, HeatLane.heat_id == Heat.id)
        .where(
            Heat.prova_id == heat.prova_id,
            HeatLane.athlete_id.is_not(None),
        )
    )
    for athlete_id, alloc_heat in result.all():
        if athlete_id:
            allocated[athlete_id] = alloc_heat

    payload = []
    for athlete in athlete_rows:
        if not athlete_eligible(athlete, heat):
            continue
        alloc = allocated.get(athlete.id)
        payload.append(
            {
                "id": athlete.id,
                "event_id": athlete.event_id,
                "team_id": athlete.team_id,
                "name": athlete.name,
                "naipe": athlete.naipe,
                "category": athlete.category,
                "registration_code": athlete.registration_code,
                "allocated": alloc is not None,
                "allocated_heat_id": alloc.id if alloc else None,
                "allocated_heat_name": alloc.name if alloc else None,
            }
        )
    return payload


@router.patch("/api/heats/{heat_id}")
async def update_heat(
    heat_id: str,
    payload: HeatUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    heat = await _get_heat(session, heat_id)
    event_id = heat.event_id
    async with _heat_guard(f"event:{event_id}"):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        event = await _get_event(session, event_id)
        if heat.status not in ("scheduled", "ready_check", "finished"):
            raise HTTPException(
                status_code=409, detail="bateria_ja_iniciada"
            )
        data = payload.model_dump(
            exclude_unset=True, exclude={"force", "override_reason"}
        )
        old_prova_id = heat.prova_id

        group_fields = {
            "heat_type",
            "stroke",
            "naipe",
            "category",
            "distance_m",
            "duration_s",
        }
        group_touched = bool(group_fields & set(data))
        regroups = group_touched or "classify_alone" in data

        has_result = heat.status == "finished" or (
            await snapshots.latest_for_heat(session, heat.id)
        ) is not None
        if has_result and group_fields & set(data):
            if not payload.force:
                raise HTTPException(
                    status_code=409, detail="bateria_com_resultado"
                )
            check_override(request, True, payload.override_reason)

        candidate_type = data.get("heat_type", heat.heat_type)
        candidate_stroke = data.get("stroke", heat.stroke)
        candidate_naipe = data.get("naipe", heat.naipe)
        candidate_category = data.get("category", heat.category)
        candidate_distance = data.get("distance_m", heat.distance_m)
        candidate_duration = data.get("duration_s", heat.duration_s)

        if group_touched:
            if not candidate_stroke or not candidate_naipe or not candidate_category:
                raise HTTPException(
                    status_code=422, detail="grupo_incompleto"
                )
            if candidate_type == "bateria":
                if candidate_distance is None:
                    raise HTTPException(
                        status_code=422, detail="distance_m_obrigatorio"
                    )
                if "duration_s" in data and data["duration_s"] is not None:
                    raise HTTPException(
                        status_code=422,
                        detail="campo_incompativel_bateria",
                    )
            else:
                if candidate_duration is None:
                    raise HTTPException(
                        status_code=422, detail="duration_s_obrigatorio"
                    )
                candidate_distance = None

        if "lane_count" in data:
            occupied = await _heat_lanes(session, heat.id)
            highest = max(
                (lane.lane_number for lane in occupied), default=0
            )
            if highest > data["lane_count"]:
                raise HTTPException(
                    status_code=422, detail="lane_count_menor_que_raias"
                )

        for field, value in data.items():
            setattr(heat, field, value)
        if candidate_type == "bateria":
            heat.distance_m = candidate_distance
            if "duration_s" in data:
                heat.duration_s = None
        else:
            heat.distance_m = None
            heat.duration_s = candidate_duration

        if regroups:
            _prova, _previous = await prova_rules.attach_heat_to_group(
                session, event, heat
            )
            if old_prova_id and old_prova_id != heat.prova_id:
                await prova_rules.remove_prova_if_empty(
                    session, old_prova_id
                )
            await prova_rules.renumber_provas(session, event_id)

        if has_result and payload.force and group_fields & set(data):
            snapshot = await snapshots.record_revision(
                session,
                heat,
                reason=snapshots.REASON_GROUP_CHANGE,
                status=snapshots.SNAPSHOT_CORRECTED,
                role="supervisor",
                ip=_client_ip(request),
                lock=False,
            )
            now = time.time()
            _log_action(
                session,
                action="override_grupo",
                received_at=now,
                effective_ts=now,
                event_id=heat.event_id,
                heat_id=heat.id,
                source_ip=_client_ip(request),
                payload={
                    "reason": (payload.override_reason or "").strip(),
                    "snapshot_id": snapshot.id,
                    "revision": snapshot.revision,
                },
            )

        prova = await session.get(Prova, heat.prova_id)
        if prova is not None:
            await _sync_prova_status(session, prova.id)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(
                status_code=400, detail="order_num_duplicado"
            )
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        payload_out = await _heat_payload(session, heat)
        prova_ids = {heat.prova_id}
        if old_prova_id:
            prova_ids.add(old_prova_id)

    await _broadcast_provas(session, prova_ids)
    return payload_out


@router.patch("/api/events/{event_id}/heats/order")
async def order_heats(
    event_id: str,
    payload: HeatOrderRequest,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Reordena baterias do evento (lista completa ou mover para posição N)."""
    async with _heat_guard(f"event:{event_id}"):
        session.expire_all()
        await _get_event(session, event_id)
        heats = await reorder_event_heats(session, event_id, payload)
        await prova_rules.renumber_provas(session, event_id)
        result = await session.execute(
            select(Prova)
            .where(Prova.event_id == event_id)
            .order_by(Prova.order_num)
        )
        provas = list(result.scalars().all())
        await session.commit()
        prova_payloads = await _provas_payload_for_broadcast(
            session, provas
        )
        heat_payloads = [
            await _heat_payload(session, heat) for heat in heats
        ]

    for prova_payload in prova_payloads:
        await manager.broadcast(_prova_state_message(prova_payload))
    return heat_payloads


async def _provas_payload_for_broadcast(
    session: AsyncSession, provas: list[Prova]
) -> list[dict]:
    from ..services.payloads import _provas_payload

    return await _provas_payload(session, provas, include_heats=True)


@router.delete("/api/heats/{heat_id}", status_code=204)
async def delete_heat(
    heat_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    heat = await _get_heat(session, heat_id)
    prova_id = heat.prova_id
    event_id = heat.event_id
    became_finished = False
    async with _heat_guard(f"event:{event_id}"):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status != "scheduled":
            raise HTTPException(
                status_code=409, detail="bateria_nao_esta_scheduled"
            )
        lane_ids = select(HeatLane.id).where(HeatLane.heat_id == heat_id)
        await session.execute(
            delete(LapEvent).where(LapEvent.lane_id.in_(lane_ids))
        )
        await session.execute(
            delete(HeatLane).where(HeatLane.heat_id == heat_id)
        )
        await session.delete(heat)
        await session.flush()
        await renumber_heats(session, event_id)
        await prova_rules.remove_prova_if_empty(session, prova_id)
        await session.flush()
        await prova_rules.renumber_provas(session, event_id)
        if await session.get(Prova, prova_id) is not None:
            await _sync_prova_status(session, prova_id)
        await session.commit()
        event = await session.get(Event, event_id)
        if event is not None:
            event.presentation_json = (
                presentation.serialize_presentation(
                    presentation.remove_refs(
                        event.presentation_json,
                        {f"bateria:{heat_id}"},
                    )
                )
            )
        changed, became_finished = await _sync_event_status(session, event_id)
        if changed or event is not None:
            await session.commit()
        result = await session.execute(
            select(Prova)
            .where(Prova.event_id == event_id)
            .order_by(Prova.order_num)
        )
        provas = list(result.scalars().all())
        prova_payloads = await _provas_payload_for_broadcast(
            session, provas
        )
    await _broadcast_server_status()
    if became_finished:
        await backup_service.backup_now(event_id, kind="final")
    for prova_payload in prova_payloads:
        await manager.broadcast(_prova_state_message(prova_payload))


@router.post("/api/heats/{heat_id}/open-ready-check")
async def open_ready_check(
    heat_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status not in ("scheduled", "ready_check"):
            raise HTTPException(status_code=409, detail="bateria_nao_esta_scheduled")
        heat.status = "ready_check"
        await _sync_prova_status(session, heat.prova_id)
        await session.commit()
        await session.refresh(heat)
        changed, _became_finished = await _sync_event_status(
            session, heat.event_id
        )
        if changed:
            await session.commit()
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        return await _heat_payload(session, heat)


@router.post("/api/heats/{heat_id}/start")
async def start_heat(
    heat_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        direct_start = heat.status == "scheduled" and heat.heat_type == "maratona"
        if heat.status != "ready_check" and not direct_start:
            raise HTTPException(
                status_code=400, detail="bateria_nao_esta_em_ready_check"
            )

        if heat.heat_type == "bateria" and heat.distance_m is None:
            raise HTTPException(status_code=400, detail="distance_m_obrigatorio")
        if heat.heat_type == "maratona" and heat.duration_s is None:
            raise HTTPException(status_code=400, detail="duration_s_obrigatorio")

        lanes = await _heat_lanes(session, heat.id)
        participants = _participant_lanes(lanes)
        if not participants:
            raise HTTPException(status_code=400, detail="sem_participantes")
        if any(lane.finish_at is not None for lane in participants):
            raise HTTPException(
                status_code=409, detail="bateria_com_resultados_anteriores"
            )
        if not direct_start:
            pending = [
                lane.lane_number for lane in participants if lane.status != "ready"
            ]
            if pending:
                listed = ", ".join(str(number) for number in pending)
                raise HTTPException(
                    status_code=400, detail=f"raias_pendentes: {listed}"
                )

        started_at = time.time()
        heat.status = "active"
        heat.started_at = started_at
        heat.finished_at = None
        for lane in participants:
            lane.status = "active"
        _anchor_heat(heat)
        _log_action(
            session,
            action="start",
            received_at=started_at,
            effective_ts=started_at,
            event_id=heat.event_id,
            heat_id=heat.id,
            source_ip=_client_ip(request),
        )
        await _sync_prova_status(session, heat.prova_id)
        await session.commit()
        await session.refresh(heat)
        changed, _became_finished = await _sync_event_status(
            session, heat.event_id
        )
        if changed:
            await session.commit()
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        await _broadcast_server_status()
        return await _heat_payload(session, heat)


@router.post("/api/heats/{heat_id}/abort")
async def abort_heat(
    heat_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status not in ("ready_check", "active"):
            raise HTTPException(status_code=409, detail="bateria_nao_esta_ativa")
        now = time.time()
        was_active = heat.status == "active"
        heat.status = "scheduled"
        heat.started_at = None
        heat.finished_at = None
        _drop_anchor(heat.id)
        if was_active:
            # Cancelar a prova invalida tempos, DQ e voltas parciais; as raias
            # continuam inscritas e voltam a "ready" para um novo disparo.
            lane_ids = select(HeatLane.id).where(HeatLane.heat_id == heat.id)
            await session.execute(
                delete(LapEvent).where(LapEvent.lane_id.in_(lane_ids))
            )
            await session.execute(
                update(HeatLane)
                .where(
                    HeatLane.heat_id == heat.id,
                    HeatLane.status.in_(("active", "finished", "dq")),
                )
                .values(
                    status="ready",
                    finish_at=None,
                    race_time_ms=None,
                    received_at=None,
                    late=False,
                )
            )
        else:
            await session.execute(
                update(HeatLane)
                .where(
                    HeatLane.heat_id == heat.id,
                    HeatLane.status == "active",
                )
                .values(status="ready")
            )
        _log_action(
            session,
            action="abort",
            received_at=now,
            effective_ts=now,
            event_id=heat.event_id,
            heat_id=heat.id,
            source_ip=_client_ip(request),
        )
        await _sync_prova_status(session, heat.prova_id)
        await session.commit()
        await session.refresh(heat)
        changed, _became_finished = await _sync_event_status(
            session, heat.event_id
        )
        if changed:
            await session.commit()
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        await _broadcast_server_status()
        return await _heat_payload(session, heat)


@router.post("/api/heats/{heat_id}/finish")
async def finish_heat(
    heat_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status == "finished":
            return await _heat_payload(session, heat)
        if heat.status == "scheduled":
            raise HTTPException(status_code=409, detail="bateria_nao_iniciada")
        if heat.status != "active":
            raise HTTPException(status_code=409, detail="bateria_nao_ativa")
        now = time.time()
        heat.status = "finished"
        heat.finished_at = now
        _drop_anchor(heat.id)
        await snapshots.record_revision(
            session,
            heat,
            reason=snapshots.REASON_FINISH,
            status=snapshots.SNAPSHOT_PROVISIONAL,
            role="supervisor",
            ip=_client_ip(request),
        )
        _log_action(
            session,
            action="finish_heat",
            received_at=now,
            effective_ts=now,
            event_id=heat.event_id,
            heat_id=heat.id,
            source_ip=_client_ip(request),
        )
        await _sync_prova_status(session, heat.prova_id)
        await session.commit()
        await session.refresh(heat)
        changed, became_finished = await _sync_event_status(
            session, heat.event_id
        )
        if changed:
            await session.commit()
        await _broadcast_heat(session, heat)
        await _broadcast_server_status()
        if became_finished:
            await backup_service.backup_now(heat.event_id, kind="final")
        else:
            backup_service.schedule_after_finish(heat.event_id)
        return await _heat_payload(session, heat)


@router.post("/api/heats/{heat_id}/homologate")
async def homologate_heat(
    heat_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Supervisor homologa o resultado de uma bateria finalizada."""
    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status != "finished":
            raise HTTPException(
                status_code=409, detail="bateria_nao_finalizada"
            )
        latest = await snapshots.latest_for_heat(session, heat.id)
        if latest is not None and latest.status == snapshots.SNAPSHOT_OFFICIAL:
            raise HTTPException(
                status_code=409, detail="bateria_ja_homologada"
            )
        snapshot = await snapshots.record_revision(
            session,
            heat,
            reason=snapshots.REASON_HOMOLOGATION,
            status=snapshots.SNAPSHOT_OFFICIAL,
            role="supervisor",
            ip=_client_ip(request),
        )
        now = time.time()
        _log_action(
            session,
            action="homologate",
            received_at=now,
            effective_ts=now,
            event_id=heat.event_id,
            heat_id=heat.id,
            source_ip=_client_ip(request),
            payload={
                "snapshot_id": snapshot.id,
                "revision": snapshot.revision,
                "hash": snapshot.hash,
            },
        )
        await session.commit()
        await session.refresh(heat)
        backup_service.notify_activity(heat.event_id)
        await _broadcast_heat(session, heat)
        payload = await _heat_payload(session, heat)
        payload["result_snapshot"] = snapshots.snapshot_summary(snapshot)
        return payload


@router.post("/api/heats/{heat_id}/lanes")
async def configure_lanes(
    heat_id: str,
    payload: HeatLaneConfigRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    numbers = [item.lane_number for item in payload.lanes]
    if len(numbers) != len(set(numbers)):
        raise HTTPException(status_code=400, detail="raias_duplicadas")

    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status not in ("scheduled", "ready_check"):
            raise HTTPException(status_code=409, detail="bateria_ja_iniciada")
        if any(item.lane_number > heat.lane_count for item in payload.lanes):
            raise HTTPException(
                status_code=422, detail="raia_acima_de_lane_count"
            )

        existing = {
            lane.lane_number: lane for lane in await _heat_lanes(session, heat.id)
        }

        # Estado final da bateria apos aplicar o payload: a validacao precisa
        # considerar trocas de raia dentro da mesma bateria.
        prospective = {
            number: lane.athlete_id for number, lane in existing.items()
        }
        for item in payload.lanes:
            prospective[item.lane_number] = item.athlete_id
        await enforce_heat_inscricao(
            session,
            heat=heat,
            final_athlete_ids=[
                athlete_id
                for athlete_id in prospective.values()
                if athlete_id
            ],
            force=payload.force,
            override_reason=payload.override_reason,
            request=request,
        )

        for item in payload.lanes:
            athlete = None
            if item.athlete_id is not None:
                athlete = await session.get(Athlete, item.athlete_id)
                if athlete is None or athlete.event_id != heat.event_id:
                    raise HTTPException(
                        status_code=404, detail="atleta_nao_encontrado"
                    )
            else:
                if item.team_id is not None:
                    team = await session.get(Team, item.team_id)
                    if team is None or team.event_id != heat.event_id:
                        raise HTTPException(
                            status_code=404, detail="equipe_nao_encontrada"
                        )
            participant_name = (
                athlete.name if athlete else item.participant_name
            )
            team_id = athlete.team_id if athlete else item.team_id
            lane = existing.get(item.lane_number)
            if lane is None:
                lane = HeatLane(
                    heat_id=heat.id,
                    lane_number=item.lane_number,
                    participant_name=participant_name,
                    athlete_id=item.athlete_id,
                    team_id=team_id,
                    status="assigned",
                )
                session.add(lane)
            else:
                lane.participant_name = participant_name
                lane.athlete_id = item.athlete_id
                lane.team_id = team_id
                lane.status = "assigned"
        await session.commit()
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        return await _heat_payload(session, heat)
