import io

import pytest
from openpyxl import Workbook

from tests.conftest import create_athlete, create_event, create_team

HEADER = "NOME,EQUIPE,NAIPE,CATEGORIA\n"


def _csv(*rows: str) -> str:
    return HEADER + "".join(row + "\n" for row in rows)


def _xlsx(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def _import(client, event_id, name, content, media_type):
    return await client.post(
        f"/api/events/{event_id}/athletes/import",
        files={"file": (name, content, media_type)},
    )


@pytest.mark.asyncio
async def test_import_csv_creates_athletes_and_teams(client):
    event = await create_event(client)
    csv_data = _csv(
        "Ana Souza,Leões,F,SUB-12",
        "Bia Lima,Leões,F,SUB-14",
        "Caio Reis,Tubarões,M,SUB-12",
        "Duda, ,F,ABSOLUTO",
    )

    response = await _import(
        client, event["id"], "atletas.csv", csv_data.encode(), "text/csv"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_athletes"] == 4
    assert body["created_teams"] == 2
    assert body["errors"] == []

    listing = (await client.get(f"/api/events/{event['id']}/athletes")).json()
    assert listing["total"] == 4
    by_name = {item["name"]: item for item in listing["items"]}
    assert by_name["Ana Souza"]["team_name"] == "Leões"
    assert by_name["Duda"]["team_id"] is None
    assert by_name["Ana Souza"]["category"] == "SUB-12"


@pytest.mark.asyncio
async def test_import_csv_semicolon_and_bom(client):
    event = await create_event(client)
    content = "\ufeffNOME;EQUIPE;NAIPE;CATEGORIA\nAna;Leões;F;SUB-12\n"
    response = await _import(
        client, event["id"], "atletas.csv", content.encode(), "text/csv"
    )
    assert response.status_code == 200, response.text
    assert response.json()["created_athletes"] == 1


@pytest.mark.asyncio
async def test_import_partial_reports_invalid_rows(client):
    event = await create_event(client)
    await create_athlete(
        client, event["id"], name="Existente", naipe="M"
    )
    csv_data = _csv(
        "Válido,Equipe,F,SUB-12",
        ",Equipe,F,SUB-12",
        "Naipe Ruim,Equipe,X,SUB-12",
        "existente,,M,SUB-12",
        "Outro Válido,Equipe,M,SUB-12",
    )

    response = await _import(
        client, event["id"], "atletas.csv", csv_data.encode(), "text/csv"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_athletes"] == 2
    assert body["created_teams"] == 1
    errors = {(item["line"], item["message"]) for item in body["errors"]}
    assert (3, "nome_obrigatorio") in errors
    assert (4, "naipe_invalido") in errors
    assert (5, "atleta_duplicado") in errors

    listing = (await client.get(f"/api/events/{event['id']}/athletes")).json()
    names = {item["name"] for item in listing["items"]}
    assert names == {"Existente", "Válido", "Outro Válido"}


@pytest.mark.asyncio
async def test_import_xlsx(client):
    event = await create_event(client)
    content = _xlsx(
        [
            ["NOME", "EQUIPE", "NAIPE", "CATEGORIA"],
            ["Ana", "Leões", "Feminino", "sub-12"],
            ["Bia", "Leões", "F", "SUB-12"],
        ]
    )
    response = await _import(
        client,
        event["id"],
        "atletas.xlsx",
        content,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_athletes"] == 2
    assert body["created_teams"] == 1


@pytest.mark.asyncio
async def test_import_rejects_invalid_format(client):
    event = await create_event(client)

    wrong_extension = await _import(
        client, event["id"], "atletas.pdf", b"%PDF-1.4", "application/pdf"
    )
    assert wrong_extension.status_code == 415
    assert wrong_extension.json()["detail"] == "formato_invalido"

    fake_xlsx = await _import(
        client,
        event["id"],
        "atletas.xlsx",
        b"not-a-zip",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert fake_xlsx.status_code == 415
    assert fake_xlsx.json()["detail"] == "formato_invalido"

    corrupt_xlsx = await _import(
        client,
        event["id"],
        "atletas.xlsx",
        b"PK\x03\x04conteudo-corrompido",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert corrupt_xlsx.status_code == 400
    assert corrupt_xlsx.json()["detail"] == "planilha_invalida"

    empty = await _import(client, event["id"], "atletas.csv", b"", "text/csv")
    assert empty.status_code == 400
    assert empty.json()["detail"] == "arquivo_vazio"


@pytest.mark.asyncio
async def test_import_requires_columns(client):
    event = await create_event(client)
    content = "NOME,NAIPE\nAna,F\n"
    response = await _import(
        client, event["id"], "atletas.csv", content.encode(), "text/csv"
    )
    assert response.status_code == 400
    assert "colunas_obrigatorias" in response.json()["detail"]

    no_header = "Ana,F\n"
    response = await _import(
        client, event["id"], "atletas.csv", no_header.encode(), "text/csv"
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "planilha_sem_cabecalho"


@pytest.mark.asyncio
async def test_import_200_athletes_bulk(client):
    event = await create_event(client)
    rows = []
    for index in range(200):
        team = f"Equipe {index // 10 + 1}"
        naipe = "M" if index % 2 == 0 else "F"
        rows.append(f"Atleta {index:03d},{team},{naipe},SUB-12")
    response = await _import(
        client,
        event["id"],
        "atletas.csv",
        _csv(*rows).encode(),
        "text/csv",
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_athletes"] == 200
    assert body["created_teams"] == 20
    assert body["errors"] == []

    first_page = (
        await client.get(f"/api/events/{event['id']}/athletes")
    ).json()
    assert first_page["total"] == 200
    assert len(first_page["items"]) == 50

    second_page = (
        await client.get(
            f"/api/events/{event['id']}/athletes",
            params={"limit": 200, "offset": 0},
        )
    ).json()
    assert len(second_page["items"]) == 200

    teams = (await client.get(f"/api/events/{event['id']}/teams")).json()
    assert len(teams) == 20
    assert sum(team["athlete_count"] for team in teams) == 200


@pytest.mark.asyncio
async def test_template_download_csv_and_xlsx(client):
    event = await create_event(client)
    base = f"/api/events/{event['id']}/athletes/import-template"

    csv_response = await client.get(base, params={"format": "csv"})
    assert csv_response.status_code == 200
    assert "NOME,EQUIPE,NAIPE,CATEGORIA" in csv_response.text
    assert "attachment" in csv_response.headers["content-disposition"]

    xlsx_response = await client.get(base, params={"format": "xlsx"})
    assert xlsx_response.status_code == 200
    assert xlsx_response.content.startswith(b"PK\x03\x04")


@pytest.mark.asyncio
async def test_export_round_trip(client):
    event = await create_event(client)
    team = await create_team(client, event["id"], "Leões")
    await create_athlete(
        client,
        event["id"],
        name="Ana",
        naipe="F",
        category="SUB-12",
        team_id=team["id"],
    )

    response = await client.get(f"/api/events/{event['id']}/athletes/export")
    assert response.status_code == 200
    text = response.text.lstrip("\ufeff")
    assert "NOME,EQUIPE,NAIPE,CATEGORIA" in text
    assert "Ana,Leões,F,SUB-12" in text


@pytest.mark.asyncio
async def test_import_registration_code_disambiguates_homonyms(client):
    event = await create_event(client)
    content = (
        "NOME,EQUIPE,NAIPE,CATEGORIA,REGISTRO\n"
        "João Silva,Leões,M,SUB-12,A-001\n"
        "João Silva,Leões,M,SUB-12,A-002\n"
    )
    response = await _import(
        client, event["id"], "atletas.csv", content.encode(), "text/csv"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_athletes"] == 2
    assert body["errors"] == []

    listing = (
        await client.get(
            f"/api/events/{event['id']}/athletes", params={"limit": 200}
        )
    ).json()
    codes = sorted(
        item["registration_code"] for item in listing["items"]
    )
    assert codes == ["A-001", "A-002"]


@pytest.mark.asyncio
async def test_import_without_registration_column_still_works(client):
    event = await create_event(client)
    content = "NOME,EQUIPE,NAIPE,CATEGORIA\nAna,Leões,F,SUB-12\n"
    response = await _import(
        client, event["id"], "atletas.csv", content.encode(), "text/csv"
    )
    assert response.status_code == 200, response.text
    assert response.json()["created_athletes"] == 1


@pytest.mark.asyncio
async def test_template_and_export_include_registration_code(client):
    event = await create_event(client)
    base = f"/api/events/{event['id']}/athletes/import-template"
    csv_response = await client.get(base, params={"format": "csv"})
    assert "REGISTRO" in csv_response.text
    assert "A-001" in csv_response.text

    team = await create_team(client, event["id"], "Leões")
    await create_athlete(
        client,
        event["id"],
        name="Ana",
        naipe="F",
        team_id=team["id"],
        registration_code="C-007",
    )
    export = await client.get(f"/api/events/{event['id']}/athletes/export")
    text = export.text.lstrip("\ufeff")
    assert "REGISTRO" in text
    assert "Ana,Leões,F,,C-007" in text
