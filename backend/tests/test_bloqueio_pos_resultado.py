"""Bloqueio de alteracao de grupo apos resultado e excecao do supervisor."""
import pytest
from sqlalchemy import select

from app import database as database_module
from app.config import settings
from app.models import ActionLog, ResultSnapshot
from tests.conftest import create_event, create_heat


async def _finished_heat(client):
    event = await create_event(client)
    heat = await create_heat(
        client, event["id"], stroke="livre", distance_m=25
    )
    response = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 1, "participant_name": "Ana"}]},
    )
    assert response.status_code == 200, response.text
    current = (await client.get(f"/api/heats/{heat['id']}")).json()
    await client.post(f"/api/heats/{heat['id']}/open-ready-check")
    await client.post(f"/api/lanes/{current['heat_lanes'][0]['id']}/ready")
    await client.post(f"/api/heats/{heat['id']}/start")
    await client.post(f"/api/lanes/{current['heat_lanes'][0]['id']}/finish")
    finished = await client.post(f"/api/heats/{heat['id']}/finish")
    assert finished.status_code == 200, finished.text
    return event, finished.json()


@pytest.mark.asyncio
async def test_grupo_bloqueado_apos_resultado(client):
    _event, heat = await _finished_heat(client)
    for body in (
        {"stroke": "costas"},
        {"distance_m": 50},
        {"naipe": "F"},
        {"category": "mirim"},
    ):
        response = await client.patch(f"/api/heats/{heat['id']}", json=body)
        assert response.status_code == 409, (body, response.text)
        assert response.json()["detail"] == "bateria_com_resultado"


@pytest.mark.asyncio
async def test_nome_continua_editavel_apos_resultado(client):
    _event, heat = await _finished_heat(client)
    response = await client.patch(
        f"/api/heats/{heat['id']}", json={"name": "Final A"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Final A"


@pytest.mark.asyncio
async def test_override_exige_pin_e_motivo(client):
    _event, heat = await _finished_heat(client)
    response = await client.patch(
        f"/api/heats/{heat['id']}",
        json={
            "stroke": "costas",
            "force": True,
            "override_reason": "correcao de digitacao",
        },
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "override_requer_pin_do_supervisor"


@pytest.mark.asyncio
async def test_override_com_pin_registra_snapshot_corrected(
    client, monkeypatch
):
    monkeypatch.setattr(settings, "OPERATOR_PIN", "s3cret")
    event, heat = await _finished_heat(client)
    old_prova_id = heat["prova_id"]

    response = await client.patch(
        f"/api/heats/{heat['id']}",
        headers={"X-Operator-Pin": "s3cret"},
        json={
            "stroke": "costas",
            "force": True,
            "override_reason": "estilo cadastrado errado",
        },
    )
    assert response.status_code == 200, response.text
    moved = response.json()
    assert moved["stroke"] == "costas"
    assert moved["prova_id"] != old_prova_id

    snapshots = (
        await client.get(f"/api/heats/{heat['id']}/snapshots")
    ).json()
    assert snapshots[-1]["status"] == "corrected"
    assert snapshots[-1]["reason"] == "correcao_grupo"

    async with database_module.AsyncSessionLocal() as session:
        logs = list(
            (
                await session.execute(
                    select(ActionLog).where(
                        ActionLog.action == "override_grupo"
                    )
                )
            ).scalars()
        )
        assert len(logs) == 1
        assert "estilo cadastrado errado" in (logs[0].payload_json or "")

        rows = list(
            (
                await session.execute(
                    select(ResultSnapshot).where(
                        ResultSnapshot.heat_id == heat["id"]
                    )
                )
            ).scalars()
        )
        assert rows[-1].status == "corrected"

    # Prova antiga tem snapshot: nao e removida (historico preservado).
    assert (await client.get(f"/api/provas/{old_prova_id}")).status_code == 200
