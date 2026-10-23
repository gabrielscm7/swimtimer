"""Bateria como unidade de cadastro; prova vira grupo automatico

- `heat` ganha stroke/naipe/category/lane_count/classify_alone.
- atributos da prova sao copiados para cada bateria;
- `heat.order_num` passa a ser unico por evento (ordem global do programa);
- categorias legadas fora da lista fechada viram `livre` (prova e atleta);
- provas com a mesma chave de grupo sao fundidas;
- colunas operacionais da prova (name_override, mixed_ranking,
  legacy_incomplete, consolidate_results) sao removidas;
- `event.default_lane_count` e adicionado.

Revision ID: 0015_bateria_unidade_cadastro
Revises: 0014_prova_format_definition
Create Date: 2026-10-23

"""
from typing import Sequence, Union
import unicodedata

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "0015_bateria_unidade_cadastro"
down_revision: Union[str, None] = "0014_prova_format_definition"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STROKE_LABELS = {
    "crawl": "Crawl",
    "borboleta": "Borboleta",
    "peito": "Peito",
    "costas": "Costas",
    "livre": "Livre",
    "medley": "Medley",
}
NAIPE_LABELS = {"M": "Masculino", "F": "Feminino", "MISTO": "Misto"}
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
_CATEGORY_SLUGS = {
    "pre_mirim": "pre_mirim",
    "premirim": "pre_mirim",
    "mirim": "mirim",
    "petiz": "petiz",
    "infantil": "infantil",
    "juvenil": "juvenil",
    "junior": "junior",
    "adulto": "adulto",
    "livre": "livre",
    "aberta": "livre",
    "aberto": "livre",
    "open": "livre",
    "cat_livre": "livre",
}


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in inspect(bind).get_columns(table)}


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    ascii_value = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    chars = [char if char.isalnum() else "_" for char in ascii_value]
    slug = "".join(chars)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


def _canonical_category(value: str | None) -> str | None:
    if value is None:
        return None
    if not str(value).strip():
        return None
    return _CATEGORY_SLUGS.get(_slug(str(value)), "livre")


def _prova_name(
    *,
    heat_type: str | None,
    stroke: str | None,
    distance_m: int | None,
    naipe: str | None,
    category: str | None,
    duration_s: int | None,
) -> str:
    parts: list[str] = []
    stroke_text = STROKE_LABELS.get((stroke or "").lower(), (stroke or "").title())
    if (heat_type or "bateria") == "maratona":
        prefix = "Maratona"
        if duration_s:
            hours = duration_s / 3600
            text_hours = (
                str(int(hours))
                if float(hours).is_integer()
                else f"{hours:.1f}".rstrip("0").rstrip(".")
            )
            prefix = f"{prefix} {text_hours} h"
        parts.append(f"{prefix} · {stroke_text}" if stroke_text else prefix)
    elif distance_m is not None:
        parts.append(
            f"{distance_m} m{(' ' + stroke_text) if stroke_text else ''}"
        )
    elif stroke_text:
        parts.append(stroke_text)
    if naipe:
        parts.append(NAIPE_LABELS.get(naipe.upper(), naipe))
    if category and category.lower() != "livre":
        parts.append(
            CATEGORY_LABELS.get(category.lower(), category.title())
        )
    return " · ".join(parts) or "Prova"


def _convert_categories(bind) -> None:
    for table in ("prova", "athlete"):
        if table not in set(inspect(bind).get_table_names()):
            continue
        rows = bind.execute(
            text(f"SELECT id, category FROM {table}")
        ).mappings().all()
        for row in rows:
            converted = _canonical_category(row["category"])
            if converted != row["category"]:
                bind.execute(
                    text(
                        f"UPDATE {table} SET category = :category "
                        "WHERE id = :id"
                    ),
                    {"category": converted, "id": row["id"]},
                )


def _add_heat_columns(bind) -> None:
    columns = _columns("heat")
    if "stroke" not in columns:
        op.add_column("heat", sa.Column("stroke", sa.String(), nullable=True))
    if "naipe" not in columns:
        op.add_column("heat", sa.Column("naipe", sa.String(), nullable=True))
    if "category" not in columns:
        op.add_column("heat", sa.Column("category", sa.String(), nullable=True))
    if "classify_alone" not in columns:
        op.add_column(
            "heat",
            sa.Column(
                "classify_alone",
                sa.Boolean(),
                nullable=False,
                server_default=text("0"),
            ),
        )
    if "lane_count" not in columns:
        op.add_column(
            "heat",
            sa.Column(
                "lane_count",
                sa.Integer(),
                nullable=False,
                server_default=text("3"),
            ),
        )


