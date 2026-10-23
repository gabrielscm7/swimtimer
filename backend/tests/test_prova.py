import pytest

from tests.conftest import (
    create_event,
    create_heat,
    create_team,
)


@pytest.mark.asyncio
async def test_creating_heats_creates_group_prova(client):
    event = await create_event(client)
    first = await create_heat(
        client, event["id"], name="B1", stroke="livre", distance_m=25
    )
    second = await create_heat(
        client, event["id"], name="B2", stroke="livre", distance_m=25
    )

    assert first["prova_id"] == second["prova_id"]
    assert first["event_id"] == event["id"]
    assert (first["order_num"], second["order_num"]) == (1, 2)

    detail = (await client.get(f"/api/provas/{first['prova_id']}")).json()
    assert detail["heat_count"] == 2
    assert [heat["id"] for heat in detail["heats"]] == [
        first["id"],
        second["id"],
    ]
    assert detail["classification_criterion"] == "lowest_time"
    assert detail["status"] == "scheduled"
    assert detail["name"] == "25 m Livre · Misto"

    lista = (await client.get(f"/api/events/{event['id']}/provas")).json()
    assert len(lista) == 1
    assert lista[0]["id"] == first["prova_id"]


@pytest.mark.asyncio
async def test_heat_inherits_event_and_rejects_foreign_team(client):
    event = await create_event(client)
    other = await create_event(client, name="Outro")
    heat = await create_heat(client, event["id"])
    foreign_team = await create_team(client, other["id"], "Externa")

    assert heat["event_id"] == event["id"]
    response = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 1, "team_id": foreign_team["id"]}]},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "equipe_nao_encontrada"


@pytest.mark.asyncio
async def test_prova_attributes_follow_heat(client):
    event = await create_event(client)
    heat = await create_heat(
        client,
        event["id"],
        stroke="peito",
        distance_m=50,
        naipe="F",
        category="mirim",
    )

    detail = (await client.get(f"/api/provas/{heat['prova_id']}")).json()
    assert detail["stroke"] == "peito"
    assert detail["distance_m"] == 50
    assert detail["naipe"] == "F"
    assert detail["category"] == "mirim"
    assert detail["name"] == "50 m Peito · Feminino · Mirim"


@pytest.mark.asyncio
async def test_editing_heat_moves_it_between_groups(client):
    event = await create_event(client)
    heat = await create_heat(client, event["id"], stroke="livre")
    old_prova_id = heat["prova_id"]

    response = await client.patch(
        f"/api/heats/{heat['id']}", json={"stroke": "costas"}
    )
    assert response.status_code == 200, response.text
    moved = response.json()
    assert moved["prova_id"] != old_prova_id
    assert moved["prova_name"] == "25 m Costas · Misto"

    # A prova antiga fica vazia e sem snapshots: e removida.
    assert (
        await client.get(f"/api/provas/{old_prova_id}")
    ).status_code == 404


@pytest.mark.asyncio
async def test_delete_heat_removes_empty_prova(client):
    event = await create_event(client)
    heat = await create_heat(client, event["id"])
    response = await client.delete(f"/api/heats/{heat['id']}")
    assert response.status_code == 204, response.text
    assert (
        await client.get(f"/api/provas/{heat['prova_id']}")
    ).status_code == 404


@pytest.mark.asyncio
async def test_event_delete_removes_provas(client):
    event = await create_event(client)
    heat = await create_heat(client, event["id"])
    response = await client.delete(f"/api/events/{event['id']}")
    assert response.status_code == 204, response.text
    assert (
        await client.get(f"/api/provas/{heat['prova_id']}")
    ).status_code == 404


@pytest.mark.asyncio
async def test_prova_naipe_and_category_are_structured(client):
    event = await create_event(client)
    heat = await create_heat(
        client, event["id"], naipe="F", category="livre"
    )
    prova = (await client.get(f"/api/provas/{heat['prova_id']}")).json()
    assert prova["naipe"] == "F"
    assert prova["category"] == "livre"

    listing = (await client.get(f"/api/events/{event['id']}/provas")).json()
    assert listing[0]["naipe"] == "F"

    detail = (await client.get(f"/api/events/{event['id']}")).json()
    assert detail["provas"][0]["naipe"] == "F"


@pytest.mark.asyncio
async def test_prova_naipe_alias_and_validation(client):
    event = await create_event(client)
    heat = await create_heat(client, event["id"], naipe="masculino")
    prova = (await client.get(f"/api/provas/{heat['prova_id']}")).json()
    assert prova["naipe"] == "M"

    response = await client.post(
        f"/api/events/{event['id']}/heats",
        json={
            "heat_type": "bateria",
            "stroke": "livre",
            "distance_m": 25,
            "naipe": "X",
            "category": "livre",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_heat_naipe_moves_group(client):
    event = await create_event(client)
    heat = await create_heat(client, event["id"], naipe="M", category="mirim")
    response = await client.patch(
        f"/api/heats/{heat['id']}", json={"naipe": "F"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["naipe"] == "F"

    cleared = await client.patch(
        f"/api/heats/{heat['id']}", json={"category": None}
    )
    assert cleared.status_code == 422, cleared.text
