import json

import pytest

from app import database
from app.config import settings
from app.models import ActionLog, Heat, ResultSnapshot
from app.services import snapshots
from tests.conftest import (
    create_athlete,
    create_event,
    create_heat,
    create_team,
)


async def _setup_started(client, name: str = "Maria Silva") -> tuple:
    event = await create_event(client, name="Evento Snapshots")
    team = await create_team(client, event["id"], "Equipe Azul")
    heat = await create_heat(
        client, event["id"], name="50 Livres", heat_type="bateria", distance_m=50
    )
    athlete = await create_athlete(
        client,
        event["id"],
        name=name,
        naipe="F",
        category="SENIOR",
        team_id=team["id"],
    )
    response = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 4, "athlete_id": athlete["id"]}]},
    )
    assert response.status_code == 200, response.text
    heat = response.json()
    await client.post(f"/api/heats/{heat['id']}/open-ready-check")
    await client.post(f"/api/lanes/{heat['heat_lanes'][0]['id']}/ready")
    response = await client.post(f"/api/heats/{heat['id']}/start")
    assert response.status_code == 200, response.text
    return event, response.json(), athlete


async def _finish_all(client, heat: dict) -> None:
    for lane in heat["heat_lanes"]:
        response = await client.post(f"/api/lanes/{lane['id']}/finish")
        assert response.status_code == 200, response.text


async def _rows(heat_id: str) -> list[ResultSnapshot]:
    async with database.AsyncSessionLocal() as session:
        from sqlalchemy import select, text

        result = await session.execute(
            select(ResultSnapshot)
            .where(ResultSnapshot.heat_id == heat_id)
            .order_by(text("rowid ASC"))
        )
        return list(result.scalars().all())


@pytest.mark.asyncio
async def test_finish_creates_provisional_revision(client):
    event, heat, _athlete = await _setup_started(client)
    await _finish_all(client, heat)

    response = await client.get(f"/api/heats/{heat['id']}")
    assert response.status_code == 200, response.text
    snapshot = response.json()["result_snapshot"]
    assert snapshot["revision"] == 1
    assert snapshot["status"] == "provisional"
    assert snapshot["reason"] == "finish"
    assert snapshot["created_by"] == "fiscal"

    rows = await _rows(heat["id"])
    assert len(rows) == 1
    payload = json.loads(rows[0].payload_json)
    lane = payload["lanes"][0]
    assert lane["lane_number"] == 4
    assert lane["athlete"]["name"] == "Maria Silva"
    assert lane["athlete"]["naipe"] == "F"
    assert lane["athlete"]["category"] == "SENIOR"
    assert lane["team_name"] == "Equipe Azul"
    assert lane["race_time_ms"] is not None
    assert rows[0].prev_hash == snapshots.GENESIS


@pytest.mark.asyncio
async def test_homologation_creates_official_revision(client):
    event, heat, _athlete = await _setup_started(client)
    await _finish_all(client, heat)

    response = await client.post(f"/api/heats/{heat['id']}/homologate")
    assert response.status_code == 200, response.text
    snapshot = response.json()["result_snapshot"]
    assert snapshot["revision"] == 2
    assert snapshot["status"] == "official"
    assert snapshot["reason"] == "homologacao"
    assert snapshot["created_by"] == "supervisor"

    rows = await _rows(heat["id"])
    assert rows[1].prev_hash == rows[0].hash

    verify = await client.get(f"/api/events/{event['id']}/audit/verify")
    assert verify.status_code == 200
    assert verify.json()["ok"] is True
    assert verify.json()["count"] == 2

    again = await client.post(f"/api/heats/{heat['id']}/homologate")
    assert again.status_code == 409
    assert again.json()["detail"] == "bateria_ja_homologada"


@pytest.mark.asyncio
async def test_homologation_requires_finished_heat(client):
    event = await create_event(client, name="Evento Nao Finalizado")
    heat = await create_heat(client, event["id"])
    response = await client.post(f"/api/heats/{heat['id']}/homologate")
    assert response.status_code == 409
    assert response.json()["detail"] == "bateria_nao_finalizada"


