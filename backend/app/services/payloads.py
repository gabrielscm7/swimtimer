from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..classification import build_classification, prova_status
from ..models import Athlete, Event, Heat, HeatLane, LapEvent, Prova, Team
from ..schemas import compute_speed, format_race_time


async def _team_map(session: AsyncSession, event_id: str) -> dict[str, dict]:
    result = await session.execute(select(Team).where(Team.event_id == event_id))
    return {
        team.id: {"name": team.name, "logo_url": team.logo_url}
        for team in result.scalars().all()
    }


async def _team_athlete_counts(
    session: AsyncSession, event_id: str
) -> dict[str, int]:
    result = await session.execute(
        select(Athlete.team_id, func.count(Athlete.id))
        .where(Athlete.event_id == event_id, Athlete.team_id.is_not(None))
        .group_by(Athlete.team_id)
    )
    return {team_id: count for team_id, count in result.all()}


def _team_dict(team: Team, athlete_count: int = 0) -> dict:
    return {
        "id": team.id,
        "event_id": team.event_id,
        "name": team.name,
        "logo_url": team.logo_url,
        "athlete_count": athlete_count,
    }


def _lane_dict(
    lane: HeatLane,
    *,
    heat: Heat,
    pool_length_m: int,
    team_name: str | None,
    team_logo_url: str | None = None,
    athlete: Athlete | None = None,
    laps: int = 0,
    last_lap_at: float | None = None,
) -> dict:
    return {
        "id": lane.id,
        "heat_id": lane.heat_id,
        "lane_number": lane.lane_number,
        "participant_name": athlete.name if athlete else lane.participant_name,
        "athlete_id": lane.athlete_id,
        "naipe": athlete.naipe if athlete else None,
        "category": athlete.category if athlete else None,
        "team_id": lane.team_id,
        "team": team_name,
        "team_logo_url": team_logo_url,
        "status": lane.status,
        "finish_at": lane.finish_at,
        "race_time_ms": lane.race_time_ms,
        "received_at": lane.received_at,
        "late": bool(lane.late),
        "race_time_display": format_race_time(lane.race_time_ms),
        "speed_ms": compute_speed(heat.distance_m, lane.race_time_ms),
        "laps": laps,
        "meters": laps * pool_length_m,
        "last_lap_at": last_lap_at,
    }


async def _lane_payload(
    session: AsyncSession, lane: HeatLane, heat: Heat
) -> dict:
    event = await session.get(Event, heat.event_id)
    athlete = (
        await session.get(Athlete, lane.athlete_id)
        if lane.athlete_id
        else None
    )
    team = await session.get(Team, lane.team_id) if lane.team_id else None
    return _lane_dict(
        lane,
        heat=heat,
        pool_length_m=event.pool_length_m if event else 0,
        team_name=team.name if team else None,
        team_logo_url=team.logo_url if team else None,
        athlete=athlete,
    )


