"""Backup continuo do SQLite durante a prova.

Usa `sqlite3.Connection.backup()` (copia consistente mesmo com WAL e escritas
em andamento) em thread, sem bloquear o event loop. Gera sidecar `.sha256`,
aplica retencao (12 mais recentes + 1 por hora + final) e, se configurado,
espelha para um pendrive com verificacao de checksum.
"""

import asyncio
import hashlib
import logging
import re
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)

FINISH_DEBOUNCE_S = 10.0
KEEP_RECENT = 12
_BACKUP_RE = re.compile(
    r"^swimtimer_(\d{8}_\d{6}_\d{6})(_final)?\.db$"
)


def db_file_path(database_url: str | None = None) -> Path | None:
    """Caminho do arquivo SQLite ou None para bancos em memoria."""
    url = database_url or settings.DATABASE_URL
    if ":memory:" in url or "///" not in url:
        return None
    raw = url.split("///", 1)[1].split("?", 1)[0]
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_stamp(path: Path) -> str | None:
    match = _BACKUP_RE.match(path.name)
    return match.group(1) if match else None


def _is_final(path: Path) -> bool:
    match = _BACKUP_RE.match(path.name)
    return bool(match and match.group(2))


def retention_candidates(
    backups: list[Path], keep_recent: int = KEEP_RECENT
) -> list[Path]:
    """Arquivos a apagar: mantem os N mais novos, 1 por hora e todos os finais.

    `backups` deve conter apenas os arquivos `.db` regulares/finais.
    """
    finals = [path for path in backups if _is_final(path)]
    regular = sorted(
        (path for path in backups if not _is_final(path)),
        key=lambda path: _backup_stamp(path) or "",
        reverse=True,
    )
    keep = set(regular[:keep_recent])
    seen_hours: set[str] = set()
    for path in regular[keep_recent:]:
        stamp = _backup_stamp(path) or ""
        hour = stamp[:11]
        if hour and hour not in seen_hours:
            seen_hours.add(hour)
            keep.add(path)
    keep.update(finals)
    return [path for path in backups if path not in keep]


def prune_backups(dest_dir: Path, keep_recent: int = KEEP_RECENT) -> list[Path]:
    backups = [
        path
        for path in dest_dir.glob("swimtimer_*.db")
        if path.is_file() and not path.name.endswith(".tmp")
    ]
    removed = []
    for path in retention_candidates(backups, keep_recent):
        try:
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".sha256").unlink(missing_ok=True)
            removed.append(path)
        except OSError as exc:
            logger.warning("falha ao remover backup %s: %s", path, exc)
    return removed


def _copy_database(db_path: Path, dest: Path) -> None:
    source = sqlite3.connect(str(db_path), timeout=30)
    try:
        target = sqlite3.connect(str(dest))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


