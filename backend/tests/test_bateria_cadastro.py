"""Prova automatica: find-or-create, mudanca de grupo e remocao (ADR-012)."""
import pytest

from tests.conftest import create_event, create_heat


def _key(heat):
    return (
        heat["heat_type"],
        heat["stroke"],
        heat["distance_m"] if heat["heat_type"] == "bateria" else None,
        heat["naipe"],
        heat["category"],
    )


@pytest.mark.asyncio
async def test_mesma_chave_reutiliza_prova_e_chaves_distintas_separam(client):
    event = await create_event(client)
    a1 = await create_heat(client, event["id"], stroke="livre", distance_m=25)
    a2 = await create_heat(client, event["id"], stroke="livre", distance_m=25)
    b1 = await create_heat(client, event["id"], stroke="livre", distance_m=50)
    c1 = await create_heat(
        client, event["id"], stroke="livre", distance_m=25, naipe="F"
    )

    assert a1["prova_id"] == a2["prova_id"]
    assert a1["prova_id"] != b1["prova_id"]
    assert a1["prova_id"] != c1["prova_id"]

    provas = (await client.get(f"/api/events/{event['id']}/provas")).json()
    for prova in provas:
        keys = {_key(heat) for heat in prova["heats"]}
        assert len(keys) <= 1, "prova nao pode ter baterias de grupos diferentes"


@pytest.mark.asyncio
async def test_editar_move_grupo_e_remove_prova_vazia(client):
    event = await create_event(client)
    heat = await create_heat(client, event["id"], stroke="livre")
    old_id = heat["prova_id"]

    response = await client.patch(
        f"/api/heats/{heat['id']}", json={"category": "mirim"}
    )
    assert response.status_code == 200, response.text
    moved = response.json()
    assert moved["prova_id"] != old_id
    assert moved["prova_name"] == "25 m Livre · Misto · Mirim"
    assert (await client.get(f"/api/provas/{old_id}")).status_code == 404

    back = await client.patch(
        f"/api/heats/{heat['id']}", json={"category": "livre"}
    )
    assert back.status_code == 200, back.text
    assert back.json()["prova_id"] != moved["prova_id"]
    assert (
        await client.get(f"/api/provas/{moved['prova_id']}")
    ).status_code == 404


@pytest.mark.asyncio
async def test_classificar_isolada_cria_grupo_proprio(client):
    event = await create_event(client)
    shared = await create_heat(client, event["id"], stroke="crawl")
    isolated = await create_heat(
        client, event["id"], stroke="crawl", classify_alone=True
    )
    assert isolated["prova_id"] != shared["prova_id"]

    # Desmarcar "isolada" devolve a bateria ao grupo compartilhado.
    response = await client.patch(
        f"/api/heats/{isolated['id']}", json={"classify_alone": False}
    )
    assert response.status_code == 200, response.text
    assert response.json()["prova_id"] == shared["prova_id"]
    assert (
        await client.get(f"/api/provas/{isolated['prova_id']}")
    ).status_code == 404


@pytest.mark.asyncio
async def test_lane_count_limita_raias(client):
    event = await create_event(client)
    heat = await create_heat(
        client, event["id"], lane_count=2
    )
    assert heat["lane_count"] == 2

    response = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 3, "participant_name": "Ana"}]},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "raia_acima_de_lane_count"

    ok = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 2, "participant_name": "Ana"}]},
    )
    assert ok.status_code == 200, ok.text

    shrink = await client.patch(
        f"/api/heats/{heat['id']}", json={"lane_count": 1}
    )
    assert shrink.status_code == 422
    assert shrink.json()["detail"] == "lane_count_menor_que_raias"


@pytest.mark.asyncio
async def test_lane_count_herda_default_do_evento(client):
    event = await create_event(client)
    assert event["default_lane_count"] == 3
    response = await client.patch(
        f"/api/events/{event['id']}", json={"default_lane_count": 5}
    )
    assert response.status_code == 200, response.text
    heat = await create_heat(client, event["id"])
    assert heat["lane_count"] == 5


@pytest.mark.asyncio
async def test_nome_gerado_para_grupos_de_maratona(client):
    event = await create_event(client)
    heat = await create_heat(
        client,
        event["id"],
        heat_type="maratona",
        distance_m=None,
        duration_s=5400,
        stroke="peito",
        naipe="F",
        category="juvenil",
    )
    assert heat["prova_name"] == "Maratona 1.5 h · Peito · Feminino · Juvenil"
