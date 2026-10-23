"""Constantes e regras puras do dominio de baterias e provas.

Fonte unica dos vocabularios fechados compartilhados com o frontend
(`frontend/static/common/labels.js`). Alteracoes aqui devem ser espelhadas la;
o teste `frontend/tests/domain_sync.test.js` verifica a igualdade das listas.
"""

from __future__ import annotations

import unicodedata

STROKES = ("crawl", "borboleta", "peito", "costas", "livre", "medley")

STROKE_LABELS = {
    "crawl": "Crawl",
    "borboleta": "Borboleta",
    "peito": "Peito",
    "costas": "Costas",
    "livre": "Livre",
    "medley": "Medley",
}

NAIPES = ("M", "F", "MISTO")

NAIPE_LABELS = {"M": "Masculino", "F": "Feminino", "MISTO": "Misto"}

CATEGORIES = (
    "pre_mirim",
    "mirim",
    "petiz",
    "infantil",
    "juvenil",
    "junior",
    "adulto",
    "livre",
)

CATEGORY_LABELS = {
    "pre_mirim": "Pré Mirim",
    "mirim": "Mirim",
    "petiz": "Petiz",
    "infantil": "Infantil",
    "juvenil": "Juvenil",
    "junior": "Júnior",
    "adulto": "Adulto",
    "livre": "Cat. Livre",
}

# Valor de categoria que representa ausencia de restricao etaria.
FREE_CATEGORY = "livre"

HEAT_TYPES = ("bateria", "maratona")

GROUP_KEY_FIELDS = ("heat_type", "stroke", "distance_m", "naipe", "category")


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _slug(value: str) -> str:
    cleaned = _strip_accents(value.strip().lower())
    chars = [char if char.isalnum() else "_" for char in cleaned]
    slug = "".join(chars)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


_CATEGORY_ALIASES = {
    "aberta": FREE_CATEGORY,
    "aberto": FREE_CATEGORY,
    "open": FREE_CATEGORY,
    "cat_livre": FREE_CATEGORY,
    "pre_mirim": "pre_mirim",
    "premirim": "pre_mirim",
    "mirim": "mirim",
    "petiz": "petiz",
    "infantil": "infantil",
    "juvenil": "juvenil",
    "junior": "junior",
    "adulto": "adulto",
    "livre": FREE_CATEGORY,
}

_NAIPE_ALIASES = {
    "m": "M",
    "masc": "M",
    "mas": "M",
    "masculino": "M",
    "f": "F",
    "fem": "F",
    "feminino": "F",
    "feminina": "F",
    "misto": "MISTO",
    "mista": "MISTO",
    "mixto": "MISTO",
    "mixed": "MISTO",
}


def normalize_stroke(value: object) -> object:
    if isinstance(value, str):
        cleaned = _slug(value)
        return cleaned or None
    return value


def normalize_naipe(value: object) -> object:
    if isinstance(value, str):
        cleaned = _strip_accents(value.strip().lower())
        return _NAIPE_ALIASES.get(cleaned, cleaned.upper())
    return value


def normalize_category(value: object) -> object:
    """Normaliza rotulos livres/legados para a chave canonica da lista."""
    if isinstance(value, str):
        slug = _slug(value)
        if not slug:
            return None
        return _CATEGORY_ALIASES.get(slug, slug)
    return value


def coerce_category(value: object) -> str | None:
    """Normaliza para a lista fechada; valores desconhecidos viram `livre`."""
    normalized = normalize_category(value)
    if normalized is None:
        return None
    if normalized in CATEGORIES:
        return normalized
    return FREE_CATEGORY


def stroke_label(value: str | None) -> str:
    if not value:
        return ""
    return STROKE_LABELS.get(value.lower(), value.title())


def naipe_label(value: str | None) -> str:
    if not value:
        return ""
    return NAIPE_LABELS.get(value.upper(), value)


def category_label(value: str | None) -> str:
    if not value:
        return ""
    return CATEGORY_LABELS.get(value.lower(), value.title())


def is_free_category(value: str | None) -> bool:
    return (value or "").strip().lower() == FREE_CATEGORY


def group_key(*, heat_type: str, stroke: str | None, distance_m: int | None,
              naipe: str | None, category: str | None) -> tuple:
    """Chave do grupo (prova). Distancia so entra para baterias de tempo."""
    return (
        (heat_type or "").lower(),
        (stroke or "").lower(),
        distance_m if (heat_type or "").lower() == "bateria" else None,
        (naipe or "").upper(),
        (category or "").lower(),
    )


def _format_hours(duration_s: int | None) -> str:
    if not duration_s:
        return ""
    hours = duration_s / 3600
    if float(hours).is_integer():
        text = str(int(hours))
    else:
        text = f"{hours:.1f}".rstrip("0").rstrip(".")
    return f"{text} h"


def generate_prova_name(
    *,
    heat_type: str | None = "bateria",
    stroke: str | None,
    distance_m: int | None,
    naipe: str | None,
    category: str | None,
    duration_s: int | None = None,
) -> str:
    """Rotulo padrao: "25 m Crawl · Masculino · Mirim".

    Categoria `livre` e omitida. Maratonas usam "Maratona <duracao> h".
    """
    parts: list[str] = []
    stroke_text = stroke_label(stroke)
    if (heat_type or "bateria").lower() == "maratona":
        prefix = "Maratona"
        duration_text = _format_hours(duration_s)
        if duration_text:
            prefix = f"{prefix} {duration_text}"
        if stroke_text:
            parts.append(f"{prefix} · {stroke_text}")
        else:
            parts.append(prefix)
    elif distance_m is not None:
        parts.append(f"{distance_m} m{(' ' + stroke_text) if stroke_text else ''}")
    elif stroke_text:
        parts.append(stroke_text)
    if naipe:
        parts.append(naipe_label(naipe))
    if category and not is_free_category(category):
        parts.append(category_label(category))
    return " · ".join(parts) or "Prova"


def is_legacy_incomplete(
    stroke: str | None,
    naipe: str | None,
    category: str | None,
    *,
    heat_type: str | None = None,
    distance_m: int | None = None,
) -> bool:
    if not stroke or not naipe or not category:
        return True
    if (heat_type or "bateria").lower() == "bateria" and not distance_m:
        return True
    return False
