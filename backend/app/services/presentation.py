"""Configuracao da apresentacao curada do telao publico."""

import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Event, Heat, Prova
from . import provas as prova_rules

DEFAULT_PRESENTATION: dict = {
    "enabled": True,
    "rotation": True,
    "slide_duration_s": 15,
    "show_next_prova": True,
    "pinned_ref": None,
    "slides": [],
}

_MAX_SLIDES = 100
_MIN_DURATION = 5
_MAX_DURATION = 60


def make_ref(kind: str, target_id: str) -> str:
    return f"{kind}:{target_id}"


def parse_ref(ref: object) -> tuple[str, str] | None:
    if not isinstance(ref, str):
        return None
    kind, separator, target_id = ref.partition(":")
    if not separator or kind not in ("prova", "bateria") or not target_id:
        return None
    return kind, target_id


def _clamp_duration(value: object, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(_MIN_DURATION, min(_MAX_DURATION, number))


def normalize_presentation(raw: str | dict | None) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = None
    if not isinstance(raw, dict):
        raw = {}

    slides: list[dict] = []
    seen: set[str] = set()
    raw_slides = raw.get("slides")
    for item in raw_slides if isinstance(raw_slides, list) else []:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        target_id = item.get("target_id")
        if kind not in ("prova", "bateria") or not isinstance(target_id, str):
            continue
        target_id = target_id.strip()
        if not target_id:
            continue
        ref = make_ref(kind, target_id)
        if ref in seen or len(slides) >= _MAX_SLIDES:
            continue
        seen.add(ref)
        slides.append({"kind": kind, "target_id": target_id})

    pinned_ref = raw.get("pinned_ref")
    if pinned_ref not in seen:
        pinned_ref = None

    return {
        "enabled": bool(raw.get("enabled", DEFAULT_PRESENTATION["enabled"])),
        "rotation": bool(
            raw.get("rotation", DEFAULT_PRESENTATION["rotation"])
        ),
        "slide_duration_s": _clamp_duration(
            raw.get("slide_duration_s"),
            DEFAULT_PRESENTATION["slide_duration_s"],
        ),
        "show_next_prova": bool(
            raw.get(
                "show_next_prova",
                DEFAULT_PRESENTATION["show_next_prova"],
            )
        ),
        "pinned_ref": pinned_ref,
        "slides": slides,
    }


def serialize_presentation(config: dict) -> str:
    return json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def remove_refs(raw: str | dict | None, refs: set[str]) -> dict:
    config = normalize_presentation(raw)
    config["slides"] = [
        slide
        for slide in config["slides"]
        if make_ref(slide["kind"], slide["target_id"]) not in refs
    ]
    valid_refs = {
        make_ref(slide["kind"], slide["target_id"])
        for slide in config["slides"]
    }
    if config["pinned_ref"] not in valid_refs:
        config["pinned_ref"] = None
    return config


async def validate_targets(
    session: AsyncSession, event_id: str, config: dict
) -> str | None:
    """Valida que todos os slides e o pin pertencem ao evento."""
    for slide in config["slides"]:
        if slide["kind"] == "prova":
            prova = await session.get(Prova, slide["target_id"])
            if prova is None or prova.event_id != event_id:
                return "slide_prova_invalida"
        else:
            heat = await session.get(Heat, slide["target_id"])
            if heat is None or heat.event_id != event_id:
                return "slide_bateria_invalida"
    pinned = parse_ref(config.get("pinned_ref"))
    if pinned is not None:
        ref = make_ref(*pinned)
        if ref not in {
            make_ref(slide["kind"], slide["target_id"])
            for slide in config["slides"]
        }:
            return "pin_invalido"
    return None


async def hydrate_presentation(
    session: AsyncSession, event: Event, config: dict
) -> dict:
    """Resolve labels/status/elegibilidade para a pagina interna."""
    slides = []
    for slide in config["slides"]:
        item = {
            "kind": slide["kind"],
            "target_id": slide["target_id"],
            "ref": make_ref(slide["kind"], slide["target_id"]),
            "label": "",
            "status": None,
            "eligible": False,
        }
        if slide["kind"] == "prova":
            prova = await session.get(Prova, slide["target_id"])
            if prova is not None and prova.event_id == event.id:
                item["label"] = prova_rules.prova_label(prova)
                item["status"] = prova.status
                item["eligible"] = prova.status == "finished"
            else:
                item["label"] = "Item removido"
        else:
            heat = await session.get(Heat, slide["target_id"])
            if heat is not None and heat.event_id == event.id:
                prova = await session.get(Prova, heat.prova_id)
                total = await session.scalar(
                    select(func.count())
                    .select_from(Heat)
                    .where(Heat.prova_id == heat.prova_id)
                )
                index = await session.scalar(
                    select(func.count())
                    .select_from(Heat)
                    .where(
                        Heat.prova_id == heat.prova_id,
                        Heat.order_num <= heat.order_num,
                    )
                )
                heat.heat_index_in_prova = int(index or heat.order_num)
                heat.heats_in_prova = int(total or 1)
                item["label"] = prova_rules.bateria_label(
                    heat,
                    prova,
                    include_prova=prova is not None,
                )
                item["status"] = heat.status
                item["eligible"] = heat.status == "finished"
                item["prova_id"] = heat.prova_id
            else:
                item["label"] = "Item removido"
        slides.append(item)

    return {
        **config,
        "slides": slides,
        "eligible_count": sum(1 for item in slides if item["eligible"]),
    }
