"""Diario NDJSON por evento: espelho externo do action_log e dos snapshots.

Cada linha e um JSON completo, escrito em modo append com `flush` + `fsync`
antes de retornar. Falhas de escrita nunca interrompem a prova: sao apenas
registradas no log do processo.
"""

import json
import logging
import os
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)


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
