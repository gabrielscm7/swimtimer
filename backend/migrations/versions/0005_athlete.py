"""Introduz a entidade Athlete e vincula raias a atletas

Os atletas passam a ser cadastrados por evento, com naipe e categoria
proprios. `heat_lane.athlete_id` e opcional para preservar a compatibilidade
com raias legadas que usam apenas `participant_name`.

Revision ID: 0005_athlete
Revises: 0004_team_logo
Create Date: 2026-10-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0005_athlete"
down_revision: Union[str, None] = "0004_team_logo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "athlete" not in tables:
        op.create_table(
            "athlete",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "event_id",
                sa.String(),
                sa.ForeignKey("event.id"),
                nullable=False,
            ),
            sa.Column(
                "team_id",
                sa.String(),
                sa.ForeignKey("team.id"),
                nullable=True,
            ),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("naipe", sa.String(), nullable=False),
            sa.Column("category", sa.String(), nullable=True),
            sa.Column("created_at", sa.Float(), nullable=False),
            sa.Column("updated_at", sa.Float(), nullable=True),
        )

    indexes = {
        idx["name"] for idx in inspector.get_indexes("athlete")
    } if "athlete" in tables else set()

    if "ix_athlete_event" not in indexes:
        op.create_index("ix_athlete_event", "athlete", ["event_id"])
    if "ix_athlete_event_team" not in indexes:
        op.create_index(
            "ix_athlete_event_team", "athlete", ["event_id", "team_id"]
        )
    if "ix_athlete_event_name" not in indexes:
        op.create_index(
            "ix_athlete_event_name", "athlete", ["event_id", "name"]
        )
    if "uq_athlete_event_name_team" not in indexes:
        # COALESCE garante que atletas sem equipe tambem sejam deduplicados.
        bind.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_athlete_event_name_team "
            "ON athlete (event_id, name COLLATE NOCASE, COALESCE(team_id, ''))"
        )

    lane_columns = {
        col["name"] for col in inspect(bind).get_columns("heat_lane")
    }
    if "athlete_id" not in lane_columns:
        # SQLite nao permite ALTER TABLE ADD CONSTRAINT; a referencia pode ser
        # declarada inline na coluna adicionada (default NULL).
        bind.exec_driver_sql(
            "ALTER TABLE heat_lane ADD COLUMN athlete_id VARCHAR "
            "REFERENCES athlete (id)"
        )

    lane_indexes = {
        idx["name"] for idx in inspect(bind).get_indexes("heat_lane")
    }
    if "ix_heat_lane_athlete" not in lane_indexes:
        op.create_index(
            "ix_heat_lane_athlete", "heat_lane", ["athlete_id"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    lane_indexes = {
        idx["name"] for idx in inspector.get_indexes("heat_lane")
    }
    if "ix_heat_lane_athlete" in lane_indexes:
        op.drop_index("ix_heat_lane_athlete", table_name="heat_lane")

    lane_columns = {
        col["name"] for col in inspector.get_columns("heat_lane")
    }
    if "athlete_id" in lane_columns:
        bind.exec_driver_sql(
            "ALTER TABLE heat_lane DROP COLUMN athlete_id"
        )

    tables = set(inspector.get_table_names())
    if "athlete" in tables:
        op.drop_table("athlete")
