"""Privacidade opcional por evento

Adiciona `public_results_enabled` (liga/desliga resultados publicos e os
endpoints `/api/public/...`) e `public_name_mode` (`full`|`initials`, afeta
apenas a exibicao publica). Ambos com default seguro para eventos existentes.

Revision ID: 0011_event_public_settings
Revises: 0010_result_snapshot
Create Date: 2026-10-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0011_event_public_settings"
down_revision: Union[str, None] = "0010_result_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in inspect(bind).get_columns(table)}


def upgrade() -> None:
    columns = _columns("event")
    if "public_results_enabled" not in columns:
        op.add_column(
            "event",
            sa.Column(
                "public_results_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )
    if "public_name_mode" not in columns:
        op.add_column(
            "event",
            sa.Column(
                "public_name_mode",
                sa.String(),
                nullable=False,
                server_default="full",
            ),
        )


def downgrade() -> None:
    columns = _columns("event")
    if "public_name_mode" in columns:
        op.drop_column("event", "public_name_mode")
    if "public_results_enabled" in columns:
        op.drop_column("event", "public_results_enabled")