async def _heats_payload(
    session: AsyncSession, heats: list[Heat]
) -> list[dict]:
    """Carrega raias, voltas e equipes de varias baterias em lote."""
    if not heats:
        return []

    event_ids = {heat.event_id for heat in heats}
    result = await session.execute(
        select(Event).where(Event.id.in_(event_ids))
    )
    events = {event.id: event for event in result.scalars().all()}

    result = await session.execute(
        select(Team).where(Team.event_id.in_(event_ids))
    )
    teams_by_event: dict[str, dict[str, dict]] = {}
    for team in result.scalars().all():
        teams_by_event.setdefault(team.event_id, {})[team.id] = {
            "name": team.name,
            "logo_url": team.logo_url,
        }

    heat_ids = [heat.id for heat in heats]
    result = await session.execute(
        select(HeatLane)
        .where(HeatLane.heat_id.in_(heat_ids))
        .order_by(HeatLane.heat_id, HeatLane.lane_number)
    )
    lanes_by_heat: dict[str, list[HeatLane]] = {}
    lane_ids: list[str] = []
    for lane in result.scalars().all():
        lanes_by_heat.setdefault(lane.heat_id, []).append(lane)
        lane_ids.append(lane.id)

    athlete_ids = {
        lane.athlete_id
        for lanes in lanes_by_heat.values()
        for lane in lanes
        if lane.athlete_id
    }
    athletes_by_id: dict[str, Athlete] = {}
    if athlete_ids:
        result = await session.execute(
            select(Athlete).where(Athlete.id.in_(athlete_ids))
        )
        athletes_by_id = {item.id: item for item in result.scalars().all()}

    lap_counts: dict[str, int] = {}
    last_laps: dict[str, float] = {}
    if lane_ids:
        rows = await session.execute(
            select(
                LapEvent.lane_id,
                func.count(LapEvent.id),
                func.max(LapEvent.recorded_at),
            )
            .where(LapEvent.lane_id.in_(lane_ids), LapEvent.is_undo.is_(False))
            .group_by(LapEvent.lane_id)
        )
        for lane_id, count, last in rows.all():
            lap_counts[lane_id] = count
            if last is not None:
                last_laps[lane_id] = last

    payloads: list[dict] = []
    for heat in heats:
        event = events.get(heat.event_id)
        pool_length_m = event.pool_length_m if event else 0
        team_map = teams_by_event.get(heat.event_id, {})
        lanes = lanes_by_heat.get(heat.id, [])
        payloads.append(
            {
                "id": heat.id,
                "event_id": heat.event_id,
                "prova_id": heat.prova_id,
                "name": heat.name,
                "order_num": heat.order_num,
                "heat_type": heat.heat_type,
                "distance_m": heat.distance_m,
                "duration_s": heat.duration_s,
                "status": heat.status,
                "started_at": heat.started_at,
                "finished_at": heat.finished_at,
                "heat_lanes": [
                    _lane_dict(
                        lane,
                        heat=heat,
                        pool_length_m=pool_length_m,
                        team_name=(team_map.get(lane.team_id) or {}).get("name")
                        if lane.team_id
                        else None,
                        team_logo_url=(
                            team_map.get(lane.team_id) or {}
                        ).get("logo_url")
                        if lane.team_id
                        else None,
                        athlete=athletes_by_id.get(lane.athlete_id)
                        if lane.athlete_id
                        else None,
                        laps=lap_counts.get(lane.id, 0),
                        last_lap_at=last_laps.get(lane.id),
                    )
                    for lane in lanes
                ],
            }
        )
    return payloads


async def _heat_payload(session: AsyncSession, heat: Heat) -> dict:
    payloads = await _heats_payload(session, [heat])
    return payloads[0]


async def _prova_heats(session: AsyncSession, prova_id: str) -> list[Heat]:
    result = await session.execute(
        select(Heat)
        .where(Heat.prova_id == prova_id)
        .order_by(Heat.order_num)
    )
    return list(result.scalars().all())


async def _provas_payload(
    session: AsyncSession,
    provas: list[Prova],
    *,
    include_heats: bool = True,
) -> list[dict]:
    if not provas:
        return []
    event_id = provas[0].event_id
    result = await session.execute(
        select(Heat)
        .where(Heat.event_id == event_id)
        .order_by(Heat.order_num)
    )
    heats = list(result.scalars().all())
    heat_payloads = await _heats_payload(session, heats) if include_heats else []
    payload_by_heat = {payload["id"]: payload for payload in heat_payloads}
    heats_by_prova: dict[str, list[Heat]] = {}
    for heat in heats:
        heats_by_prova.setdefault(heat.prova_id, []).append(heat)

    payloads = []
    for prova in provas:
        prova_heats = sorted(
            heats_by_prova.get(prova.id, []),
            key=lambda heat: heat.order_num,
        )
        payloads.append(
            {
                "id": prova.id,
                "event_id": prova.event_id,
                "name": prova.name,
                "order_num": prova.order_num,
                "stroke": prova.stroke,
                "distance_m": prova.distance_m,
                "category": prova.category,
                "naipe": prova.naipe,
                "consolidate_results": prova.consolidate_results,
                "classification_criterion": prova.classification_criterion,
                "status": prova_status([heat.status for heat in prova_heats]),
                "created_at": prova.created_at,
                "heat_count": len(prova_heats),
                "heat_orders": [heat.order_num for heat in prova_heats],
                "heats": [
                    payload_by_heat[heat.id]
                    for heat in prova_heats
                    if heat.id in payload_by_heat
                ],
            }
        )
    return payloads


async def _prova_payload(
    session: AsyncSession, prova: Prova, *, include_heats: bool = True
) -> dict:
    payloads = await _provas_payload(
        session, [prova], include_heats=include_heats
    )
    return payloads[0]


