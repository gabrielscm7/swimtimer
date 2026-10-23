"""Migracao 0014: formato da prova, legado incompleto e name_override."""
import sqlite3

from alembic import command
from alembic.config import Config

from app.config import BACKEND_DIR, settings


def _alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def _columns(db, table):
    con = sqlite3.connect(db)
    try:
        return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    finally:
        con.close()


def _seed(db):
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO event (id, name, pool_length_m, status, created_at) "
        "VALUES ('e1', 'Evento', 25, 'draft', 0)"
    )
    provas = [
        ("p_bat", 1, "livre", 100, "M", "SUB-12"),
        ("p_mar", 2, None, None, None, None),
        ("p_none", 3, "costas", 50, "F", "ABERTA"),
        ("p_inc", 4, None, 50, None, None),
        ("p_mix", 5, "peito", 100, "MISTO", "ABERTA"),
    ]
    for prova_id, order, stroke, distance, naipe, category in provas:
        con.execute(
            "INSERT INTO prova (id, event_id, name, order_num, stroke, "
            "distance_m, naipe, category, consolidate_results, "
            "classification_criterion, status, created_at) "
            "VALUES (?, 'e1', ?, ?, ?, ?, ?, ?, 1, 'lowest_time', "
            "'scheduled', 0)",
            (
                prova_id,
                prova_id,
                order,
                stroke,
                distance,
                naipe,
                category,
            ),
        )
    heats = [
        ("h_bat", "p_bat", "bateria", 100, 1),
        ("h_mar", "p_mar", "maratona", None, 1),
        ("h_inc", "p_inc", "bateria", 50, 1),
        ("h_mix_b", "p_mix", "bateria", 100, 1),
        ("h_mix_m", "p_mix", "maratona", None, 2),
    ]
    for heat_id, prova_id, heat_type, distance, order in heats:
        con.execute(
            "INSERT INTO heat (id, event_id, prova_id, name, order_num, "
            "heat_type, distance_m, status) "
            "VALUES (?, 'e1', ?, ?, ?, ?, ?, 'scheduled')",
            (heat_id, prova_id, heat_id, order, heat_type, distance),
        )
    con.commit()
    con.close()


def test_backfill_formato_e_legado_incompleto(tmp_path, monkeypatch):
    db = tmp_path / "prova_format.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    config = _alembic_config()

    command.upgrade(config, "0013_event_presentation")
    assert "format" not in _columns(db, "prova")
    _seed(db)

    command.upgrade(config, "0014_prova_format_definition")

    con = sqlite3.connect(db)
    rows = {
        row[0]: (row[1], row[2], row[3])
        for row in con.execute(
            "SELECT id, format, legacy_incomplete, name_override FROM prova"
        )
    }
    con.close()
    assert rows["p_bat"] == ("bateria", 0, 0)
    assert rows["p_mar"] == ("maratona", 1, 0)
    assert rows["p_none"] == ("bateria", 0, 0)
    assert rows["p_inc"] == ("bateria", 1, 0)
    assert rows["p_mix"] == ("bateria", 0, 0)


def test_downgrade_remove_colunas_preservando_dados(tmp_path, monkeypatch):
    db = tmp_path / "prova_format_down.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    config = _alembic_config()

    command.upgrade(config, "0013_event_presentation")
    _seed(db)
    command.upgrade(config, "0014_prova_format_definition")
    command.downgrade(config, "0013_event_presentation")

    columns = _columns(db, "prova")
    assert "format" not in columns
    assert "legacy_incomplete" not in columns
    assert "name_override" not in columns

    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM prova").fetchone()[0] == 5
    assert con.execute("SELECT COUNT(*) FROM heat").fetchone()[0] == 5
    con.close()
