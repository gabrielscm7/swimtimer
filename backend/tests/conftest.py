import atexit
import os
import tempfile

_db_fd, _DB_PATH = tempfile.mkstemp(suffix=".db", prefix="swimtimer_test_")
os.close(_db_fd)
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_DB_PATH}")


@atexit.register
def _cleanup_test_db() -> None:
    try:
        os.remove(_DB_PATH)
    except OSError:
        pass


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
    main_module.app.dependency_overrides[get_db] = override_get_db
    main_module.AsyncSessionLocal = session_factory
    try:
        transport = ASGITransport(app=main_module.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        main_module.app.dependency_overrides.clear()
        main_module.AsyncSessionLocal = original_factory
        await engine.dispose()


@pytest.fixture
def ws_client():
    with TestClient(main_module.app) as test_client:
        yield test_client


async def create_event(
    client: AsyncClient,
    name: str = "Evento Teste",
    pool_length_m: int = 25,
) -> dict:
    response = await client.post(
        "/api/events",
        json={"name": name, "pool_length_m": pool_length_m},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_team(
    client: AsyncClient,
    event_id: str,
    name: str = "Equipe A",
) -> dict:
    response = await client.post(
        f"/api/events/{event_id}/teams",
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_heat(
    client: AsyncClient,
    event_id: str,
    *,
    name: str = "Prova Teste",
    heat_type: str = "bateria",
    distance_m: int | None = 25,
    duration_s: int | None = None,
    order_num: int | None = None,
) -> dict:
    body: dict = {"name": name, "heat_type": heat_type}
    if distance_m is not None:
        body["distance_m"] = distance_m
    if duration_s is not None:
        body["duration_s"] = duration_s
    if order_num is not None:
        body["order_num"] = order_num
    response = await client.post(f"/api/events/{event_id}/heats", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def configure_lanes(
    client: AsyncClient,
    heat_id: str,
    participants: list[tuple[int, str]],
) -> dict:
    lanes = [
        {"lane_number": number, "participant_name": name}
        for number, name in participants
    ]
    response = await client.post(
        f"/api/heats/{heat_id}/lanes", json={"lanes": lanes}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def ready_all(client: AsyncClient, heat: dict) -> dict:
    for lane in heat["heat_lanes"]:
        response = await client.post(f"/api/lanes/{lane['id']}/ready")
        assert response.status_code == 200, response.text
    return heat


async def setup_bateria(
    client: AsyncClient,
    participants: list[tuple[int, str]],
    distance_m: int = 25,
) -> tuple[dict, dict]:
    event = await create_event(client, pool_length_m=25)
    team = await create_team(client, event["id"], "Equipe Azul")
    heat = await create_heat(
        client,
        event["id"],
        heat_type="bateria",
        distance_m=distance_m,
    )
    heat = await configure_lanes(client, heat["id"], participants)
    for lane in heat["heat_lanes"]:
        response = await client.patch(
            f"/api/lanes/{lane['id']}", json={"team_id": team["id"]}
        )
        assert response.status_code == 200, response.text
    response = await client.post(f"/api/heats/{heat['id']}/open-ready-check")
    assert response.status_code == 200, response.text
    return event, response.json()
