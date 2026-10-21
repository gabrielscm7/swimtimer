import pytest

from tests.conftest import (
    configure_lanes,
    create_event,
    create_heat_in_prova,
    create_prova,
    ready_all,
)


async def _start_heat(client, heat_id):
    await configure_lanes(client, heat_id, [(1, "Ana")])
    response = await client.post(f"/api/heats/{heat_id}/open-ready-check")
    assert response.status_code == 200, response.text
    heat = response.json()
    await ready_all(client, heat)
    response = await client.post(f"/api/heats/{heat_id}/start")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_reorder_heats_move_down(client):
    event = await create_event(client)
    prova = await create_prova(client, event["id"])
    first = await create_heat_in_prova(client, prova["id"], name="B1")
    second = await create_heat_in_prova(client, prova["id"], name="B2")
    third = await create_heat_in_prova(client, prova["id"], name="B3")

    response = await client.put(
        f"/api/provas/{prova['id']}/heats/order",
        json={"ids": [third["id"], first["id"], second["id"]]},
    )
    assert response.status_code == 200, response.text

    heats = (await client.get(f"/api/provas/{prova['id']}/heats")).json()
    assert [(heat["name"], heat["order_num"]) for heat in heats] == [
        ("B3", 1),
        ("B1", 2),
        ("B2", 3),
    ]


@pytest.mark.asyncio
async def test_reorder_heats_move_up(client):
    event = await create_event(client)
    prova = await create_prova(client, event["id"])
    first = await create_heat_in_prova(client, prova["id"], name="B1")
    second = await create_heat_in_prova(client, prova["id"], name="B2")
    third = await create_heat_in_prova(client, prova["id"], name="B3")

    response = await client.put(
        f"/api/provas/{prova['id']}/heats/order",
        json={"ids": [second["id"], third["id"], first["id"]]},
    )
    assert response.status_code == 200, response.text

    heats = (await client.get(f"/api/provas/{prova['id']}/heats")).json()
    assert [(heat["name"], heat["order_num"]) for heat in heats] == [
        ("B2", 1),
        ("B3", 2),
        ("B1", 3),
    ]


@pytest.mark.asyncio
async def test_reorder_heats_rejects_invalid_ids(client):
    event = await create_event(client)
    other_event = await create_event(client, name="Outro")
    prova = await create_prova(client, event["id"])
    other_prova = await create_prova(client, other_event["id"])
    first = await create_heat_in_prova(client, prova["id"], name="B1")
    second = await create_heat_in_prova(client, prova["id"], name="B2")
    foreign = await create_heat_in_prova(
        client, other_prova["id"], name="Externa"
    )
    url = f"/api/provas/{prova['id']}/heats/order"

    missing = await client.put(url, json={"ids": [first["id"]]})
    assert missing.status_code == 400
    assert missing.json()["detail"] == "ordem_ids_invalidos"

    duplicated = await client.put(
        url, json={"ids": [first["id"], second["id"], second["id"]]}
    )
    assert duplicated.status_code == 400
    assert duplicated.json()["detail"] == "ordem_ids_invalidos"

    foreign_response = await client.put(
        url, json={"ids": [first["id"], foreign["id"]]}
    )
    assert foreign_response.status_code == 400
    assert foreign_response.json()["detail"] == "ordem_ids_invalidos"


@pytest.mark.asyncio
async def test_reorder_heats_blocks_started_heat(client):
    event = await create_event(client)
    prova = await create_prova(client, event["id"])
    first = await create_heat_in_prova(client, prova["id"], name="B1")
    second = await create_heat_in_prova(client, prova["id"], name="B2")
    await _start_heat(client, first["id"])

    response = await client.put(
        f"/api/provas/{prova['id']}/heats/order",
        json={"ids": [second["id"], first["id"]]},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "prova_ja_iniciada"


@pytest.mark.asyncio
async def test_reorder_provas_move_down(client):
    event = await create_event(client)
    first = await create_prova(client, event["id"], name="P1")
    second = await create_prova(client, event["id"], name="P2")
    third = await create_prova(client, event["id"], name="P3")

    response = await client.put(
        f"/api/events/{event['id']}/provas/order",
        json={"ids": [third["id"], first["id"], second["id"]]},
    )
    assert response.status_code == 200, response.text

    provas = (await client.get(f"/api/events/{event['id']}/provas")).json()
    assert [(prova["name"], prova["order_num"]) for prova in provas] == [
        ("P3", 1),
        ("P1", 2),
        ("P2", 3),
    ]


@pytest.mark.asyncio
async def test_reorder_provas_rejects_foreign_id(client):
    event = await create_event(client)
    other_event = await create_event(client, name="Outro")
    own = await create_prova(client, event["id"], name="P1")
    foreign = await create_prova(client, other_event["id"], name="Externa")

    response = await client.put(
        f"/api/events/{event['id']}/provas/order",
        json={"ids": [own["id"], foreign["id"]]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "ordem_ids_invalidos"


@pytest.mark.asyncio
async def test_reorder_provas_blocks_started_prova(client):
    event = await create_event(client)
    first = await create_prova(client, event["id"], name="P1")
    second = await create_prova(client, event["id"], name="P2")
    heat = await create_heat_in_prova(client, first["id"], name="B1")
    await _start_heat(client, heat["id"])

    response = await client.put(
        f"/api/events/{event['id']}/provas/order",
        json={"ids": [second["id"], first["id"]]},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "prova_ja_iniciada"


@pytest.mark.asyncio
async def test_heat_order_can_repeat_across_different_provas(client):
    """Regressao: ordem de bateria e unica por PROVA, nunca por evento."""
    event = await create_event(client)
    prova_a = await create_prova(client, event["id"], name="Peito")
    prova_b = await create_prova(client, event["id"], name="Costas")

    first = await create_heat_in_prova(
        client, prova_a["id"], name="Bateria 1", order_num=1
    )
    second = await create_heat_in_prova(
        client, prova_b["id"], name="Bateria 1", order_num=1
    )
    assert first["order_num"] == 1
    assert second["order_num"] == 1

    duplicate = await client.post(
        f"/api/provas/{prova_a['id']}/heats",
        json={
            "name": "Duplicada",
            "heat_type": "bateria",
            "distance_m": 50,
            "order_num": 1,
        },
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "order_num_duplicado"
