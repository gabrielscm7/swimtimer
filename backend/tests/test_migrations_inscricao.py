"""Testes das migracoes 0008 (prova.mixed_ranking) e 0009 (registration_code)."""
import sqlite3

from alembic import command
from alembic.config import Config

from app.config import BACKEND_DIR, settings


def _alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def test_mixed_ranking_added_with_default_both(tmp_path, monkeypatch):
    db = tmp_path / "mixed_ranking.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    command.upgrade(_alembic_config(), "head")

    con = sqlite3.connect(db)
    columns = [row[1] for row in con.execute("PRAGMA table_info(prova)")]
    assert "mixed_ranking" in columns
    con.execute(
        "INSERT INTO event (id, name, pool_length_m, status, created_at) "
        "VALUES ('e1', 'Evento', 25, 'draft', 1.0)"
    )
    con.execute(
        "INSERT INTO prova (id, event_id, name, order_num, status, created_at, "
        "consolidate_results, classification_criterion) "
        "VALUES ('p1', 'e1', 'Prova', 1, 'scheduled', 1.0, 1, 'lowest_time')"
    )
    value = con.execute(
        "SELECT mixed_ranking FROM prova WHERE id = 'p1'"
    ).fetchone()[0]
    assert value == "both"
    con.commit()
    con.close()


def test_mixed_ranking_downgrade_removes_column(tmp_path, monkeypatch):
    db = tmp_path / "mixed_ranking_down.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    config = _alembic_config()
    command.upgrade(config, "head")
    command.downgrade(config, "0007_time_ack_idempotencia")

    con = sqlite3.connect(db)
    columns = [row[1] for row in con.execute("PRAGMA table_info(prova)")]
    assert "mixed_ranking" not in columns
    con.close()


def test_registration_code_and_new_unique_index(tmp_path, monkeypatch):
    db = tmp_path / "registration.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    command.upgrade(_alembic_config(), "head")

    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys=ON")
    columns = [row[1] for row in con.execute("PRAGMA table_info(athlete)")]
    assert "registration_code" in columns
    indexes = {
        row[1] for row in con.execute("PRAGMA index_list('athlete')")
    }
    assert "uq_athlete_event_name_team_code" in indexes
    assert "uq_athlete_event_name_team" not in indexes

    con.execute(
        "INSERT INTO event (id, name, pool_length_m, status, created_at) "
        "VALUES ('e1', 'Evento', 25, 'draft', 1.0)"
    )
    con.execute(
        "INSERT INTO team (id, event_id, name) VALUES ('t1', 'e1', 'Leões')"
    )

    def insert(code: str) -> None:
        con.execute(
            "INSERT INTO athlete (id, event_id, team_id, name, naipe, "
            "created_at, registration_code) "
            "VALUES (?, 'e1', 't1', 'João Silva', 'M', 1.0, ?)",
            (f"a-{code}", code),
        )

    insert("A-001")
    insert("A-002")  # homonimos da mesma equipe com codigos distintos
    try:
        insert("A-001")
        raise AssertionError("codigo duplicado deveria violar a unicidade")
    except sqlite3.IntegrityError:
        con.rollback()
    con.close()


def test_registration_code_downgrade_restores_old_index(tmp_path, monkeypatch):
    db = tmp_path / "registration_down.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    config = _alembic_config()
    command.upgrade(config, "head")
    command.downgrade(config, "0008_prova_mixed_ranking")

    con = sqlite3.connect(db)
    columns = [row[1] for row in con.execute("PRAGMA table_info(athlete)")]
    assert "registration_code" not in columns
    indexes = {
        row[1] for row in con.execute("PRAGMA index_list('athlete')")
    }
    assert "uq_athlete_event_name_team" in indexes
    assert "uq_athlete_event_name_team_code" not in indexes
    con.close()
