import asyncio
import time

import pytest

import app.main as main_module
from tests.conftest import create_competition_with_lanes


async def create_bateria_with_participants(
    client,
    distance_m: int = 25,
    participants: int = 1,
) -> tuple[dict, list[dict]]:
    response = await client.post(
        "/api/competition",
        json={
            "name": "Bateria Teste",
            "duration_s": 3600,
            "meters_lap": 25,
            "event_type": "bateria",
            "distance_m": distance_m,
        },
    )
    assert response.status_code == 201, response.text
    competition = response.json()
    state = (await client.get("/api/competition/current")).json()
    lanes = state["lanes"][:participants]
    for lane in lanes:
        assign = await client.post(
            f"/api/lane/{lane['id']}/assign",
            json={"team_id": None, "participant_name": f"Atleta {lane['number']}"},
        )
        assert assign.status_code == 200, assign.text
    return competition, lanes


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}


@pytest.mark.asyncio
async def test_create_competition(client):
    response = await client.post(
        "/api/competition",
        json={"name": "Festival Infantil SESI", "duration_s": 10800, "meters_lap": 25},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Festival Infantil SESI"
    assert body["status"] == "draft"
    assert body["duration_s"] == 10800
    assert body["meters_lap"] == 25
    assert body["id"]


@pytest.mark.asyncio
async def test_register_lap_uses_server_timestamp(client):
    _competition, lanes = await create_competition_with_lanes(client)
    lane_id = lanes[0]["id"]

    before = time.time()
    response = await client.post(f"/api/lane/{lane_id}/lap")
    after = time.time()

    assert response.status_code == 200
    body = response.json()
    assert body["lane_id"] == lane_id
    assert body["lap_number"] == 1
    assert body["is_undo"] is False
    assert before <= body["recorded_at"] <= after

    state = await client.get("/api/competition/current")
    lane = next(item for item in state.json()["lanes"] if item["id"] == lane_id)
    assert lane["laps"] == 1
    assert lane["meters"] == 25
    assert lane["status"] == "active"


@pytest.mark.asyncio
async def test_undo_lap_within_30s(client):
    _competition, lanes = await create_competition_with_lanes(client)
    lane_id = lanes[0]["id"]

    await client.post(f"/api/lane/{lane_id}/lap")
    response = await client.delete(f"/api/lane/{lane_id}/lap/last")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "undone"
    assert body["laps"] == 0


@pytest.mark.asyncio
async def test_undo_lap_after_30s(client, monkeypatch):
    _competition, lanes = await create_competition_with_lanes(client)
    lane_id = lanes[0]["id"]

    await client.post(f"/api/lane/{lane_id}/lap")

    future = time.time() + 31
    monkeypatch.setattr(main_module.time, "time", lambda: future)

    response = await client.delete(f"/api/lane/{lane_id}/lap/last")
    assert response.status_code == 400
    assert response.json()["detail"] == "fora_do_prazo"


@pytest.mark.asyncio
async def test_bateria_finish_registers_time(client):
    competition, lanes = await create_bateria_with_participants(
        client, distance_m=25
    )
    await client.post(f"/api/competition/{competition['id']}/start")
    await asyncio.sleep(0.02)

    response = await client.post(f"/api/lane/{lanes[0]['id']}/finish")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["race_time_ms"] > 0
    assert body["speed_ms"] == round(25000 / body["race_time_ms"], 2)
    assert body["race_time_display"]
    assert body["participant_name"] == "Atleta 1"


@pytest.mark.asyncio
async def test_bateria_no_double_finish(client):
    competition, lanes = await create_bateria_with_participants(client)
    await client.post(f"/api/competition/{competition['id']}/start")
    await asyncio.sleep(0.02)

    first = await client.post(f"/api/lane/{lanes[0]['id']}/finish")
    assert first.status_code == 200

    second = await client.post(f"/api/lane/{lanes[0]['id']}/finish")
    assert second.status_code == 409
    assert second.json()["detail"] == "ja_finalizou"


@pytest.mark.asyncio
async def test_bateria_auto_finish_when_all_done(client):
    competition, lanes = await create_bateria_with_participants(
        client, participants=2
    )
    await client.post(f"/api/competition/{competition['id']}/start")
    await asyncio.sleep(0.02)

    await client.post(f"/api/lane/{lanes[0]['id']}/finish")
    await client.post(f"/api/lane/{lanes[1]['id']}/finish")

    state = await client.get("/api/competition/current")
    assert state.json()["competition"]["status"] == "finished"


@pytest.mark.asyncio
async def test_bateria_finish_rejected_before_start(client):
    _competition, lanes = await create_bateria_with_participants(client)

    response = await client.post(f"/api/lane/{lanes[0]['id']}/finish")
    assert response.status_code == 400
    assert response.json()["detail"] == "competicao_nao_ativa"
