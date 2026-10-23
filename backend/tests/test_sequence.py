import pytest

from tests.conftest import (
    create_event,
    create_heat_in_prova,
    create_prova,
)


async def _four_heats(client):
    event = await create_event(client)
    prova_a = await create_prova(
        client, event["id"], name="Prova A", order_num=1
    )
    prova_b = await create_prova(
        client, event["id"], name="Prova B", order_num=2
    )
    a1 = await create_heat_in_prova(
        client, prova_a["id"], name="A1", order_num=1
    )
    a2 = await create_heat_in_prova(
        client, prova_a["id"], name="A2", order_num=2
    )
    b1 = await create_heat_in_prova(
        client, prova_b["id"], name="B1", order_num=1
    )
    b2 = await create_heat_in_prova(
        client, prova_b["id"], name="B2", order_num=2
    )
    return event, prova_a, prova_b, [a1, a2, b1, b2]


@pytest.mark.asyncio
async def test_heat_payload_has_global_event_sequence(client):
    event, prova_a, prova_b, _ = await _four_heats(client)

    heats = (await client.get(f"/api/events/{event['id']}/heats")).json()
    assert [heat["name"] for heat in heats] == ["A1", "A2", "B1", "B2"]
    assert [heat["event_seq"] for heat in heats] == [1, 2, 3, 4]
    assert [heat["prova_order_num"] for heat in heats] == [1, 1, 2, 2]
    assert [heat["prova_name"] for heat in heats] == [
        "Prova A",
        "Prova A",
        "Prova B",
        "Prova B",
    ]
    assert [heat["heat_index_in_prova"] for heat in heats] == [1, 2, 1, 2]
    assert [heat["heats_in_prova"] for heat in heats] == [2, 2, 2, 2]
    # order_num isolado repete entre provas — nao pode ser usado para ordenar.
    assert [heat["order_num"] for heat in heats] == [1, 2, 1, 2]


@pytest.mark.asyncio
async def test_prova_heats_keep_global_event_sequence(client):
    event, _, prova_b, _ = await _four_heats(client)

    heats = (await client.get(f"/api/provas/{prova_b['id']}/heats")).json()
    assert [heat["name"] for heat in heats] == ["B1", "B2"]
    assert [heat["event_seq"] for heat in heats] == [3, 4]
    assert [heat["heat_index_in_prova"] for heat in heats] == [1, 2]


@pytest.mark.asyncio
async def test_single_heat_payload_has_sequence_fields(client):
    event, _, _, (a1, *_rest) = await _four_heats(client)

    # Reordenar provas muda a sequencia global de todas as baterias.
    heats = (await client.get(f"/api/events/{event['id']}/heats")).json()
    response = await client.put(
        f"/api/events/{event['id']}/provas/order",
        json={"ids": [heats[2]["prova_id"], heats[0]["prova_id"]]},
    )
    assert response.status_code == 200, response.text

    heat = (
        await client.get(f"/api/provas/{a1['prova_id']}/heats")
    ).json()[0]
    assert heat["event_seq"] == 3
    assert heat["prova_order_num"] == 2