@pytest.mark.asyncio
async def test_correction_keeps_previous_revision(client):
    _event, heat, _athlete = await _setup_started(client)
    await _finish_all(client, heat)
    original = (await _rows(heat["id"]))[0]

    async with database.AsyncSessionLocal() as session:
        current = await session.get(Heat, heat["id"])
        corrected = await snapshots.record_revision(
            session,
            current,
            reason="dq_undo",
            status=snapshots.SNAPSHOT_CORRECTED,
            role="supervisor",
            ip="10.42.0.9",
        )
        await session.commit()
        corrected_id = corrected.id

    rows = await _rows(heat["id"])
    assert [row.revision for row in rows] == [1, 2]
    assert rows[0].id == original.id
    assert rows[0].payload_json == original.payload_json
    assert rows[0].hash == original.hash
    assert rows[1].id == corrected_id
    assert rows[1].status == "corrected"
    assert rows[1].reason == "dq_undo"
    assert rows[1].prev_hash == rows[0].hash
    assert rows[1].created_by == "supervisor"
    assert rows[1].created_by_ip == "10.42.0.9"


@pytest.mark.asyncio
async def test_snapshot_keeps_athlete_data_at_the_moment(client):
    _event, heat, athlete = await _setup_started(client)
    await _finish_all(client, heat)
    original = (await _rows(heat["id"]))[0]

    response = await client.patch(
        f"/api/athletes/{athlete['id']}", json={"name": "Maria Alterada"}
    )
    assert response.status_code == 200, response.text

    rows = await _rows(heat["id"])
    assert rows[0].payload_json == original.payload_json
    payload = json.loads(rows[0].payload_json)
    assert payload["lanes"][0]["athlete"]["name"] == "Maria Silva"


@pytest.mark.asyncio
async def test_verify_detects_forged_rows(client):
    event, heat, _athlete = await _setup_started(client)
    await _finish_all(client, heat)

    async with database.AsyncSessionLocal() as session:
        session.add(
            ResultSnapshot(
                id="forged",
                event_id=event["id"],
                prova_id=heat["prova_id"],
                heat_id=heat["id"],
                revision=9,
                status="official",
                reason="homologacao",
                created_at=1.0,
                created_by="supervisor",
                created_by_ip=None,
                payload_json=(
                    '{"event":{"id":"' + event["id"] + '"},"heat":{"id":"'
                    + heat["id"] + '"}}'
                ),
                prev_hash="0" * 64,
                hash="f" * 64,
            )
        )
        await session.commit()

    verify = await client.get(f"/api/events/{event['id']}/audit/verify")
    assert verify.status_code == 200
    body = verify.json()
    assert body["ok"] is False
    assert body["broken_id"] == "forged"
    assert body["reason"] == "cadeia_quebrada"


@pytest.mark.asyncio
async def test_event_with_snapshots_cannot_be_deleted(client):
    event, heat, _athlete = await _setup_started(client)
    await _finish_all(client, heat)

    response = await client.delete(f"/api/events/{event['id']}")
    assert response.status_code == 409
    assert response.json()["detail"] == "evento_possui_resultados"


@pytest.mark.asyncio
async def test_journal_mirrors_action_log_and_snapshots(client):
    event, heat, _athlete = await _setup_started(client)
    await _finish_all(client, heat)

    path = settings.journal_dir / f"{event['id']}.ndjson"
    assert path.is_file()
    lines = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    kinds = {line["kind"] for line in lines}
    assert {"action_log", "result_snapshot"} <= kinds

    async with database.AsyncSessionLocal() as session:
        from sqlalchemy import select

        db_ids = {
            row.id
            for row in (
                await session.execute(
                    select(ActionLog).where(ActionLog.event_id == event["id"])
                )
            )
            .scalars()
            .all()
        }
        journal_ids = {
            line["id"] for line in lines if line["kind"] == "action_log"
        }
    assert journal_ids == db_ids
    assert all(line["event_id"] == event["id"] for line in lines)
