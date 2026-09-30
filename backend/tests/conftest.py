import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.database import Base, get_db
from app.main import app


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    original_factory = main_module.AsyncSessionLocal
    app.dependency_overrides[get_db] = override_get_db
    main_module.AsyncSessionLocal = session_factory
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await main_module.timer.reset()
        app.dependency_overrides.clear()
        main_module.AsyncSessionLocal = original_factory
        await engine.dispose()


@pytest.fixture
def ws_client():
    with TestClient(app) as test_client:
        yield test_client


async def create_competition_with_lanes(
    client: AsyncClient,
    name: str = "Prova Teste",
    duration_s: int = 10800,
    meters_lap: int = 25,
) -> tuple[dict, list[dict]]:
    response = await client.post(
        "/api/competition",
        json={
            "name": name,
            "duration_s": duration_s,
            "meters_lap": meters_lap,
        },
    )
    assert response.status_code == 201, response.text
    competition = response.json()
    state = await client.get("/api/competition/current")
    assert state.status_code == 200
    lanes = state.json()["lanes"]
    return competition, lanes
