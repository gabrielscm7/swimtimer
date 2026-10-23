"""Regressões das correções de revisão (P0/P1)."""
import asyncio
import io
import json
import time

import pytest
from fastapi import HTTPException
from openpyxl import Workbook

from app import database
from app.models import ActionLog, Heat, ResultSnapshot
from app.services.athlete_import import _parse_xlsx_rows
from app.services.exports import csv_safe
from app.services.marathon import finish_expired_heats
from tests.conftest import (
    configure_lanes,
    create_athlete,
    create_event,
    create_heat,
    create_heat_in_prova,
    create_prova,
    create_team,
)


async def _heat(client, event_id, heat_id):
    heats = (await client.get(f"/api/events/{event_id}/heats")).json()
    return next(item for item in heats if item["id"] == heat_id)


async def _start_bateria(client, event_id, heat, participant_count=2):
    heat = await configure_lanes(
        client,
        heat["id"],
        [(number, f"Atleta {number}") for number in range(1, participant_count + 1)],
    )
    await client.post(f"/api/heats/{heat['id']}/open-ready-check")
    current = await _heat(client, event_id, heat["id"])
    for lane in current["heat_lanes"]:
        response = await client.post(f"/api/lanes/{lane['id']}/ready")
        assert response.status_code == 200, response.text
    response = await client.post(f"/api/heats/{heat['id']}/start")
    assert response.status_code == 200, response.text
    return await _heat(client, event_id, heat["id"])


@pytest.mark.asyncio
async def test_patch_null_em_campos_obrigatorios_retorna_422(client):
    event = await create_event(client)
    team = await create_team(client, event["id"])
    prova = await create_prova(client, event["id"])
    heat = await create_heat(client, event["id"])

    cases = [
        (f"/api/events/{event['id']}", {"name": None}),
        (f"/api/events/{event['id']}", {"pool_length_m": None}),
        (f"/api/events/{event['id']}", {"status": None}),
        (f"/api/events/{event['id']}", {"public_results_enabled": None}),
        (f"/api/provas/{prova['id']}", {"name": None}),
        (f"/api/provas/{prova['id']}", {"order_num": None}),
        (f"/api/provas/{prova['id']}", {"mixed_ranking": None}),
        (f"/api/provas/{prova['id']}", {"consolidate_results": None}),
        (f"/api/heats/{heat['id']}", {"name": None}),
        (f"/api/heats/{heat['id']}", {"order_num": None}),
        (f"/api/teams/{team['id']}", {"name": None}),
    ]
    for path, body in cases:
        response = await client.patch(path, json=body)
        assert response.status_code == 422, (path, body, response.text)