def _copy_prova_attributes(bind) -> None:
    bind.execute(
        text(
            "UPDATE heat SET "
            "heat_type = COALESCE("
            "(SELECT format FROM prova WHERE prova.id = heat.prova_id), "
            "heat_type), "
            "stroke = (SELECT stroke FROM prova WHERE prova.id = heat.prova_id), "
            "naipe = (SELECT naipe FROM prova WHERE prova.id = heat.prova_id), "
            "category = (SELECT category FROM prova WHERE prova.id = heat.prova_id), "
            "distance_m = CASE "
            "WHEN COALESCE((SELECT format FROM prova WHERE prova.id = heat.prova_id), heat.heat_type) = 'maratona' "
            "THEN NULL "
            "ELSE (SELECT distance_m FROM prova WHERE prova.id = heat.prova_id) "
            "END"
        )
    )


def _adjust_lane_count(bind) -> None:
    bind.execute(
        text(
            "UPDATE heat SET lane_count = CASE "
            "WHEN (SELECT MAX(lane_number) FROM heat_lane "
            "      WHERE heat_lane.heat_id = heat.id) IS NULL THEN 3 "
            "ELSE MIN(8, MAX(1, (SELECT MAX(lane_number) FROM heat_lane "
            "      WHERE heat_lane.heat_id = heat.id))) END"
        )
    )


def _renumber_heat_orders(bind) -> None:
    rows = bind.execute(
        text(
            "SELECT h.id, h.event_id FROM heat h "
            "LEFT JOIN prova p ON p.id = h.prova_id "
            "ORDER BY h.event_id, COALESCE(p.order_num, 999999), "
            "h.order_num, h.id"
        )
    ).mappings().all()
    by_event: dict[str, list[str]] = {}
    order: list[str] = []
    for row in rows:
        by_event.setdefault(row["event_id"], []).append(row["id"])
    for heat_ids in by_event.values():
        for index, heat_id in enumerate(heat_ids, start=1):
            bind.execute(
                text("UPDATE heat SET order_num = :order WHERE id = :id"),
                {"order": index, "id": heat_id},
            )
        order.extend(heat_ids)


def _group_key(row) -> tuple:
    return (
        (row["format"] or "").lower(),
        (row["stroke"] or "").lower(),
        (row["distance_m"] if (row["format"] or "").lower() == "bateria" else None),
        (row["naipe"] or "").upper(),
        (row["category"] or "").lower(),
    )


def _merge_duplicate_groups(bind) -> None:
    """Funde provas com a mesma chave, preservando provas com snapshots."""
    rows = bind.execute(
        text(
            "SELECT id, event_id, format, stroke, distance_m, naipe, category, "
            "order_num FROM prova ORDER BY event_id, order_num, id"
        )
    ).mappings().all()
    canonical: dict[tuple, str] = {}
    snapshots = {
        row[0]
        for row in bind.execute(
            text("SELECT DISTINCT prova_id FROM result_snapshot")
        ).all()
    }
    for row in rows:
        key = (row["event_id"],) + _group_key(row)
        keeper = canonical.get(key)
        if keeper is None:
            canonical[key] = row["id"]
            continue
        bind.execute(
            text("UPDATE heat SET prova_id = :keeper WHERE prova_id = :dup"),
            {"keeper": keeper, "dup": row["id"]},
        )
        if row["id"] not in snapshots:
            bind.execute(
                text("DELETE FROM prova WHERE id = :id"),
                {"id": row["id"]},
            )


def _rebuild_prova_names(bind) -> None:
    rows = bind.execute(
        text(
            "SELECT p.id, p.format, p.stroke, p.distance_m, p.naipe, "
            "p.category, "
            "(SELECT MIN(order_num) FROM heat WHERE heat.prova_id = p.id) "
            "AS min_order, "
            "(SELECT COUNT(DISTINCT duration_s) FROM heat "
            " WHERE heat.prova_id = p.id AND duration_s IS NOT NULL) "
            "AS durations, "
            "(SELECT MIN(duration_s) FROM heat WHERE heat.prova_id = p.id) "
            "AS duration_s "
            "FROM prova p ORDER BY p.event_id, p.order_num, p.id"
        )
    ).mappings().all()
    for row in rows:
        duration = row["duration_s"] if row["durations"] == 1 else None
        name = _prova_name(
            heat_type=row["format"],
            stroke=row["stroke"],
            distance_m=row["distance_m"],
            naipe=row["naipe"],
            category=row["category"],
            duration_s=duration,
        )
        bind.execute(
            text("UPDATE prova SET name = :name WHERE id = :id"),
            {"name": name, "id": row["id"]},
        )


