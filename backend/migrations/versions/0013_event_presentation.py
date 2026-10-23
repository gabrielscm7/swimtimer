"""Adiciona a configuracao de apresentacao curada do telao

Revision ID: 0013_event_presentation
Revises: 0012_event_theme
Create Date: 2026-10-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0013_event_presentation"
down_revision: Union[str, None] = "0012_event_theme"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in inspect(bind).get_columns(table)}


def upgrade() -> None:
    if "presentation_json" not in _columns("event"):
        op.add_column(
            "event",
            sa.Column("presentation_json", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    if "presentation_json" in _columns("event"):
        op.drop_column("event", "presentation_json")
