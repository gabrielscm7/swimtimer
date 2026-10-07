"""Corrige lap_event legado e garante unicidade de lap_number por raia

Bancos criados pela versao antiga tinham `lap_event.lane_id` referenciando a
tabela `lane`, que foi removida na migracao 0001. Com `foreign_keys=ON` isso
torna qualquer INSERT em lap_event invalido ("no such table: lane"). Esta
migracao reconstroi a tabela com a FK correta para `heat_lane`, renumera as
voltas duplicadas (condicao de corrida) e cria a constraint unica
(lane_id, lap_number).

Revision ID: 0002_lap_unique
Revises: 0001_event_heat_refactor
Create Date: 2026-10-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_lap_unique"
down_revision: Union[str, None] = "0001_event_heat_refactor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RENUMBER = """
UPDATE lap_event
SET lap_number = (
    SELECT COUNT(*)
    FROM lap_event AS other
    WHERE other.lane_id = lap_event.lane_id
      AND (
        other.recorded_at < lap_event.recorded_at
        OR (other.recorded_at = lap_event.recorded_at AND other.id < lap_event.id)
      )
) + 1
"""

_COPY = (
    "INSERT INTO lap_event (id, lane_id, lap_number, recorded_at, is_undo) "
    "SELECT id, lane_id, lap_number, recorded_at, is_undo FROM lap_event_old"
)


def _rebuild(*, unique: bool) -> None:
    bind = op.get_bind()
    op.rename_table("lap_event", "lap_event_old")
    bind.exec_driver_sql("DROP INDEX IF EXISTS ix_lap_event_lane_recorded")

    columns = [
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "lane_id",
            sa.String(),
            sa.ForeignKey("heat_lane.id"),
            nullable=False,
        ),
        sa.Column("lap_number", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.Float(), nullable=False),
        sa.Column("is_undo", sa.Boolean(), nullable=False),
    ]
    if unique:
        columns.append(
            sa.UniqueConstraint(
                "lane_id", "lap_number", name="uq_lap_event_lane_number"
            )
        )
    op.create_table("lap_event", *columns)
    op.create_index(
        "ix_lap_event_lane_recorded", "lap_event", ["lane_id", "recorded_at"]
    )
    bind.exec_driver_sql(_COPY)
    op.drop_table("lap_event_old")


def upgrade() -> None:
    op.execute(_RENUMBER)
    _rebuild(unique=True)


def downgrade() -> None:
    _rebuild(unique=False)
