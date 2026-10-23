"""Testes do tema configuravel do front publico."""
import base64

import pytest

from app.config import settings
from app.services.themes import normalize_theme
from tests.conftest import create_event

# PNG 1x1 transparente valido.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

DEFAULT_THEME = {
    "bg": "#0f1117",
    "bg2": "#14161f",
    "panel": "#1a1d27",
    "text": "#e8eaf0",
    "muted": "#6b7280",
    "accent": "#00d4ff",
    "accent_strong": "#00b0d6",
    "lvl_prova": "#a78bfa",
    "lvl_bateria": "#22d3ee",
    "bg_image_url": None,
    "bg_opacity": 1.0,
    "bg_fit": "cover",
    "bg_position": "center",
    "logo_url": None,
    "title_override": None,
    "footer_text": None,
    "show_team_logos": True,
    "font_scale": 1.0,
}


def _theme(**overrides):
    theme = dict(DEFAULT_THEME)
    theme.update(overrides)
    return theme


def _png_with_size(width: int, height: int) -> bytes:
    body = (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + len(body).to_bytes(4, "big")
        + b"IHDR"
        + body
    )


async def _upload(
    client,
    event_id: str,
    content: bytes,
    *,
    kind: str = "background",
    filename: str = "bg.png",
    mime: str = "image/png",
):
    return await client.post(
        f"/api/events/{event_id}/theme/image?kind={kind}",
        files={"file": (filename, content, mime)},
    )


@pytest.mark.asyncio
async def test_get_theme_returns_default_when_unset(client):
    event = await create_event(client)

    response = await client.get(f"/api/events/{event['id']}/theme")
    assert response.status_code == 200, response.text
    assert response.json() == DEFAULT_THEME


@pytest.mark.asyncio
async def test_put_theme_persists_normalized_values(client):
    event = await create_event(client)
    body = _theme(
        bg="#0A0B0C",
        panel="#101010",
        text="#ffffff",
        muted="#cccccc",
        accent="#FF0000",
        accent_strong="#CC0000",
        bg_opacity=0.4,
        bg_fit="contain",
        bg_position="top center",
        title_override="Copa Swim",
        footer_text="Boa prova!",
        show_team_logos=False,
        font_scale=1.2,
    )

    response = await client.put(f"/api/events/{event['id']}/theme", json=body)
    assert response.status_code == 200, response.text
    theme = response.json()
    assert theme["bg"] == "#0a0b0c"
    assert theme["accent"] == "#ff0000"
    assert theme["bg_fit"] == "contain"
    assert theme["font_scale"] == 1.2
    assert theme["show_team_logos"] is False

    fetched = await client.get(f"/api/events/{event['id']}/theme")
    assert fetched.json() == theme


