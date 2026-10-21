"""Adiciona logo_url as equipes

Revision ID: 0004_team_logo
Revises: 0003_prova_hierarchy
Create Date: 2026-10-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0004_team_logo"
down_revision: Union[str, None] = "0003_prova_hierarchy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {col["name"] for col in inspect(bind).get_columns("team")}
    if "logo_url" not in columns:
        op.add_column("team", sa.Column("logo_url", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {col["name"] for col in inspect(bind).get_columns("team")}
    if "logo_url" in columns:
        bind.exec_driver_sql("ALTER TABLE team DROP COLUMN logo_url")
