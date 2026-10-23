import pytest

from tests.conftest import (
    create_athlete,
    create_event,
    create_heat,
    create_team,
)


async def _get_heat(client, event_id, heat_id):
    heats = (await client.get(f"/api/events/{event_id}/heats")).json()
    return next(heat for heat in heats if heat["id"] == heat_id)


@pytest.mark.asyncio
async def test_create_and_list_athlete(client):
    event = await create_event(client)
    team = await create_team(client, event["id"], "Leões")

    athlete = await create_athlete(
        client,
        event["id"],
        name="Ana Souza",
        naipe="F",
        category="mirim",
        team_id=team["id"],
    )
    assert athlete["name"] == "Ana Souza"
    assert athlete["naipe"] == "F"
    assert athlete["category"] == "mirim"
    assert athlete["team_id"] == team["id"]
    assert athlete["team_name"] == "Leões"

    listing = await client.get(f"/api/events/{event['id']}/athletes")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == athlete["id"]

    teams = (await client.get(f"/api/events/{event['id']}/teams")).json()
    assert teams[0]["athlete_count"] == 1


@pytest.mark.asyncio
async def test_athlete_duplicate_rejected_case_insensitive(client):
    event = await create_event(client)
    await create_athlete(client, event["id"], name="Ana Souza")

    response = await client.post(
        f"/api/events/{event['id']}/athletes",
        json={"name": "ana souza", "naipe": "F"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "atleta_duplicado"


@pytest.mark.asyncio
async def test_athlete_validation(client):
    event = await create_event(client)
    other_event = await create_event(client, name="Outro")
    other_team = await create_team(client, other_event["id"])

    invalid_naipe = await client.post(
        f"/api/events/{event['id']}/athletes",
        json={"name": "Ana", "naipe": "X"},
    )
    assert invalid_naipe.status_code == 422

    blank_name = await client.post(
        f"/api/events/{event['id']}/athletes",
        json={"name": "   ", "naipe": "F"},
    )
    assert blank_name.status_code == 422

    foreign_team = await client.post(
        f"/api/events/{event['id']}/athletes",
        json={"name": "Ana", "naipe": "F", "team_id": other_team["id"]},
    )
    assert foreign_team.status_code == 404
    assert foreign_team.json()["detail"] == "equipe_nao_encontrada"


@pytest.mark.asyncio
async def test_list_filters_and_pagination(client):
    event = await create_event(client)
    leoes = await create_team(client, event["id"], "Leões")
    tubaroes = await create_team(client, event["id"], "Tubarões")

    await create_athlete(
        client, event["id"], name="Ana", naipe="F",
        category="mirim", team_id=leoes["id"],
    )
    await create_athlete(
        client, event["id"], name="Bia", naipe="F",
        category="petiz", team_id=tubaroes["id"],
    )
    await create_athlete(
        client, event["id"], name="Caio", naipe="M",
        category="mirim", team_id=leoes["id"],
    )

    url = f"/api/events/{event['id']}/athletes"
    assert (await client.get(url, params={"naipe": "M"})).json()["total"] == 1
    assert (
        await client.get(url, params={"category": "mirim"})
    ).json()["total"] == 2
    assert (
        await client.get(url, params={"team_id": tubaroes["id"]})
    ).json()["total"] == 1
    assert (await client.get(url, params={"q": "an"})).json()["total"] == 1

    page = (await client.get(url, params={"limit": 1, "offset": 1})).json()
    assert page["total"] == 3
    assert len(page["items"]) == 1

    invalid = await client.get(url, params={"naipe": "Z"})
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "naipe_invalido"


@pytest.mark.asyncio
async def test_lane_uses_athlete_and_stays_in_sync(client):
    event = await create_event(client)
    team_a = await create_team(client, event["id"], "Equipe A")
    team_b = await create_team(client, event["id"], "Equipe B")
    athlete = await create_athlete(
        client, event["id"], name="Ana", naipe="F", team_id=team_a["id"]
    )
    heat = await create_heat(client, event["id"])

    response = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={
            "lanes": [
                {"lane_number": 1, "athlete_id": athlete["id"]},
                {"lane_number": 2, "participant_name": "Manual"},
            ]
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    lane = payload["heat_lanes"][0]
    assert lane["athlete_id"] == athlete["id"]
    assert lane["participant_name"] == "Ana"
    assert lane["team_id"] == team_a["id"]
    assert lane["naipe"] == "F"

    response = await client.patch(
        f"/api/athletes/{athlete['id']}",
        json={"name": "Ana Lima", "team_id": team_b["id"]},
    )
    assert response.status_code == 200, response.text

    updated = await _get_heat(client, event["id"], heat["id"])
    updated_lane = updated["heat_lanes"][0]
    assert updated_lane["participant_name"] == "Ana Lima"
    assert updated_lane["team_id"] == team_b["id"]
    assert updated_lane["team"] == "Equipe B"


@pytest.mark.asyncio
async def test_athlete_cross_event_rejected_in_lane(client):
    event = await create_event(client)
    other_event = await create_event(client, name="Outro")
    athlete = await create_athlete(client, other_event["id"])
    heat = await create_heat(client, event["id"])

    response = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 1, "athlete_id": athlete["id"]}]},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "atleta_nao_encontrado"


