import asyncio

import pytest

from tests.conftest import (
    configure_lanes,
    create_event,
    create_heat,
    ready_all,
    setup_bateria,
)


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "2.0.0"}


@pytest.mark.asyncio
async def test_status(client):
    response = await client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert "uptime" in body
    assert "connected_clients" in body
    assert "active_heats" in body


@pytest.mark.asyncio
async def test_full_heat_flow_bateria(client):
    event, heat = await setup_bateria(
        client, [(1, "Ana"), (2, "Bia"), (3, "Caio")]
    )
    assert heat["status"] == "ready_check"

    await ready_all(client, heat)

    start = await client.post(f"/api/heats/{heat['id']}/start")
    assert start.status_code == 200, start.text
    assert start.json()["status"] == "active"

    await asyncio.sleep(0.02)

    for lane in heat["heat_lanes"]:
        finish = await client.post(f"/api/lanes/{lane['id']}/finish")
        assert finish.status_code == 200, finish.text

    result = await client.get(f"/api/events/{event['id']}/heats")
    final = result.json()[0]
    assert final["status"] == "finished"
    for lane in final["heat_lanes"]:
        assert lane["race_time_ms"] > 0
        assert lane["race_time_display"]
        assert lane["speed_ms"] is not None


@pytest.mark.asyncio
async def test_start_blocked_until_all_ready(client):
    _event, heat = await setup_bateria(
        client, [(1, "Ana"), (2, "Bia"), (3, "Caio")]
    )

    for lane in heat["heat_lanes"][:2]:
        response = await client.post(f"/api/lanes/{lane['id']}/ready")
        assert response.status_code == 200, response.text

    pending_lane = heat["heat_lanes"][2]
    response = await client.post(f"/api/heats/{heat['id']}/start")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "raias_pendentes" in detail
    assert str(pending_lane["lane_number"]) in detail


@pytest.mark.asyncio
async def test_no_double_finish(client):
    _event, heat = await setup_bateria(client, [(1, "Ana")])
    await ready_all(client, heat)

    await client.post(f"/api/heats/{heat['id']}/start")
    await asyncio.sleep(0.02)

    lane_id = heat["heat_lanes"][0]["id"]
    first = await client.post(f"/api/lanes/{lane_id}/finish")
    assert first.status_code == 200

    second = await client.post(f"/api/lanes/{lane_id}/finish")
    assert second.status_code == 409
    assert second.json()["detail"] == "ja_finalizou"


@pytest.mark.asyncio
async def test_dq_counts_as_finish(client):
    event, heat = await setup_bateria(client, [(1, "Ana"), (2, "Bia")])
    await ready_all(client, heat)

    await client.post(f"/api/heats/{heat['id']}/start")
    await asyncio.sleep(0.02)

    first, second = heat["heat_lanes"]
    finish = await client.post(f"/api/lanes/{first['id']}/finish")
    assert finish.status_code == 200

    dq = await client.post(f"/api/lanes/{second['id']}/dq")
    assert dq.status_code == 200

    result = await client.get(f"/api/events/{event['id']}/heats")
    assert result.json()[0]["status"] == "finished"


@pytest.mark.asyncio
async def test_maratona_lap_and_undo(client):
    event = await create_event(client, pool_length_m=25)
    heat = await create_heat(
        client,
        event["id"],
        heat_type="maratona",
        distance_m=None,
        duration_s=10800,
    )
    heat = await configure_lanes(client, heat["id"], [(1, "Ana")])
    await client.post(f"/api/heats/{heat['id']}/open-ready-check")

    lane_id = heat["heat_lanes"][0]["id"]
    await client.post(f"/api/lanes/{lane_id}/ready")
    await client.post(f"/api/heats/{heat['id']}/start")

    lap = await client.post(f"/api/lanes/{lane_id}/lap")
    assert lap.status_code == 200, lap.text
    assert lap.json()["lap_number"] == 1

    result = await client.get(f"/api/events/{event['id']}/heats")
    lane = result.json()[0]["heat_lanes"][0]
    assert lane["laps"] == 1
    assert lane["meters"] == 25

    undo = await client.delete(f"/api/lanes/{lane_id}/lap/last")
    assert undo.status_code == 200

    result = await client.get(f"/api/events/{event['id']}/heats")
    assert result.json()[0]["heat_lanes"][0]["laps"] == 0


@pytest.mark.asyncio
async def test_event_delete_only_when_draft(client):
    event = await create_event(client)
    deleted = await client.delete(f"/api/events/{event['id']}")
    assert deleted.status_code == 204

    event = await create_event(client, name="Evento Ativo")
    await client.patch(f"/api/events/{event['id']}", json={"status": "active"})
    blocked = await client.delete(f"/api/events/{event['id']}")
    assert blocked.status_code == 409
