import asyncio
import sqlite3

import pytest

from app.config import settings
from app.services import backup as backup_module
from app.services.backup import BackupService, retention_candidates, sha256_file


def _make_db(path) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT)")
    con.execute("INSERT INTO sample (name) VALUES ('ok')")
    con.commit()
    con.close()


def _configure(tmp_path, monkeypatch):
    source = tmp_path / "swimtimer.db"
    _make_db(source)
    monkeypatch.setattr(
        settings, "DATABASE_URL", f"sqlite+aiosqlite:///{source}"
    )
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "BACKUP_MIRROR_DIR", "")
    return source


@pytest.mark.asyncio
async def test_backup_is_valid_and_restorable(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    service = BackupService()

    path = await service.backup_now("evt-1")
    assert path is not None and path.is_file()
    sidecar = path.with_name(path.name + ".sha256")
    assert sidecar.is_file()
    assert sha256_file(path) in sidecar.read_text(encoding="utf-8")
    assert service.last_backup_at is not None
    assert service.last_error is None

    con = sqlite3.connect(path)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("SELECT name FROM sample").fetchone()[0] == "ok"
    con.close()

    # Restauracao: copia o backup para outro caminho e reabre.
    restored = tmp_path / "restored.db"
    source = sqlite3.connect(path)
    target = sqlite3.connect(restored)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    con = sqlite3.connect(restored)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 1
    con.close()


def test_retention_keeps_12_recent_hourly_and_final(tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir()
    files = []

    def touch(name):
        path = folder / name
        path.write_bytes(b"x")
        files.append(path)
        return path

    for index in range(12):
        touch(f"swimtimer_20260101_100000_{index:06d}.db")
    for index in range(3):
        touch(f"swimtimer_20260101_090000_{index:06d}.db")
    for index in range(2):
        touch(f"swimtimer_20260101_080000_{index:06d}.db")
    final = touch("swimtimer_20260101_070000_000000_final.db")

    removed = set(retention_candidates(files))
    assert final not in removed
    assert sorted(path.name for path in removed) == [
        "swimtimer_20260101_080000_000000.db",
        "swimtimer_20260101_090000_000000.db",
        "swimtimer_20260101_090000_000001.db",
    ]

    for path in files:
        path.with_name(path.name + ".sha256").write_text("hash\n")
    backup_module.prune_backups(folder)
    remaining = {path.name for path in folder.glob("*.db")}
    assert final.name in remaining
    assert len(remaining) == 15
    assert len(list(folder.glob("*.sha256"))) == 15


@pytest.mark.asyncio
async def test_mirror_copy_and_verification(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    monkeypatch.setattr(settings, "BACKUP_MIRROR_DIR", str(mirror))

    service = BackupService()
    path = await service.backup_now("evt-1")
    assert path is not None
    mirrored = mirror / "evt-1" / path.name
    assert mirrored.is_file()
    assert sha256_file(mirrored) == sha256_file(path)
    assert service.mirror_ok is True

    mirrored.write_bytes(b"corrompido")
    path.with_name(path.name + ".sha256").write_text("0" * 64 + "\n")
    service._mirror(path)
    assert service.mirror_ok is False
    assert "checksum" in (service.last_error or "")


@pytest.mark.asyncio
async def test_finish_debounce_coalesces_backups(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(backup_module, "FINISH_DEBOUNCE_S", 0.01)
    service = BackupService()
    calls = []

    async def fake_backup(event_id, *, kind="auto"):
        calls.append(event_id)
        return None

    service.backup_now = fake_backup  # type: ignore[method-assign]
    service.schedule_after_finish("evt-1")
    service.schedule_after_finish("evt-1")
    await asyncio.sleep(0.05)
    await service.stop()

    assert calls == ["evt-1"]


@pytest.mark.asyncio
async def test_status_flags_missing_mirror(tmp_path, monkeypatch):
    monkeypatch.setattr(
        settings, "BACKUP_MIRROR_DIR", str(tmp_path / "pendrive-ausente")
    )
    service = BackupService()
    status = service.status()
    assert status["mirror_enabled"] is True
    assert status["mirror_ok"] is False


@pytest.mark.asyncio
async def test_status_exposes_backup_fields(client):
    response = await client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert "last_backup_at" in body
    assert "last_error" in body
    assert "mirror_ok" in body
