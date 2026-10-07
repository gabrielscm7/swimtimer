"""Valida a migração 0002 (unicidade de lap_number) em banco com duplicatas."""
import sqlite3
import uuid

import pytest
from alembic import command
from alembic.config import Config

from app.config import BACKEND_DIR, settings


def _alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def _insert_lap(con, lane_id, lap_number, recorded_at):
    con.execute(
        "INSERT INTO lap_event (id, lane_id, lap_number, recorded_at, is_undo) "
        "VALUES (?, ?, ?, ?, 0)",
        (str(uuid.uuid4()), lane_id, lap_number, recorded_at),
    )


def test_migration_dedupes_lap_numbers(tmp_path, monkeypatch):
    db = tmp_path / "mig.db"
    monkeypatch.setattr(
        settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}"
    )
    config = _alembic_config()

    command.upgrade(config, "0001_event_heat_refactor")

    con = sqlite3.connect(db)
    # Duas voltas com o mesmo lap_number na mesma raia (cenário da corrida).
    _insert_lap(con, "lane-x", 1, 1.0)
    _insert_lap(con, "lane-x", 3, 2.0)
    _insert_lap(con, "lane-x", 3, 3.0)
    con.commit()
    con.close()

    command.upgrade(config, "head")

    con = sqlite3.connect(db)
    numbers = [
        row[0]
        for row in con.execute(
            "SELECT lap_number FROM lap_event WHERE lane_id='lane-x' "
            "ORDER BY recorded_at"
        )
    ]
    assert numbers == [1, 2, 3], f"renumeração incorreta: {numbers}"

    # A constraint única deve bloquear novas duplicatas.
    duplicate = False
    try:
        _insert_lap(con, "lane-x", 3, 4.0)
        con.commit()
    except sqlite3.IntegrityError:
        duplicate = True
    finally:
        con.close()
    assert duplicate, "constraint única não foi aplicada"


def test_migration_fixes_dangling_lane_fk(tmp_path, monkeypatch):
    """lap_event legado apontava FK para a tabela 'lane' (removida em 0001)."""
    db = tmp_path / "legacy.db"
    monkeypatch.setattr(
        settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}"
    )
    config = _alembic_config()

    command.upgrade(config, "0001_event_heat_refactor")

    con = sqlite3.connect(db)
    con.execute("DROP INDEX IF EXISTS ix_lap_event_lane_recorded")
    con.execute("ALTER TABLE lap_event RENAME TO lap_event_new")
    con.execute("CREATE TABLE lane (id VARCHAR PRIMARY KEY)")
    con.execute(
        "CREATE TABLE lap_event ("
        "id VARCHAR NOT NULL, lane_id VARCHAR NOT NULL, "
        "lap_number INTEGER NOT NULL, recorded_at FLOAT NOT NULL, "
        "is_undo BOOLEAN NOT NULL, PRIMARY KEY (id), "
        "FOREIGN KEY(lane_id) REFERENCES lane (id))"
    )
    con.execute("DROP TABLE lap_event_new")
    con.execute("DROP TABLE lane")
    con.commit()
    con.close()

    command.upgrade(config, "head")

    con = sqlite3.connect(db)
    sql = con.execute(
        "SELECT sql FROM sqlite_master WHERE name='lap_event'"
    ).fetchone()[0]
    assert "REFERENCES heat_lane" in sql
    assert "REFERENCES lane " not in sql

    con.execute("PRAGMA foreign_keys=ON")
    con.execute(
        "INSERT INTO event (id, name, pool_length_m, status, created_at) "
        "VALUES ('e1', 'E', 25, 'draft', 0)"
    )
    con.execute(
        "INSERT INTO heat (id, event_id, name, order_num, heat_type, status) "
        "VALUES ('h1', 'e1', 'H', 1, 'maratona', 'scheduled')"
    )
    con.execute(
        "INSERT INTO heat_lane (id, heat_id, lane_number, status) "
        "VALUES ('l1', 'h1', 1, 'active')"
    )
    con.execute(
        "INSERT INTO lap_event (id, lane_id, lap_number, recorded_at, is_undo) "
        "VALUES ('x', 'l1', 1, 1.0, 0)"
    )
    con.commit()
    con.close()


def test_migration_fresh_db_has_unique_constraint(tmp_path, monkeypatch):
    db = tmp_path / "fresh.db"
    monkeypatch.setattr(
        settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}"
    )
    config = _alembic_config()

    command.upgrade(config, "head")

    con = sqlite3.connect(db)
    tables = {
        row[0]
        for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"event", "heat", "heat_lane", "lap_event"} <= tables
    con.close()
