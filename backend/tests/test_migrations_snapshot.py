"""Migracoes 0010/0011: snapshot imutavel (triggers) e settings publicas."""

import asyncio
import sqlite3
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import BACKEND_DIR, settings
from app.services import snapshots


def _alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def _insert_snapshot(
    con: sqlite3.Connection,
    *,
    event_id: str = "evt-1",
    heat_id: str = "heat-1",
    payload_json: str = '{"event":{"id":"evt-1"},"heat":{"id":"heat-1"}}',
    prev_hash: str | None = None,
    hash_value: str | None = None,
) -> str:
    snapshot_id = str(uuid.uuid4())
    if prev_hash is None:
        prev_hash = snapshots.GENESIS
    if hash_value is None:
        hash_value = snapshots.hash_snapshot(prev_hash, payload_json)
    con.execute(
        "INSERT INTO result_snapshot (id, event_id, prova_id, heat_id, revision, "
        "status, reason, created_at, created_by, created_by_ip, payload_json, "
        "prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            snapshot_id,
            event_id,
            "prova-1",
            heat_id,
            1,
            "provisional",
            "finish",
            1.0,
            "system",
            None,
            payload_json,
            prev_hash,
            hash_value,
        ),
    )
    return snapshot_id


def test_result_snapshot_is_append_only(tmp_path, monkeypatch):
    db = tmp_path / "snap.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    command.upgrade(_alembic_config(), "head")

    con = sqlite3.connect(db)
    _insert_snapshot(con)
    con.commit()

    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE result_snapshot SET status='official'")
    con.rollback()

    with pytest.raises(sqlite3.IntegrityError):
        con.execute("DELETE FROM result_snapshot")
    con.rollback()

    count = con.execute("SELECT COUNT(*) FROM result_snapshot").fetchone()[0]
    con.close()
    assert count == 1


def test_verify_detects_tampered_hash(tmp_path, monkeypatch):
    db = tmp_path / "snap_verify.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    command.upgrade(_alembic_config(), "head")

    con = sqlite3.connect(db)
    first = _insert_snapshot(con, heat_id="heat-1")
    second_payload = (
        '{"event":{"id":"evt-1"},"heat":{"id":"heat-2"}}'
    )
    second = _insert_snapshot(
        con,
        heat_id="heat-2",
        payload_json=second_payload,
        prev_hash=snapshots.hash_snapshot(
            snapshots.GENESIS,
            '{"event":{"id":"evt-1"},"heat":{"id":"heat-1"}}',
        ),
        hash_value="0" * 64,
    )
    con.commit()
    con.close()

    async def _verify() -> dict:
        engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
        try:
            async with AsyncSession(engine) as session:
                return await snapshots.verify_event(session, "evt-1")
        finally:
            await engine.dispose()

    result = asyncio.run(_verify())
    assert result["ok"] is False
    assert result["broken_id"] == second
    assert result["reason"] == "hash_invalido"
    assert first != second


def test_event_public_settings_columns(tmp_path, monkeypatch):
    db = tmp_path / "settings.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    config = _alembic_config()
    command.upgrade(config, "0010_result_snapshot")

    con = sqlite3.connect(db)
    event_id = str(uuid.uuid4())
    con.execute(
        "INSERT INTO event (id, name, pool_length_m, status, created_at) "
        "VALUES (?, 'Evento', 25, 'draft', 1.0)",
        (event_id,),
    )
    con.commit()
    con.close()

    command.upgrade(config, "head")

    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT public_results_enabled, public_name_mode FROM event WHERE id=?",
        (event_id,),
    ).fetchone()
    con.close()
    assert row == (1, "full")

    command.downgrade(config, "0010_result_snapshot")
    con = sqlite3.connect(db)
    columns = {
        item[1] for item in con.execute("PRAGMA table_info(event)").fetchall()
    }
    con.close()
    assert "public_results_enabled" not in columns
    assert "public_name_mode" not in columns
