import asyncio
from collections.abc import AsyncGenerator

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from .config import BACKEND_DIR, settings


class Base(DeclarativeBase):
    pass


_engine_kwargs: dict = {"echo": False, "future": True}
if ":memory:" in settings.DATABASE_URL:
    _engine_kwargs["poolclass"] = StaticPool
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs["connect_args"] = {"timeout": 30}

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


def _alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option(
        "script_location", str(BACKEND_DIR / "migrations")
    )
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    return config


def _upgrade() -> None:
    command.upgrade(_alembic_config(), "head")


async def init_db() -> None:
    from . import models  # noqa: F401  # garante o registro dos modelos

    if ":memory:" in settings.DATABASE_URL:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return

    await asyncio.to_thread(_upgrade)
