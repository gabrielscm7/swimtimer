"""Formato da prova e marcacao de provas legadas incompletas

Revision ID: 0014_prova_format_definition
Revises: 0013_event_presentation
Create Date: 2026-10-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "0014_prova_format_definition"
down_revision: Union[str, None] = "0013_event_presentation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns("prova")

    if "format" not in columns:
        op.add_column(
            "prova",
            sa.Column(
                "format",
                sa.String(),
                nullable=False,
                server_default=text("'bateria'"),
            ),
        )
    if "name_override" not in columns:
        op.add_column(
            "prova",
            sa.Column(
                "name_override",
                sa.Boolean(),
                nullable=False,
                server_default=text("0"),
            ),
        )
    if "legacy_incomplete" not in columns:
        op.add_column(
            "prova",
            sa.Column(
                "legacy_incomplete",
                sa.Boolean(),
                nullable=False,
                server_default=text("0"),
            ),
        )

    # Backfill do formato pelas baterias existentes. Provas sem baterias
    # permanecem como "bateria" (formato padrao do produto).
    bind.execute(
        text(
            "UPDATE prova SET format = CASE "
            "WHEN EXISTS (SELECT 1 FROM heat h WHERE h.prova_id = prova.id "
            "AND h.heat_type = 'bateria') THEN 'bateria' "
            "WHEN EXISTS (SELECT 1 FROM heat h WHERE h.prova_id = prova.id) "
            "THEN 'maratona' "
            "ELSE 'bateria' END"
        )
    )

    # Marca provas que nao tem a definicao minima para o novo modelo. Os dados
    # existentes permanecem intactos; a gestao exige a conclusao ao editar.
    bind.execute(
        text(
            "UPDATE prova SET legacy_incomplete = CASE "
            "WHEN stroke IS NULL OR naipe IS NULL OR category IS NULL "
            "THEN 1 "
            "WHEN format = 'bateria' AND distance_m IS NULL THEN 1 "
            "ELSE 0 END"
        )
    )


def downgrade() -> None:
    columns = _columns("prova")
    if "legacy_incomplete" in columns:
        op.drop_column("prova", "legacy_incomplete")
    if "name_override" in columns:
        op.drop_column("prova", "name_override")
    if "format" in columns:
        op.drop_column("prova", "format")
