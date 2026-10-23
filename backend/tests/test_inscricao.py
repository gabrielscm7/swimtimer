"""Validacoes de inscricao e override do supervisor (ADR-009)."""
import json

import pytest
from sqlalchemy import select

from app import database as database_module
from app.config import settings
from app.models import ActionLog
from tests.conftest import (
    create_athlete,
    create_event,
    create_heat_in_prova,
    create_prova,
)


async def _prova(client, event, *, name="Prova", naipe=None, category=None):
    return await create_prova(
        client,
        event["id"],
        name=name,
        naipe=naipe,
        category=category,
        distance_m=100,
    )


async def _assign(client, heat_id, lanes):
    return await client.post(
        f"/api/heats/{heat_id}/lanes", json={"lanes": lanes}
    )


async def _override_logs():
    async with database_module.AsyncSessionLocal() as session:
        result = await session.execute(
            select(ActionLog).where(
                ActionLog.action == "override_inscricao"
            )
        )
        return list(result.scalars().all())


@pytest.fixture
def supervisor_pin(monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_PIN", "s3cret")
    return "s3cret"


# --------------------------------------------------------------------------- #
# Naipe
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_prova_masculina_rejects_female_athlete(client):
    event = await create_event(client)
    prova = await _prova(client, event, naipe="M")
    heat = await create_heat_in_prova(client, prova["id"])
    female = await create_athlete(
        client, event["id"], name="Maria", naipe="F"
    )

    response = await _assign(
        client, heat["id"], [{"lane_number": 1, "athlete_id": female["id"]}]
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "naipe_incompativel"


@pytest.mark.asyncio
async def test_prova_misto_accepts_m_and_f(client):
    event = await create_event(client)
    prova = await _prova(client, event, naipe="MISTO")
    heat = await create_heat_in_prova(client, prova["id"])
    male = await create_athlete(client, event["id"], name="Mario", naipe="M")
    female = await create_athlete(
        client, event["id"], name="Maria", naipe="F"
    )

    response = await _assign(
        client,
        heat["id"],
        [
            {"lane_number": 1, "athlete_id": male["id"]},
            {"lane_number": 2, "athlete_id": female["id"]},
        ],
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_prova_without_naipe_does_not_validate(client):
    event = await create_event(client)
    prova = await _prova(client, event, naipe=None)
    heat = await create_heat_in_prova(client, prova["id"])
    female = await create_athlete(
        client, event["id"], name="Maria", naipe="F"
    )

    response = await _assign(
        client, heat["id"], [{"lane_number": 1, "athlete_id": female["id"]}]
    )
    assert response.status_code == 200, response.text


# --------------------------------------------------------------------------- #
# Categoria
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_categoria_incompativel_blocks(client):
    event = await create_event(client)
    prova = await _prova(client, event, category="SUB-12")
    heat = await create_heat_in_prova(client, prova["id"])
    athlete = await create_athlete(
        client, event["id"], name="Ana", naipe="F", category="SUB-14"
    )

    response = await _assign(
        client, heat["id"], [{"lane_number": 1, "athlete_id": athlete["id"]}]
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "categoria_incompativel"


@pytest.mark.asyncio
async def test_categoria_definida_bloqueia_atleta_sem_categoria(client):
    event = await create_event(client)
    prova = await _prova(client, event, category="SUB-12")
    heat = await create_heat_in_prova(client, prova["id"])
    athlete = await create_athlete(
        client, event["id"], name="Ana", naipe="F", category=None
    )

    response = await _assign(
        client, heat["id"], [{"lane_number": 1, "athlete_id": athlete["id"]}]
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "categoria_incompativel"


# --------------------------------------------------------------------------- #
# Duplicidade / outra bateria ativa
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_atleta_duplicado_na_bateria(client):
    event = await create_event(client)
    prova = await _prova(client, event)
    heat = await create_heat_in_prova(client, prova["id"])
    athlete = await create_athlete(client, event["id"], name="Ana", naipe="F")

    response = await _assign(
        client,
        heat["id"],
        [
            {"lane_number": 1, "athlete_id": athlete["id"]},
            {"lane_number": 2, "athlete_id": athlete["id"]},
        ],
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "atleta_duplicado_na_bateria"


@pytest.mark.asyncio
async def test_atleta_duplicado_na_prova_informa_a_bateria(client):
    event = await create_event(client)
    prova = await _prova(client, event)
    first = await create_heat_in_prova(client, prova["id"], name="Bateria 1")
    second = await create_heat_in_prova(client, prova["id"], name="Bateria 2")
    athlete = await create_athlete(client, event["id"], name="Ana", naipe="F")

    ok = await _assign(
        client, first["id"], [{"lane_number": 1, "athlete_id": athlete["id"]}]
    )
    assert ok.status_code == 200, ok.text

    response = await _assign(
        client, second["id"], [{"lane_number": 1, "athlete_id": athlete["id"]}]
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "atleta_duplicado_na_prova: Bateria 1"


@pytest.mark.asyncio
async def test_mover_atleta_de_raia_na_mesma_bateria_e_permitido(client):
    event = await create_event(client)
    prova = await _prova(client, event)
    heat = await create_heat_in_prova(client, prova["id"])
    athlete = await create_athlete(client, event["id"], name="Ana", naipe="F")

    await _assign(
        client, heat["id"], [{"lane_number": 1, "athlete_id": athlete["id"]}]
    )
    response = await _assign(
        client,
        heat["id"],
        [
            {"lane_number": 1, "athlete_id": None},
            {"lane_number": 2, "athlete_id": athlete["id"]},
        ],
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_atleta_em_outra_bateria_ativa(client):
    event = await create_event(client)
    prova_a = await _prova(client, event, name="A")
    prova_b = await _prova(client, event, name="B")
    heat_a = await create_heat_in_prova(client, prova_a["id"])
    heat_b = await create_heat_in_prova(client, prova_b["id"])
    athlete = await create_athlete(client, event["id"], name="Ana", naipe="F")

    ok = await _assign(
        client, heat_a["id"], [{"lane_number": 1, "athlete_id": athlete["id"]}]
    )
    assert ok.status_code == 200, ok.text
    opened = await client.post(f"/api/heats/{heat_a['id']}/open-ready-check")
    assert opened.status_code == 200, opened.text

    response = await _assign(
        client, heat_b["id"], [{"lane_number": 1, "athlete_id": athlete["id"]}]
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "atleta_em_outra_bateria_ativa"


@pytest.mark.asyncio
async def test_atleta_em_bateria_agendada_de_outra_prova_e_permitido(client):
    event = await create_event(client)
    prova_a = await _prova(client, event, name="A")
    prova_b = await _prova(client, event, name="B")
    heat_a = await create_heat_in_prova(client, prova_a["id"])
    heat_b = await create_heat_in_prova(client, prova_b["id"])
    athlete = await create_athlete(client, event["id"], name="Ana", naipe="F")

    await _assign(
        client, heat_a["id"], [{"lane_number": 1, "athlete_id": athlete["id"]}]
    )
    response = await _assign(
        client, heat_b["id"], [{"lane_number": 1, "athlete_id": athlete["id"]}]
    )
    assert response.status_code == 200, response.text


# --------------------------------------------------------------------------- #
# PATCH de raia (update_lane)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_update_lane_validates_naipe(client):
    event = await create_event(client)
    prova = await _prova(client, event, naipe="M")
    heat = await create_heat_in_prova(client, prova["id"])
    male = await create_athlete(client, event["id"], name="Mario", naipe="M")
    female = await create_athlete(
        client, event["id"], name="Maria", naipe="F"
    )
    created = await _assign(
        client, heat["id"], [{"lane_number": 1, "athlete_id": male["id"]}]
    )
    lane_id = created.json()["heat_lanes"][0]["id"]

    response = await client.patch(
        f"/api/lanes/{lane_id}", json={"athlete_id": female["id"]}
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "naipe_incompativel"


@pytest.mark.asyncio
async def test_update_lane_detects_duplicate_in_heat(client):
    event = await create_event(client)
    prova = await _prova(client, event)
    heat = await create_heat_in_prova(client, prova["id"])
    first = await create_athlete(client, event["id"], name="Ana", naipe="F")
    second = await create_athlete(client, event["id"], name="Bia", naipe="F")
    created = await _assign(
        client,
        heat["id"],
        [
            {"lane_number": 1, "athlete_id": first["id"]},
            {"lane_number": 2, "athlete_id": second["id"]},
        ],
    )
    lane_id = next(
        lane["id"]
        for lane in created.json()["heat_lanes"]
        if lane["lane_number"] == 2
    )

    response = await client.patch(
        f"/api/lanes/{lane_id}", json={"athlete_id": first["id"]}
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "atleta_duplicado_na_bateria"


# --------------------------------------------------------------------------- #
# PATCH de atleta
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_athlete_patch_validates_existing_assignments(client):
    event = await create_event(client)
    prova = await _prova(client, event, naipe="M", category="SUB-12")
    heat = await create_heat_in_prova(client, prova["id"])
    athlete = await create_athlete(
        client, event["id"], name="Mario", naipe="M", category="SUB-12"
    )
    await _assign(
        client, heat["id"], [{"lane_number": 1, "athlete_id": athlete["id"]}]
    )

    naipe_response = await client.patch(
        f"/api/athletes/{athlete['id']}", json={"naipe": "F"}
    )
    assert naipe_response.status_code == 422, naipe_response.text
    assert naipe_response.json()["detail"] == "naipe_incompativel"

    category_response = await client.patch(
        f"/api/athletes/{athlete['id']}", json={"category": "SUB-14"}
    )
    assert category_response.status_code == 422, category_response.text
    assert (
        category_response.json()["detail"] == "categoria_incompativel"
    )


# --------------------------------------------------------------------------- #
# Override do supervisor
# --------------------------------------------------------------------------- #
async def _violating_assignment(client, *, naipe="M"):
    event = await create_event(client)
    prova = await _prova(client, event, naipe=naipe)
    heat = await create_heat_in_prova(client, prova["id"])
    athlete = await create_athlete(client, event["id"], name="Ana", naipe="F")
    return event, heat, athlete


@pytest.mark.asyncio
async def test_force_without_operator_pin_is_denied(client, monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_PIN", None)
    _, heat, athlete = await _violating_assignment(client)

    response = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={
            "lanes": [{"lane_number": 1, "athlete_id": athlete["id"]}],
            "force": True,
            "override_reason": "caso excepcional",
        },
        headers={"X-Operator-Pin": "qualquer"},
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "override_requer_pin_do_supervisor"


@pytest.mark.asyncio
async def test_force_requires_reason(client, supervisor_pin):
    _, heat, athlete = await _violating_assignment(client)

    response = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={
            "lanes": [{"lane_number": 1, "athlete_id": athlete["id"]}],
            "force": True,
            "override_reason": "   ",
        },
        headers={"X-Operator-Pin": supervisor_pin},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "override_reason_obrigatorio"


@pytest.mark.asyncio
async def test_force_requires_valid_pin(client, supervisor_pin):
    _, heat, athlete = await _violating_assignment(client)

    response = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={
            "lanes": [{"lane_number": 1, "athlete_id": athlete["id"]}],
            "force": True,
            "override_reason": "caso excepcional",
        },
        headers={"X-Operator-Pin": "errado"},
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "pin_do_supervisor_invalido"


@pytest.mark.asyncio
async def test_force_with_pin_bypasses_and_logs_action(client, supervisor_pin):
    _, heat, athlete = await _violating_assignment(client)

    response = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={
            "lanes": [{"lane_number": 1, "athlete_id": athlete["id"]}],
            "force": True,
            "override_reason": "autorizado pela organizacao",
        },
        headers={"X-Operator-Pin": supervisor_pin},
    )
    assert response.status_code == 200, response.text
    assert response.json()["heat_lanes"][0]["athlete_id"] == athlete["id"]

    logs = await _override_logs()
    assert len(logs) == 1
    payload = json.loads(logs[0].payload_json)
    assert payload["reason"] == "autorizado pela organizacao"
    assert "naipe_incompativel" in payload["violations"]
    assert athlete["id"] in payload["athlete_ids"]


@pytest.mark.asyncio
async def test_update_lane_accepts_force(client, supervisor_pin):
    event, heat, athlete = await _violating_assignment(client)
    female = athlete
    male = await create_athlete(client, event["id"], name="Mario", naipe="M")
    created = await _assign(
        client, heat["id"], [{"lane_number": 1, "athlete_id": male["id"]}]
    )
    lane_id = created.json()["heat_lanes"][0]["id"]

    response = await client.patch(
        f"/api/lanes/{lane_id}",
        json={
            "athlete_id": female["id"],
            "force": True,
            "override_reason": "decisao do supervisor",
        },
        headers={"X-Operator-Pin": supervisor_pin},
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_athlete_patch_accepts_force(client, supervisor_pin):
    event = await create_event(client)
    prova = await _prova(client, event, naipe="M")
    heat = await create_heat_in_prova(client, prova["id"])
    athlete = await create_athlete(client, event["id"], name="Mario", naipe="M")
    await _assign(
        client, heat["id"], [{"lane_number": 1, "athlete_id": athlete["id"]}]
    )

    response = await client.patch(
        f"/api/athletes/{athlete['id']}",
        json={
            "naipe": "F",
            "force": True,
            "override_reason": "retificacao de cadastro",
        },
        headers={"X-Operator-Pin": supervisor_pin},
    )
    assert response.status_code == 200, response.text
    assert response.json()["naipe"] == "F"


@pytest.mark.asyncio
async def test_fiscal_endpoints_do_not_accept_force(client, supervisor_pin):
    """force so existe na gestao; no fiscal o campo e ignorado."""
    event = await create_event(client)
    prova = await _prova(client, event, naipe="M")
    heat = await create_heat_in_prova(client, prova["id"])
    athlete = await create_athlete(client, event["id"], name="Mario", naipe="M")
    created = await _assign(
        client, heat["id"], [{"lane_number": 1, "athlete_id": athlete["id"]}]
    )
    lane_id = created.json()["heat_lanes"][0]["id"]

    response = await client.post(
        f"/api/lanes/{lane_id}/ready",
        json={"force": True, "override_reason": "x"},
        headers={"X-Operator-Pin": supervisor_pin},
    )
    # Bateria nao esta em ready_check: force nao altera a regra.
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "bateria_nao_esta_em_ready_check"
