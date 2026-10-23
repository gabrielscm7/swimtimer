"""Migracao 0015: bateria como unidade de cadastro e prova como grupo."""
import sqlite3

from alembic import command
from alembic.config import Config

from app.config import BACKEND_DIR, settings

BASE_REVISION = "0014_prova_format_definition"
NEW_REVISION = "0015_bateria_unidade_cadastro"


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
        ("p_livre", 1, "bateria", "livre", 25, "M", "ABERTA"),
        ("p_sub", 2, "bateria", "crawl", 50, "F", "SUB-12"),
        ("p_dup_a", 3, "bateria", "peito", 100, "MISTO", "MIRIM"),
        ("p_dup_b", 4, "bateria", "peito", 100, "MISTO", "MIRIM"),
        ("p_dup_c", 5, "bateria", "peito", 100, "MISTO", "MIRIM"),
        ("p_legacy", 6, "bateria", None, None, None, None),
        ("p_mar", 7, "maratona", "livre", None, "F", "ABERTA"),
    ]
    for prova_id, order, fmt, stroke, distance, naipe, category in provas:
        con.execute(
            "INSERT INTO prova (id, event_id, name, order_num, format, stroke, "
            "distance_m, naipe, category, consolidate_results, "
            "classification_criterion, status, created_at) "
            "VALUES (?, 'e1', ?, ?, ?, ?, ?, ?, ?, 1, 'lowest_time', "
            "'scheduled', 0)",
            (
                prova_id,
                prova_id,
                order,
                fmt,
                stroke,
                distance,
                naipe,
                category,
            ),
        )
    heats = [
        ("h1", "p_livre", "bateria", 25, 1, None),
        ("h2", "p_livre", "bateria", 25, 2, None),
        ("h3", "p_sub", "bateria", 50, 1, None),
        ("h4", "p_dup_a", "bateria", 100, 1, None),
        ("h5", "p_dup_b", "bateria", 100, 1, None),
        ("h6", "p_dup_c", "bateria", 100, 1, None),
        ("h7", "p_legacy", "bateria", None, 1, None),
        ("h8", "p_mar", "maratona", None, 1, 7200),
    ]
    for heat_id, prova_id, heat_type, distance, order, duration in heats:
        con.execute(
            "INSERT INTO heat (id, event_id, prova_id, name, order_num, "
            "heat_type, distance_m, duration_s, status) "
            "VALUES (?, 'e1', ?, ?, ?, ?, ?, ?, 'scheduled')",
            (
                heat_id,
                prova_id,
                heat_id,
                order,
                heat_type,
                distance,
                duration,
            ),
        )
    for lane_number in range(1, 5):
        con.execute(
            "INSERT INTO heat_lane (id, heat_id, lane_number, status) "
            "VALUES (?, 'h2', ?, 'assigned')",
            (f"l2-{lane_number}", lane_number),
        )
    for lane_number in range(1, 3):
        con.execute(
            "INSERT INTO heat_lane (id, heat_id, lane_number, status) "
            "VALUES (?, 'h3', ?, 'assigned')",
            (f"l3-{lane_number}", lane_number),
        )
    # snapshot em p_dup_b: a prova duplicada deve ser preservada (historico),
    # mas fica sem baterias apos a fusao.
    con.execute(
        "INSERT INTO result_snapshot (id, event_id, prova_id, heat_id, "
        "revision, status, reason, created_at, created_by, payload_json, "
        "prev_hash, hash) VALUES ('s1', 'e1', 'p_dup_b', 'h5', 1, "
        "'provisional', 'finish', 0, 'system', '{}', 'genesis', 'hash')"
    )
    con.execute(
        "INSERT INTO athlete (id, event_id, name, naipe, category, created_at) "
        "VALUES ('a1', 'e1', 'Atleta Um', 'M', 'SUB-12', 0)"
    )
    con.execute(
        "INSERT INTO athlete (id, event_id, name, naipe, category, created_at) "
        "VALUES ('a2', 'e1', 'Atleta Dois', 'F', 'mirim', 0)"
    )
    con.commit()
    con.close()


def _upgrade(tmp_path, monkeypatch, name="bateria.db"):
    db = tmp_path / name
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    config = _alembic_config()
    command.upgrade(config, BASE_REVISION)
    _seed(db)
    command.upgrade(config, "head")
    return db, config


