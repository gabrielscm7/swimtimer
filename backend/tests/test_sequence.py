import pytest

from tests.conftest import create_event, create_heat


async def _four_heats(client):
    event = await create_event(client)
    a1 = await create_heat(client, event["id"], name="A1", stroke="livre")
    a2 = await create_heat(client, event["id"], name="A2", stroke="livre")
    b1 = await create_heat(client, event["id"], name="B1", stroke="costas")
    b2 = await create_heat(client, event["id"], name="B2", stroke="costas")
    return event, a1, a2, b1, b2


@pytest.mark.asyncio
async def test_heat_payload_has_global_event_sequence(client):
    event, *_ = await _four_heats(client)

    heats = (await client.get(f"/api/events/{event['id']}/heats")).json()
    assert [heat["name"] for heat in heats] == ["A1", "A2", "B1", "B2"]
    assert [heat["event_seq"] for heat in heats] == [1, 2, 3, 4]
    assert [heat["prova_order_num"] for heat in heats] == [1, 1, 2, 2]
    assert [heat["prova_name"] for heat in heats] == [
        "25 m Livre · Misto",
        "25 m Livre · Misto",
        "25 m Costas · Misto",
        "25 m Costas · Misto",
    ]
    assert [heat["heat_index_in_prova"] for heat in heats] == [1, 2, 1, 2]
    assert [heat["heats_in_prova"] for heat in heats] == [2, 2, 2, 2]
    # order_num e a ordem global do evento (ADR-012).
    assert [heat["order_num"] for heat in heats] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_prova_heats_keep_global_event_sequence(client):
    event, *_, b1, b2 = await _four_heats(client)

    heats = (
        await client.get(f"/api/provas/{b1['prova_id']}/heats")
    ).json()
    assert [heat["name"] for heat in heats] == ["B1", "B2"]
    assert [heat["event_seq"] for heat in heats] == [3, 4]
    assert [heat["heat_index_in_prova"] for heat in heats] == [1, 2]


@pytest.mark.asyncio
async def test_single_heat_payload_has_sequence_fields(client):
    event, a1, a2, b1, b2 = await _four_heats(client)

    response = await client.patch(
        f"/api/events/{event['id']}/heats/order",
        json={"ids": [b2["id"], b1["id"], a2["id"], a1["id"]]},
    )
    assert response.status_code == 200, response.text

    heats = (await client.get(f"/api/events/{event['id']}/heats")).json()
    by_id = {heat["id"]: heat for heat in heats}
    assert by_id[a1["id"]]["event_seq"] == 4
    assert by_id[a1["id"]]["prova_order_num"] == 2
    assert by_id[a1["id"]]["heat_index_in_prova"] == 2
