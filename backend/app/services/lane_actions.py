import json
import math
import time
import uuid

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.errors import LaneActionError
from ..core.locks import _heat_guard
from ..models import ActionLog, Heat, HeatLane, LapEvent, ProcessedOp, Team
from ..schemas import compute_speed, format_race_time
from . import snapshots
from .backup import backup_service
from .broadcast import _broadcast_heat, _broadcast_server_status
from .journal import append as journal_append
from .payloads import _heat_lanes, _participant_lanes, _sync_prova_status

# Âncora monotônica por bateria: (monotonic_no_início, wall_no_início).
# Usada para medir duração de toques sem client_ts, imune a ajustes de relógio.
# Volátil por processo — após restart o cálculo cai para wall-clock.
_mono_anchors: dict[str, tuple[float, float]] = {}


def _anchor_heat(heat: Heat) -> None:
    wall = heat.started_at if heat.started_at is not None else time.time()
    _mono_anchors[heat.id] = (time.monotonic(), wall)


def _drop_anchor(heat_id: str) -> None:
    _mono_anchors.pop(heat_id, None)


def _coerce_ts(value: object) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _effective_time(
    heat: Heat, client_ts: float | None
) -> tuple[float, float, bool, float]:
    """Calcula (effective_ts, received_at, late, duração_da_prova).

    - Com client_ts: usa o toque do fiscal, limitado a [started_at, agora].
    - Sem client_ts: usa a âncora monotônica da bateria (se conhecida);
      após restart, cai para o relógio de parede.
    """
    now = time.time()
    started_at = heat.started_at if heat.started_at is not None else now
    if client_ts is not None:
        effective_ts = min(max(client_ts, started_at), now)
        late = (now - effective_ts) > settings.LATE_AFTER_S
        return effective_ts, now, late, max(0.0, effective_ts - started_at)

    anchor = _mono_anchors.get(heat.id)
    if anchor is not None:
        mono_start, wall_start = anchor
        elapsed = max(0.0, time.monotonic() - mono_start)
        effective_ts = wall_start + elapsed
        late = (now - effective_ts) > settings.LATE_AFTER_S
        return effective_ts, now, late, elapsed

    return now, now, False, max(0.0, now - started_at)


def _quantize_race_time_ms(duration_s: float) -> int:
    """Centésimos: piso para múltiplo de 10 ms, coerente com o display."""
    ms = max(0, int(duration_s * 1000))
    return ms - (ms % 10)


def _client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


async def _cached_op_result(
    session: AsyncSession, op_id: str | None
) -> dict | None:
    if not op_id:
        return None
    row = await session.get(ProcessedOp, op_id)
    if row is None:
        return None
    try:
        return json.loads(row.result_json)
    except (TypeError, ValueError):
        return None


def _remember_op(
    session: AsyncSession,
    *,
    op_id: str | None,
    lane_id: str | None,
    action: str,
    result: dict,
) -> None:
    if not op_id:
        return
    session.add(
        ProcessedOp(
            op_id=op_id,
            lane_id=lane_id,
            action=action,
            result_json=json.dumps(result, default=str),
            created_at=time.time(),
        )
    )


def _log_action(
    session: AsyncSession,
    *,
    action: str,
    received_at: float,
    effective_ts: float,
    event_id: str | None = None,
    heat_id: str | None = None,
    lane_id: str | None = None,
    op_id: str | None = None,
    source_ip: str | None = None,
    payload: dict | None = None,
) -> None:
    entry = ActionLog(
        id=str(uuid.uuid4()),
        received_at=received_at,
        effective_ts=effective_ts,
        event_id=event_id,
        heat_id=heat_id,
        lane_id=lane_id,
        action=action,
        op_id=op_id,
        source_ip=source_ip,
        payload_json=(
            json.dumps(payload, default=str) if payload is not None else None
        ),
    )
    session.add(entry)
    journal_append(
        event_id,
        {
            "kind": "action_log",
            "id": entry.id,
            "received_at": entry.received_at,
            "effective_ts": entry.effective_ts,
            "event_id": entry.event_id,
            "heat_id": entry.heat_id,
            "lane_id": entry.lane_id,
            "action": entry.action,
            "op_id": entry.op_id,
            "source_ip": entry.source_ip,
            "payload_json": entry.payload_json,
        },
    )
    backup_service.notify_activity(event_id)


async def _maybe_finish_heat(
    session: AsyncSession,
    heat: Heat,
    *,
    role: str = "system",
    source_ip: str | None = None,
) -> bool:
    await session.flush()
    lanes = await _heat_lanes(session, heat.id)
    participants = _participant_lanes(lanes)
    finished = False
    if participants and all(
        lane.status in ("finished", "dq") for lane in participants
    ):
        heat.status = "finished"
        heat.finished_at = time.time()
        await snapshots.record_revision(
            session,
            heat,
            reason=snapshots.REASON_FINISH,
            status=snapshots.SNAPSHOT_PROVISIONAL,
            role=role,
            ip=source_ip,
        )
        finished = True
    await _sync_prova_status(session, heat.prova_id)
    return finished


