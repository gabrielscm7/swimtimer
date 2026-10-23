"""Resultados auditaveis: snapshots append-only com cadeia de hashes

Cria `result_snapshot`, que guarda uma revisao imutavel do resultado de uma
bateria (payload canonico, hash encadeado ao snapshot anterior do evento).
Triggers `BEFORE UPDATE`/`BEFORE DELETE` abortam qualquer alteracao: a tabela
so aceita INSERT.

Revision ID: 0010_result_snapshot
Revises: 0009_athlete_registration_code
Create Date: 2026-10-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0010_result_snapshot"
down_revision: Union[str, None] = "0009_athlete_registration_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MESSAGE = "result_snapshot_e_imutavel"


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    if "result_snapshot" not in tables:
        op.create_table(
            "result_snapshot",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("event_id", sa.String(), nullable=False),
            sa.Column("prova_id", sa.String(), nullable=False),
            sa.Column("heat_id", sa.String(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("reason", sa.String(), nullable=False),
            sa.Column("created_at", sa.Float(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_by_ip", sa.String(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("prev_hash", sa.String(length=64), nullable=False),
            sa.Column("hash", sa.String(length=64), nullable=False),
        )
        op.create_index(
            "ix_result_snapshot_event",
            "result_snapshot",
            ["event_id"],
        )
        op.create_index(
            "uq_result_snapshot_heat_revision",
            "result_snapshot",
            ["heat_id", "revision"],
            unique=True,
        )

    bind.exec_driver_sql(
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_result_snapshot_no_update
        BEFORE UPDATE ON result_snapshot
        BEGIN
            SELECT RAISE(ABORT, '{_MESSAGE}');
        END
        """
    )
    bind.exec_driver_sql(
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_result_snapshot_no_delete
        BEFORE DELETE ON result_snapshot
        BEGIN
            SELECT RAISE(ABORT, '{_MESSAGE}');
        END
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    if "result_snapshot" in tables:
        bind.exec_driver_sql(
            "DROP TRIGGER IF EXISTS trg_result_snapshot_no_delete"
        )
        bind.exec_driver_sql(
            "DROP TRIGGER IF EXISTS trg_result_snapshot_no_update"
        )
        op.drop_index(
            "uq_result_snapshot_heat_revision", table_name="result_snapshot"
        )
        op.drop_index(
            "ix_result_snapshot_event", table_name="result_snapshot"
        )
        op.drop_table("result_snapshot")
