"""Testes da migracao 0003 (Prova/heat.prova_id) e 0004 (team.logo_url)."""
import sqlite3

import pytest
from alembic import command
from alembic.config import Config

from app.config import BACKEND_DIR, settings


def _alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def _seed_legacy(db) -> None:
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute(
        "INSERT INTO event (id, name, pool_length_m, status, created_at) "
        "VALUES ('e1', 'Evento', 25, 'finished', 1.0)"
    )
    con.execute(
        "INSERT INTO team (id, event_id, name) VALUES ('t1', 'e1', 'Equipe A')"
    )
    con.execute(
        "INSERT INTO heat (id, event_id, name, order_num, heat_type, distance_m, "
        "status, started_at, finished_at) "
        "VALUES ('h1', 'e1', '100 Livres', 1, 'bateria', 100, 'finished', 10.0, 20.0)"
    )
    con.execute(
        "INSERT INTO heat (id, event_id, name, order_num, heat_type, distance_m, "
        "status, started_at, finished_at) "
        "VALUES ('h2', 'e1', '100 Livres - Bateria 2', 2, 'bateria', 100, "
        "'finished', 30.0, 40.0)"
    )
    con.execute(
        "INSERT INTO heat_lane (id, heat_id, lane_number, participant_name, "
        "team_id, status, finish_at, race_time_ms) "
        "VALUES ('l1', 'h1', 4, 'Ana', 't1', 'finished', 70.0, 59800)"
    )
    con.execute(
        "INSERT INTO heat_lane (id, heat_id, lane_number, participant_name, "
        "team_id, status, finish_at, race_time_ms) "
        "VALUES ('l2', 'h2', 5, 'Bia', 't1', 'finished', 80.0, 60200)"
    )
    con.execute(
        "INSERT INTO lap_event (id, lane_id, lap_number, recorded_at, is_undo) "
        "VALUES ('lap1', 'l1', 1, 65.0, 0)"
    )
    con.commit()
    con.close()


def test_upgrade_creates_prova_per_legacy_heat(tmp_path, monkeypatch):
    db = tmp_path / "legacy_prova.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    config = _alembic_config()

    command.upgrade(config, "0002_lap_unique")
    _seed_legacy(db)
    command.upgrade(config, "head")

    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys=ON")
    provas = con.execute(
        "SELECT event_id, name, order_num, consolidate_results, "
        "classification_criterion, status FROM prova ORDER BY order_num"
    ).fetchall()
    assert len(provas) == 2
    assert provas[0][0] == "e1"
    assert provas[0][3] == 1
    assert provas[0][4] == "lowest_time"
    assert provas[0][5] == "finished"
    assert [row[2] for row in provas] == [1, 2]

    heat_rows = con.execute(
        "SELECT id, event_id, prova_id, order_num FROM heat ORDER BY id"
    ).fetchall()
    assert all(row[2] for row in heat_rows)
    assert {row[0] for row in heat_rows} == {"h1", "h2"}
    assert all(row[1] == "e1" for row in heat_rows)

    lanes = con.execute(
        "SELECT id, heat_id, lane_number, participant_name, team_id, "
        "race_time_ms FROM heat_lane ORDER BY id"
    ).fetchall()
    assert lanes == [
        ("l1", "h1", 4, "Ana", "t1", 59800),
        ("l2", "h2", 5, "Bia", "t1", 60200),
    ]
    laps = con.execute(
        "SELECT lane_id, lap_number, recorded_at FROM lap_event"
    ).fetchall()
    assert laps == [("l1", 1, 65.0)]

    fk_targets = {
        row[2] for row in con.execute("PRAGMA foreign_key_list(heat)").fetchall()
    }
    assert "prova" in fk_targets

    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO heat (id, event_id, name, order_num, heat_type, status) "
            "VALUES ('hx', 'e1', 'X', 1, 'bateria', 'scheduled')"
        )
    con.rollback()

    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO heat (id, event_id, prova_id, name, order_num, "
            "heat_type, status) VALUES ('hy', 'e1', ?, 'Y', 1, 'bateria', "
            "'scheduled')",
            (heat_rows[0][2],),
        )
    con.rollback()

    logo_columns = [row[1] for row in con.execute("PRAGMA table_info(team)")]
    assert "logo_url" in logo_columns
    con.close()


def test_downgrade_restores_heat_order_and_data(tmp_path, monkeypatch):
    db = tmp_path / "legacy_down.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    config = _alembic_config()

    command.upgrade(config, "0002_lap_unique")
    _seed_legacy(db)
    command.upgrade(config, "head")
    command.downgrade(config, "0002_lap_unique")

    con = sqlite3.connect(db)
    tables = {
        row[0]
        for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "prova" not in tables
    columns = [row[1] for row in con.execute("PRAGMA table_info(heat)")]
    assert "prova_id" not in columns
    orders = dict(
        con.execute("SELECT id, order_num FROM heat ORDER BY id").fetchall()
    )
    assert orders == {"h1": 1, "h2": 2}
    assert con.execute("SELECT COUNT(*) FROM heat_lane").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM lap_event").fetchone()[0] == 1
    con.close()


def test_fresh_db_upgrade_creates_prova_schema(tmp_path, monkeypatch):
    db = tmp_path / "fresh_prova.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    config = _alembic_config()

    command.upgrade(config, "head")

    con = sqlite3.connect(db)
    tables = {
        row[0]
        for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"event", "prova", "heat", "heat_lane", "lap_event", "team"} <= tables
    heat_columns = [row[1] for row in con.execute("PRAGMA table_info(heat)")]
    assert "prova_id" in heat_columns
    team_columns = [row[1] for row in con.execute("PRAGMA table_info(team)")]
    assert "logo_url" in team_columns
    con.close()