@pytest.mark.asyncio
async def test_athlete_patch_naipe_null_retorna_422_amigavel(client):
    event = await create_event(client)
    athlete = await create_athlete(client, event["id"])
    response = await client.patch(
        f"/api/athletes/{athlete['id']}", json={"naipe": None}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "naipe_obrigatorio"


@pytest.mark.asyncio
async def test_abort_reseta_tempos_e_permite_novo_finish(client):
    event = await create_event(client)
    heat = await create_heat(client, event["id"])
    current = await _start_bateria(client, event["id"], heat)
    first, second = current["heat_lanes"]

    finish = await client.post(f"/api/lanes/{first['id']}/finish")
    assert finish.status_code == 200, finish.text

    abort = await client.post(f"/api/heats/{heat['id']}/abort")
    assert abort.status_code == 200, abort.text

    after_abort = await _heat(client, event["id"], heat["id"])
    for lane in after_abort["heat_lanes"]:
        assert lane["finish_at"] is None
        assert lane["race_time_ms"] is None
        assert lane["status"] == "ready"

    await client.post(f"/api/heats/{heat['id']}/open-ready-check")
    again = await client.post(f"/api/heats/{heat['id']}/start")
    assert again.status_code == 200, again.text
    finish_again = await client.post(f"/api/lanes/{first['id']}/finish")
    assert finish_again.status_code == 200, finish_again.text
    assert finish_again.json()["race_time_ms"] is not None
    assert second["id"] != first["id"]


@pytest.mark.asyncio
async def test_undo_lap_pos_finish_gera_revisao_corrigida(
    client, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "MIN_LAP_INTERVAL_S", 0.0)
    event = await create_event(client)
    heat = await create_heat(
        client,
        event["id"],
        heat_type="maratona",
        distance_m=None,
        duration_s=3600,
    )
    heat = await configure_lanes(client, heat["id"], [(1, "Ana")])
    lane_id = heat["heat_lanes"][0]["id"]
    start = await client.post(f"/api/heats/{heat['id']}/start")
    assert start.status_code == 200, start.text

    for _ in range(2):
        lap = await client.post(f"/api/lanes/{lane_id}/lap")
        assert lap.status_code == 200, lap.text

    finish = await client.post(f"/api/heats/{heat['id']}/finish")
    assert finish.status_code == 200, finish.text
    assert finish.json()["result_snapshot"]["revision"] == 1

    undo = await client.delete(f"/api/lanes/{lane_id}/lap/last")
    assert undo.status_code == 200, undo.text

    after = await client.get(f"/api/heats/{heat['id']}")
    snapshot = after.json()["result_snapshot"]
    assert snapshot["revision"] == 2
    assert snapshot["status"] == "corrected"
    assert snapshot["reason"] == "undo_finish"

    async with database.AsyncSessionLocal() as session:
        from sqlalchemy import select, text

        rows = list(
            (
                await session.execute(
                    select(ResultSnapshot)
                    .where(ResultSnapshot.heat_id == heat["id"])
                    .order_by(text("rowid ASC"))
                )
            )
            .scalars()
            .all()
        )
        payload = json.loads(rows[-1].payload_json)
        assert payload["lanes"][0]["laps"] == 1

    verify = await client.get(f"/api/events/{event['id']}/audit/verify")
    assert verify.status_code == 200
    assert verify.json()["ok"] is True


@pytest.mark.asyncio
async def test_op_id_reutilizado_em_outra_raia_retorna_409(client):
    event = await create_event(client)
    heat = await create_heat(client, event["id"])
    current = await _start_bateria(client, event["id"], heat)
    first, second = current["heat_lanes"]

    one = await client.post(
        f"/api/lanes/{first['id']}/finish", json={"op_id": "op-repetido"}
    )
    assert one.status_code == 200, one.text
    two = await client.post(
        f"/api/lanes/{second['id']}/finish", json={"op_id": "op-repetido"}
    )
    assert two.status_code == 409
    assert two.json()["detail"] == "op_id_conflitante"


@pytest.mark.asyncio
async def test_finish_rejeita_raia_dq_e_raia_vazia(client):
    event = await create_event(client)
    heat = await create_heat(client, event["id"])
    current = await _start_bateria(client, event["id"], heat)
    first, _second = current["heat_lanes"]

    dq = await client.post(f"/api/lanes/{first['id']}/dq")
    assert dq.status_code == 200, dq.text
    finish_dq = await client.post(f"/api/lanes/{first['id']}/finish")
    assert finish_dq.status_code == 409
    assert finish_dq.json()["detail"] == "raia_desclassificada"

    empty_event = await create_event(client, name="Evento raia vazia")
    empty_heat = await create_heat(client, empty_event["id"])
    response = await client.post(
        f"/api/heats/{empty_heat['id']}/lanes",
        json={
            "lanes": [
                {"lane_number": 1, "participant_name": "Ana"},
                {"lane_number": 2},
            ]
        },
    )
    assert response.status_code == 200, response.text
    await client.post(f"/api/heats/{empty_heat['id']}/open-ready-check")
    current = await _heat(client, empty_event["id"], empty_heat["id"])
    for lane in current["heat_lanes"]:
        if lane["participant_name"]:
            await client.post(f"/api/lanes/{lane['id']}/ready")
    start = await client.post(f"/api/heats/{empty_heat['id']}/start")
    assert start.status_code == 200, start.text
    empty_lane = next(
        lane for lane in start.json()["heat_lanes"] if not lane["participant_name"]
    )
    finish_empty = await client.post(f"/api/lanes/{empty_lane['id']}/finish")
    assert finish_empty.status_code == 409
    assert finish_empty.json()["detail"] == "raia_sem_participante"


@pytest.mark.asyncio
async def test_update_lane_nao_dessincroniza_equipe_do_atleta(client):
    event = await create_event(client)
    team_a = await create_team(client, event["id"], "Equipe A")
    team_b = await create_team(client, event["id"], "Equipe B")
    athlete = await create_athlete(
        client, event["id"], team_id=team_a["id"]
    )
    heat = await create_heat(client, event["id"])
    response = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={
            "lanes": [
                {"lane_number": 1, "athlete_id": athlete["id"]}
            ]
        },
    )
    assert response.status_code == 200, response.text
    lane = response.json()["heat_lanes"][0]

    patch = await client.patch(
        f"/api/lanes/{lane['id']}", json={"team_id": team_b["id"]}
    )
    assert patch.status_code == 422
    assert patch.json()["detail"] == "equipe_do_atleta"


@pytest.mark.asyncio
async def test_exclusao_de_evento_ativo_e_bloqueada(client):
    event = await create_event(client)
    heat = await create_heat(client, event["id"])
    await _start_bateria(client, event["id"], heat)

    detail = (await client.get(f"/api/events/{event['id']}")).json()
    assert detail["status"] == "active"

    response = await client.delete(f"/api/events/{event['id']}")
    assert response.status_code == 409
    assert response.json()["detail"] == "evento_com_baterias_iniciadas"


