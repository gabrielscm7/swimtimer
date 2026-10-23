"""Apresentação curada do telão e árvore interna de resultados."""
import pytest

from app.services import presentation
from tests.conftest import (
    configure_lanes,
    create_event,
    create_heat,
    create_heat_in_prova,
    create_prova,
)


async def _finished_heat(client):
    event = await create_event(client)
    created = await create_heat(
        client,
        event["id"],
        name="Bateria 1",
        stroke="livre",
        distance_m=100,
        naipe="MISTO",
        category="livre",
    )
    heat = created
    prova = (await client.get(f"/api/provas/{heat['prova_id']}")).json()
    heat = await configure_lanes(client, heat["id"], [(1, "Ana")])
    await client.post(f"/api/heats/{heat['id']}/open-ready-check")
    lane = heat["heat_lanes"][0]
    await client.post(f"/api/lanes/{lane['id']}/ready")
    await client.post(f"/api/heats/{heat['id']}/start")
    finish = await client.post(f"/api/lanes/{lane['id']}/finish")
    assert finish.status_code == 200, finish.text
    return event, prova, heat


@pytest.mark.asyncio
async def test_presentation_default_e_persistencia(client):
    event = await create_event(client)
    response = await client.get(f"/api/events/{event['id']}/presentation")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["show_next_prova"] is True
    assert body["slides"] == []

    event, prova, heat = await _finished_heat(client)
    payload = {
        "enabled": True,
        "rotation": False,
        "slide_duration_s": 20,
        "show_next_prova": False,
        "pinned_ref": f"prova:{prova['id']}",
        "slides": [
            {"kind": "prova", "target_id": prova["id"]},
            {"kind": "bateria", "target_id": heat["id"]},
            {"kind": "prova", "target_id": prova["id"]},
        ],
    }
    saved = await client.put(
        f"/api/events/{event['id']}/presentation", json=payload
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["rotation"] is False
    assert body["slide_duration_s"] == 20
    assert body["show_next_prova"] is False
    assert len(body["slides"]) == 2
    assert body["slides"][0]["label"] == "PROVA 1 · 100 m Livre · Misto"
    assert body["slides"][0]["eligible"] is True
    assert body["slides"][1]["kind"] == "bateria"
    assert body["slides"][1]["eligible"] is True

    loaded = await client.get(f"/api/events/{event['id']}/presentation")
    assert loaded.status_code == 200
    assert loaded.json()["pinned_ref"] == f"prova:{prova['id']}"


@pytest.mark.asyncio
async def test_presentation_rejeita_ref_de_outro_evento(client):
    event = await create_event(client)
    other = await create_event(client, name="Outro")
    other_prova = await create_prova(client, other["id"])

    response = await client.put(
        f"/api/events/{event['id']}/presentation",
        json={
            "slides": [{"kind": "prova", "target_id": other_prova["id"]}],
            "pinned_ref": None,
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "slide_prova_invalida"


@pytest.mark.asyncio
async def test_results_tree_e_snapshot_history(client):
    event, prova, heat = await _finished_heat(client)

    response = await client.get(f"/api/events/{event['id']}/results")
    assert response.status_code == 200
    body = response.json()
    assert body["event"]["id"] == event["id"]
    assert body["provas"][0]["id"] == prova["id"]
    tree_heat = body["provas"][0]["heats"][0]
    assert tree_heat["id"] == heat["id"]
    assert tree_heat["athlete_count"] == 1
    assert tree_heat["finished_count"] == 1
    assert tree_heat["result_snapshot"]["revision"] == 1
    assert "heat_lanes" not in tree_heat

    history = await client.get(f"/api/heats/{heat['id']}/snapshots")
    assert history.status_code == 200
    rows = history.json()
    assert len(rows) == 1
    assert rows[0]["revision"] == 1
    assert rows[0]["status"] == "provisional"


@pytest.mark.asyncio
async def test_exclusao_remove_refs_da_apresentacao(client):
    event = await create_event(client)
    heat = await create_heat(client, event["id"])
    prova = (await client.get(f"/api/provas/{heat['prova_id']}")).json()

    saved = await client.put(
        f"/api/events/{event['id']}/presentation",
        json={
            "slides": [
                {"kind": "prova", "target_id": prova["id"]},
                {"kind": "bateria", "target_id": heat["id"]},
            ],
            "pinned_ref": f"bateria:{heat['id']}",
        },
    )
    assert saved.status_code == 200, saved.text

    deleted = await client.delete(f"/api/heats/{heat['id']}")
    assert deleted.status_code == 204, deleted.text

    body = (await client.get(f"/api/events/{event['id']}/presentation")).json()
    # A prova fica vazia e sem snapshots, entao tambem e removida e seus
    # refs saem da apresentacao.
    assert body["slides"] == []
    assert body["pinned_ref"] is None


def test_normalize_presentation_deduplica_e_limita():
    config = presentation.normalize_presentation(
        {
            "slide_duration_s": 999,
            "pinned_ref": "prova:a",
            "slides": [
                {"kind": "prova", "target_id": "a"},
                {"kind": "prova", "target_id": "a"},
                {"kind": "bateria", "target_id": "b"},
                {"kind": "x", "target_id": "c"},
            ],
        }
    )
    assert config["slide_duration_s"] == 60
    assert len(config["slides"]) == 2
    assert config["pinned_ref"] == "prova:a"


def test_presentation_updated_broadcast(ws_client):
    event = ws_client.post(
        "/api/events", json={"name": "Evento WS presentation", "date": "2026-10-23"}
    ).json()
    heat = ws_client.post(
        f"/api/events/{event['id']}/heats",
        json={
            "heat_type": "bateria",
            "stroke": "livre",
            "distance_m": 25,
            "naipe": "M",
            "category": "livre",
        },
    ).json()
    prova = ws_client.get(f"/api/provas/{heat['prova_id']}").json()

    with ws_client.websocket_connect("/ws") as websocket:
        assert websocket.receive_json()["type"] == "server_status"
        websocket.send_json({"type": "subscribe", "event_id": event["id"]})
        assert websocket.receive_json()["type"] == "subscribed"

        response = ws_client.put(
            f"/api/events/{event['id']}/presentation",
            json={"slides": [{"kind": "prova", "target_id": prova["id"]}]},
        )
        assert response.status_code == 200, response.text

        message = None
        for _ in range(20):
            candidate = websocket.receive_json()
            if candidate.get("type") == "presentation_updated":
                message = candidate
                break
        assert message is not None
        assert message["event_id"] == event["id"]
        assert message["payload"]["slides"][0]["target_id"] == prova["id"]
