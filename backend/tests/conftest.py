import atexit
import os
import shutil
import tempfile

_db_fd, _DB_PATH = tempfile.mkstemp(suffix=".db", prefix="swimtimer_test_")
os.close(_db_fd)
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_DB_PATH}")

_LOGO_DIR = tempfile.mkdtemp(prefix="swimtimer_logos_")
os.environ.setdefault("LOGO_DIR", _LOGO_DIR)

_DATA_DIR = tempfile.mkdtemp(prefix="swimtimer_data_")
os.environ.setdefault("JOURNAL_DIR", os.path.join(_DATA_DIR, "journal"))
os.environ.setdefault("BACKUP_DIR", os.path.join(_DATA_DIR, "backups"))


@atexit.register
def _cleanup_test_db() -> None:
    try:
        os.remove(_DB_PATH)
    except OSError:
        pass
    shutil.rmtree(_LOGO_DIR, ignore_errors=True)
    shutil.rmtree(_DATA_DIR, ignore_errors=True)


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
from app import database as database_module
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

    original_factory = database_module.AsyncSessionLocal
    main_module.app.dependency_overrides[get_db] = override_get_db
    database_module.AsyncSessionLocal = session_factory
    try:
        transport = ASGITransport(app=main_module.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        main_module.app.dependency_overrides.clear()
        database_module.AsyncSessionLocal = original_factory
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


async def create_athlete(
    client: AsyncClient,
    event_id: str,
    *,
    name: str = "Atleta Teste",
    naipe: str = "M",
    category: str | None = None,
    team_id: str | None = None,
    registration_code: str | None = None,
) -> dict:
    body: dict = {"name": name, "naipe": naipe}
    if category is not None:
        body["category"] = category
    if team_id is not None:
        body["team_id"] = team_id
    if registration_code is not None:
        body["registration_code"] = registration_code
    response = await client.post(
        f"/api/events/{event_id}/athletes", json=body
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
    prova_body: dict = {"name": name}
    if distance_m is not None:
        prova_body["distance_m"] = distance_m
    if order_num is not None:
        prova_body["order_num"] = order_num
    prova_response = await client.post(
        f"/api/events/{event_id}/provas", json=prova_body
    )
    assert prova_response.status_code == 201, prova_response.text
    prova = prova_response.json()
    body["order_num"] = 1
    response = await client.post(f"/api/provas/{prova['id']}/heats", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def create_prova(
    client: AsyncClient,
    event_id: str,
    *,
    name: str = "Prova",
    order_num: int | None = None,
    consolidate_results: bool = True,
    distance_m: int | None = None,
    stroke: str | None = None,
    category: str | None = None,
    naipe: str | None = None,
) -> dict:
    body: dict = {
        "name": name,
        "consolidate_results": consolidate_results,
    }
    if order_num is not None:
        body["order_num"] = order_num
    if distance_m is not None:
        body["distance_m"] = distance_m
    if stroke is not None:
        body["stroke"] = stroke
    if category is not None:
        body["category"] = category
    if naipe is not None:
        body["naipe"] = naipe
    response = await client.post(f"/api/events/{event_id}/provas", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def create_heat_in_prova(
    client: AsyncClient,
    prova_id: str,
    *,
    name: str = "Bateria",
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
    response = await client.post(f"/api/provas/{prova_id}/heats", json=body)
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
