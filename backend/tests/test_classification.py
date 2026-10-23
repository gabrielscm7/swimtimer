"""Testes da classificacao consolidada por menor tempo."""
import asyncio

import pytest

from app import database as database_module
from app.classification import build_classification, rank_valid
from app.models import HeatLane
from tests.conftest import (
    configure_lanes,
    create_event,
    create_heat,
    create_heat_in_prova,
    create_prova,
    ready_all,
)


def _lap_dict(lane_id, lane_number, time_ms, status="finished", name=None):
    return {
        "id": lane_id,
        "lane_number": lane_number,
        "participant_name": name or f"Atleta {lane_number}",
        "team_id": None,
        "status": status,
        "race_time_ms": time_ms,
    }


def _heat(heat_id, order_num, lanes, status="finished"):
    return {
        "id": heat_id,
        "name": f"Bateria {order_num}",
        "order_num": order_num,
        "status": status,
        "distance_m": 100,
        "lanes": lanes,
    }


def test_rank_lowest_time_independent_of_heat_order():
    heats = [
        _heat(
            "h1",
            1,
            [
                _lap_dict("a", 4, 62400, name="Atleta A"),
                _lap_dict("b", 5, 59800, name="Atleta B"),
            ],
        ),
        _heat(
            "h2",
            2,
            [
                _lap_dict("c", 3, 61100, name="Atleta C"),
                _lap_dict("d", 6, 60200, name="Atleta D"),
            ],
        ),
    ]
    result = build_classification(
        heats=heats,
        team_map={},
        pool_distance_m=25,
    )
    assert [entry["participant_name"] for entry in result["standings"]] == [
        "Atleta B",
        "Atleta D",
        "Atleta C",
        "Atleta A",
    ]
    assert [entry["position"] for entry in result["standings"]] == [1, 2, 3, 4]
    assert [entry["race_time_ms"] for entry in result["standings"]] == [
        59800,
        60200,
        61100,
        62400,
    ]
    assert result["is_provisional"] is False
    assert result["status"] == "finished"


def test_ties_share_position_and_are_flagged():
    entries = [
        {
            "lane_id": "a",
            "lane_number": 1,
            "participant_name": "A",
            "team_name": None,
            "classification_status": "valid",
            "race_time_ms": 60000,
            "tied": False,
            "position": None,
        },
        {
            "lane_id": "b",
            "lane_number": 2,
            "participant_name": "B",
            "team_name": None,
            "classification_status": "valid",
            "race_time_ms": 60000,
            "tied": False,
            "position": None,
        },
        {
            "lane_id": "c",
            "lane_number": 3,
            "participant_name": "C",
            "team_name": None,
            "classification_status": "valid",
            "race_time_ms": 61000,
            "tied": False,
            "position": None,
        },
        {
            "lane_id": "d",
            "lane_number": 4,
            "participant_name": "D",
            "team_name": None,
            "classification_status": "valid",
            "race_time_ms": 62000,
            "tied": False,
            "position": None,
        },
    ]
    ranked = rank_valid(entries)
    assert [entry["position"] for entry in ranked] == [1, 1, 3, 4]
    assert ranked[0]["tied"] is True
    assert ranked[1]["tied"] is True
    assert ranked[2]["tied"] is False


def test_invalid_results_never_win():
    heats = [
        _heat(
            "h1",
            1,
            [
                _lap_dict("dq", 1, 50000, status="dq", name="DQ"),
                _lap_dict("none", 2, None, name="Sem tempo"),
                _lap_dict("ok", 3, 60000, name="Ok"),
                _lap_dict("active", 4, None, status="active", name="Em prova"),
            ],
        )
    ]
    result = build_classification(
        heats=heats,
        team_map={},
        pool_distance_m=25,
    )
    assert [entry["participant_name"] for entry in result["standings"]] == ["Ok"]
    statuses = {
        entry["participant_name"]: entry["classification_status"]
        for entry in result["excluded"]
    }
    assert statuses == {
        "DQ": "dq",
        "Sem tempo": "no_time",
        "Em prova": "pending",
    }


def test_group_always_consolidates_and_keeps_batteries():
    heats = [
        _heat("h1", 1, [_lap_dict("a", 1, 60000)]),
        _heat("h2", 2, [_lap_dict("b", 1, 59000)]),
    ]
    result = build_classification(
        heats=heats,
        team_map={},
        pool_distance_m=25,
    )
    assert [entry["lane_id"] for entry in result["standings"]] == ["b", "a"]
    assert len(result["battery_results"]) == 2
    assert result["battery_results"][0]["entries"][0]["lane_id"] == "a"
    assert result["battery_results"][1]["entries"][0]["lane_id"] == "b"


