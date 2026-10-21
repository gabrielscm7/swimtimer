"""Testes do modelo Prova (evento -> prova -> bateria)."""
import pytest

from tests.conftest import (
    configure_lanes,
    create_event,
    create_heat,
    create_heat_in_prova,
    create_prova,
    create_team,
)


@pytest.mark.asyncio
async def test_create_event_prova_and_multiple_heats(client):
    event = await create_event(client)
    prova = await create_prova(
        client,
        event["id"],
        name="100 Livres Masculino",
        stroke="livre",
        distance_m=100,
        category="masculino",
    )
    assert prova["event_id"] == event["id"]
    assert prova["consolidate_results"] is True
    assert prova["classification_criterion"] == "lowest_time"
    assert prova["status"] == "scheduled"

    first = await create_heat_in_prova(client, prova["id"], name="Bateria 1")
    second = await create_heat_in_prova(client, prova["id"], name="Bateria 2")
    assert first["prova_id"] == prova["id"]
    assert first["event_id"] == event["id"]
    assert (first["order_num"], second["order_num"]) == (1, 2)

    detail = (await client.get(f"/api/provas/{prova['id']}")).json()
    assert detail["heat_count"] == 2
    assert [heat["id"] for heat in detail["heats"]] == [
        first["id"],
        second["id"],
    ]
    lista = (await client.get(f"/api/events/{event['id']}/provas")).json()
    assert len(lista) == 1
    assert lista[0]["id"] == prova["id"]


@pytest.mark.asyncio
async def test_heat_inherits_event_and_rejects_foreign_team(client):
    event = await create_event(client)
    other_event = await create_event(client, name="Outro evento")
    foreign_team = await create_team(client, other_event["id"], "Equipe B")
    prova = await create_prova(client, event["id"])
    heat = await create_heat_in_prova(client, prova["id"])

    assert heat["event_id"] == event["id"]

    response = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={
            "lanes": [
                {
                    "lane_number": 1,
                    "participant_name": "Ana",
                    "team_id": foreign_team["id"],
                }
            ]
        },
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "equipe_nao_encontrada"


@pytest.mark.asyncio
async def test_prova_classification_config_persists(client):
    event = await create_event(client)
    prova = await create_prova(client, event["id"], distance_m=200)

    response = await client.patch(
        f"/api/provas/{prova['id']}",
        json={
            "consolidate_results": False,
            "classification_criterion": "lowest_time",
            "category": "sub-12",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["consolidate_results"] is False

    detail = (await client.get(f"/api/provas/{prova['id']}")).json()
    assert detail["consolidate_results"] is False
    assert detail["category"] == "SUB-12"


@pytest.mark.asyncio
async def test_prova_order_unique_per_event(client):
    event = await create_event(client)
    await create_prova(client, event["id"], order_num=1)
    response = await client.post(
        f"/api/events/{event['id']}/provas",
        json={"name": "Duplicada", "order_num": 1},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "order_num_duplicado"


@pytest.mark.asyncio
async def test_prova_order_can_change_when_unique(client):
    event = await create_event(client)
    first = await create_prova(client, event["id"], order_num=1)
    await create_prova(client, event["id"], order_num=2)

    response = await client.patch(
        f"/api/provas/{first['id']}", json={"order_num": 1}
    )
    assert response.status_code == 200, response.text
    again = await client.patch(
        f"/api/provas/{first['id']}", json={"order_num": 2}
    )
    assert again.status_code == 400, again.text


@pytest.mark.asyncio
async def test_delete_prova_blocked_after_heat_started(client):
    event = await create_event(client)
    prova = await create_prova(client, event["id"])
    heat = await create_heat_in_prova(client, prova["id"])
    heat = await configure_lanes(client, heat["id"], [(1, "Ana")])
    await client.post(f"/api/heats/{heat['id']}/open-ready-check")
    await client.post(f"/api/lanes/{heat['heat_lanes'][0]['id']}/ready")
    await client.post(f"/api/heats/{heat['id']}/start")

    response = await client.delete(f"/api/provas/{prova['id']}")
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "prova_possui_baterias_iniciadas"


@pytest.mark.asyncio
async def test_delete_prova_removes_scheduled_heats(client):
    event = await create_event(client)
    prova = await create_prova(client, event["id"])
    heat = await create_heat_in_prova(client, prova["id"])
    await configure_lanes(client, heat["id"], [(1, "Ana")])

    response = await client.delete(f"/api/provas/{prova['id']}")
    assert response.status_code == 204, response.text
    assert (await client.get(f"/api/provas/{prova['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_legacy_heat_endpoint_creates_wrapper_prova(client):
    event = await create_event(client)
    heat = await create_heat(client, event["id"], name="Prova Legada")

    assert heat["prova_id"]
    prova = (await client.get(f"/api/provas/{heat['prova_id']}")).json()
    assert prova["name"] == "Prova Legada"
    assert prova["heat_count"] == 1
    assert prova["heats"][0]["id"] == heat["id"]


@pytest.mark.asyncio
async def test_event_delete_removes_provas(client):
    event = await create_event(client)
    prova = await create_prova(client, event["id"])
    heat = await create_heat_in_prova(client, prova["id"])
    await configure_lanes(client, heat["id"], [(1, "Ana")])

    response = await client.delete(f"/api/events/{event['id']}")
    assert response.status_code == 204, response.text
    assert (await client.get(f"/api/provas/{prova['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_prova_naipe_and_category_are_structured(client):
    event = await create_event(client)
    prova = await create_prova(
        client,
        event["id"],
        name="Peito 50m",
        distance_m=50,
        category="sub-12",
        naipe="f",
    )
    assert prova["naipe"] == "F"
    assert prova["category"] == "SUB-12"

    listing = (await client.get(f"/api/events/{event['id']}/provas")).json()
    assert listing[0]["naipe"] == "F"

    detail = (await client.get(f"/api/events/{event['id']}")).json()
    assert detail["provas"][0]["naipe"] == "F"


@pytest.mark.asyncio
async def test_prova_naipe_alias_and_validation(client):
    event = await create_event(client)
    prova = await create_prova(client, event["id"], naipe="Masculino")
    assert prova["naipe"] == "M"

    response = await client.post(
        f"/api/events/{event['id']}/provas",
        json={"name": "Inválida", "naipe": "X"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_prova_naipe(client):
    event = await create_event(client)
    prova = await create_prova(client, event["id"], naipe="M")

    response = await client.patch(
        f"/api/provas/{prova['id']}", json={"naipe": "feminino"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["naipe"] == "F"

    cleared = await client.patch(
        f"/api/provas/{prova['id']}", json={"naipe": None}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["naipe"] is None
