"""Tempo do toque, log de acoes e idempotencia de operacoes

Adiciona `action_log` (auditoria de toda acao que muda estado), `processed_op`
(resultado cacheado por op_id, para reenvios idempotentes) e as colunas
`received_at`/`late` em `heat_lane` e `lap_event`. Em `lap_event.recorded_at`
passa a representar o tempo efetivo do toque; `received_at` guarda o instante
de recebimento no servidor.

Revision ID: 0007_time_ack_idempotencia
Revises: 0006_prova_naipe
Create Date: 2026-10-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0007_time_ack_idempotencia"
down_revision: Union[str, None] = "0006_prova_naipe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    if "action_log" not in tables:
        op.create_table(
            "action_log",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("received_at", sa.Float(), nullable=False),
            sa.Column("effective_ts", sa.Float(), nullable=False),
            sa.Column("event_id", sa.String(), nullable=True),
            sa.Column("heat_id", sa.String(), nullable=True),
            sa.Column("lane_id", sa.String(), nullable=True),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("op_id", sa.String(), nullable=True),
            sa.Column("source_ip", sa.String(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True),
        )
        op.create_index(
            "ix_action_log_heat_received",
            "action_log",
            ["heat_id", "received_at"],
        )

    if "processed_op" not in tables:
        op.create_table(
            "processed_op",
            sa.Column("op_id", sa.String(), primary_key=True),
            sa.Column("lane_id", sa.String(), nullable=True),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Float(), nullable=False),
        )

    lane_columns = _columns("heat_lane")
    if "received_at" not in lane_columns:
        op.add_column(
            "heat_lane",
            sa.Column("received_at", sa.Float(), nullable=True),
        )
    if "late" not in lane_columns:
        op.add_column(
            "heat_lane",
            sa.Column(
                "late",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    lap_columns = _columns("lap_event")
    if "received_at" not in lap_columns:
        op.add_column(
            "lap_event",
            sa.Column("received_at", sa.Float(), nullable=True),
        )
    if "late" not in lap_columns:
        op.add_column(
            "lap_event",
            sa.Column(
                "late",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    lap_columns = _columns("lap_event")
    if "late" in lap_columns:
        op.drop_column("lap_event", "late")
    if "received_at" in lap_columns:
        op.drop_column("lap_event", "received_at")

    lane_columns = _columns("heat_lane")
    if "late" in lane_columns:
        op.drop_column("heat_lane", "late")
    if "received_at" in lane_columns:
        op.drop_column("heat_lane", "received_at")

    if "processed_op" in tables:
        op.drop_table("processed_op")
    if "action_log" in tables:
        op.drop_index("ix_action_log_heat_received", table_name="action_log")
        op.drop_table("action_log")
