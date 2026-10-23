"""Adiciona registration_code ao atleta e o inclui na unicidade

Dois homonimos da mesma equipe eram bloqueados pela unicidade
(event_id, name, team_id). O codigo de registro opcional desambigua.
A unicidade passa a ser (event_id, name COLLATE NOCASE, team_id,
registration_code), com COALESCE para campos nulos.

Revision ID: 0009_athlete_registration_code
Revises: 0008_prova_mixed_ranking
Create Date: 2026-10-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0009_athlete_registration_code"
down_revision: Union[str, None] = "0008_prova_mixed_ranking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {col["name"] for col in inspect(bind).get_columns("athlete")}
    if "registration_code" not in columns:
        op.add_column(
            "athlete",
            sa.Column("registration_code", sa.String(), nullable=True),
        )

    bind.exec_driver_sql(
        "DROP INDEX IF EXISTS uq_athlete_event_name_team"
    )
    bind.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_athlete_event_name_team_code "
        "ON athlete (event_id, name COLLATE NOCASE, "
        "COALESCE(team_id, ''), COALESCE(registration_code, ''))"
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "DROP INDEX IF EXISTS uq_athlete_event_name_team_code"
    )
    columns = {col["name"] for col in inspect(bind).get_columns("athlete")}
    if "registration_code" in columns:
        bind.exec_driver_sql(
            "ALTER TABLE athlete DROP COLUMN registration_code"
        )
    bind.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_athlete_event_name_team "
        "ON athlete (event_id, name COLLATE NOCASE, COALESCE(team_id, ''))"
    )
