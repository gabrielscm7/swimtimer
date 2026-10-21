"""Introduz a entidade Prova (evento -> prova -> bateria)

Cada bateria legada (`heat`) origina uma prova propria, pois nao ha informacao
suficiente para agrupa-las com seguranca. O numero de ordem original e
preservado na prova; a bateria migrada fica com order_num = 1 dentro da prova.

A coluna `heat.prova_id` e obrigatoria. Como o SQLite nao permite adicionar
coluna NOT NULL sem default, a obrigatoriedade e garantida por triggers
(BEFORE INSERT/UPDATE), mantendo integridade referencial sem reconstruir a
tabela `heat` (o que poderia quebrar as FKs de `heat_lane`).

Revision ID: 0003_prova_hierarchy
Revises: 0002_lap_unique
Create Date: 2026-10-21

"""
from typing import Sequence, Union

import time
import uuid as _uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "0003_prova_hierarchy"
down_revision: Union[str, None] = "0002_lap_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _new_id() -> str:
    return str(_uuid.uuid4())


_PROVA_STATUS = {
    "scheduled": "scheduled",
    "ready_check": "in_progress",
    "active": "in_progress",
    "finished": "finished",
}


def _create_prova_table() -> None:
    op.create_table(
        "prova",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(),
            sa.ForeignKey("event.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("order_num", sa.Integer(), nullable=False),
        sa.Column("stroke", sa.String(), nullable=True),
        sa.Column("distance_m", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("consolidate_results", sa.Boolean(), nullable=False),
        sa.Column("classification_criterion", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_prova_event_order", "prova", ["event_id", "order_num"])
    op.create_index(
        "uq_prova_event_order", "prova", ["event_id", "order_num"], unique=True
    )


def _backfill(bind) -> None:
    heats = bind.execute(
        text(
            "SELECT id, event_id, name, order_num, distance_m, status "
            "FROM heat"
        )
    ).mappings().all()

    by_event: dict[str, list[dict]] = {}
    for heat in heats:
        by_event.setdefault(heat["event_id"], []).append(dict(heat))

    now = time.time()
    for event_heats in by_event.values():
        ordered = sorted(
            event_heats, key=lambda item: (item["order_num"], item["id"])
        )
        for position, heat in enumerate(ordered, start=1):
            prova_id = _new_id()
            bind.execute(
                text(
                    "INSERT INTO prova (id, event_id, name, order_num, stroke, "
                    "distance_m, category, consolidate_results, "
                    "classification_criterion, status, created_at) "
                    "VALUES (:id, :event, :name, :order_num, NULL, :distance, "
                    "NULL, 1, 'lowest_time', :status, :created)"
                ),
                {
                    "id": prova_id,
                    "event": heat["event_id"],
                    "name": heat["name"] or "Prova migrada",
                    "order_num": position,
                    "distance": heat["distance_m"],
                    "status": _PROVA_STATUS.get(heat["status"], "scheduled"),
                    "created": now,
                },
            )
            bind.execute(
                text(
                    "UPDATE heat SET prova_id = :prova, order_num = 1 "
                    "WHERE id = :heat"
                ),
                {"prova": prova_id, "heat": heat["id"]},
            )


def _enforce_not_null(bind) -> None:
    bind.exec_driver_sql(
        "CREATE TRIGGER trg_heat_prova_id_insert "
        "BEFORE INSERT ON heat "
        "WHEN NEW.prova_id IS NULL "
        "BEGIN SELECT RAISE(ABORT, 'heat.prova_id obrigatorio'); END"
    )
    bind.exec_driver_sql(
        "CREATE TRIGGER trg_heat_prova_id_update "
        "BEFORE UPDATE OF prova_id ON heat "
        "WHEN NEW.prova_id IS NULL "
        "BEGIN SELECT RAISE(ABORT, 'heat.prova_id obrigatorio'); END"
    )


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())

    if "prova" not in existing:
        _create_prova_table()

    heat_columns = {col["name"] for col in inspect(bind).get_columns("heat")}
    if "prova_id" not in heat_columns:
        # ALTER TABLE ADD COLUMN com REFERENCES e aceito pelo SQLite (NULL);
        # op.add_column nao suporta FK no dialeto sem batch mode.
        bind.exec_driver_sql(
            "ALTER TABLE heat ADD COLUMN prova_id VARCHAR "
            "REFERENCES prova(id)"
        )

    pending = bind.execute(
        text("SELECT COUNT(*) FROM heat WHERE prova_id IS NULL")
    ).scalar_one()
    if pending:
        _backfill(bind)

    bind.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_heat_prova_order "
        "ON heat (prova_id, order_num)"
    )
    _enforce_not_null(bind)


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "DROP INDEX IF EXISTS uq_heat_prova_order"
    )
    bind.exec_driver_sql("DROP TRIGGER IF EXISTS trg_heat_prova_id_insert")
    bind.exec_driver_sql("DROP TRIGGER IF EXISTS trg_heat_prova_id_update")

    heat_columns = {col["name"] for col in inspect(bind).get_columns("heat")}
    if "prova_id" in heat_columns:
        bind.exec_driver_sql(
            "UPDATE heat SET order_num = COALESCE("
            "(SELECT order_num FROM prova WHERE prova.id = heat.prova_id), "
            "order_num)"
        )
        bind.exec_driver_sql("ALTER TABLE heat DROP COLUMN prova_id")

    bind.exec_driver_sql("DROP INDEX IF EXISTS uq_prova_event_order")
    op.drop_index("ix_prova_event_order", table_name="prova")
    op.drop_table("prova")
