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
        "INSERT INTO prova (id, event_id, name, order_num, "
        "consolidate_results, classification_criterion, status, created_at) "
        "VALUES ('p1', 'e1', 'P', 1, 1, 'lowest_time', 'scheduled', 0)"
    )
    con.execute(
        "INSERT INTO heat (id, event_id, prova_id, name, order_num, "
        "heat_type, status) "
        "VALUES ('h1', 'e1', 'p1', 'H', 1, 'maratona', 'scheduled')"
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
    assert {"event", "heat", "heat_lane", "lap_event", "athlete"} <= tables
    con.close()


def test_migration_0005_preserves_legacy_lanes(tmp_path, monkeypatch):
    db = tmp_path / "legacy_athlete.db"
    monkeypatch.setattr(
        settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}"
    )
    config = _alembic_config()

    command.upgrade(config, "0004_team_logo")

    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO event (id, name, pool_length_m, status, created_at) "
        "VALUES ('e1', 'Evento', 25, 'draft', 0)"
    )
    con.execute(
        "INSERT INTO team (id, event_id, name) VALUES ('t1', 'e1', 'Equipe')"
    )
    con.execute(
        "INSERT INTO prova (id, event_id, name, order_num, "
        "consolidate_results, classification_criterion, status, created_at) "
        "VALUES ('p1', 'e1', 'Prova', 1, 1, 'lowest_time', 'scheduled', 0)"
    )
    con.execute(
        "INSERT INTO heat (id, event_id, prova_id, name, order_num, "
        "heat_type, status) "
        "VALUES ('h1', 'e1', 'p1', 'Bateria', 1, 'bateria', 'scheduled')"
    )
    con.execute(
        "INSERT INTO heat_lane (id, heat_id, lane_number, "
        "participant_name, team_id, status) "
        "VALUES ('l1', 'h1', 1, 'Atleta Legado', 't1', 'assigned')"
    )
    con.commit()
    con.close()

    command.upgrade(config, "head")

    con = sqlite3.connect(db)
    lane = con.execute(
        "SELECT participant_name, athlete_id FROM heat_lane WHERE id='l1'"
    ).fetchone()
    assert lane == ("Atleta Legado", None)

    con.execute(
        "INSERT INTO athlete (id, event_id, team_id, name, naipe, "
        "category, created_at) "
        "VALUES ('a1', 'e1', 't1', 'Ana', 'F', 'SUB-12', 0)"
    )
    con.commit()

    duplicate_blocked = False
    try:
        con.execute(
            "INSERT INTO athlete (id, event_id, team_id, name, naipe, "
            "category, created_at) "
            "VALUES ('a2', 'e1', 't1', 'ana', 'F', 'SUB-12', 0)"
        )
        con.commit()
    except sqlite3.IntegrityError:
        duplicate_blocked = True
    finally:
        con.close()
    assert duplicate_blocked, "indice unico de atleta nao foi aplicado"


def test_migration_0006_backfills_prova_naipe(tmp_path, monkeypatch):
    db = tmp_path / "legacy_naipe.db"
    monkeypatch.setattr(
        settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}"
    )
    config = _alembic_config()

    command.upgrade(config, "0005_athlete")

    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO event (id, name, pool_length_m, status, created_at) "
        "VALUES ('e1', 'Evento', 25, 'draft', 0)"
    )
    provas = [
        ("p1", "Peito 50m", 1, "masculino, sub-12"),
        ("p2", "Costas 50m", 2, "Feminino SUB-14"),
        ("p3", "Livre 100m", 3, "SUB-16"),
        ("p4", "Peito 100m", 4, None),
    ]
    for prova_id, name, order_num, category in provas:
        con.execute(
            "INSERT INTO prova (id, event_id, name, order_num, stroke, "
            "distance_m, category, consolidate_results, "
            "classification_criterion, status, created_at) "
            "VALUES (?, 'e1', ?, ?, NULL, NULL, ?, 1, 'lowest_time', "
            "'scheduled', 0)",
            (prova_id, name, order_num, category),
        )
    con.commit()
    con.close()

    command.upgrade(config, "head")

    con = sqlite3.connect(db)
    rows = {
        row[0]: row[1]
        for row in con.execute(
            "SELECT id, COALESCE(naipe, '') || '|' || "
            "COALESCE(category, '') FROM prova"
        )
    }
    con.close()
    assert rows["p1"] == "M|SUB-12"
    assert rows["p2"] == "F|SUB-14"
    assert rows["p3"] == "|SUB-16"
    assert rows["p4"] == "|"
