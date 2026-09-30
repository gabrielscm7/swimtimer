from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from .config import settings


class Base(DeclarativeBase):
    pass


_engine_kwargs: dict = {"echo": False, "future": True}
if ":memory:" in settings.DATABASE_URL:
    _engine_kwargs["poolclass"] = StaticPool
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


# Colunas adicionadas pelo modo "Bateria Cronometrada". Cada entrada é
# (tabela, coluna, definição DDL). A migração é idempotente: só executa o
# ALTER TABLE quando a coluna ainda não existe.
_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("competition", "event_type", "TEXT NOT NULL DEFAULT 'maratona'"),
    ("competition", "distance_m", "INTEGER DEFAULT 25"),
    ("lane", "participant_name", "TEXT"),
    ("lane", "finish_at", "REAL"),
    ("lane", "race_time_ms", "INTEGER"),
)


def _apply_migrations(conn) -> None:
    from sqlalchemy import inspect

    inspector = inspect(conn)
    for table, column, ddl in _MIGRATIONS:
        if not inspector.has_table(table):
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        if column in existing:
            continue
        conn.exec_driver_sql(
            f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'
        )


async def init_db() -> None:
    from . import models  # noqa: F401  # garante o registro dos modelos

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_migrations)
