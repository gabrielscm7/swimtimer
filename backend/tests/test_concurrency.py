"""Testes de concorrência (requerem banco em arquivo, não :memory:).

Cobrem as corridas identificadas na auditoria: finalização dupla, voltas com
numeração repetida, criação simultânea de provas (order_num) e start duplo.
"""
import asyncio
from collections import Counter

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.main as main_module
from app.database import Base, get_db
from app.models import Heat, LapEvent


@pytest_asyncio.fixture
async def client(tmp_path):
    db = tmp_path / "test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db}", connect_args={"timeout": 30}
    )
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with factory() as session:
            yield session

    original = main_module.AsyncSessionLocal
    main_module.app.dependency_overrides[get_db] = override_get_db
    main_module.AsyncSessionLocal = factory
    try:
        transport = ASGITransport(app=main_module.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, factory
    finally:
        main_module.app.dependency_overrides.clear()
        main_module.AsyncSessionLocal = original
        await engine.dispose()


async def _event(client):
    response = await client.post(
        "/api/events", json={"name": "Evento", "pool_length_m": 25}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _heat(client, event_id, **overrides):
    body = {"name": "Prova", "heat_type": "bateria", "distance_m": 25}
    body.update(overrides)
    response = await client.post(f"/api/events/{event_id}/heats", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _lanes(client, heat_id, participants):
    response = await client.post(
        f"/api/heats/{heat_id}/lanes",
        json={
            "lanes": [
                {"lane_number": number, "participant_name": name}
                for number, name in participants
            ]
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _get_heat(client, event_id, heat_id):
    heats = (await client.get(f"/api/events/{event_id}/heats")).json()
    return next(heat for heat in heats if heat["id"] == heat_id)


async def _active_bateria(client, participants):
    event = await _event(client)
    heat = await _heat(client, event["id"])
    await _lanes(client, heat["id"], participants)
    await client.post(f"/api/heats/{heat['id']}/open-ready-check")
    heat = await _get_heat(client, event["id"], heat["id"])
    for lane in heat["heat_lanes"]:
        await client.post(f"/api/lanes/{lane['id']}/ready")
    return event, heat


async def _active_maratona(client, participants):
    event = await _event(client)
    heat = await _heat(
        client, event["id"], heat_type="maratona", distance_m=None, duration_s=3600
    )
    await _lanes(client, heat["id"], participants)
    await client.post(f"/api/heats/{heat['id']}/open-ready-check")
    heat = await _get_heat(client, event["id"], heat["id"])
    for lane in heat["heat_lanes"]:
        await client.post(f"/api/lanes/{lane['id']}/ready")
    start = await client.post(f"/api/heats/{heat['id']}/start")
    assert start.status_code == 200, start.text
    return event, await _get_heat(client, event["id"], heat["id"])


@pytest.mark.asyncio
async def test_concurrent_finish_only_one_accepted(client):
    http, _factory = client
    _event_data, heat = await _active_bateria(http, [(1, "Ana")])
    lane_id = heat["heat_lanes"][0]["id"]
    await http.post(f"/api/heats/{heat['id']}/start")
    await asyncio.sleep(0.02)

    responses = await asyncio.gather(
        *[http.post(f"/api/lanes/{lane_id}/finish") for _ in range(5)]
    )
    codes = Counter(r.status_code for r in responses)
    assert codes == {200: 1, 409: 4}, f"respostas inesperadas: {codes}"


@pytest.mark.asyncio
async def test_concurrent_laps_unique_numbers(client):
    http, factory = client
    _event_data, heat = await _active_maratona(http, [(1, "Ana")])
    lane_id = heat["heat_lanes"][0]["id"]

    responses = await asyncio.gather(
        *[http.post(f"/api/lanes/{lane_id}/lap") for _ in range(5)]
    )
    assert all(r.status_code == 200 for r in responses)

    async with factory() as session:
        numbers = (
            await session.execute(
                select(LapEvent.lap_number).where(LapEvent.lane_id == lane_id)
            )
        ).scalars().all()
        total = await session.scalar(
            select(func.count(LapEvent.id)).where(LapEvent.lane_id == lane_id)
        )
    assert total == 5
    assert sorted(numbers) == [1, 2, 3, 4, 5], f"numeração repetida: {sorted(numbers)}"


@pytest.mark.asyncio
async def test_concurrent_create_heat_unique_order(client):
    http, factory = client
    event = await _event(http)

    async def make(index):
        return await http.post(
            f"/api/events/{event['id']}/heats",
            json={"name": f"H{index}", "heat_type": "bateria", "distance_m": 25},
        )

    responses = await asyncio.gather(*[make(i) for i in range(6)])
    assert all(r.status_code == 201 for r in responses)

    async with factory() as session:
        orders = (
            await session.execute(
                select(Heat.order_num).where(Heat.event_id == event["id"])
            )
        ).scalars().all()
    assert sorted(orders) == [1, 2, 3, 4, 5, 6], f"order_num colidiu: {sorted(orders)}"


@pytest.mark.asyncio
async def test_concurrent_start_only_one(client):
    http, _factory = client
    event, heat = await _active_bateria(http, [(1, "Ana"), (2, "Bia")])

    responses = await asyncio.gather(
        *[http.post(f"/api/heats/{heat['id']}/start") for _ in range(5)]
    )
    codes = Counter(r.status_code for r in responses)
    assert codes[200] == 1, f"mais de um start aceito: {codes}"
    assert set(codes) <= {200, 400}, f"respostas inesperadas: {codes}"

    final = await _get_heat(http, event["id"], heat["id"])
    assert final["status"] == "active"


@pytest.mark.asyncio
async def test_lap_unique_constraint_holds(client):
    import uuid

    from sqlalchemy.exc import IntegrityError

    _http, factory = client
    async with factory() as session:
        session.add_all(
            [
                LapEvent(
                    id=str(uuid.uuid4()),
                    lane_id="lane-x",
                    lap_number=1,
                    recorded_at=1.0,
                    is_undo=False,
                ),
                LapEvent(
                    id=str(uuid.uuid4()),
                    lane_id="lane-x",
                    lap_number=1,
                    recorded_at=2.0,
                    is_undo=False,
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            await session.commit()