@pytest.mark.asyncio
async def test_put_theme_rejects_bad_values(client):
    event = await create_event(client)

    bad_hex = _theme(bg="vermelho")
    response = await client.put(
        f"/api/events/{event['id']}/theme", json=bad_hex
    )
    assert response.status_code == 422

    bad_fit = _theme(bg_fit="stretch")
    response = await client.put(
        f"/api/events/{event['id']}/theme", json=bad_fit
    )
    assert response.status_code == 422

    bad_opacity = _theme(bg_opacity=1.5)
    response = await client.put(
        f"/api/events/{event['id']}/theme", json=bad_opacity
    )
    assert response.status_code == 422

    bad_scale = _theme(font_scale=2.0)
    response = await client.put(
        f"/api/events/{event['id']}/theme", json=bad_scale
    )
    assert response.status_code == 422

    bad_url = _theme(bg_image_url="https://example.com/x.png")
    response = await client.put(
        f"/api/events/{event['id']}/theme", json=bad_url
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_theme_blocks_low_contrast(client):
    event = await create_event(client)
    body = _theme(
        bg="#888888",
        bg2="#888888",
        panel="#888888",
        text="#777777",
    )

    response = await client.put(f"/api/events/{event['id']}/theme", json=body)
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "contraste_insuficiente"


@pytest.mark.asyncio
async def test_upload_png_preserves_bytes_and_alpha(client):
    event = await create_event(client)

    response = await _upload(client, event["id"], PNG_1PX)
    assert response.status_code == 200, response.text
    theme = response.json()
    url = theme["bg_image_url"]
    assert url.startswith("/theme/")
    assert (settings.theme_dir / url.split("/")[-1]).read_bytes() == PNG_1PX

    served = await client.get(url)
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == PNG_1PX


@pytest.mark.asyncio
async def test_upload_logo_and_replace_removes_old_file(client):
    event = await create_event(client)
    first = (await _upload(client, event["id"], PNG_1PX, kind="logo")).json()
    first_url = first["logo_url"]
    first_path = settings.theme_dir / first_url.split("/")[-1]
    assert first_path.is_file()

    second_png = _png_with_size(2, 1)
    response = await _upload(
        client,
        event["id"],
        second_png,
        kind="logo",
        filename="logo.png",
    )
    assert response.status_code == 200, response.text
    second_url = response.json()["logo_url"]
    assert second_url != first_url
    assert not first_path.exists()
    assert (settings.theme_dir / second_url.split("/")[-1]).is_file()


@pytest.mark.asyncio
async def test_upload_rejects_invalid_files(client, monkeypatch):
    event = await create_event(client)

    empty = await _upload(client, event["id"], b"")
    assert empty.status_code == 400
    assert empty.json()["detail"] == "arquivo_vazio"

    not_image = await _upload(client, event["id"], b"nao sou imagem")
    assert not_image.status_code == 415
    assert not_image.json()["detail"] == "imagem_formato_invalido"

    too_wide = await _upload(client, event["id"], _png_with_size(3841, 10))
    assert too_wide.status_code == 413
    assert too_wide.json()["detail"] == "imagem_muito_grande"

    monkeypatch.setattr(settings, "MAX_THEME_IMAGE_BYTES", 10)
    too_big = await _upload(client, event["id"], PNG_1PX)
    assert too_big.status_code == 413
    assert too_big.json()["detail"] == "arquivo_muito_grande"


@pytest.mark.asyncio
async def test_delete_theme_image_removes_file(client):
    event = await create_event(client)
    theme = (await _upload(client, event["id"], PNG_1PX)).json()
    url = theme["bg_image_url"]
    path = settings.theme_dir / url.split("/")[-1]
    assert path.is_file()

    response = await client.delete(
        f"/api/events/{event['id']}/theme/image?kind=background"
    )
    assert response.status_code == 200, response.text
    assert response.json()["bg_image_url"] is None
    assert not path.exists()


@pytest.mark.asyncio
async def test_put_default_removes_unreferenced_images(client):
    event = await create_event(client)
    bg = (await _upload(client, event["id"], PNG_1PX)).json()[
        "bg_image_url"
    ]
    logo = (
        await _upload(client, event["id"], PNG_1PX, kind="logo")
    ).json()["logo_url"]

    response = await client.put(
        f"/api/events/{event['id']}/theme", json=_theme()
    )
    assert response.status_code == 200, response.text
    assert response.json()["bg_image_url"] is None
    assert response.json()["logo_url"] is None
    assert not (settings.theme_dir / bg.split("/")[-1]).exists()
    assert not (settings.theme_dir / logo.split("/")[-1]).exists()


@pytest.mark.asyncio
async def test_put_rejects_stale_foreign_and_missing_images(client):
    event = await create_event(client)
    first = (await _upload(client, event["id"], PNG_1PX)).json()[
        "bg_image_url"
    ]
    second = (await _upload(client, event["id"], PNG_1PX)).json()[
        "bg_image_url"
    ]
    assert first != second
    assert not (settings.theme_dir / first.split("/")[-1]).exists()

    stale = await client.put(
        f"/api/events/{event['id']}/theme",
        json=_theme(bg_image_url=first),
    )
    assert stale.status_code == 422, stale.text
    assert stale.json()["detail"] == "url_tema_invalida"

    current = await client.put(
        f"/api/events/{event['id']}/theme",
        json=_theme(bg_image_url=second),
    )
    assert current.status_code == 200, current.text

    (settings.theme_dir / second.split("/")[-1]).unlink()
    missing = await client.put(
        f"/api/events/{event['id']}/theme",
        json=_theme(bg_image_url=second),
    )
    assert missing.status_code == 422, missing.text
    assert missing.json()["detail"] == "imagem_tema_ausente"

    other = await create_event(client, name="Outro evento")
    foreign = await client.put(
        f"/api/events/{other['id']}/theme",
        json=_theme(bg_image_url=second),
    )
    assert foreign.status_code == 422, foreign.text
    assert foreign.json()["detail"] == "url_tema_invalida"


@pytest.mark.asyncio
async def test_shared_image_reference_is_not_deleted(client):
    event = await create_event(client)
    shared = (await _upload(client, event["id"], PNG_1PX)).json()[
        "bg_image_url"
    ]
    path = settings.theme_dir / shared.split("/")[-1]

    response = await client.put(
        f"/api/events/{event['id']}/theme",
        json=_theme(bg_image_url=shared, logo_url=shared),
    )
    assert response.status_code == 200, response.text

    replacement = (await _upload(client, event["id"], PNG_1PX)).json()
    assert replacement["logo_url"] == shared
    assert replacement["bg_image_url"] != shared
    assert path.is_file()


@pytest.mark.asyncio
async def test_put_theme_blocks_low_contrast_accent(client):
    event = await create_event(client)
    body = _theme(accent="#0f1117", accent_strong="#14161f")

    response = await client.put(f"/api/events/{event['id']}/theme", json=body)
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "contraste_insuficiente"


def test_normalize_theme_matches_schema_text_limits():
    theme = normalize_theme(
        {
            "title_override": "x" * 250,
            "footer_text": "y" * 350,
        }
    )
    assert len(theme["title_override"]) == 200
    assert len(theme["footer_text"]) == 300


@pytest.mark.asyncio
async def test_delete_event_removes_theme_files(client):
    event = await create_event(client)
    bg = (await _upload(client, event["id"], PNG_1PX)).json()[
        "bg_image_url"
    ]
    logo = (
        await _upload(client, event["id"], PNG_1PX, kind="logo")
    ).json()["logo_url"]

    response = await client.delete(f"/api/events/{event['id']}")
    assert response.status_code == 204, response.text
    assert not (settings.theme_dir / bg.split("/")[-1]).exists()
    assert not (settings.theme_dir / logo.split("/")[-1]).exists()


def _create_event(ws_client):
    response = ws_client.post(
        "/api/events", json={"name": "Evento WS tema", "date": "2026-10-23", "pool_length_m": 25}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_theme_updated_broadcast(ws_client):
    event = _create_event(ws_client)
    with ws_client.websocket_connect("/ws") as websocket:
        assert websocket.receive_json()["type"] == "server_status"
        response = ws_client.put(
            f"/api/events/{event['id']}/theme",
            json=_theme(accent="#ff5500", accent_strong="#cc4400"),
        )
        assert response.status_code == 200, response.text

        message = None
        for _ in range(30):
            candidate = websocket.receive_json()
            if candidate.get("type") == "theme_updated":
                message = candidate
                break
        assert message is not None
        assert message["scope"] == "event"
        assert message["event_id"] == event["id"]
        assert message["payload"]["accent"] == "#ff5500"
