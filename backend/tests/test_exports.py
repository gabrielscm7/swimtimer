import hashlib
import io
import zipfile

import pytest

from tests.conftest import (
    create_athlete,
    create_event,
    create_heat,
    create_team,
)


async def _finished_heat(client):
    event = await create_event(client, name="Evento Export")
    team = await create_team(client, event["id"], "Equipe Azul")
    heat = await create_heat(
        client, event["id"], name="100 Livres", heat_type="bateria", distance_m=100
    )
    athlete = await create_athlete(
        client,
        event["id"],
        name="Maria da Silva",
        naipe="F",
        category="SENIOR",
        team_id=team["id"],
    )
    response = await client.post(
        f"/api/heats/{heat['id']}/lanes",
        json={"lanes": [{"lane_number": 3, "athlete_id": athlete["id"]}]},
    )
    assert response.status_code == 200, response.text
    heat = response.json()
    await client.post(f"/api/heats/{heat['id']}/open-ready-check")
    await client.post(f"/api/lanes/{heat['heat_lanes'][0]['id']}/ready")
    await client.post(f"/api/heats/{heat['id']}/start")
    response = await client.post(
        f"/api/lanes/{heat['heat_lanes'][0]['id']}/finish"
    )
    assert response.status_code == 200, response.text
    return event, heat


@pytest.mark.asyncio
async def test_results_csv(client):
    event, heat = await _finished_heat(client)
    response = await client.get(f"/api/events/{event['id']}/export/results.csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    text = response.content.decode("utf-8")
    assert text.startswith("\ufeff")
    lines = text.lstrip("\ufeff").splitlines()
    assert lines[0] == (
        "prova;bateria;raia;atleta;equipe;tempo;status;revisao;oficial"
    )
    assert lines[1].split(";")[:5] == [
        "100 Livres",
        "100 Livres",
        "3",
        "Maria da Silva",
        "Equipe Azul",
    ]
    assert lines[1].split(";")[7] == "1"
    assert lines[1].split(";")[8] == "nao"

    await client.post(f"/api/heats/{heat['id']}/homologate")
    again = await client.get(
        f"/api/events/{event['id']}/export/results.csv"
    )
    row = again.content.decode("utf-8").lstrip("\ufeff").splitlines()[1]
    assert row.split(";")[7] == "2"
    assert row.split(";")[8] == "sim"


@pytest.mark.asyncio
async def test_bundle_contains_db_csv_sumulas_and_manifest(client):
    event, _heat = await _finished_heat(client)
    response = await client.post(f"/api/events/{event['id']}/export/bundle")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert "results.csv" in names
        assert "manifest.sha256" in names
        assert any(name.startswith("sumulas/") for name in names)
        assert "backup/swimtimer.db" in names

        manifest = archive.read("manifest.sha256").decode("utf-8").splitlines()
        assert manifest
        declared = {}
        for line in manifest:
            digest, name = line.split("  ", 1)
            declared[name] = digest
        for name, digest in declared.items():
            content = archive.read(name)
            assert hashlib.sha256(content).hexdigest() == digest

        sumula = archive.read(
            next(name for name in names if name.startswith("sumulas/"))
        ).decode("utf-8")
        assert "Maria da Silva" in sumula
        assert "revisao 1" in sumula
        assert "@media print" in sumula
