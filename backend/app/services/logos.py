from pathlib import Path

from ..config import settings


def _sniff_image(data: bytes) -> tuple[str, str] | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if (
        len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):
        return "webp", "image/webp"
    return None


def _logo_path_from_url(url: str | None) -> Path | None:
    if not url or not url.startswith("/logos/"):
        return None
    name = url[len("/logos/"):]
    if "/" in name or "\\" in name or name in ("", ".", ".."):
        return None
    return settings.logo_dir / name


def _remove_logo_file(url: str | None) -> None:
    path = _logo_path_from_url(url)
    if path is None:
        return
    try:
        if path.parent == settings.logo_dir:
            path.unlink(missing_ok=True)
    except OSError:
        pass