class BackupService:
    def __init__(self) -> None:
        self.last_backup_at: float | None = None
        self.last_error: str | None = None
        self.mirror_ok: bool | None = None
        self._dirty: set[str] = set()
        self._debounce: dict[str, asyncio.Task] = {}
        self._interval_task: asyncio.Task | None = None

    @property
    def enabled(self) -> bool:
        return db_file_path() is not None

    def notify_activity(self, event_id: str | None) -> None:
        if event_id and self.enabled:
            self._dirty.add(event_id)

    def schedule_after_finish(self, event_id: str | None) -> None:
        if not event_id or not self.enabled:
            return
        self._dirty.add(event_id)
        current = self._debounce.get(event_id)
        if current is not None and not current.done():
            current.cancel()

        async def _deferred() -> None:
            try:
                await asyncio.sleep(FINISH_DEBOUNCE_S)
            except asyncio.CancelledError:
                return
            await self.backup_now(event_id)

        try:
            self._debounce[event_id] = asyncio.create_task(_deferred())
        except RuntimeError:
            # Sem event loop (ex.: chamada sincrona em teste): ignora.
            self._debounce.pop(event_id, None)

    async def backup_now(
        self, event_id: str, *, kind: str = "auto"
    ) -> Path | None:
        db_path = db_file_path()
        if db_path is None:
            return None
        if not db_path.is_file():
            self.last_error = "banco_ausente"
            return None
        try:
            path = await asyncio.to_thread(
                self._write_backup, db_path, event_id, kind
            )
            self.last_backup_at = time.time()
            self.last_error = None
            self._dirty.discard(event_id)
        except Exception as exc:  # noqa: BLE001 - status deve refletir falhas
            logger.warning("falha no backup de %s: %s", event_id, exc)
            self.last_error = str(exc)
            return None
        await asyncio.to_thread(self._mirror, path)
        return path

    def _write_backup(
        self, db_path: Path, event_id: str, kind: str
    ) -> Path:
        dest_dir = settings.backup_dir / event_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        suffix = "_final" if kind == "final" else ""
        dest = dest_dir / f"swimtimer_{stamp}{suffix}.db"
        tmp = dest.with_name(dest.name + ".tmp")
        try:
            _copy_database(db_path, tmp)
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
        digest = sha256_file(dest)
        dest.with_name(dest.name + ".sha256").write_text(
            f"{digest}  {dest.name}\n", encoding="utf-8"
        )
        prune_backups(dest_dir)
        return dest

    def _mirror(self, path: Path) -> None:
        mirror_root = settings.BACKUP_MIRROR_DIR
        if not mirror_root:
            self.mirror_ok = None
            return
        root = Path(mirror_root)
        try:
            if not root.is_dir():
                raise RuntimeError("espelho_indisponivel")
            dest_dir = root / path.parent.name
            dest_dir.mkdir(parents=True, exist_ok=True)
            mirrored = dest_dir / path.name
            shutil.copy2(path, mirrored)
            sidecar = path.with_name(path.name + ".sha256")
            mirrored_sidecar = dest_dir / sidecar.name
            shutil.copy2(sidecar, mirrored_sidecar)
            expected = (sidecar.read_text(encoding="utf-8").split() or [""])[0]
            if sha256_file(mirrored) != expected:
                raise RuntimeError("espelho_checksum_invalido")
            self.mirror_ok = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("falha no espelho de backup: %s", exc)
            self.mirror_ok = False
            self.last_error = str(exc)

    async def _interval_loop(self) -> None:
        interval_s = max(1.0, settings.BACKUP_INTERVAL_MIN * 60)
        while True:
            await asyncio.sleep(interval_s)
            for event_id in list(self._dirty):
                await self.backup_now(event_id)

    async def start(self) -> None:
        if not self.enabled:
            logger.info("backup continuo desabilitado (banco em memoria)")
            return
        if self._interval_task is not None and not self._interval_task.done():
            return
        self._interval_task = asyncio.create_task(self._interval_loop())

    async def stop(self) -> None:
        tasks = list(self._debounce.values())
        if self._interval_task is not None:
            tasks.append(self._interval_task)
            self._interval_task = None
        for task in tasks:
            try:
                task.cancel()
            except RuntimeError:
                # Loop ja encerrado (ex.: shutdown do TestClient).
                pass
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, RuntimeError):
                pass
            except Exception:  # noqa: BLE001
                pass
        self._debounce.clear()

    def status(self) -> dict:
        mirror_enabled = bool(settings.BACKUP_MIRROR_DIR)
        mirror_ok = self.mirror_ok
        if (
            mirror_enabled
            and mirror_ok is None
            and not Path(settings.BACKUP_MIRROR_DIR).is_dir()
        ):
            # Espelho configurado mas ausente (pendrive nao montado).
            mirror_ok = False
        return {
            "last_backup_at": self.last_backup_at,
            "last_error": self.last_error,
            "mirror_enabled": mirror_enabled,
            "mirror_ok": mirror_ok if mirror_enabled else None,
        }


backup_service = BackupService()
