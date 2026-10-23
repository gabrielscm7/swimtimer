"""Regras do grupo automatico: definicao da bateria, nome gerado e legado."""
import pytest
from sqlalchemy import select

from app import database as database_module
from app.classification import build_classification
from app.models import Heat
from tests.conftest import create_event, create_heat


async def _post_heat(client, event_id, **overrides):
    body = {
        "heat_type": "bateria",
        "stroke": "livre",
        "distance_m": 25,
        "naipe": "M",
        "category": "livre",
    }
    body.update(overrides)
    return await client.post(f"/api/events/{event_id}/heats", json=body)


@pytest.mark.asyncio
async def test_bateria_exige_definicao_completa(client):
    event = await create_event(client)
    for body in (
        {"heat_type": "bateria", "distance_m": 25, "naipe": "M", "category": "livre"},
        {"heat_type": "bateria", "stroke": "livre", "naipe": "M", "category": "livre"},
        {"heat_type": "bateria", "stroke": "livre", "distance_m": 25, "category": "livre"},
        {"heat_type": "bateria", "stroke": "livre", "distance_m": 25, "naipe": "M"},
        {"heat_type": "bateria", "stroke": "invalido", "distance_m": 25, "naipe": "M", "category": "livre"},
        {"heat_type": "bateria", "stroke": "livre", "distance_m": 25, "naipe": "M", "category": "senior"},
        {"heat_type": "maratona", "stroke": "livre", "naipe": "M", "category": "livre"},
    ):
        response = await client.post(
            f"/api/events/{event['id']}/heats", json=body
        )
        assert response.status_code == 422, (body, response.text)


@pytest.mark.asyncio
async def test_mesmo_grupo_nao_duplica_prova(client):
    event = await create_event(client)
    first = await _post_heat(
        client, event["id"], stroke="LIVRE", naipe="m", category="mirim"
    )
    assert first.status_code == 201, first.text
    second = await _post_heat(
        client, event["id"], stroke="Livre", naipe="M", category="MIRIM"
    )
    assert second.status_code == 201, second.text
    assert first.json()["prova_id"] == second.json()["prova_id"]


@pytest.mark.asyncio
async def test_nome_gerado_e_estilos_distintos(client):
    event = await create_event(client)
    crawl = (await _post_heat(client, event["id"], stroke="crawl")).json()
    livre = (await _post_heat(client, event["id"], stroke="livre")).json()
    assert crawl["prova_id"] != livre["prova_id"]
    assert crawl["prova_name"] == "25 m Crawl · Masculino"
    assert livre["prova_name"] == "25 m Livre · Masculino"

    mirim = (
        await _post_heat(client, event["id"], category="mirim")
    ).json()
    assert mirim["prova_name"] == "25 m Livre · Masculino · Mirim"


@pytest.mark.asyncio
async def test_editar_atributos_move_e_renomeia_grupo(client):
    event = await create_event(client)
    heat = (await _post_heat(client, event["id"])).json()
    response = await client.patch(
        f"/api/heats/{heat['id']}",
        json={"stroke": "crawl", "category": "mirim"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["prova_name"] == "25 m Crawl · Masculino · Mirim"
    assert body["prova_id"] != heat["prova_id"]


@pytest.mark.asyncio
async def test_maratona_nao_exige_distancia(client):
    event = await create_event(client)
    heat = (
        await _post_heat(
            client,
            event["id"],
            heat_type="maratona",
            distance_m=None,
            duration_s=7200,
            naipe="F",
            category="livre",
        )
    ).json()
    prova = (await client.get(f"/api/provas/{heat['prova_id']}")).json()
    assert prova["format"] == "maratona"
    assert prova["distance_m"] is None
    assert prova["name"] == "Maratona 2 h · Livre · Feminino"


@pytest.mark.asyncio
async def test_bateria_legada_incompleta_exige_conclusao(client):
    event = await create_event(client)
    heat = (await _post_heat(client, event["id"])).json()

    async with database_module.AsyncSessionLocal() as session:
        row = await session.get(Heat, heat["id"])
        row.stroke = None
        row.naipe = None
        row.category = None
        await session.commit()

    detail = (await client.get(f"/api/heats/{heat['id']}")).json()
    assert detail["legacy_incomplete"] is True

    # Edicao operacional (nome) continua permitida.
    renamed = await client.patch(
        f"/api/heats/{heat['id']}", json={"name": "Final A"}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["legacy_incomplete"] is True

    # Concluir a definicao exige os tres campos.
    partial = await client.patch(
        f"/api/heats/{heat['id']}", json={"stroke": "livre"}
    )
    assert partial.status_code == 422
    assert partial.json()["detail"] == "grupo_incompleto"

    fixed = await client.patch(
        f"/api/heats/{heat['id']}",
        json={"stroke": "livre", "naipe": "M", "category": "livre"},
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["legacy_incomplete"] is False


@pytest.mark.asyncio
async def test_evento_data_obrigatoria_iso_e_aviso_de_duplicidade(client):
    missing = await client.post("/api/events", json={"name": "Sem data"})
    assert missing.status_code == 422
    invalid = await client.post(
        "/api/events", json={"name": "Data ruim", "date": "23/10/2026"}
    )
    assert invalid.status_code == 422

    first = await client.post(
        "/api/events",
        json={"name": "Festival", "date": "2026-10-23", "pool_length_m": 25},
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        "/api/events",
        json={"name": "Festival", "date": "2026-10-23", "pool_length_m": 25},
    )
    assert second.status_code == 201, second.text
    assert "evento_mesmo_nome_data" in second.json()["warnings"]


def _heat_dict(prova_id: str, heat_id: str, distance_m: int) -> dict:
    return {
        "id": heat_id,
        "name": heat_id,
        "order_num": 1,
        "prova_id": prova_id,
        "status": "finished",
        "distance_m": distance_m,
        "lanes": [],
    }


def test_classificacao_sinaliza_bateria_divergente():
    result = build_classification(
        heats=[_heat_dict("p1", "h1", 50)],
        team_map={},
        pool_distance_m=25,
        prova_distance_m=25,
        prova_id="p1",
        mixed_ranking="overall",
    )
    assert result["warnings"][0]["code"] == "bateria_distancia_divergente"


@pytest.mark.asyncio
async def test_summary_expoe_grupo_e_sequencia(client):
    event = await create_event(client)
    first = (await _post_heat(client, event["id"], stroke="livre")).json()
    second = (await _post_heat(client, event["id"], stroke="costas")).json()

    summary = (
        await client.get(f"/api/provas/{first['prova_id']}/summary")
    ).json()
    assert summary["heat_count"] == 1
    assert summary["stroke"] == "livre"
    assert summary["classification"]["mixed_ranking"] == "overall"

    heats = (await client.get(f"/api/events/{event['id']}/heats")).json()
    assert [heat["id"] for heat in heats] == [first["id"], second["id"]]
    assert [heat["event_seq"] for heat in heats] == [1, 2]
