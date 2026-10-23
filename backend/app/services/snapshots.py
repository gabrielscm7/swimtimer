"""Snapshots imutaveis de resultado, encadeados por hash.

Cada revisao guarda o payload canonico do estado da bateria no momento em que
foi gerada (nomes, equipe, naipe e categoria do atleta desnormalizados), o
hash da revisao anterior do mesmo evento e o proprio hash. O `Verify` recalcula
a cadeia inteira e aponta a primeira linha quebrada.
"""

import hashlib
import json
import time
import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.locks import _heat_guard
from ..models import Athlete, Event, Heat, HeatLane, LapEvent, ResultSnapshot, Team
from ..schemas import format_race_time
from .journal import queue as journal_queue

GENESIS = "0" * 64

SNAPSHOT_PROVISIONAL = "provisional"
SNAPSHOT_OFFICIAL = "official"
SNAPSHOT_CORRECTED = "corrected"

# Contrato de reasons. O fluxo de correcoes (DQ/undo/reset) chama
# `record_revision(..., status=SNAPSHOT_CORRECTED)` com um destes valores
# sempre que a bateria ja estiver finalizada.
REASON_FINISH = "finish"
REASON_HOMOLOGATION = "homologacao"
REASON_DQ = "dq"
REASON_DQ_UNDO = "dq_undo"
REASON_RESET_FINISH = "reset_finish"
REASON_UNDO_FINISH = "undo_finish"
REASON_GROUP_CHANGE = "correcao_grupo"


def canonical_json(payload: dict) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def hash_snapshot(prev_hash: str, payload_json: str) -> str:
    return hashlib.sha256(
        (prev_hash + payload_json).encode("utf-8")
    ).hexdigest()


async def _snapshot_payload(session: AsyncSession, heat: Heat) -> dict:
    event = await session.get(Event, heat.event_id)
    result = await session.execute(
        select(HeatLane)
        .where(HeatLane.heat_id == heat.id)
        .order_by(HeatLane.lane_number)
    )
    lanes = list(result.scalars().all())

    lap_counts: dict[str, int] = {}
    lane_ids = [lane.id for lane in lanes]
    if lane_ids:
        rows = await session.execute(
            select(LapEvent.lane_id, func.count(LapEvent.id))
            .where(
                LapEvent.lane_id.in_(lane_ids), LapEvent.is_undo.is_(False)
            )
            .group_by(LapEvent.lane_id)
        )
        lap_counts = {lane_id: count for lane_id, count in rows.all()}

    team_ids = {lane.team_id for lane in lanes if lane.team_id}
    teams: dict[str, Team] = {}
    if team_ids:
        rows = await session.execute(select(Team).where(Team.id.in_(team_ids)))
        teams = {team.id: team for team in rows.scalars().all()}

    athlete_ids = {lane.athlete_id for lane in lanes if lane.athlete_id}
    athletes: dict[str, Athlete] = {}
    if athlete_ids:
        rows = await session.execute(
            select(Athlete).where(Athlete.id.in_(athlete_ids))
        )
        athletes = {athlete.id: athlete for athlete in rows.scalars().all()}

    lane_payloads = []
    for lane in lanes:
        athlete = athletes.get(lane.athlete_id) if lane.athlete_id else None
        team = teams.get(lane.team_id) if lane.team_id else None
        lane_payloads.append(
            {
                "lane_id": lane.id,
                "lane_number": lane.lane_number,
                "participant_name": (
                    athlete.name if athlete else lane.participant_name
                ),
                "athlete": (
                    {
                        "id": athlete.id,
                        "name": athlete.name,
                        "naipe": athlete.naipe,
                        "category": athlete.category,
                    }
                    if athlete
                    else None
                ),
                "team_id": lane.team_id,
                "team_name": team.name if team else None,
                "status": lane.status,
                "finish_at": lane.finish_at,
                "race_time_ms": lane.race_time_ms,
                "race_time_display": format_race_time(lane.race_time_ms),
                "received_at": lane.received_at,
                "late": bool(lane.late),
                "laps": lap_counts.get(lane.id, 0),
            }
        )

    return {
        "event": {
            "id": heat.event_id,
            "name": event.name if event else None,
            "pool_length_m": event.pool_length_m if event else None,
        },
        "heat": {
            "id": heat.id,
            "event_id": heat.event_id,
            "prova_id": heat.prova_id,
            "name": heat.name,
            "order_num": heat.order_num,
            "heat_type": heat.heat_type,
            "stroke": heat.stroke,
            "naipe": heat.naipe,
            "category": heat.category,
            "classify_alone": bool(heat.classify_alone),
            "lane_count": heat.lane_count,
            "distance_m": heat.distance_m,
            "duration_s": heat.duration_s,
            "status": heat.status,
            "started_at": heat.started_at,
            "finished_at": heat.finished_at,
        },
        "lanes": lane_payloads,
    }


