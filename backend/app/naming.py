"""Exibicao publica de nomes (nunca altera os dados armazenados)."""

from typing import Any

_CONNECTORS = {
    "da",
    "das",
    "de",
    "di",
    "do",
    "dos",
    "du",
    "e",
    "la",
    "las",
    "le",
    "les",
    "del",
    "van",
    "von",
}


def display_name(name: str | None, mode: str = "full") -> str | None:
    """`full` devolve o nome; `initials` devolve "Maria S.".

    Mantem o primeiro nome e a inicial do ultimo sobrenome significativo,
    ignorando conectivos (da, de, dos...).
    """
    if name is None:
        return None
    if mode != "initials":
        return name
    tokens = name.split()
    if not tokens:
        return name
    first = tokens[0]
    significant = [
        token for token in tokens[1:] if token.strip().lower() not in _CONNECTORS
    ]
    if not significant:
        return first if len(tokens) == 1 else f"{first}."
    return f"{first} {significant[-1][0].upper()}."


def mask_names(value: Any, mode: str = "full") -> Any:
    """Aplica `display_name` recursivamente aos campos `participant_name`."""
    if isinstance(value, dict):
        return {
            key: (
                display_name(item, mode)
                if key == "participant_name" and isinstance(item, str)
                else mask_names(item, mode)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_names(item, mode) for item in value]
    return value
