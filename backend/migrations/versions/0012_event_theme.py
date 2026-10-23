"""Tema configuravel do front publico por evento

Adiciona `event.theme_json` (TEXT). Nulo significa usar o tema padrao.

Revision ID: 0012_event_theme
Revises: 0011_event_public_settings
Create Date: 2026-10-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0012_event_theme"
down_revision: Union[str, None] = "0011_event_public_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in inspect(bind).get_columns(table)}


def upgrade() -> None:
    if "theme_json" not in _columns("event"):
        op.add_column(
            "event", sa.Column("theme_json", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    if "theme_json" in _columns("event"):
        op.drop_column("event", "theme_json")
