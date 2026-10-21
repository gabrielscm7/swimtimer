"""Testes do upload/remocao de logotipo de equipe."""
import pytest

from app.config import settings
from tests.conftest import create_event, create_team

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF" + (64).to_bytes(4, "little") + b"WEBP" + b"\x00" * 64


async def _upload(client, team_id, content, filename="logo.png", mime="image/png"):
    return await client.post(
        f"/api/teams/{team_id}/logo",
        files={"file": (filename, content, mime)},
    )


@pytest.mark.asyncio
async def test_upload_and_serve_logo(client):
    event = await create_event(client)
    team = await create_team(client, event["id"], "Equipe Azul")

    response = await _upload(client, team["id"], PNG)
    assert response.status_code == 200, response.text
    logo_url = response.json()["logo_url"]
    assert logo_url.startswith("/logos/")
    assert (settings.logo_dir / logo_url.split("/")[-1]).is_file()

    served = await client.get(logo_url)
    assert served.status_code == 200
    assert served.content == PNG

    listing = (await client.get(f"/api/events/{event['id']}/teams")).json()
    assert listing[0]["logo_url"] == logo_url


@pytest.mark.asyncio
async def test_replace_logo_removes_old_file(client):
    event = await create_event(client)
    team = await create_team(client, event["id"], "Equipe")
    first = (await _upload(client, team["id"], PNG)).json()["logo_url"]

    response = await _upload(
        client, team["id"], JPEG, filename="nova.jpg", mime="image/jpeg"
    )
    assert response.status_code == 200, response.text
    second = response.json()["logo_url"]
    assert second != first
    assert not (settings.logo_dir / first.split("/")[-1]).exists()
    assert (settings.logo_dir / second.split("/")[-1]).is_file()


@pytest.mark.asyncio
async def test_remove_logo(client):
    event = await create_event(client)
    team = await create_team(client, event["id"], "Equipe")
    logo_url = (await _upload(client, team["id"], WEBP)).json()["logo_url"]

    response = await client.delete(f"/api/teams/{team['id']}/logo")
    assert response.status_code == 200, response.text
    assert response.json()["logo_url"] is None
    assert not (settings.logo_dir / logo_url.split("/")[-1]).exists()


@pytest.mark.asyncio
async def test_rejects_content_not_matching_extension(client):
    event = await create_event(client)
    team = await create_team(client, event["id"], "Equipe")

    response = await _upload(
        client, team["id"], b"nao sou imagem", filename="falsa.png"
    )
    assert response.status_code == 415, response.text
    assert response.json()["detail"] == "formato_invalido"


@pytest.mark.asyncio
async def test_rejects_oversized_logo(client, monkeypatch):
    event = await create_event(client)
    team = await create_team(client, event["id"], "Equipe")
    monkeypatch.setattr(settings, "MAX_LOGO_BYTES", 10)

    response = await _upload(client, team["id"], PNG)
    assert response.status_code == 413, response.text
    assert response.json()["detail"] == "arquivo_muito_grande"


@pytest.mark.asyncio
async def test_rejects_empty_file(client):
    event = await create_event(client)
    team = await create_team(client, event["id"], "Equipe")

    response = await _upload(client, team["id"], b"")
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "arquivo_vazio"


@pytest.mark.asyncio
async def test_team_without_logo_still_works(client):
    event = await create_event(client)
    team = await create_team(client, event["id"], "Sem Logo")
    assert team["logo_url"] is None
    response = await client.delete(f"/api/teams/{team['id']}/logo")
    assert response.status_code == 200
    assert response.json()["logo_url"] is None


@pytest.mark.asyncio
async def test_update_team_name(client):
    event = await create_event(client)
    team = await create_team(client, event["id"], "Antigo")

    response = await client.patch(
        f"/api/teams/{team['id']}", json={"name": "Novo"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Novo"
