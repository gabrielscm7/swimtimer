"""Adiciona naipe estruturado as provas e migra o texto legado

Provas antigas guardavam genero e categoria no mesmo campo `category`
(ex.: "masculino, sub-12"). A migracao extrai o naipe para a nova coluna e
remove o termo de genero do texto, preservando a categoria de idade.

Revision ID: 0006_prova_naipe
Revises: 0005_athlete
Create Date: 2026-10-21

"""
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "0006_prova_naipe"
down_revision: Union[str, None] = "0005_athlete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALIASES = {
    "M": "M",
    "MAS": "M",
    "MASC": "M",
    "MASC.": "M",
    "MASCULINO": "M",
    "F": "F",
    "FEM": "F",
    "FEM.": "F",
    "FEMININO": "F",
    "FEMININA": "F",
}
_SPLIT = re.compile(r"[\s,;/|]+")


def _extract_naipe(category: str | None) -> tuple[str | None, str | None]:
    """Retorna (naipe, categoria_limpa) a partir do texto legado."""
    if not category:
        return None, category
    tokens = [token for token in _SPLIT.split(category.strip()) if token]
    naipe = None
    for token in tokens:
        naipe = _ALIASES.get(token.upper())
        if naipe:
            break
    if naipe is None:
        return None, category
    remaining = [
        token for token in tokens if _ALIASES.get(token.upper()) is None
    ]
    cleaned = " ".join(remaining).strip(" -.,;/").upper() or None
    return naipe, cleaned


def upgrade() -> None:
    bind = op.get_bind()
    columns = {col["name"] for col in inspect(bind).get_columns("prova")}
    if "naipe" not in columns:
        op.add_column("prova", sa.Column("naipe", sa.String(), nullable=True))

    rows = bind.execute(
        text("SELECT id, category FROM prova WHERE naipe IS NULL")
    ).fetchall()
    for row in rows:
        naipe, category = _extract_naipe(row.category)
        if naipe is None:
            continue
        bind.execute(
            text(
                "UPDATE prova SET naipe = :naipe, category = :category "
                "WHERE id = :id"
            ),
            {"naipe": naipe, "category": category, "id": row.id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {col["name"] for col in inspect(bind).get_columns("prova")}
    if "naipe" in columns:
        bind.exec_driver_sql("ALTER TABLE prova DROP COLUMN naipe")