def test_provisional_until_all_batteries_finish():
    heats = [
        _heat("h1", 1, [_lap_dict("a", 1, 60000)]),
        _heat("h2", 2, [_lap_dict("b", 1, None, status="active")], "active"),
    ]
    result = build_classification(
        heats=heats,
        team_map={},
        pool_distance_m=25,
    )
    assert result["is_provisional"] is True
    assert result["status"] == "in_progress"
    assert [entry["lane_id"] for entry in result["standings"]] == ["a"]


async def _create_battery(client, prova_id, name):
    heat = await create_heat_in_prova(
        client, prova_id, name=name, distance_m=100
    )
    return await configure_lanes(client, heat["id"], [(1, name)])


async def _finish_battery(client, heat):
    await client.post(f"/api/heats/{heat['id']}/open-ready-check")
    heats = (await client.get(f"/api/provas/{heat['prova_id']}/heats")).json()
    current = next(item for item in heats if item["id"] == heat["id"])
    await ready_all(client, current)
    response = await client.post(f"/api/heats/{heat['id']}/start")
    assert response.status_code == 200, response.text
    await asyncio.sleep(0.01)
    lane = current["heat_lanes"][0]
    finish = await client.post(f"/api/lanes/{lane['id']}/finish")
    assert finish.status_code == 200, finish.text
    return lane["id"]


async def _set_time(lane_id, time_ms):
    async with database_module.AsyncSessionLocal() as session:
        lane = await session.get(HeatLane, lane_id)
        lane.race_time_ms = time_ms
        await session.commit()


@pytest.mark.asyncio
async def test_api_consolidates_four_batteries_by_lowest_time(client):
    event = await create_event(client)
    first = await configure_lanes(
        client,
        (
            await create_heat(
                client, event["id"], name="Bateria 1", distance_m=100
            )
        )["id"],
        [(1, "A")],
    )
    prova_id = first["prova_id"]
    times = [62400, 59800, 61100, 60200]
    lanes = [await _finish_battery(client, first)]
    for index, name in enumerate(["B", "C", "D"], start=2):
        heat = await _create_battery(client, prova_id, f"Bateria {index}")
        lane_id = await _finish_battery(client, heat)
        lanes.append(lane_id)
    for lane_id, time_ms in zip(lanes, times):
        await _set_time(lane_id, time_ms)

    response = await client.get(
        f"/api/provas/{prova_id}/classification"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_provisional"] is False
    assert body["status"] == "finished"
    assert [entry["race_time_ms"] for entry in body["standings"]] == [
        59800,
        60200,
        61100,
        62400,
    ]
    assert [entry["lane_id"] for entry in body["standings"]] == [
        lanes[1],
        lanes[3],
        lanes[2],
        lanes[0],
    ]
    assert body["standings"][0]["position"] == 1


@pytest.mark.asyncio
async def test_api_classification_updates_after_time_correction(client):
    event = await create_event(client)
    prova = await create_prova(client, event["id"], distance_m=100)
    first = await _create_battery(client, prova["id"], "Bateria 1")
    second = await _create_battery(client, prova["id"], "Bateria 2")
    first_lane = await _finish_battery(client, first)
    second_lane = await _finish_battery(client, second)
    await _set_time(first_lane, 61000)
    await _set_time(second_lane, 60000)

    before = (
        await client.get(f"/api/provas/{prova['id']}/classification")
    ).json()
    assert before["standings"][0]["lane_id"] == second_lane

    await _set_time(first_lane, 59000)
    after = (
        await client.get(f"/api/provas/{prova['id']}/classification")
    ).json()
    assert after["standings"][0]["lane_id"] == first_lane
    assert after["standings"][0]["race_time_ms"] == 59000


@pytest.mark.asyncio
async def test_api_provisional_while_battery_pending(client):
    event = await create_event(client)
    prova = await create_prova(client, event["id"], distance_m=100)
    finished_heat = await _create_battery(client, prova["id"], "Bateria 1")
    await _create_battery(client, prova["id"], "Bateria 2")
    finished_lane = await _finish_battery(client, finished_heat)
    await _set_time(finished_lane, 60000)

    body = (
        await client.get(f"/api/provas/{prova['id']}/classification")
    ).json()
    assert body["is_provisional"] is True
    assert body["status"] == "in_progress"
    assert len(body["standings"]) == 1


@pytest.mark.asyncio
async def test_api_classify_alone_creates_own_group(client):
    event = await create_event(client)
    shared = await create_heat(client, event["id"], distance_m=100)
    isolated = await create_heat(
        client, event["id"], distance_m=100, classify_alone=True
    )
    assert isolated["prova_id"] != shared["prova_id"]

    isolated = await configure_lanes(
        client, isolated["id"], [(1, "Isolada")]
    )
    isolated_lane = await _finish_battery(client, isolated)
    await _set_time(isolated_lane, 60000)

    body = (
        await client.get(f"/api/provas/{isolated['prova_id']}/classification")
    ).json()
    assert len(body["standings"]) == 1
    assert len(body["battery_results"]) == 1