async def _do_finish(
    session: AsyncSession,
    lane_id: str,
    *,
    op_id: str | None = None,
    client_ts: float | None = None,
    source_ip: str | None = None,
) -> dict:
    lane = await session.get(HeatLane, lane_id)
    if lane is None:
        raise LaneActionError(404, "raia_nao_encontrada")
    heat_id = lane.heat_id

    async with _heat_guard(heat_id):
        session.expire_all()
        lane = await session.get(HeatLane, lane_id)
        if lane is None:
            raise LaneActionError(404, "raia_nao_encontrada")
        cached = await _cached_op_result(session, op_id)
        if cached is not None:
            return cached
        heat = await session.get(Heat, heat_id)
        if heat is None:
            raise LaneActionError(404, "bateria_nao_encontrada")
        if heat.heat_type != "bateria":
            raise LaneActionError(400, "nao_e_bateria")
        if lane.finish_at is not None:
            raise LaneActionError(409, "ja_finalizou")
        if heat.status != "active":
            raise LaneActionError(400, "bateria_nao_ativa")
        if heat.started_at is None:
            raise LaneActionError(400, "bateria_nao_iniciada")

        effective_ts, received_at, late, duration_s = _effective_time(
            heat, _coerce_ts(client_ts)
        )
        lane.finish_at = effective_ts
        lane.race_time_ms = _quantize_race_time_ms(duration_s)
        lane.received_at = received_at
        lane.late = late
        lane.status = "finished"
        all_finished = await _maybe_finish_heat(
            session, heat, role="fiscal", source_ip=source_ip
        )

        team_name = None
        if lane.team_id:
            team = await session.get(Team, lane.team_id)
            team_name = team.name if team else None

        result = {
            "lane_id": lane.id,
            "lane_number": lane.lane_number,
            "participant_name": lane.participant_name,
            "team_name": team_name,
            "race_time_ms": lane.race_time_ms,
            "race_time_display": format_race_time(lane.race_time_ms),
            "speed_ms": compute_speed(heat.distance_m, lane.race_time_ms) or 0.0,
            "received_at": received_at,
            "late": late,
        }
        _remember_op(
            session,
            op_id=op_id,
            lane_id=lane.id,
            action="finish",
            result=result,
        )
        _log_action(
            session,
            action="finish",
            received_at=received_at,
            effective_ts=effective_ts,
            event_id=heat.event_id,
            heat_id=heat.id,
            lane_id=lane.id,
            op_id=op_id,
            source_ip=source_ip,
            payload={
                "race_time_ms": result["race_time_ms"],
                "late": late,
            },
        )
        await session.commit()
        await session.refresh(lane)

        await _broadcast_heat(session, heat)
        if all_finished:
            await _broadcast_server_status()
            backup_service.schedule_after_finish(heat.event_id)

        return result


async def _do_lap(
    session: AsyncSession,
    lane_id: str,
    *,
    op_id: str | None = None,
    client_ts: float | None = None,
    source_ip: str | None = None,
) -> dict:
    lane = await session.get(HeatLane, lane_id)
    if lane is None:
        raise LaneActionError(404, "raia_nao_encontrada")
    heat_id = lane.heat_id

    async with _heat_guard(heat_id):
        session.expire_all()
        lane = await session.get(HeatLane, lane_id)
        if lane is None:
            raise LaneActionError(404, "raia_nao_encontrada")
        cached = await _cached_op_result(session, op_id)
        if cached is not None:
            return cached
        heat = await session.get(Heat, heat_id)
        if heat is None:
            raise LaneActionError(404, "bateria_nao_encontrada")
        if heat.heat_type != "maratona":
            raise LaneActionError(400, "nao_e_maratona")
        if heat.status != "active":
            raise LaneActionError(400, "bateria_nao_ativa")

        effective_ts, received_at, late, _duration_s = _effective_time(
            heat, _coerce_ts(client_ts)
        )

        result = await session.execute(
            select(LapEvent.recorded_at)
            .where(LapEvent.lane_id == lane.id, LapEvent.is_undo.is_(False))
            .order_by(LapEvent.recorded_at.desc())
            .limit(1)
        )
        last_lap_at = result.scalar_one_or_none()
        if (
            last_lap_at is not None
            and effective_ts - last_lap_at < settings.MIN_LAP_INTERVAL_S
        ):
            raise LaneActionError(409, "volta_duplicada")

        result = await session.execute(
            select(func.max(LapEvent.lap_number)).where(
                LapEvent.lane_id == lane.id
            )
        )
        current = result.scalar_one()
        lap_number = int(current or 0) + 1
        event = LapEvent(
            lane_id=lane.id,
            lap_number=lap_number,
            recorded_at=effective_ts,
            is_undo=False,
            received_at=received_at,
            late=late,
        )
        session.add(event)
        if lane.status in ("assigned", "ready"):
            lane.status = "active"
        await session.flush()

        payload = {
            "id": event.id,
            "lane_id": event.lane_id,
            "lap_number": event.lap_number,
            "recorded_at": event.recorded_at,
            "is_undo": event.is_undo,
            "received_at": received_at,
            "late": late,
        }
        _remember_op(
            session,
            op_id=op_id,
            lane_id=lane.id,
            action="lap",
            result=payload,
        )
        _log_action(
            session,
            action="lap",
            received_at=received_at,
            effective_ts=effective_ts,
            event_id=heat.event_id,
            heat_id=heat.id,
            lane_id=lane.id,
            op_id=op_id,
            source_ip=source_ip,
            payload={"lap_number": lap_number, "late": late},
        )
        await session.commit()
        await session.refresh(event)
        await _broadcast_heat(session, heat)
        return payload
