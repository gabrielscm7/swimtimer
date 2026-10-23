"""GET /api/provas/{id}/summary — cabecalho, progresso e ranking da prova."""
import asyncio

import pytest

from tests.conftest import (
    create_athlete,
    create_event,
    create_heat,
    ready_all,
)


async def _finish_heat(client, prova_id, heat, athletes):
    await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={
            "lanes": [
                {"lane_number": index, "athlete_id": athlete["id"]}
                for index, athlete in enumerate(athletes, start=1)
            ]
        },
    )
    await client.post(f"/api/heats/{heat['id']}/open-ready-check")
    current = next(
        item
        for item in (
            await client.get(f"/api/provas/{prova_id}/heats")
        ).json()
        if item["id"] == heat["id"]
    )
    await ready_all(client, current)
    await client.post(f"/api/heats/{heat['id']}/start")
    await asyncio.sleep(0.01)
    for lane in current["heat_lanes"]:
        await client.post(f"/api/lanes/{lane['id']}/finish")


@pytest.mark.asyncio
async def test_summary_has_header_progress_and_own_classification(client):
    event = await create_event(client)
    first = await create_heat(
        client,
        event["id"],
        name="Bateria 1",
        stroke="livre",
        naipe="MISTO",
        category="mirim",
        distance_m=100,
    )
    prova = (await client.get(f"/api/provas/{first['prova_id']}")).json()
    second = await create_heat(
        client,
        event["id"],
        name="Bateria 2",
        stroke="livre",
        naipe="MISTO",
        category="mirim",
        distance_m=100,
    )
    await create_heat(
        client,
        event["id"],
        name="Outra bateria",
        stroke="costas",
        distance_m=50,
    )

    ana = await create_athlete(
        client, event["id"], name="Ana", naipe="F", category="mirim"
    )
    bia = await create_athlete(
        client, event["id"], name="Bia", naipe="F", category="mirim"
    )
    await _finish_heat(client, prova["id"], first, [ana])

    body = (
        await client.get(f"/api/provas/{prova['id']}/summary")
    ).json()
    assert body["name"] == "100 m Livre · Misto · Mirim"
    assert body["naipe"] == "MISTO"
    assert body["category"] == "mirim"
    assert body["distance_m"] == 100
    assert body["heat_count"] == 2
    assert body["heats_finished"] == 1
    assert [heat["name"] for heat in body["heats"]] == [
        "Bateria 1",
        "Bateria 2",
    ]
    assert [heat["heat_index_in_prova"] for heat in body["heats"]] == [1, 2]
    assert all(heat["heats_in_prova"] == 2 for heat in body["heats"])
    assert body["classification"]["is_provisional"] is True
    assert body["classification"]["mixed_ranking"] == "both"
    # Classificacao SO desta prova: Bia ainda nao entrou, Ana sim.
    assert [
        entry["participant_name"]
        for entry in body["classification"]["standings"]
    ] == ["Ana"]

    await _finish_heat(client, prova["id"], second, [bia])
    final = (
        await client.get(f"/api/provas/{prova['id']}/summary")
    ).json()
    assert final["heats_finished"] == 2
    assert final["classification"]["is_provisional"] is False
    assert len(final["classification"]["standings"]) == 2


@pytest.mark.asyncio
async def test_summary_returns_404_for_unknown_prova(client):
    response = await client.get("/api/provas/inexistente/summary")
    assert response.status_code == 404
    assert response.json()["detail"] == "prova_nao_encontrada"