async def _classification_payload(
    session: AsyncSession, prova: Prova
) -> dict:
    heats = await _prova_heats(session, prova.id)
    heat_ids = [heat.id for heat in heats]
    lane_map: dict[str, list[HeatLane]] = {heat_id: [] for heat_id in heat_ids}
    if heat_ids:
        result = await session.execute(
            select(HeatLane)
            .where(HeatLane.heat_id.in_(heat_ids))
            .order_by(HeatLane.lane_number)
        )
        for lane in result.scalars().all():
            lane_map[lane.heat_id].append(lane)

    event = await session.get(Event, prova.event_id)
    team_map = await _team_map(session, prova.event_id)
    heat_dicts = [
        {
            "id": heat.id,
            "name": heat.name,
            "order_num": heat.order_num,
            "status": heat.status,
            "distance_m": heat.distance_m,
            "lanes": [
                {
                    "id": lane.id,
                    "lane_number": lane.lane_number,
                    "participant_name": lane.participant_name,
                    "team_id": lane.team_id,
                    "status": lane.status,
                    "race_time_ms": lane.race_time_ms,
                }
                for lane in lane_map.get(heat.id, [])
            ],
        }
        for heat in heats
    ]
    classification = build_classification(
        consolidate_results=prova.consolidate_results,
        heats=heat_dicts,
        team_map=team_map,
        pool_distance_m=event.pool_length_m if event else None,
    )
    return {
        "prova_id": prova.id,
        "name": prova.name,
        "naipe": prova.naipe,
        "category": prova.category,
        "status": classification["status"],
        "consolidate_results": prova.consolidate_results,
        "classification_criterion": prova.classification_criterion,
        "is_provisional": classification["is_provisional"],
        "standings": classification["standings"],
        "excluded": classification["excluded"],
        "battery_results": classification["battery_results"],
    }


async def _sync_prova_status(session: AsyncSession, prova_id: str) -> None:
    prova = await session.get(Prova, prova_id)
    if prova is None:
        return
    result = await session.execute(
        select(Heat.status).where(Heat.prova_id == prova_id)
    )
    prova.status = prova_status(list(result.scalars().all()))


async def _event_payload(
    session: AsyncSession, event: Event, *, include_teams: bool = False
) -> dict:
    result = await session.execute(
        select(Heat)
        .join(Prova, Heat.prova_id == Prova.id)
        .where(Heat.event_id == event.id)
        .order_by(Prova.order_num, Heat.order_num)
    )
    heats = result.scalars().all()
    result = await session.execute(
        select(Prova)
        .where(Prova.event_id == event.id)
        .order_by(Prova.order_num)
    )
    provas = result.scalars().all()
    payload = {
        "id": event.id,
        "name": event.name,
        "location": event.location,
        "date": event.date,
        "pool_length_m": event.pool_length_m,
        "status": event.status,
        "created_at": event.created_at,
        "provas": [
            {
                "id": prova.id,
                "event_id": prova.event_id,
                "name": prova.name,
                "order_num": prova.order_num,
                "stroke": prova.stroke,
                "distance_m": prova.distance_m,
                "category": prova.category,
                "naipe": prova.naipe,
                "consolidate_results": prova.consolidate_results,
                "classification_criterion": prova.classification_criterion,
                "status": prova.status,
                "heat_count": sum(
                    1 for heat in heats if heat.prova_id == prova.id
                ),
            }
            for prova in provas
        ],
        "heats": await _heats_payload(session, heats),
    }
    if include_teams:
        result = await session.execute(
            select(Team).where(Team.event_id == event.id).order_by(Team.name)
        )
        counts = await _team_athlete_counts(session, event.id)
        payload["teams"] = [
            _team_dict(team, counts.get(team.id, 0))
            for team in result.scalars().all()
        ]
    return payload


def _participant_lanes(lanes: list[HeatLane]) -> list[HeatLane]:
    return [
        lane
        for lane in lanes
        if lane.participant_name or lane.athlete_id or lane.team_id
    ]


async def _heat_lanes(session: AsyncSession, heat_id: str) -> list[HeatLane]:
    result = await session.execute(
        select(HeatLane)
        .where(HeatLane.heat_id == heat_id)
        .order_by(HeatLane.lane_number)
    )
    return list(result.scalars().all())


def _ready_payload(lanes: list[HeatLane]) -> dict:
    participants = _participant_lanes(lanes)
    ready = [lane.lane_number for lane in participants if lane.status == "ready"]
    pending = [lane.lane_number for lane in participants if lane.status != "ready"]
    return {
        "lanes_ready": ready,
        "lanes_pending": pending,
        "all_ready": bool(participants) and not pending,
    }
