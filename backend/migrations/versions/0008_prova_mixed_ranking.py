"""Adiciona mixed_ranking as provas (overall | by_naipe | both)

Provas mistas (naipe MISTO) podem ter ranking unico por tempo (`overall`),
um ranking por naipe (`by_naipe`) ou ambos (`both`, padrao). Provas
existentes mantem o comportamento historico de ranking geral.

Revision ID: 0008_prova_mixed_ranking
Revises: 0007_time_ack_idempotencia
Create Date: 2026-10-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0008_prova_mixed_ranking"
down_revision: Union[str, None] = "0007_time_ack_idempotencia"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {col["name"] for col in inspect(bind).get_columns("prova")}
    if "mixed_ranking" not in columns:
        op.add_column(
            "prova",
            sa.Column(
                "mixed_ranking",
                sa.String(),
                nullable=False,
                server_default="both",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {col["name"] for col in inspect(bind).get_columns("prova")}
    if "mixed_ranking" in columns:
        bind.exec_driver_sql(
            "ALTER TABLE prova DROP COLUMN mixed_ranking"
        )
