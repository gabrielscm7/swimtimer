"""Finalizacao automatica de maratonas pelo relogio do servidor.

O cliente do supervisor nao e fonte de verdade: a bateria de maratona termina
quando `started_at + duration_s` vence, mesmo que nenhuma aba esteja aberta.
"""

import asyncio
import logging
import time

from sqlalchemy import select

from .. import database
from ..core.locks import _heat_guard
from ..models import Heat
from .backup import backup_service
from .broadcast import _broadcast_heat, _broadcast_server_status
from .lane_actions import _drop_anchor, _log_action
from .payloads import _sync_event_status, _sync_prova_status
from . import snapshots

logger = logging.getLogger(__name__)

TICK_S = 5.0


async def finish_expired_heats() -> int:
    """Finaliza maratonas vencidas; devolve quantas foram finalizadas."""
    now = time.time()
    async with database.AsyncSessionLocal() as session:
        result = await session.execute(
            select(Heat.id).where(
                Heat.status == "active",
                Heat.heat_type == "maratona",
                Heat.started_at.is_not(None),
                Heat.duration_s.is_not(None),
            )
        )
        candidates = list(result.scalars().all())

    finished = 0
    for heat_id in candidates:
        if await _finish_if_expired(heat_id, now):
            finished += 1
    return finished


async def _finish_if_expired(heat_id: str, now: float) -> bool:
    async with _heat_guard(heat_id):
        async with database.AsyncSessionLocal() as session:
            session.expire_all()
            heat = await session.get(Heat, heat_id)
            if heat is None or heat.status != "active":
                return False
            if heat.started_at is None or heat.duration_s is None:
                return False
            if now < heat.started_at + heat.duration_s:
                return False

            heat.status = "finished"
            heat.finished_at = now
            _drop_anchor(heat.id)
            await snapshots.record_revision(
                session,
                heat,
                reason=snapshots.REASON_FINISH,
                status=snapshots.SNAPSHOT_PROVISIONAL,
                role="system",
                ip=None,
            )
            _log_action(
                session,
                action="finish_heat",
                received_at=now,
                effective_ts=now,
                event_id=heat.event_id,
                heat_id=heat.id,
                payload={"automatico": True, "motivo": "duracao_esgotada"},
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
            return True


class MarathonService:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, RuntimeError):
            pass
        except Exception:  # noqa: BLE001
            logger.exception("erro ao encerrar o servico de maratona")

    async def _loop(self) -> None:
        while True:
            try:
                await finish_expired_heats()
            except Exception:  # noqa: BLE001
                logger.exception("falha ao finalizar maratonas vencidas")
            await asyncio.sleep(TICK_S)


marathon_service = MarathonService()
