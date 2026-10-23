"""Tema do front publico: defaults, contraste, arquivos e dimensoes."""

import json
import re

from ..config import settings

DEFAULT_THEME: dict = {
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

_COLOR_KEYS = (
    "bg",
    "bg2",
    "panel",
    "text",
    "muted",
    "accent",
    "accent_strong",
    "lvl_prova",
    "lvl_bateria",
)
_IMAGE_KEYS = ("bg_image_url", "logo_url")
_TEXT_LIMITS = {"title_override": 200, "footer_text": 300}
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_URL_RE = re.compile(r"^/theme/[A-Za-z0-9._-]+$")
_POSITION_RE = re.compile(r"^[A-Za-z0-9% .-]{1,40}$")
_FITS = ("cover", "contain", "center")


def _hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or not _HEX_RE.match(value):
        return None
    return (
        int(value[1:3], 16),
        int(value[3:5], 16),
        int(value[5:7], 16),
    )


def _relative_luminance(value: str) -> float | None:
    rgb = _hex_to_rgb(value)
    if rgb is None:
        return None
    channels = []
    for component in rgb:
        channel = component / 255
        channels.append(
            channel / 12.92
            if channel <= 0.03928
            else ((channel + 0.055) / 1.055) ** 2.4
        )
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    first_lum = _relative_luminance(first)
    second_lum = _relative_luminance(second)
    if first_lum is None or second_lum is None:
        return 0.0
    lighter = max(first_lum, second_lum)
    darker = min(first_lum, second_lum)
    return (lighter + 0.05) / (darker + 0.05)


def theme_contrast_report(theme: dict) -> dict:
    text = theme.get("text", DEFAULT_THEME["text"])
    muted = theme.get("muted", DEFAULT_THEME["muted"])
    accent = theme.get("accent", DEFAULT_THEME["accent"])
    accent_strong = theme.get(
        "accent_strong", DEFAULT_THEME["accent_strong"]
    )
    lvl_prova = theme.get("lvl_prova", DEFAULT_THEME["lvl_prova"])
    lvl_bateria = theme.get("lvl_bateria", DEFAULT_THEME["lvl_bateria"])
    panel = theme.get("panel", DEFAULT_THEME["panel"])
    background = theme.get("bg", DEFAULT_THEME["bg"])

    pairs = {
        "text_panel": contrast_ratio(text, panel),
        "text_bg": contrast_ratio(text, background),
        "muted_panel": contrast_ratio(muted, panel),
        "muted_bg": contrast_ratio(muted, background),
        "accent_panel": contrast_ratio(accent, panel),
        "accent_bg": contrast_ratio(accent, background),
        "accent_strong_panel": contrast_ratio(accent_strong, panel),
        "accent_strong_bg": contrast_ratio(accent_strong, background),
        "lvl_prova_panel": contrast_ratio(lvl_prova, panel),
        "lvl_prova_bg": contrast_ratio(lvl_prova, background),
        "lvl_bateria_panel": contrast_ratio(lvl_bateria, panel),
        "lvl_bateria_bg": contrast_ratio(lvl_bateria, background),
    }
    text_min = min(pairs["text_panel"], pairs["text_bg"])
    report = {key: round(value, 2) for key, value in pairs.items()}
    report["text_min"] = round(text_min, 2)
    report["min"] = round(min(pairs.values()), 2)
    return report


def normalize_theme(raw: str | dict | None) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = None
    if not isinstance(raw, dict):
        raw = {}

    theme = dict(DEFAULT_THEME)
    for key in _COLOR_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and _HEX_RE.match(value):
            theme[key] = value.lower()

    for key in _IMAGE_KEYS:
        value = raw.get(key)
        if value is None:
            theme[key] = None
        elif isinstance(value, str) and _URL_RE.match(value):
            theme[key] = value

    try:
        opacity = float(raw.get("bg_opacity", theme["bg_opacity"]))
        theme["bg_opacity"] = min(1.0, max(0.0, opacity))
    except (TypeError, ValueError):
        pass

    fit = raw.get("bg_fit")
    if fit in _FITS:
        theme["bg_fit"] = fit

    position = raw.get("bg_position")
    if isinstance(position, str) and _POSITION_RE.match(position):
        theme["bg_position"] = position

    for key, limit in _TEXT_LIMITS.items():
        value = raw.get(key)
        if value is None:
            theme[key] = None
        elif isinstance(value, str):
            theme[key] = value[:limit]

    show_logos = raw.get("show_team_logos")
    if isinstance(show_logos, bool):
        theme["show_team_logos"] = show_logos

    try:
        scale = float(raw.get("font_scale", theme["font_scale"]))
        theme["font_scale"] = min(1.4, max(0.8, scale))
    except (TypeError, ValueError):
        pass

    return theme


def serialize_theme(theme: dict) -> str:
    return json.dumps(
        theme,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def theme_path_from_url(url: str | None, event_id: str | None = None):
    if not isinstance(url, str) or not _URL_RE.match(url):
        return None
    name = url[len("/theme/"):]
    if event_id and not name.startswith(f"{event_id}-"):
        return None
    path = settings.theme_dir / name
    if path.parent != settings.theme_dir:
        return None
    return path


def referenced_theme_urls(theme: dict) -> set[str]:
    return {
        url
        for key in _IMAGE_KEYS
        if isinstance((url := theme.get(key)), str) and url
    }


def validate_theme_references(
    theme: dict, event_id: str, allowed_urls: set[str]
) -> str | None:
    """Rejeita URLs que não sejam atuais nem arquivos existentes do evento."""
    for url in referenced_theme_urls(theme):
        if url not in allowed_urls:
            return "url_tema_invalida"
        path = theme_path_from_url(url, event_id)
        if path is None or not path.is_file():
            return "imagem_tema_ausente"
    return None


def remove_unreferenced_theme_files(
    previous: dict, current: dict, event_id: str
) -> None:
    stale = referenced_theme_urls(previous) - referenced_theme_urls(current)
    for url in sorted(stale):
        remove_theme_file(url, event_id)


def remove_theme_file(url: str | None, event_id: str | None = None) -> None:
    path = theme_path_from_url(url, event_id)
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def remove_theme_files(theme: dict, event_id: str) -> None:
    for url in referenced_theme_urls(theme):
        remove_theme_file(url, event_id)


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) < 24 or data[12:16] != b"IHDR":
            return None
        return (
            int.from_bytes(data[16:20], "big"),
            int.from_bytes(data[20:24], "big"),
        )

    if data.startswith(b"\xff\xd8\xff"):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                index += 2
                continue
            if index + 4 > len(data):
                break
            length = int.from_bytes(data[index + 2:index + 4], "big")
            if length < 2:
                break
            if (
                0xC0 <= marker <= 0xCF
                and marker not in (0xC4, 0xC8, 0xCC)
            ):
                height = int.from_bytes(data[index + 5:index + 7], "big")
                width = int.from_bytes(data[index + 7:index + 9], "big")
                return (width, height)
            index += 2 + length
        return None

    if (
        len(data) >= 30
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):
        chunk = data[12:16]
        if chunk == b"VP8X":
            return (
                int.from_bytes(data[24:27], "little") + 1,
                int.from_bytes(data[27:30], "little") + 1,
            )
        if chunk == b"VP8L" and data[20] == 0x2F:
            bits = int.from_bytes(data[21:25], "little")
            return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        if chunk == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
            return (
                int.from_bytes(data[26:28], "little") & 0x3FFF,
                int.from_bytes(data[28:30], "little") & 0x3FFF,
            )
    return None