def test_upgrade_copia_atributos_e_recalcula_ordem(tmp_path, monkeypatch):
    db, _config = _upgrade(tmp_path, monkeypatch)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    heats = {
        row["id"]: dict(row)
        for row in con.execute(
            "SELECT id, prova_id, order_num, heat_type, stroke, naipe, "
            "category, lane_count, classify_alone, distance_m FROM heat"
        )
    }
    provas = {
        row["id"]: dict(row)
        for row in con.execute(
            "SELECT id, order_num, name, category FROM prova"
        )
    }
    events = dict(
        con.execute("SELECT id, default_lane_count FROM event").fetchone()
    )
    athletes = {
        row[0]: row[1]
        for row in con.execute("SELECT id, category FROM athlete")
    }
    con.close()

    assert events["default_lane_count"] == 3
    assert heats["h1"]["stroke"] == "livre"
    assert heats["h1"]["naipe"] == "M"
    assert heats["h1"]["category"] == "livre"
    assert heats["h2"]["lane_count"] == 4
    assert heats["h3"]["lane_count"] == 2
    assert heats["h1"]["lane_count"] == 3
    assert heats["h7"]["stroke"] is None
    assert heats["h7"]["category"] is None
    assert heats["h8"]["heat_type"] == "maratona"
    assert heats["h8"]["distance_m"] is None

    assert heats["h4"]["prova_id"] == "p_dup_a"
    assert heats["h5"]["prova_id"] == "p_dup_a"
    assert heats["h6"]["prova_id"] == "p_dup_a"
    assert "p_dup_b" in provas  # preservada por ter snapshot
    assert "p_dup_c" not in provas  # sem snapshot: removida

    assert [heats[f"h{index}"]["order_num"] for index in range(1, 9)] == list(
        range(1, 9)
    )
    assert provas["p_livre"]["name"] == "25 m Livre · Masculino"
    assert provas["p_sub"]["name"] == "50 m Crawl · Feminino"
    assert provas["p_dup_a"]["name"] == "100 m Peito · Misto · Mirim"
    assert provas["p_mar"]["name"] == "Maratona 2 h · Livre · Feminino"
    assert provas["p_livre"]["order_num"] == 1
    assert provas["p_sub"]["order_num"] == 2
    assert provas["p_dup_a"]["order_num"] == 3

    assert athletes["a1"] == "livre"
    assert athletes["a2"] == "mirim"


def test_upgrade_remove_colunas_operacionais_e_cria_indice(tmp_path, monkeypatch):
    db, _config = _upgrade(tmp_path, monkeypatch, name="schema.db")
    prova_columns = _columns(db, "prova")
    heat_columns = _columns(db, "heat")
    assert "name_override" not in prova_columns
    assert "mixed_ranking" not in prova_columns
    assert "legacy_incomplete" not in prova_columns
    assert "consolidate_results" not in prova_columns
    assert {"stroke", "naipe", "category", "lane_count", "classify_alone"} <= set(
        heat_columns
    )
    con = sqlite3.connect(db)
    indexes = {
        row[0]
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'heat'"
        )
    }
    con.close()
    assert "uq_heat_event_order" in indexes
    assert "uq_heat_prova_order" not in indexes


def test_downgrade_restaura_estrutura_preservando_dados(tmp_path, monkeypatch):
    db, config = _upgrade(tmp_path, monkeypatch, name="down.db")
    command.downgrade(config, BASE_REVISION)

    prova_columns = _columns(db, "prova")
    heat_columns = _columns(db, "heat")
    assert {
        "name_override",
        "mixed_ranking",
        "legacy_incomplete",
        "consolidate_results",
    } <= set(prova_columns)
    assert not (
        {"stroke", "naipe", "category", "lane_count", "classify_alone"}
        & set(heat_columns)
    )
    assert "default_lane_count" not in _columns(db, "event")

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    order = {
        row["id"]: row["order_num"]
        for row in con.execute("SELECT id, order_num FROM heat")
    }
    athletes = {
        row[0]: row[1]
        for row in con.execute("SELECT id, category FROM athlete")
    }
    indexes = {
        row[0]
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'heat'"
        )
    }
    snapshots = con.execute("SELECT COUNT(*) FROM result_snapshot").fetchone()[0]
    con.close()

    assert order["h1"] == 1
    assert order["h2"] == 2
    assert athletes["a1"] == "ABERTA"
    assert athletes["a2"] == "MIRIM"
    assert "uq_heat_prova_order" in indexes
    assert "uq_heat_event_order" not in indexes
    assert snapshots == 1
