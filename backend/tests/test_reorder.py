import pytest

from tests.conftest import (
    configure_lanes,
    create_event,
    create_heat,
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


async def _three_heats(client):
    event = await create_event(client)
    first = await create_heat(client, event["id"], name="B1", stroke="livre")
    second = await create_heat(client, event["id"], name="B2", stroke="livre")
    third = await create_heat(client, event["id"], name="B3", stroke="livre")
    return event, first, second, third


@pytest.mark.asyncio
async def test_reorder_heats_move_down(client):
    event, first, second, third = await _three_heats(client)

    response = await client.patch(
        f"/api/events/{event['id']}/heats/order",
        json={"ids": [third["id"], first["id"], second["id"]]},
    )
    assert response.status_code == 200, response.text

    heats = (await client.get(f"/api/events/{event['id']}/heats")).json()
    assert [(heat["name"], heat["order_num"]) for heat in heats] == [
        ("B3", 1),
        ("B1", 2),
        ("B2", 3),
    ]


@pytest.mark.asyncio
async def test_reorder_heats_move_up(client):
    event, first, second, third = await _three_heats(client)

    response = await client.patch(
        f"/api/events/{event['id']}/heats/order",
        json={"ids": [second["id"], third["id"], first["id"]]},
    )
    assert response.status_code == 200, response.text

    heats = (await client.get(f"/api/events/{event['id']}/heats")).json()
    assert [(heat["name"], heat["order_num"]) for heat in heats] == [
        ("B2", 1),
        ("B3", 2),
        ("B1", 3),
    ]


@pytest.mark.asyncio
async def test_reorder_heats_rejects_invalid_ids(client):
    event, first, second, _third = await _three_heats(client)
    other_event = await create_event(client, name="Outro")
    foreign = await create_heat(client, other_event["id"], name="Externa")
    url = f"/api/events/{event['id']}/heats/order"

    missing = await client.patch(url, json={"ids": [first["id"]]})
    assert missing.status_code == 400
    assert missing.json()["detail"] == "ordem_ids_invalidos"

    duplicated = await client.patch(
        url, json={"ids": [first["id"], second["id"], second["id"]]}
    )
    assert duplicated.status_code == 400
    assert duplicated.json()["detail"] == "ordem_ids_invalidos"

    foreign_response = await client.patch(
        url, json={"ids": [first["id"], second["id"], foreign["id"]]}
    )
    assert foreign_response.status_code == 400
    assert foreign_response.json()["detail"] == "ordem_ids_invalidos"


@pytest.mark.asyncio
async def test_reorder_heats_blocks_started_heat(client):
    event, first, second, _third = await _three_heats(client)
    await _start_heat(client, first["id"])

    response = await client.patch(
        f"/api/events/{event['id']}/heats/order",
        json={"heat_id": first["id"], "position": 3},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "bateria_ancorada"


@pytest.mark.asyncio
async def test_reorder_interleaved_groups(client):
    """Ordem intercalada A1, B1, A2, B2 preserva a classificacao por grupo."""
    event = await create_event(client)
    a1 = await create_heat(client, event["id"], name="A1", stroke="livre")
    a2 = await create_heat(client, event["id"], name="A2", stroke="livre")
    b1 = await create_heat(client, event["id"], name="B1", stroke="costas")
    b2 = await create_heat(client, event["id"], name="B2", stroke="costas")
    assert a1["prova_id"] == a2["prova_id"]
    assert b1["prova_id"] == b2["prova_id"]
    assert a1["prova_id"] != b1["prova_id"]

    response = await client.patch(
        f"/api/events/{event['id']}/heats/order",
        json={"ids": [a1["id"], b1["id"], a2["id"], b2["id"]]},
    )
    assert response.status_code == 200, response.text

    heats = (await client.get(f"/api/events/{event['id']}/heats")).json()
    assert [heat["name"] for heat in heats] == ["A1", "B1", "A2", "B2"]
    assert [heat["event_seq"] for heat in heats] == [1, 2, 3, 4]
    assert [heat["heat_index_in_prova"] for heat in heats] == [1, 1, 2, 2]

    provas = (await client.get(f"/api/events/{event['id']}/provas")).json()
    by_id = {prova["id"]: prova for prova in provas}
    assert by_id[a1["prova_id"]]["heat_orders"] == [1, 3]
    assert by_id[b1["prova_id"]]["heat_orders"] == [2, 4]
    assert by_id[a1["prova_id"]]["order_num"] == 1
    assert by_id[b1["prova_id"]]["order_num"] == 2


@pytest.mark.asyncio
async def test_move_heat_to_position(client):
    event, first, second, third = await _three_heats(client)

    response = await client.patch(
        f"/api/events/{event['id']}/heats/order",
        json={"heat_id": third["id"], "position": 1},
    )
    assert response.status_code == 200, response.text

    heats = (await client.get(f"/api/events/{event['id']}/heats")).json()
    assert [heat["name"] for heat in heats] == ["B3", "B1", "B2"]
    assert [heat["order_num"] for heat in heats] == [1, 2, 3]


@pytest.mark.asyncio
async def test_heat_order_is_unique_per_event(client):
    event = await create_event(client)
    first = await create_heat(
        client, event["id"], name="B1", stroke="livre", order_num=1
    )
    second = await create_heat(
        client, event["id"], name="B2", stroke="costas", order_num=1
    )
    assert first["order_num"] == 1
    assert second["order_num"] == 1
    heats = (await client.get(f"/api/events/{event['id']}/heats")).json()
    assert [heat["order_num"] for heat in heats] == [1, 2]
