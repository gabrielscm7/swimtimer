"""Migracao do tema configuravel por evento."""
import sqlite3

from alembic import command
from alembic.config import Config

from app.config import BACKEND_DIR, settings


def _alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def _event_columns(db) -> set[str]:
    con = sqlite3.connect(db)
    try:
        return {row[1] for row in con.execute("PRAGMA table_info(event)")}
    finally:
        con.close()


def test_migration_adds_and_removes_theme_json(tmp_path, monkeypatch):
    db = tmp_path / "theme_migration.db"
    monkeypatch.setattr(
        settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db}"
    )
    config = _alembic_config()

    command.upgrade(config, "0011_event_public_settings")
    assert "theme_json" not in _event_columns(db)

    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO event (id, name, pool_length_m, status, created_at) "
        "VALUES ('e1', 'Evento', 25, 'draft', 0)"
    )
    con.commit()
    con.close()

    command.upgrade(config, "head")
    assert "theme_json" in _event_columns(db)

    con = sqlite3.connect(db)
    value = con.execute(
        "SELECT theme_json FROM event WHERE id='e1'"
    ).fetchone()[0]
    con.close()
    assert value is None

    command.downgrade(config, "0011_event_public_settings")
    assert "theme_json" not in _event_columns(db)