@pytest.mark.asyncio
async def test_delete_athlete_blocked_when_in_use(client):
    event = await create_event(client)
    athlete = await create_athlete(client, event["id"])
    heat = await create_heat(client, event["id"])
    await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 1, "athlete_id": athlete["id"]}]},
    )

    blocked = await client.delete(f"/api/athletes/{athlete['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "atleta_em_uso"

    cleared = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 1}]},
    )
    assert cleared.status_code == 200, cleared.text
    removed = await client.delete(f"/api/athletes/{athlete['id']}")
    assert removed.status_code == 204


@pytest.mark.asyncio
async def test_delete_team_blocked_when_has_athletes(client):
    event = await create_event(client)
    team = await create_team(client, event["id"])
    await create_athlete(client, event["id"], team_id=team["id"])

    response = await client.delete(f"/api/teams/{team['id']}")
    assert response.status_code == 409
    assert response.json()["detail"] == "equipe_em_uso"


@pytest.mark.asyncio
async def test_get_athlete_not_found(client):
    response = await client.get("/api/athletes/inexistente")
    assert response.status_code == 404
    assert response.json()["detail"] == "atleta_nao_encontrado"


@pytest.mark.asyncio
async def test_update_athlete_rejects_null_name(client):
    event = await create_event(client)
    athlete = await create_athlete(client, event["id"])
    response = await client.patch(
        f"/api/athletes/{athlete['id']}", json={"name": None}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "nome_obrigatorio"


@pytest.mark.asyncio
async def test_homonimos_mesma_equipe_com_codigos_distintos(client):
    event = await create_event(client)
    team = await create_team(client, event["id"], "Leões")
    first = await create_athlete(
        client,
        event["id"],
        name="João Silva",
        naipe="M",
        team_id=team["id"],
        registration_code="A-001",
    )
    second = await create_athlete(
        client,
        event["id"],
        name="João Silva",
        naipe="M",
        team_id=team["id"],
        registration_code="A-002",
    )
    assert first["registration_code"] == "A-001"
    assert second["registration_code"] == "A-002"

    duplicate = await client.post(
        f"/api/events/{event['id']}/athletes",
        json={
            "name": "João Silva",
            "naipe": "M",
            "team_id": team["id"],
            "registration_code": "A-001",
        },
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["detail"] == "atleta_duplicado"


@pytest.mark.asyncio
async def test_update_registration_code(client):
    event = await create_event(client)
    athlete = await create_athlete(client, event["id"], name="Ana")
    response = await client.patch(
        f"/api/athletes/{athlete['id']}",
        json={"registration_code": "  B-010  "},
    )
    assert response.status_code == 200, response.text
    assert response.json()["registration_code"] == "B-010"

    cleared = await client.patch(
        f"/api/athletes/{athlete['id']}",
        json={"registration_code": "   "},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["registration_code"] is None
