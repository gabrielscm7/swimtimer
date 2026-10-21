"""Regras de classificacao consolidada por prova.

Este modulo e puro (sem banco, sem HTTP) para ser facil de testar. A unica
unidade de tempo considerada e `race_time_ms` (inteiro, milissegundos). Nunca
se compara a string formatada nem se usa float.
"""

from .schemas import compute_speed, format_race_time


def prova_status(heat_statuses: list[str]) -> str:
    if not heat_statuses:
        return "scheduled"
    values = set(heat_statuses)
    if values == {"finished"}:
        return "finished"
    if values <= {"scheduled"}:
        return "scheduled"
    return "in_progress"


def is_provisional(heat_statuses: list[str]) -> bool:
    if not heat_statuses:
        return True
    return any(status != "finished" for status in heat_statuses)


def classify_lane(lane_status: str, race_time_ms: int | None) -> str:
    """Classifica uma raia em valid, dq, no_time ou pending."""
    if lane_status == "dq":
        return "dq"
    if lane_status == "finished":
        return "valid" if race_time_ms is not None else "no_time"
    return "pending"


def _entry(
    *,
    lane: dict,
    heat: dict,
    team_map: dict[str, dict],
    pool_distance_m: int | None,
) -> dict:
    team = team_map.get(lane.get("team_id") or "")
    time_ms = lane.get("race_time_ms")
    distance = heat.get("distance_m") or pool_distance_m
    classification_status = classify_lane(lane.get("status", ""), time_ms)
    return {
        "position": None,
        "lane_id": lane["id"],
        "heat_id": heat["id"],
        "heat_name": heat.get("name", ""),
        "heat_order_num": heat.get("order_num", 0),
        "lane_number": lane.get("lane_number", 0),
        "participant_name": lane.get("participant_name"),
        "team_id": lane.get("team_id"),
        "team_name": team["name"] if team else None,
        "team_logo_url": team.get("logo_url") if team else None,
        "race_time_ms": time_ms,
        "race_time_display": format_race_time(time_ms),
        "speed_ms": compute_speed(distance, time_ms),
        "status": lane.get("status"),
        "classification_status": classification_status,
        "tied": False,
    }


def _sort_key(entry: dict) -> tuple:
    """Desempate visual deterministico (nao altera a posicao esportiva)."""
    return (
        entry["race_time_ms"],
        entry["lane_number"],
        entry.get("participant_name") or "",
        entry.get("team_name") or "",
        entry["lane_id"],
    )


def _ordered_battery(entries: list[dict]) -> list[dict]:
    valid = sorted(
        (item for item in entries if item["classification_status"] == "valid"),
        key=_sort_key,
    )
    invalid = [item for item in entries if item["classification_status"] != "valid"]
    invalid.sort(
        key=lambda item: (
            item["classification_status"] != "dq",
            item["lane_number"],
            item.get("participant_name") or "",
            item["lane_id"],
        )
    )
    return valid + invalid


def rank_valid(entries: list[dict]) -> list[dict]:
    """Atribui posicao esportiva: tempos iguais compartilham a posicao (1,2,2,4)."""
    ordered = sorted(
        (item for item in entries if item["classification_status"] == "valid"),
        key=_sort_key,
    )
    index = 0
    total = len(ordered)
    while index < total:
        end = index
        while (
            end + 1 < total
            and ordered[end + 1]["race_time_ms"] == ordered[index]["race_time_ms"]
        ):
            end += 1
        position = index + 1
        tied = end > index
        for item in ordered[index:end + 1]:
            item["position"] = position
            item["tied"] = tied
        index = end + 1
    return ordered


def build_classification(
    *,
    consolidate_results: bool,
    heats: list[dict],
    team_map: dict[str, dict],
    pool_distance_m: int | None,
) -> dict:
    """Monta a resposta de classificacao a partir de heats ja carregados.

    `heats` e uma lista de dicts com id, name, order_num, status, distance_m e
    lanes (lista de dicts com id, lane_number, participant_name, team_id,
    status, race_time_ms).
    """
    statuses = [heat.get("status", "scheduled") for heat in heats]
    battery_results: list[dict] = []
    all_entries: list[dict] = []

    for heat in heats:
        entries = [
            _entry(
                lane=lane,
                heat=heat,
                team_map=team_map,
                pool_distance_m=pool_distance_m,
            )
            for lane in heat.get("lanes", [])
            if lane.get("participant_name") or lane.get("team_id")
        ]
        all_entries.extend(entries)
        battery_results.append(
            {
                "heat_id": heat["id"],
                "heat_name": heat.get("name", ""),
                "heat_order_num": heat.get("order_num", 0),
                "status": heat.get("status", "scheduled"),
                "entries": _ordered_battery(entries),
            }
        )

    provisional = is_provisional(statuses)
    result = {
        "status": prova_status(statuses),
        "is_provisional": provisional,
        "standings": [],
        "excluded": [],
        "battery_results": battery_results,
    }

    if not consolidate_results:
        return result

    valid = [entry for entry in all_entries if entry["classification_status"] == "valid"]
    standings = rank_valid(valid)
    result["standings"] = standings
    excluded = [
        entry
        for entry in all_entries
        if entry["classification_status"] != "valid"
    ]
    excluded.sort(
        key=lambda item: (
            item["classification_status"] != "dq",
            item["heat_order_num"],
            item["lane_number"],
            item["lane_id"],
        )
    )
    result["excluded"] = excluded
    return result