@pytest.mark.asyncio
async def test_evento_vira_finished_quando_todas_as_baterias_terminam(client):
    event = await create_event(client)
    heat = await create_heat(client, event["id"])
    current = await _start_bateria(
        client, event["id"], heat, participant_count=1
    )
    finish = await client.post(
        f"/api/lanes/{current['heat_lanes'][0]['id']}/finish"
    )
    assert finish.status_code == 200, finish.text

    detail = (await client.get(f"/api/events/{event['id']}")).json()
    assert detail["status"] == "finished"


@pytest.mark.asyncio
async def test_maratona_finaliza_pelo_relogio_do_servidor(client):
    event = await create_event(client)
    heat = await create_heat(
        client,
        event["id"],
        heat_type="maratona",
        distance_m=None,
        duration_s=3600,
    )
    heat = await configure_lanes(client, heat["id"], [(1, "Ana")])
    start = await client.post(f"/api/heats/{heat['id']}/start")
    assert start.status_code == 200, start.text

    async with database.AsyncSessionLocal() as session:
        row = await session.get(Heat, heat["id"])
        row.started_at = time.time() - 3700
        await session.commit()

    finished = await finish_expired_heats()
    assert finished == 1

    current = await client.get(f"/api/heats/{heat['id']}")
    assert current.status_code == 200
    body = current.json()
    assert body["status"] == "finished"
    assert body["result_snapshot"]["revision"] == 1

    async with database.AsyncSessionLocal() as session:
        from sqlalchemy import select

        logs = list(
            (
                await session.execute(
                    select(ActionLog).where(
                        ActionLog.heat_id == heat["id"],
                        ActionLog.action == "finish_heat",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert logs


@pytest.mark.asyncio
async def test_audit_verify_detecta_metadados_adulterados(client):
    event = await create_event(client)
    heat = await create_heat(client, event["id"])
    current = await _start_bateria(
        client, event["id"], heat, participant_count=1
    )
    await client.post(f"/api/lanes/{current['heat_lanes'][0]['id']}/finish")

    async with database.AsyncSessionLocal() as session:
        from sqlalchemy import select

        snapshot = (
            await session.execute(
                select(ResultSnapshot).where(
                    ResultSnapshot.heat_id == heat["id"]
                )
            )
        ).scalars().first()
        snapshot.status = "official"
        await session.commit()

    verify = await client.get(f"/api/events/{event['id']}/audit/verify")
    assert verify.status_code == 200
    body = verify.json()
    assert body["ok"] is False
    assert body["reason"] == "metadados_inconsistentes"


def test_csv_safe_previne_formulas():
    assert csv_safe("=SOMA(A1)") == "'=SOMA(A1)"
    assert csv_safe("+1") == "'+1"
    assert csv_safe("-1") == "'-1"
    assert csv_safe("@cmd") == "'@cmd"
    assert csv_safe("Maria") == "Maria"
    assert csv_safe(None) == ""


def test_xlsx_respeita_limite_de_linhas_antes_de_materializar():
    workbook = Workbook()
    sheet = workbook.active
    for index in range(40):
        sheet.append(["NOME", "EQUIPE", "NAIPE", "CATEGORIA"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    with pytest.raises(HTTPException) as excinfo:
        _parse_xlsx_rows(buffer.getvalue(), max_rows=10)
    assert excinfo.value.status_code == 413


def _ws_event(ws_client, name):
    response = ws_client.post(
        "/api/events", json={"name": name, "pool_length_m": 25}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_ws_publico_mascara_nomes_por_assinatura(ws_client):
    event = _ws_event(ws_client, "Evento WS privacidade")
    response = ws_client.patch(
        f"/api/events/{event['id']}",
        json={"public_name_mode": "initials"},
    )
    assert response.status_code == 200, response.text
    team = ws_client.post(
        f"/api/events/{event['id']}/teams", json={"name": "Equipe Azul"}
    ).json()
    athlete = ws_client.post(
        f"/api/events/{event['id']}/athletes",
        json={
            "name": "Maria da Silva",
            "naipe": "F",
            "team_id": team["id"],
        },
    ).json()
    prova = ws_client.post(
        f"/api/events/{event['id']}/provas",
        json={"name": "100 Livres", "distance_m": 100},
    ).json()
    heat = ws_client.post(
        f"/api/provas/{prova['id']}/heats",
        json={"name": "Bateria 1", "heat_type": "bateria", "distance_m": 100},
    ).json()
    response = ws_client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 1, "athlete_id": athlete["id"]}]},
    )
    assert response.status_code == 200, response.text
    ws_client.post(f"/api/heats/{heat['id']}/open-ready-check")

    with ws_client.websocket_connect("/ws") as websocket:
        first = websocket.receive_json()
        assert first["type"] == "server_status"
        websocket.send_json(
            {
                "type": "subscribe",
                "event_id": event["id"],
                "public": True,
            }
        )
        assert websocket.receive_json()["type"] == "subscribed"
        state = None
        for _ in range(30):
            message = websocket.receive_json()
            if (
                message.get("type") == "heat_state"
                and message.get("heat_id") == heat["id"]
            ):
                state = message
                break
        assert state is not None
        lane = state["payload"]["heat_lanes"][0]
        assert lane["participant_name"] == "Maria S."


def test_ws_athletes_changed_respeita_evento_assinado(ws_client):
    event_a = _ws_event(ws_client, "Evento WS A")
    event_b = _ws_event(ws_client, "Evento WS B")

    with ws_client.websocket_connect("/ws") as websocket:
        assert websocket.receive_json()["type"] == "server_status"
        websocket.send_json({"type": "subscribe", "event_id": event_a["id"]})
        assert websocket.receive_json()["type"] == "subscribed"

        ws_client.post(
            f"/api/events/{event_b['id']}/athletes",
            json={"name": "Atleta B", "naipe": "M"},
        )
        ws_client.post(
            f"/api/events/{event_a['id']}/athletes",
            json={"name": "Atleta A", "naipe": "F"},
        )

        seen = []
        for _ in range(20):
            message = websocket.receive_json()
            if message.get("type") == "athletes_changed":
                seen.append(message)
                if message.get("event_id") == event_a["id"]:
                    break
        assert seen
        assert all(item["event_id"] == event_a["id"] for item in seen)


@pytest.mark.asyncio
async def test_cadeia_de_auditoria_sob_concorrencia_entre_baterias(client):
    event = await create_event(client)
    prova = await create_prova(client, event["id"])
    heats = []
    for index in range(3):
        heat = await create_heat_in_prova(
            client, prova["id"], name=f"Bateria {index + 1}", distance_m=50
        )
        heat = await configure_lanes(
            client, heat["id"], [(1, f"Atleta {index}")]
        )
        await client.post(f"/api/heats/{heat['id']}/open-ready-check")
        current = await _heat(client, event["id"], heat["id"])
        await client.post(
            f"/api/lanes/{current['heat_lanes'][0]['id']}/ready"
        )
        response = await client.post(f"/api/heats/{heat['id']}/start")
        assert response.status_code == 200, response.text
        heats.append(response.json())

    responses = await asyncio.gather(
        *[
            client.post(f"/api/lanes/{heat['heat_lanes'][0]['id']}/finish")
            for heat in heats
        ]
    )
    assert all(response.status_code == 200 for response in responses)

    verify = await client.get(f"/api/events/{event['id']}/audit/verify")
    assert verify.status_code == 200
    body = verify.json()
    assert body["ok"] is True, body
    assert body["count"] == 3


@pytest.mark.asyncio
async def test_nao_altera_naipe_de_atleta_com_resultado_finalizado(client):
    event = await create_event(client)
    athlete = await create_athlete(client, event["id"], naipe="F")
    heat = await create_heat(client, event["id"])
    response = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 1, "athlete_id": athlete["id"]}]},
    )
    assert response.status_code == 200, response.text
    heat = response.json()
    await client.post(f"/api/heats/{heat['id']}/open-ready-check")
    lane = heat["heat_lanes"][0]
    await client.post(f"/api/lanes/{lane['id']}/ready")
    start = await client.post(f"/api/heats/{heat['id']}/start")
    assert start.status_code == 200, start.text
    finish = await client.post(f"/api/lanes/{lane['id']}/finish")
    assert finish.status_code == 200, finish.text

    patch = await client.patch(
        f"/api/athletes/{athlete['id']}", json={"naipe": "M"}
    )
    assert patch.status_code == 409
    assert patch.json()["detail"] == "atleta_com_resultado"


@pytest.mark.asyncio
async def test_nao_altera_piscina_ou_config_operacional_apos_inicio(client):
    event = await create_event(client)
    prova = await create_prova(client, event["id"], naipe="M")
    heat = await create_heat_in_prova(client, prova["id"])
    await _start_bateria(client, event["id"], heat, participant_count=2)

    pool = await client.patch(
        f"/api/events/{event['id']}", json={"pool_length_m": 50}
    )
    assert pool.status_code == 409
    assert pool.json()["detail"] == "evento_ja_iniciado"

    config = await client.patch(
        f"/api/provas/{prova['id']}", json={"naipe": "MISTO"}
    )
    assert config.status_code == 409
    assert config.json()["detail"] == "prova_ja_iniciada"
