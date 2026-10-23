"""Diario NDJSON por evento: espelho externo do action_log e dos snapshots.

Cada linha e um JSON completo, escrito em modo append com `flush` + `fsync`
antes de retornar. Falhas de escrita nunca interrompem a prova: sao apenas
registradas no log do processo.
"""

import json
import logging
import os
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.orm import Session

from ..config import settings

logger = logging.getLogger(__name__)

_QUEUE_KEY = "journal_records"


def queue(session: Session, event_id: str | None, record: dict) -> None:
    """Agenda a escrita do diario para depois do commit da transacao."""
    if not event_id:
        return
    target = getattr(session, "sync_session", session)
    records = target.info.setdefault(_QUEUE_KEY, [])
    records.append((event_id, record))


@event.listens_for(Session, "after_commit")
def _flush_after_commit(session: Session) -> None:
    records = session.info.pop(_QUEUE_KEY, [])
    for event_id, record in records:
        try:
            append(event_id, record)
        except Exception:  # noqa: BLE001 - nunca falhar o commit por auditoria
            logger.exception("falha ao gravar journal de %s", event_id)


@event.listens_for(Session, "after_rollback")
def _discard_after_rollback(session: Session) -> None:
    session.info.pop(_QUEUE_KEY, None)


def journal_path(event_id: str) -> Path:
    return settings.journal_dir / f"{event_id}.ndjson"


def append(event_id: str | None, record: dict) -> None:
    if not event_id:
        return
    path = journal_path(event_id)
    line = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "ab") as handle:
            handle.write(line.encode("utf-8") + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        logger.warning("falha ao escrever journal %s: %s", event_id, exc)
