import json

import pytest
from sqlalchemy import select, text

from app import database
from app.models import ResultSnapshot
from tests.conftest import (
    create_athlete,
    create_event,
    create_heat,
    create_team,
)


async def _snapshot_rows(event_id: str):
    async with database.AsyncSessionLocal() as session:
        result = await session.execute(
            select(ResultSnapshot)
            .where(ResultSnapshot.event_id == event_id)
            .order_by(text("rowid ASC"))
        )
        return list(result.scalars().all())


async def _finished_heat(client, name: str = "Maria da Silva"):
    event = await create_event(client, name="Evento Publico")
    team = await create_team(client, event["id"], "Equipe Azul")
    heat = await create_heat(
        client, event["id"], name="100 Livres", heat_type="bateria", distance_m=100
    )
    athlete = await create_athlete(
        client,
        event["id"],
        name=name,
        naipe="F",
        category="SENIOR",
        team_id=team["id"],
    )
    response = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 3, "athlete_id": athlete["id"]}]},
    )
    assert response.status_code == 200, response.text
    heat = response.json()
    await client.post(f"/api/heats/{heat['id']}/open-ready-check")
    await client.post(f"/api/lanes/{heat['heat_lanes'][0]['id']}/ready")
    await client.post(f"/api/heats/{heat['id']}/start")
    response = await client.post(
        f"/api/lanes/{heat['heat_lanes'][0]['id']}/finish"
    )
    assert response.status_code == 200, response.text
    return event, heat, athlete


@pytest.mark.asyncio
async def test_public_results_headers_and_shape(client):
    event, heat, _athlete = await _finished_heat(client)

    response = await client.get(f"/api/public/events/{event['id']}/results")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "max-age=2"
    etag = response.headers["etag"]
    assert etag.startswith('"')

    body = response.json()
    assert body["event"]["id"] == event["id"]
    assert body["event"]["public_name_mode"] == "full"
    assert len(body["provas"]) == 1
    prova = body["provas"][0]
    assert prova["badge"] == "provisional"
    assert prova["heats"][0]["badge"] == "provisional"
    assert prova["heats"][0]["result_snapshot"]["revision"] == 1
    names = [entry["participant_name"] for entry in prova["standings"]]
    assert names == ["Maria da Silva"]

    not_modified = await client.get(
        f"/api/public/events/{event['id']}/results",
        headers={"If-None-Match": etag},
    )
    assert not_modified.status_code == 304

    single = await client.get(f"/api/public/provas/{prova['id']}")
    assert single.status_code == 200
    assert single.json()["prova"]["id"] == prova["id"]
    assert single.headers["cache-control"] == "max-age=2"


@pytest.mark.asyncio
async def test_initials_mode_masks_public_but_not_storage(client):
    event, heat, _athlete = await _finished_heat(client)
    before = await _snapshot_rows(event["id"])
    assert len(before) == 1

    response = await client.patch(
        f"/api/events/{event['id']}",
        json={"public_name_mode": "initials"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["public_name_mode"] == "initials"

    after = await _snapshot_rows(event["id"])
    assert len(after) == 1
    assert after[0].hash == before[0].hash
    assert after[0].payload_json == before[0].payload_json
    assert "Maria da Silva" in after[0].payload_json

    public = await client.get(f"/api/public/events/{event['id']}/results")
    assert public.status_code == 200
    text = public.text
    assert "Maria S." in text
    assert "Maria da Silva" not in text

    # Gestao/supervisor continuam vendo o nome completo.
    manage = await client.get(f"/api/events/{event['id']}")
    assert "Maria da Silva" in json.dumps(manage.json())

    # CSV e snapshots nunca sao mascarados.
    csv_response = await client.get(
        f"/api/events/{event['id']}/export/results.csv"
    )
    assert "Maria da Silva" in csv_response.text
    heat_response = await client.get(f"/api/heats/{heat['id']}")
    snapshot = heat_response.json()["result_snapshot"]
    assert snapshot["revision"] == 1


@pytest.mark.asyncio
async def test_public_results_can_be_disabled(client):
    event, heat, _athlete = await _finished_heat(client)
    prova_id = heat["prova_id"]

    response = await client.patch(
        f"/api/events/{event['id']}",
        json={"public_results_enabled": False},
    )
    assert response.status_code == 200
    assert response.json()["public_results_enabled"] is False

    assert (
        await client.get(f"/api/public/events/{event['id']}/results")
    ).status_code == 404
    assert (
        await client.get(f"/api/public/provas/{prova_id}")
    ).status_code == 404

    await client.patch(
        f"/api/events/{event['id']}",
        json={"public_results_enabled": True},
    )
    assert (
        await client.get(f"/api/public/events/{event['id']}/results")
    ).status_code == 200


def _create_event(ws_client, name="Evento WS settings"):
    response = ws_client.post(
        "/api/events", json={"name": name, "pool_length_m": 25}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_settings_updated_broadcast(ws_client):
    event = _create_event(ws_client)
    with ws_client.websocket_connect("/ws") as websocket:
        first = websocket.receive_json()
        assert first["type"] == "server_status"
        response = ws_client.patch(
            f"/api/events/{event['id']}",
            json={"public_name_mode": "initials"},
        )
        assert response.status_code == 200, response.text

        message = None
        for _ in range(30):
            candidate = websocket.receive_json()
            if candidate.get("type") == "settings_updated":
                message = candidate
                break
        assert message is not None
        assert message["scope"] == "event"
        assert message["event_id"] == event["id"]
        assert message["payload"]["public_name_mode"] == "initials"