def _renumber_prova_orders(bind) -> None:
    bind.execute(
        text("UPDATE prova SET order_num = order_num + 100000")
    )
    events = [
        row[0]
        for row in bind.execute(text("SELECT DISTINCT event_id FROM prova"))
    ]
    for event_id in events:
        rows = bind.execute(
            text(
                "SELECT p.id FROM prova p "
                "LEFT JOIN heat h ON h.prova_id = p.id "
                "WHERE p.event_id = :event "
                "GROUP BY p.id "
                "ORDER BY CASE WHEN MIN(h.order_num) IS NULL THEN 1 ELSE 0 END, "
                "MIN(h.order_num), p.id"
            ),
            {"event": event_id},
        ).all()
        for index, row in enumerate(rows, start=1):
            bind.execute(
                text("UPDATE prova SET order_num = :order WHERE id = :id"),
                {"order": index, "id": row[0]},
            )


def _drop_prova_operational_columns(bind) -> None:
    columns = _columns("prova")
    for column in (
        "name_override",
        "mixed_ranking",
        "legacy_incomplete",
        "consolidate_results",
    ):
        if column in columns:
            op.drop_column("prova", column)


def upgrade() -> None:
    bind = op.get_bind()

    if "default_lane_count" not in _columns("event"):
        op.add_column(
            "event",
            sa.Column(
                "default_lane_count",
                sa.Integer(),
                nullable=False,
                server_default=text("3"),
            ),
        )

    _add_heat_columns(bind)
    _convert_categories(bind)
    _copy_prova_attributes(bind)
    _adjust_lane_count(bind)

    # A ordem global substitui a unicidade por prova; removemos o indice antes
    # de fundir grupos e renumerar para nao violar a restricao no meio.
    bind.exec_driver_sql("DROP INDEX IF EXISTS uq_heat_prova_order")
    _merge_duplicate_groups(bind)
    _renumber_heat_orders(bind)
    bind.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_heat_event_order "
        "ON heat (event_id, order_num)"
    )

    _rebuild_prova_names(bind)
    _renumber_prova_orders(bind)
    _drop_prova_operational_columns(bind)


def downgrade() -> None:
    bind = op.get_bind()

    columns = _columns("prova")
    if "name_override" not in columns:
        op.add_column(
            "prova",
            sa.Column(
                "name_override",
                sa.Boolean(),
                nullable=False,
                server_default=text("0"),
            ),
        )
    if "mixed_ranking" not in columns:
        op.add_column(
            "prova",
            sa.Column(
                "mixed_ranking",
                sa.String(),
                nullable=False,
                server_default=text("'both'"),
            ),
        )
    if "legacy_incomplete" not in columns:
        op.add_column(
            "prova",
            sa.Column(
                "legacy_incomplete",
                sa.Boolean(),
                nullable=False,
                server_default=text("0"),
            ),
        )
    if "consolidate_results" not in columns:
        op.add_column(
            "prova",
            sa.Column(
                "consolidate_results",
                sa.Boolean(),
                nullable=False,
                server_default=text("1"),
            ),
        )
    bind.execute(
        text(
            "UPDATE prova SET legacy_incomplete = CASE "
            "WHEN stroke IS NULL OR naipe IS NULL OR category IS NULL THEN 1 "
            "WHEN format = 'bateria' AND distance_m IS NULL THEN 1 "
            "ELSE 0 END"
        )
    )

    # Categorias voltam ao vocabulario livre legado (aproximacao reversivel).
    for table in ("prova", "athlete"):
        rows = bind.execute(
            text(f"SELECT id, category FROM {table}")
        ).mappings().all()
        for row in rows:
            if row["category"] is None:
                continue
            value = str(row["category"])
            restored = "ABERTA" if value.lower() == "livre" else value.upper()
            bind.execute(
                text(f"UPDATE {table} SET category = :value WHERE id = :id"),
                {"value": restored, "id": row["id"]},
            )

    # Ordem volta a reiniciar por prova.
    bind.exec_driver_sql("DROP INDEX IF EXISTS uq_heat_event_order")
    rows = bind.execute(
        text(
            "SELECT id, prova_id FROM heat "
            "ORDER BY prova_id, order_num, id"
        )
    ).all()
    position: dict[str, int] = {}
    for heat_id, prova_id in rows:
        position[prova_id] = position.get(prova_id, 0) + 1
        bind.execute(
            text("UPDATE heat SET order_num = :order WHERE id = :id"),
            {"order": position[prova_id], "id": heat_id},
        )
    bind.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_heat_prova_order "
        "ON heat (prova_id, order_num)"
    )

    columns = _columns("heat")
    for column in (
        "classify_alone",
        "lane_count",
        "category",
        "naipe",
        "stroke",
    ):
        if column in columns:
            op.drop_column("heat", column)

    if "default_lane_count" in _columns("event"):
        op.drop_column("event", "default_lane_count")
