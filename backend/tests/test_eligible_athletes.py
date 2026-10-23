"""GET /api/heats/{id}/eligible-athletes — elegibilidade e alocacao no grupo."""
import pytest

from tests.conftest import (
    create_athlete,
    create_event,
    create_heat,
    create_team,
)


@pytest.mark.asyncio
async def test_filtra_por_naipe_e_categoria(client):
    event = await create_event(client)
    team = await create_team(client, event["id"], "Leoes")
    male_mirim = await create_athlete(
        client, event["id"], name="Mario", naipe="M",
        category="mirim", team_id=team["id"],
    )
    female_mirim = await create_athlete(
        client, event["id"], name="Maria", naipe="F",
        category="mirim", team_id=team["id"],
    )
    male_petiz = await create_athlete(
        client, event["id"], name="Pedro", naipe="M",
        category="petiz", team_id=team["id"],
    )
    sem_categoria = await create_athlete(
        client, event["id"], name="Ana", naipe="M",
        category=None, team_id=team["id"],
    )
    other_team = await create_team(client, event["id"], "Tubaroes")
    await create_athlete(
        client, event["id"], name="Bia", naipe="M",
        category="mirim", team_id=other_team["id"],
    )

    heat = await create_heat(
        client, event["id"], naipe="M", category="mirim"
    )
    response = await client.get(
        f"/api/heats/{heat['id']}/eligible-athletes",
        params={"team_id": team["id"]},
    )
    assert response.status_code == 200, response.text
    names = [item["name"] for item in response.json()]
    assert names == ["Mario"]
    assert response.json()[0]["id"] == male_mirim["id"]
    assert female_mirim["id"] not in {item["id"] for item in response.json()}
    assert male_petiz["id"] not in {item["id"] for item in response.json()}
    assert sem_categoria["id"] not in {item["id"] for item in response.json()}


@pytest.mark.asyncio
async def test_misto_e_categoria_livre_aceitam_todos(client):
    event = await create_event(client)
    team = await create_team(client, event["id"], "Leoes")
    for name, naipe, category in (
        ("Mario", "M", "mirim"),
        ("Maria", "F", "petiz"),
        ("Ana", "M", None),
    ):
        await create_athlete(
            client, event["id"], name=name, naipe=naipe,
            category=category, team_id=team["id"],
        )

    heat = await create_heat(
        client, event["id"], naipe="MISTO", category="livre"
    )
    response = await client.get(
        f"/api/heats/{heat['id']}/eligible-athletes",
        params={"team_id": team["id"]},
    )
    assert response.status_code == 200, response.text
    assert len(response.json()) == 3


@pytest.mark.asyncio
async def test_marca_alocados_no_grupo(client):
    event = await create_event(client)
    team = await create_team(client, event["id"], "Leoes")
    athlete = await create_athlete(
        client, event["id"], name="Mario", naipe="M",
        category="mirim", team_id=team["id"],
    )
    await create_athlete(
        client, event["id"], name="Pedro", naipe="M",
        category="mirim", team_id=team["id"],
    )
    first = await create_heat(
        client, event["id"], stroke="livre", naipe="M", category="mirim"
    )
    second = await create_heat(
        client, event["id"], stroke="livre", naipe="M", category="mirim"
    )
    assert first["prova_id"] == second["prova_id"]

    response = await client.post(
        f"/api/heats/{first['id']}/lanes",
        json={"lanes": [{"lane_number": 1, "athlete_id": athlete["id"]}]},
    )
    assert response.status_code == 200, response.text

    response = await client.get(
        f"/api/heats/{second['id']}/eligible-athletes",
        params={"team_id": team["id"]},
    )
    by_id = {item["id"]: item for item in response.json()}
    assert by_id[athlete["id"]]["allocated"] is True
    assert by_id[athlete["id"]]["allocated_heat_id"] == first["id"]
    assert by_id[athlete["id"]]["allocated_heat_name"] == first["name"]

    # A propria bateria tambem marca o atleta ja alocado nela.
    own = await client.get(
        f"/api/heats/{first['id']}/eligible-athletes",
        params={"team_id": team["id"]},
    )
    own_by_id = {item["id"]: item for item in own.json()}
    assert own_by_id[athlete["id"]]["allocated"] is True


@pytest.mark.asyncio
async def test_equipe_de_outro_evento_404(client):
    event = await create_event(client)
    other = await create_event(client, name="Outro")
    team = await create_team(client, other["id"])
    heat = await create_heat(client, event["id"])
    response = await client.get(
        f"/api/heats/{heat['id']}/eligible-athletes",
        params={"team_id": team["id"]},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "equipe_nao_encontrada"
