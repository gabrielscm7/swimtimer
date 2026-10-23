"""Tempo do toque, idempotência por op_id, action_log e ack via WebSocket.

Os testes usam banco em arquivo (como test_concurrency) para permitir ajustar
`started_at`/`recorded_at` diretamente e verificar efeitos colaterais.
"""
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.main as main_module
from app import database as database_module
from app.database import Base, get_db
from app.services import lane_actions
from app.models import ActionLog, Heat, HeatLane, LapEvent, ProcessedOp


@pytest_asyncio.fixture
async def client(tmp_path):
    db = tmp_path / "test_time.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db}", connect_args={"timeout": 30}
    )
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with factory() as session:
            yield session

    original = database_module.AsyncSessionLocal
    main_module.app.dependency_overrides[get_db] = override_get_db
    database_module.AsyncSessionLocal = factory
    try:
        transport = ASGITransport(app=main_module.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, factory
    finally:
        main_module.app.dependency_overrides.clear()
        database_module.AsyncSessionLocal = original
        await engine.dispose()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def _event(http):
    response = await http.post(
        "/api/events", json={"name": "Evento", "pool_length_m": 25}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _heat(http, event_id, *, heat_type="bateria", distance_m=25,
                duration_s=None):
    body = {"name": "Prova"}
    if distance_m is not None:
        body["distance_m"] = distance_m
    prova_response = await http.post(f"/api/events/{event_id}/provas", json=body)
    assert prova_response.status_code == 201, prova_response.text
    prova = prova_response.json()
    heat_body = {"name": "Bateria", "heat_type": heat_type}
    if distance_m is not None:
        heat_body["distance_m"] = distance_m
    if duration_s is not None:
        heat_body["duration_s"] = duration_s
    response = await http.post(f"/api/provas/{prova['id']}/heats", json=heat_body)
    assert response.status_code == 201, response.text
    return response.json()


async def _lanes(http, heat_id, participants):
    response = await http.post(
        f"/api/heats/{heat_id}/lanes",
        json={
            "lanes": [
                {"lane_number": number, "participant_name": name}
                for number, name in participants
            ]
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _get_heat(http, event_id, heat_id):
    heats = (await http.get(f"/api/events/{event_id}/heats")).json()
    return next(heat for heat in heats if heat["id"] == heat_id)


async def _active_bateria(http, participants):
    event = await _event(http)
    heat = await _heat(http, event["id"])
    await _lanes(http, heat["id"], participants)
    await http.post(f"/api/heats/{heat['id']}/open-ready-check")
    heat = await _get_heat(http, event["id"], heat["id"])
    for lane in heat["heat_lanes"]:
        response = await http.post(f"/api/lanes/{lane['id']}/ready")
        assert response.status_code == 200, response.text
    response = await http.post(f"/api/heats/{heat['id']}/start")
    assert response.status_code == 200, response.text
    return event, await _get_heat(http, event["id"], heat["id"])


async def _active_maratona(http, participants):
    event = await _event(http)
    heat = await _heat(
        http, event["id"], heat_type="maratona", distance_m=None, duration_s=3600
    )
    await _lanes(http, heat["id"], participants)
    await http.post(f"/api/heats/{heat['id']}/open-ready-check")
    heat = await _get_heat(http, event["id"], heat["id"])
    for lane in heat["heat_lanes"]:
        await http.post(f"/api/lanes/{lane['id']}/ready")
    response = await http.post(f"/api/heats/{heat['id']}/start")
    assert response.status_code == 200, response.text
    return event, await _get_heat(http, event["id"], heat["id"])


async def _set_started_at(factory, heat_id, started_at):
    async with factory() as session:
        heat = await session.get(Heat, heat_id)
        heat.started_at = started_at
        await session.commit()


async def _laps_count(factory, lane_id):
    async with factory() as session:
        return int(
            await session.scalar(
                select(func.count(LapEvent.id)).where(
                    LapEvent.lane_id == lane_id, LapEvent.is_undo.is_(False)
                )
            )
        )


# --------------------------------------------------------------------------- #
# GET /api/time
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_api_time_returns_now(client):
    http, _factory = client
    before = time.time()
    response = await http.get("/api/time")
    after = time.time()
    assert response.status_code == 200
    now = response.json()["now"]
    assert before - 1.0 <= now <= after + 1.0


# --------------------------------------------------------------------------- #
# client_ts / effective_ts / late
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_finish_with_client_ts_10s_back(client):
    http, factory = client
    _event_data, heat = await _active_bateria(http, [(1, "Ana")])
    started_at = time.time() - 30.0
    await _set_started_at(factory, heat["id"], started_at)
    lane_id = heat["heat_lanes"][0]["id"]

    client_ts = time.time() - 10.0
    response = await http.post(
        f"/api/lanes/{lane_id}/finish",
        json={"client_ts": client_ts},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # ~20 s de prova (30 s desde o início menos 10 s "atrasados").
    assert 19_000 <= body["race_time_ms"] <= 20_500, body
    assert body["race_time_ms"] % 10 == 0
    assert body["late"] is True
    assert body["received_at"] is not None
    assert body["received_at"] >= client_ts + 9.0


@pytest.mark.asyncio
async def test_client_ts_is_clamped(client):
    http, factory = client
    _event_data, heat = await _active_bateria(http, [(1, "Ana"), (2, "Bia")])
    started_at = time.time() - 1.0
    await _set_started_at(factory, heat["id"], started_at)
    first, second = heat["heat_lanes"]

    # Antes do início: clampa em started_at.
    response = await http.post(
        f"/api/lanes/{first['id']}/finish",
        json={"client_ts": started_at - 5.0},
    )
    assert response.status_code == 200, response.text
    assert response.json()["race_time_ms"] == 0
    assert response.json()["late"] is False

    # No futuro: clampa em "agora" (late falso).
    await _set_started_at(factory, heat["id"], time.time() - 30.0)
    response = await http.post(
        f"/api/lanes/{second['id']}/finish",
        json={"client_ts": time.time() + 60.0},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert 29_000 <= body["race_time_ms"] <= 31_000, body
    assert body["late"] is False


@pytest.mark.asyncio
async def test_quantization_tie_same_display(client):
    http, factory = client
    _event_data, heat = await _active_bateria(http, [(1, "Ana"), (2, "Bia")])
    started_at = time.time() - 10.0
    await _set_started_at(factory, heat["id"], started_at)
    first, second = heat["heat_lanes"]

    body_a = (
        await http.post(
            f"/api/lanes/{first['id']}/finish",
            json={"client_ts": started_at + 5.000},
        )
    ).json()
    body_b = (
        await http.post(
            f"/api/lanes/{second['id']}/finish",
            json={"client_ts": started_at + 5.003},
        )
    ).json()

    assert body_a["race_time_ms"] == body_b["race_time_ms"] == 5000
    assert body_a["race_time_display"] == body_b["race_time_display"]


@pytest.mark.asyncio
async def test_finish_without_body_still_works(client):
    http, _factory = client
    _event_data, heat = await _active_bateria(http, [(1, "Ana")])
    lane_id = heat["heat_lanes"][0]["id"]

    response = await http.post(f"/api/lanes/{lane_id}/finish")
    assert response.status_code == 200, response.text
    assert response.json()["race_time_ms"] >= 0
    assert response.json()["late"] is False


# --------------------------------------------------------------------------- #
# op_id idempotente
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_same_op_id_creates_single_lap(client):
    http, factory = client
    _event_data, heat = await _active_maratona(http, [(1, "Ana")])
    lane_id = heat["heat_lanes"][0]["id"]

    first = await http.post(
        f"/api/lanes/{lane_id}/lap", json={"op_id": "op-lap-1"}
    )
    assert first.status_code == 200, first.text

    second = await http.post(
        f"/api/lanes/{lane_id}/lap", json={"op_id": "op-lap-1"}
    )
    assert second.status_code == 200, second.text
    assert second.json()["lap_number"] == first.json()["lap_number"] == 1
    assert second.json()["id"] == first.json()["id"]

    assert await _laps_count(factory, lane_id) == 1

    async with factory() as session:
        assert await session.get(ProcessedOp, "op-lap-1") is not None


@pytest.mark.asyncio
async def test_same_op_id_finish_returns_original(client):
    http, _factory = client
    _event_data, heat = await _active_bateria(http, [(1, "Ana")])
    lane_id = heat["heat_lanes"][0]["id"]

    first = await http.post(
        f"/api/lanes/{lane_id}/finish", json={"op_id": "op-fin-1"}
    )
    assert first.status_code == 200, first.text

    second = await http.post(
        f"/api/lanes/{lane_id}/finish", json={"op_id": "op-fin-1"}
    )
    assert second.status_code == 200, second.text
    assert second.json()["race_time_ms"] == first.json()["race_time_ms"]


# --------------------------------------------------------------------------- #
# Debounce de volta
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_three_laps_under_5s_only_first_accepted(client):
    http, factory = client
    _event_data, heat = await _active_maratona(http, [(1, "Ana")])
    lane_id = heat["heat_lanes"][0]["id"]

    responses = [
        await http.post(f"/api/lanes/{lane_id}/lap") for _ in range(3)
    ]
    codes = [response.status_code for response in responses]
    assert codes[0] == 200, responses[0].text
    for response in responses[1:]:
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "volta_duplicada"

    assert await _laps_count(factory, lane_id) == 1


@pytest.mark.asyncio
async def test_lap_accepted_after_interval(client, monkeypatch):
    from app.config import settings

    http, factory = client
    _event_data, heat = await _active_maratona(http, [(1, "Ana")])
    lane_id = heat["heat_lanes"][0]["id"]

    monkeypatch.setattr(settings, "MIN_LAP_INTERVAL_S", 0.05)
    first = await http.post(f"/api/lanes/{lane_id}/lap")
    assert first.status_code == 200, first.text
    time.sleep(0.06)
    second = await http.post(f"/api/lanes/{lane_id}/lap")
    assert second.status_code == 200, second.text
    assert second.json()["lap_number"] == 2

    assert await _laps_count(factory, lane_id) == 2


# --------------------------------------------------------------------------- #
# action_log + fallback da âncora monotônica
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_action_log_has_rows_for_state_changes(client):
    http, factory = client

    _event_data, heat = await _active_bateria(http, [(1, "Ana"), (2, "Bia")])
    first, second = heat["heat_lanes"]
    await http.post(f"/api/lanes/{first['id']}/finish")
    await http.post(f"/api/lanes/{second['id']}/dq")

    abort_event = await _event(http)
    abort_heat = await _heat(http, abort_event["id"])
    await _lanes(http, abort_heat["id"], [(1, "Ana")])
    await http.post(f"/api/heats/{abort_heat['id']}/open-ready-check")
    await http.post(f"/api/heats/{abort_heat['id']}/abort")

    _event_data, maratona = await _active_maratona(http, [(1, "Ana")])
    lap_lane = maratona["heat_lanes"][0]["id"]
    await http.post(f"/api/lanes/{lap_lane}/lap")
    await http.delete(f"/api/lanes/{lap_lane}/lap/last")
    await http.post(f"/api/heats/{maratona['id']}/finish")

    async with factory() as session:
        rows = (await session.execute(select(ActionLog))).scalars().all()

    actions = {row.action for row in rows}
    assert {
        "start",
        "finish",
        "dq",
        "abort",
        "lap",
        "undo_lap",
        "finish_heat",
    } <= actions

    for row in rows:
        assert row.received_at is not None
        assert row.effective_ts is not None
        assert row.heat_id is not None
        assert row.event_id is not None

    finish_rows = [row for row in rows if row.action == "finish"]
    assert finish_rows and finish_rows[-1].lane_id is not None
    assert finish_rows[-1].payload_json


@pytest.mark.asyncio
async def test_monotonic_anchor_fallback_uses_wall_clock(client):
    http, factory = client
    _event_data, heat = await _active_bateria(http, [(1, "Ana")])
    lane_id = heat["heat_lanes"][0]["id"]

    await _set_started_at(factory, heat["id"], time.time() - 12.0)
    # Simula restart: sem âncora em memória para esta bateria.
    lane_actions._mono_anchors.pop(heat["id"], None)

    response = await http.post(f"/api/lanes/{lane_id}/finish")
    assert response.status_code == 200, response.text
    body = response.json()
    assert 11_000 <= body["race_time_ms"] <= 13_000, body
    assert body["race_time_ms"] % 10 == 0


# --------------------------------------------------------------------------- #
# WebSocket
# --------------------------------------------------------------------------- #
def _recv_of_type(websocket, wanted, limit=80):
    for _ in range(limit):
        message = websocket.receive_json()
        if message.get("type") == wanted:
            return message
    raise AssertionError(f"não recebeu mensagem do tipo {wanted}")


def _ws_event(ws_client, name):
    response = ws_client.post(
        "/api/events", json={"name": name, "pool_length_m": 25}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _ws_heat(ws_client, event_id, *, heat_type="bateria", distance_m=25):
    prova_body = {"name": "Prova"}
    if distance_m is not None:
        prova_body["distance_m"] = distance_m
    prova = ws_client.post(
        f"/api/events/{event_id}/provas", json=prova_body
    ).json()
    body = {"name": "Bateria", "heat_type": heat_type}
    if distance_m is not None:
        body["distance_m"] = distance_m
    if heat_type == "maratona":
        body["duration_s"] = 3600
    response = ws_client.post(f"/api/provas/{prova['id']}/heats", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _ws_active(ws_client, *, heat_type="bateria"):
    event = _ws_event(ws_client, f"Evento WS {heat_type}")
    heat = _ws_heat(ws_client, event["id"], heat_type=heat_type)
    ws_client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 1, "participant_name": "Ana"}]},
    )
    ws_client.post(f"/api/heats/{heat['id']}/open-ready-check")
    current = ws_client.get(f"/api/events/{event['id']}/heats").json()[0]
    lane_id = current["heat_lanes"][0]["id"]
    ws_client.post(f"/api/lanes/{lane_id}/ready")
    response = ws_client.post(f"/api/heats/{heat['id']}/start")
    assert response.status_code == 200, response.text
    return event, heat, lane_id


def test_ws_finish_returns_ack_with_op_id(ws_client):
    event, heat, lane_id = _ws_active(ws_client, heat_type="bateria")

    with ws_client.websocket_connect("/ws") as websocket:
        _recv_of_type(websocket, "server_status")
        websocket.send_json(
            {
                "type": "finish",
                "lane_id": lane_id,
                "op_id": "ws-finish-1",
                "client_ts": time.time(),
            }
        )
        ack = _recv_of_type(websocket, "ack")
        assert ack["op_id"] == "ws-finish-1"
        assert ack["ok"] is True
        assert ack["result"]["race_time_ms"] >= 0


def test_ws_lap_same_op_id_single_lap(ws_client):
    event, heat, lane_id = _ws_active(ws_client, heat_type="maratona")

    with ws_client.websocket_connect("/ws") as websocket:
        _recv_of_type(websocket, "server_status")
        for _ in range(2):
            websocket.send_json(
                {"type": "lap", "lane_id": lane_id, "op_id": "ws-lap-1"}
            )
            ack = _recv_of_type(websocket, "ack")
            assert ack["op_id"] == "ws-lap-1"
            assert ack["ok"] is True
            assert ack["result"]["lap_number"] == 1

    current = ws_client.get(f"/api/events/{event['id']}/heats").json()[0]
    assert current["heat_lanes"][0]["laps"] == 1
    ws_client.post(f"/api/heats/{heat['id']}/finish")


def test_ws_ping_pong(ws_client):
    with ws_client.websocket_connect("/ws") as websocket:
        _recv_of_type(websocket, "server_status")
        websocket.send_json({"type": "ping"})
        pong = _recv_of_type(websocket, "pong")
        assert pong["type"] == "pong"


def test_ws_error_includes_op_id(ws_client):
    event, heat, lane_id = _ws_active(ws_client, heat_type="bateria")

    with ws_client.websocket_connect("/ws") as websocket:
        _recv_of_type(websocket, "server_status")
        websocket.send_json(
            {"type": "lap", "lane_id": lane_id, "op_id": "ws-bad-1"}
        )
        error = _recv_of_type(websocket, "error")
        assert error["op_id"] == "ws-bad-1"
        assert error["message"] == "nao_e_maratona"

    ws_client.post(f"/api/heats/{heat['id']}/finish")