async def record_revision(
    session: AsyncSession,
    heat: Heat,
    *,
    reason: str,
    status: str,
    role: str,
    ip: str | None = None,
    lock: bool = True,
) -> ResultSnapshot:
    """Adiciona e comita uma revisao ao final da cadeia do evento.

    O commit acontece dentro do lock por evento: sem isso, duas baterias do
    mesmo evento poderiam ler o mesmo `prev_hash` e furcar a cadeia. A acao
    que originou o snapshot e os dados de resultado sao comitados juntos.
    Reasons previstos: finish, homologacao, dq, dq_undo, reset_finish,
    undo_finish (os tres ultimos sao conectados pelo fluxo de correcoes).
    """
    await session.flush()
    if lock:
        guard = _heat_guard(f"event:{heat.event_id}")
    else:
        from contextlib import nullcontext

        guard = nullcontext()
    async with guard:
        payload = await _snapshot_payload(session, heat)

        result = await session.execute(
            select(ResultSnapshot.hash)
            .where(ResultSnapshot.event_id == heat.event_id)
            .order_by(text("rowid DESC"))
            .limit(1)
        )
        prev_hash = result.scalar_one_or_none() or GENESIS

        result = await session.execute(
            select(func.max(ResultSnapshot.revision)).where(
                ResultSnapshot.heat_id == heat.id
            )
        )
        revision = int(result.scalar_one() or 0) + 1

        snapshot_id = str(uuid.uuid4())
        created_at = time.time()
        # Metadados entram no payload canonico para que o hash cubra tambem
        # status, motivo, revisao e autoria (compativel com snapshots antigos,
        # que nao possuem a chave "snapshot").
        payload["snapshot"] = {
            "id": snapshot_id,
            "revision": revision,
            "status": status,
            "reason": reason,
            "created_at": created_at,
            "created_by": role,
            "created_by_ip": ip,
        }
        payload_json = canonical_json(payload)

        snapshot = ResultSnapshot(
            id=snapshot_id,
            event_id=heat.event_id,
            prova_id=heat.prova_id,
            heat_id=heat.id,
            revision=revision,
            status=status,
            reason=reason,
            created_at=created_at,
            created_by=role,
            created_by_ip=ip,
            payload_json=payload_json,
            prev_hash=prev_hash,
            hash=hash_snapshot(prev_hash, payload_json),
        )
        session.add(snapshot)
        journal_queue(
            session,
            heat.event_id,
            {
                "kind": "result_snapshot",
                "id": snapshot.id,
                "event_id": snapshot.event_id,
                "prova_id": snapshot.prova_id,
                "heat_id": snapshot.heat_id,
                "revision": snapshot.revision,
                "status": snapshot.status,
                "reason": snapshot.reason,
                "created_at": snapshot.created_at,
                "created_by": snapshot.created_by,
                "created_by_ip": snapshot.created_by_ip,
                "payload_json": snapshot.payload_json,
                "prev_hash": snapshot.prev_hash,
                "hash": snapshot.hash,
            },
        )
        await session.commit()
        return snapshot


async def latest_for_heat(
    session: AsyncSession, heat_id: str
) -> ResultSnapshot | None:
    result = await session.execute(
        select(ResultSnapshot)
        .where(ResultSnapshot.heat_id == heat_id)
        .order_by(text("rowid DESC"))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_for_heat(
    session: AsyncSession, heat_id: str
) -> list[ResultSnapshot]:
    result = await session.execute(
        select(ResultSnapshot)
        .where(ResultSnapshot.heat_id == heat_id)
        .order_by(text("rowid ASC"))
    )
    return list(result.scalars().all())


async def latest_by_heat(
    session: AsyncSession, event_id: str
) -> dict[str, ResultSnapshot]:
    result = await session.execute(
        select(ResultSnapshot)
        .where(ResultSnapshot.event_id == event_id)
        .order_by(text("rowid ASC"))
    )
    latest: dict[str, ResultSnapshot] = {}
    for row in result.scalars().all():
        latest[row.heat_id] = row
    return latest


def snapshot_summary(snapshot: ResultSnapshot | None) -> dict | None:
    if snapshot is None:
        return None
    # Sem IP: o resumo circula em payloads de gestao/TV. O IP fica no banco e
    # no diario para auditoria.
    return {
        "id": snapshot.id,
        "revision": snapshot.revision,
        "status": snapshot.status,
        "reason": snapshot.reason,
        "created_at": snapshot.created_at,
        "created_by": snapshot.created_by,
        "hash": snapshot.hash,
        "prev_hash": snapshot.prev_hash,
    }


async def verify_event(session: AsyncSession, event_id: str) -> dict:
    """Recalcula a cadeia de hashes do evento e retorna ok/próximo quebrado."""
    result = await session.execute(
        select(ResultSnapshot)
        .where(ResultSnapshot.event_id == event_id)
        .order_by(text("rowid ASC"))
    )
    rows = list(result.scalars().all())

    prev_hash = GENESIS
    for index, row in enumerate(rows):
        if row.prev_hash != prev_hash:
            return {
                "ok": False,
                "broken_id": row.id,
                "reason": "cadeia_quebrada",
                "count": index,
            }
        expected = hash_snapshot(prev_hash, row.payload_json)
        if row.hash != expected:
            return {
                "ok": False,
                "broken_id": row.id,
                "reason": "hash_invalido",
                "count": index,
            }
        try:
            payload = json.loads(row.payload_json)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "broken_id": row.id,
                "reason": "payload_invalido",
                "count": index,
            }
        if (
            payload.get("event", {}).get("id") != row.event_id
            or payload.get("heat", {}).get("id") != row.heat_id
        ):
            return {
                "ok": False,
                "broken_id": row.id,
                "reason": "payload_inconsistente",
                "count": index,
            }
        meta = payload.get("snapshot")
        if meta is not None and not isinstance(meta, dict):
            return {
                "ok": False,
                "broken_id": row.id,
                "reason": "metadados_inconsistentes",
                "count": index,
            }
        if isinstance(meta, dict):
            expected_meta = {
                "id": row.id,
                "revision": row.revision,
                "status": row.status,
                "reason": row.reason,
                "created_at": row.created_at,
                "created_by": row.created_by,
                "created_by_ip": row.created_by_ip,
            }
            if any(meta.get(key) != value for key, value in expected_meta.items()):
                return {
                    "ok": False,
                    "broken_id": row.id,
                    "reason": "metadados_inconsistentes",
                    "count": index,
                }
        prev_hash = row.hash

    return {"ok": True, "count": len(rows)}
