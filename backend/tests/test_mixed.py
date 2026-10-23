"""Prova mista (naipe MISTO) e modos de ranking (overall/by_naipe/both)."""
import asyncio

import pytest

from app import database as database_module
from app.classification import build_classification
from app.models import HeatLane
from tests.conftest import (
    create_athlete,
    create_event,
    create_heat_in_prova,
    create_prova,
    ready_all,
)


def _lane(lane_id, lane_number, time_ms, naipe, status="finished"):
    return {
        "id": lane_id,
        "lane_number": lane_number,
        "naipe": naipe,
        "participant_name": f"{naipe}-{lane_number}",
        "team_id": None,
        "status": status,
        "race_time_ms": time_ms,
    }


def _heat(lanes):
    return {
        "id": "h1",
        "name": "Bateria 1",
        "order_num": 1,
        "status": "finished",
        "distance_m": 100,
        "lanes": lanes,
    }


def _classification(mixed_ranking):
    heats = [
        _heat(
            [
                _lane("m1", 1, 60000, "M"),
                _lane("f1", 2, 60000, "F"),
                _lane("m2", 3, 61000, "M"),
                _lane("f2", 4, 62000, "F"),
                _lane("free", 5, 60500, None),
            ]
        )
    ]
    return build_classification(
        consolidate_results=True,
        heats=heats,
        team_map={},
        pool_distance_m=25,
        mixed_ranking=mixed_ranking,
    )


def test_both_returns_overall_and_by_naipe():
    result = _classification("both")
    assert [entry["lane_id"] for entry in result["standings"]] == [
        "m1",
        "f1",
        "free",
        "m2",
        "f2",
    ]
    # Empates no geral compartilham a posicao.
    assert [entry["position"] for entry in result["standings"]] == [
        1,
        1,
        3,
        4,
        5,
    ]
    by_naipe = result["standings_by_naipe"]
    assert set(by_naipe.keys()) == {"M", "F"}
    # Empates sao tratados separadamente por naipe: ambos 1o do seu naipe.
    assert [entry["lane_id"] for entry in by_naipe["M"]] == ["m1", "m2"]
    assert [entry["position"] for entry in by_naipe["M"]] == [1, 2]
    assert [entry["lane_id"] for entry in by_naipe["F"]] == ["f1", "f2"]
    assert [entry["position"] for entry in by_naipe["F"]] == [1, 2]
    # Participante sem naipe fica fora do ranking por naipe.
    all_naipe_lanes = {
        entry["lane_id"] for entries in by_naipe.values() for entry in entries
    }
    assert "free" not in all_naipe_lanes
    assert result["standings"][0]["tied"] is True
    # Overall e by_naipe nao compartilham posicao (copias independentes).
    assert result["standings"][1]["position"] == 1
    assert by_naipe["F"][0]["position"] == 1


def test_by_naipe_only_omits_overall_standings():
    result = _classification("by_naipe")
    assert result["standings"] == []
    assert result["standings_by_naipe"] is not None


def test_overall_only_omits_by_naipe():
    result = _classification("overall")
    assert len(result["standings"]) == 5
    assert result["standings_by_naipe"] is None


@pytest.mark.asyncio
async def test_prova_misto_accepts_m_and_f_and_reports_rankings(client):
    event = await create_event(client)
    response = await client.post(
        f"/api/events/{event['id']}/provas",
        json={
            "name": "100 Livres Misto",
            "distance_m": 100,
            "naipe": "MISTO",
            "mixed_ranking": "both",
        },
    )
    assert response.status_code == 201, response.text
    prova = response.json()
    assert prova["naipe"] == "MISTO"
    assert prova["mixed_ranking"] == "both"

    male = await create_athlete(
        client, event["id"], name="Mario", naipe="M"
    )
    female = await create_athlete(
        client, event["id"], name="Maria", naipe="F"
    )
    heat = await create_heat_in_prova(
        client, prova["id"], distance_m=100
    )
    lanes = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={
            "lanes": [
                {"lane_number": 1, "athlete_id": male["id"]},
                {"lane_number": 2, "athlete_id": female["id"]},
            ]
        },
    )
    assert lanes.status_code == 200, lanes.text

    await client.post(f"/api/heats/{heat['id']}/open-ready-check")
    current = (
        await client.get(f"/api/provas/{prova['id']}/heats")
    ).json()[0]
    await ready_all(client, current)
    await client.post(f"/api/heats/{heat['id']}/start")
    await asyncio.sleep(0.01)
    lane_by_number = {
        lane["lane_number"]: lane for lane in current["heat_lanes"]
    }
    await client.post(f"/api/lanes/{lane_by_number[1]['id']}/finish")
    await client.post(f"/api/lanes/{lane_by_number[2]['id']}/finish")

    async with database_module.AsyncSessionLocal() as session:
        lane = await session.get(HeatLane, lane_by_number[1]["id"])
        lane.race_time_ms = 60000
        await session.commit()

    body = (
        await client.get(f"/api/provas/{prova['id']}/classification")
    ).json()
    assert body["mixed_ranking"] == "both"
    assert body["standings_by_naipe"] is not None
    assert [entry["naipe"] for entry in body["standings_by_naipe"]["M"]] == ["M"]
    assert [entry["naipe"] for entry in body["standings_by_naipe"]["F"]] == ["F"]


@pytest.mark.asyncio
async def test_mixed_ranking_defaults_to_both(client):
    event = await create_event(client)
    response = await client.post(
        f"/api/events/{event['id']}/provas",
        json={"name": "Sem ranking explicito"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["mixed_ranking"] == "both"


@pytest.mark.asyncio
async def test_athlete_cannot_use_misto_naipe(client):
    event = await create_event(client)
    response = await client.post(
        f"/api/events/{event['id']}/athletes",
        json={"name": "Misto", "naipe": "MISTO"},
    )
    assert response.status_code == 422, response.text
