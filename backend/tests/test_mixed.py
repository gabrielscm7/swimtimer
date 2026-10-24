"""Bateria MISTO: sempre classificacao geral + por naipe (ADR-012)."""
import asyncio

import pytest

from app import database as database_module
from app.classification import build_classification
from app.models import HeatLane
from tests.conftest import (
    create_athlete,
    create_event,
    create_heat,
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
    assert [entry["lane_id"] for entry in by_naipe["M"]] == ["m1", "m2"]
    assert [entry["position"] for entry in by_naipe["M"]] == [1, 2]
    assert [entry["lane_id"] for entry in by_naipe["F"]] == ["f1", "f2"]
    assert [entry["position"] for entry in by_naipe["F"]] == [1, 2]
    all_naipe_lanes = {
        entry["lane_id"] for entries in by_naipe.values() for entry in entries
    }
    assert "free" not in all_naipe_lanes
    assert result["standings"][0]["tied"] is True
    assert result["standings"][1]["position"] == 1
    assert by_naipe["F"][0]["position"] == 1


def test_overall_only_omits_by_naipe():
    result = _classification("overall")
    assert len(result["standings"]) == 5
    assert result["standings_by_naipe"] is None


def test_nao_misto_forca_ranking_geral_mesmo_pedindo_por_naipe():
    for naipe in ("M", "F"):
        result = build_classification(
            heats=[
                _heat(
                    [
                        _lane("m1", 1, 60000, "M"),
                        _lane("f1", 2, 61000, "F"),
                    ]
                )
            ],
            team_map={},
            pool_distance_m=25,
            mixed_ranking="both",
            prova_naipe=naipe,
        )
        assert result["mixed_ranking"] == "overall"
        assert result["standings_by_naipe"] is None
        assert len(result["standings"]) == 2


def test_misto_com_um_so_naipe_devolve_grupo_vazio():
    result = build_classification(
        heats=[_heat([_lane("m1", 1, 60000, "M"), _lane("m2", 2, 61000, "M")])],
        team_map={},
        pool_distance_m=25,
        mixed_ranking="both",
        prova_naipe="MISTO",
    )
    by_naipe = result["standings_by_naipe"]
    assert set(by_naipe.keys()) == {"M", "F"}
    assert [entry["lane_id"] for entry in by_naipe["M"]] == ["m1", "m2"]
    assert by_naipe["F"] == []


@pytest.mark.asyncio
async def test_prova_misto_accepts_m_and_f_and_reports_rankings(client):
    event = await create_event(client)
    heat = await create_heat(
        client, event["id"], stroke="livre", distance_m=100, naipe="MISTO"
    )
    assert heat["prova_name"] == "100 m Livre · Misto"
    prova = (await client.get(f"/api/provas/{heat['prova_id']}")).json()
    assert prova["naipe"] == "MISTO"
    # MISTO sempre exibe geral + por naipe.
    assert prova["mixed_ranking"] == "both"

    male = await create_athlete(
        client, event["id"], name="Mario", naipe="M"
    )
    female = await create_athlete(
        client, event["id"], name="Maria", naipe="F"
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
    current = (await client.get(f"/api/heats/{heat['id']}")).json()
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
        await client.get(f"/api/provas/{heat['prova_id']}/classification")
    ).json()
    assert body["mixed_ranking"] == "both"
    assert body["standings_by_naipe"] is not None
    assert [entry["naipe"] for entry in body["standings_by_naipe"]["M"]] == ["M"]
    assert [entry["naipe"] for entry in body["standings_by_naipe"]["F"]] == ["F"]


@pytest.mark.asyncio
async def test_prova_nao_misto_usa_apenas_geral(client):
    event = await create_event(client)
    heat = await create_heat(client, event["id"], naipe="M", category="mirim")
    body = (
        await client.get(f"/api/provas/{heat['prova_id']}/classification")
    ).json()
    assert body["mixed_ranking"] == "overall"
    assert body["standings_by_naipe"] is None


@pytest.mark.asyncio
async def test_prova_misto_com_um_so_naipe_devolve_outro_vazio(client):
    event = await create_event(client)
    heat = await create_heat(
        client, event["id"], stroke="costas", distance_m=100, naipe="MISTO"
    )
    male = await create_athlete(client, event["id"], name="Mario", naipe="M")
    lanes = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 1, "athlete_id": male["id"]}]},
    )
    assert lanes.status_code == 200, lanes.text
    await client.post(f"/api/heats/{heat['id']}/open-ready-check")
    current = (await client.get(f"/api/heats/{heat['id']}")).json()
    await ready_all(client, current)
    await client.post(f"/api/heats/{heat['id']}/start")
    await asyncio.sleep(0.01)
    await client.post(f"/api/lanes/{current['heat_lanes'][0]['id']}/finish")

    body = (
        await client.get(f"/api/provas/{heat['prova_id']}/classification")
    ).json()
    assert body["mixed_ranking"] == "both"
    assert body["standings_by_naipe"]["M"]
    assert body["standings_by_naipe"]["F"] == []


@pytest.mark.asyncio
async def test_athlete_cannot_use_misto_naipe(client):
    event = await create_event(client)
    response = await client.post(
        f"/api/events/{event['id']}/athletes",
        json={"name": "Misto", "naipe": "MISTO"},
    )
    assert response.status_code == 422, response.text
