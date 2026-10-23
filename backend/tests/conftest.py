import atexit
import os
import shutil
import tempfile

_db_fd, _DB_PATH = tempfile.mkstemp(suffix=".db", prefix="swimtimer_test_")
os.close(_db_fd)
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_DB_PATH}")

_LOGO_DIR = tempfile.mkdtemp(prefix="swimtimer_logos_")
os.environ.setdefault("LOGO_DIR", _LOGO_DIR)

_THEME_DIR = tempfile.mkdtemp(prefix="swimtimer_theme_")
os.environ.setdefault("THEME_DIR", _THEME_DIR)

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
    shutil.rmtree(_THEME_DIR, ignore_errors=True)
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
    date: str = "2026-10-23",
) -> dict:
    response = await client.post(
        "/api/events",
        json={"name": name, "date": date, "pool_length_m": pool_length_m},
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
    name: str = "",
    heat_type: str = "bateria",
    distance_m: int | None = 25,
    duration_s: int | None = None,
    order_num: int | None = None,
    stroke: str = "livre",
    naipe: str = "MISTO",
    category: str = "livre",
    lane_count: int | None = None,
    classify_alone: bool = False,
) -> dict:
    body: dict = {
        "heat_type": heat_type,
        "stroke": stroke,
        "naipe": naipe,
        "category": category,
        "classify_alone": classify_alone,
    }
    if name:
        body["name"] = name
    if distance_m is not None:
        body["distance_m"] = distance_m
    if duration_s is not None:
        body["duration_s"] = duration_s
    if order_num is not None:
        body["order_num"] = order_num
    if lane_count is not None:
        body["lane_count"] = lane_count
    response = await client.post(
        f"/api/events/{event_id}/heats", json=body
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_prova(
    client: AsyncClient,
    event_id: str,
    *,
    name: str = "Prova",
    order_num: int | None = None,
    consolidate_results: bool = True,
    distance_m: int | None = 25,
    stroke: str | None = None,
    category: str = "livre",
    naipe: str = "M",
    format: str = "bateria",
    name_override: bool = False,
) -> dict:
    """Compatibilidade: cria uma bateria e devolve a prova derivada."""
    if stroke is None:
        strokes = ["livre", "costas", "peito", "borboleta", "medley"]
        stroke = strokes[sum(ord(char) for char in name) % len(strokes)]
    heat = await create_heat(
        client,
        event_id,
        name=name if name_override else "",
        heat_type=format,
        distance_m=distance_m if format == "bateria" else None,
        duration_s=7200 if format == "maratona" else None,
        order_num=order_num,
        stroke=stroke,
        naipe=naipe,
        category=category,
    )
    response = await client.get(f"/api/provas/{heat['prova_id']}")
    assert response.status_code == 200, response.text
    return response.json()


async def create_heat_in_prova(
    client: AsyncClient,
    prova_id: str,
    *,
    name: str = "Bateria",
    heat_type: str | None = None,
    distance_m: int | None = None,
    duration_s: int | None = None,
    order_num: int | None = None,
) -> dict:
    response = await client.get(f"/api/provas/{prova_id}")
    assert response.status_code == 200, response.text
    prova = response.json()
    return await create_heat(
        client,
        prova["event_id"],
        name=name,
        heat_type=heat_type or prova["format"],
        distance_m=(
            distance_m
            if distance_m is not None
            else prova.get("distance_m")
        )
        if (heat_type or prova["format"]) == "bateria"
        else None,
        duration_s=duration_s if (heat_type or prova["format"]) == "maratona" else None,
        order_num=order_num,
        stroke=prova.get("stroke") or "livre",
        naipe=prova.get("naipe") or "MISTO",
        category=prova.get("category") or "livre",
    )


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
