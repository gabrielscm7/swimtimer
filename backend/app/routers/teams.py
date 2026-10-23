import asyncio
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.locks import _theme_guard
from ..database import get_db
from ..models import Athlete, HeatLane, Team
from ..schemas import TeamCreate, TeamResponse, TeamUpdate
from ..services.lookups import _get_event
from ..services.logos import _remove_logo_file, _sniff_image
from ..services.payloads import _team_athlete_counts, _team_dict

router = APIRouter()


@router.post(
    "/api/events/{event_id}/teams",
    status_code=201,
    response_model=TeamResponse,
)
async def create_team(
    event_id: str,
    payload: TeamCreate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    await _get_event(session, event_id)
    team = Team(event_id=event_id, name=payload.name)
    session.add(team)
    await session.commit()
    await session.refresh(team)
    return _team_dict(team)


@router.get("/api/events/{event_id}/teams", response_model=list[TeamResponse])
async def list_teams(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_event(session, event_id)
    result = await session.execute(
        select(Team).where(Team.event_id == event_id).order_by(Team.name)
    )
    counts = await _team_athlete_counts(session, event_id)
    return [
        _team_dict(team, counts.get(team.id, 0))
        for team in result.scalars().all()
    ]


@router.patch("/api/teams/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: str,
    payload: TeamUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(team, field, value)
    await session.commit()
    await session.refresh(team)
    count = await session.scalar(
        select(func.count())
        .select_from(Athlete)
        .where(Athlete.team_id == team.id)
    )
    return _team_dict(team, int(count or 0))


@router.post("/api/teams/{team_id}/logo")
async def upload_team_logo(
    team_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
) -> dict:
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
    event_id = team.event_id

    data = await file.read(settings.MAX_LOGO_BYTES + 1)
    if len(data) > settings.MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail="arquivo_muito_grande")
    if not data:
        raise HTTPException(status_code=400, detail="arquivo_vazio")
    signature = _sniff_image(data)
    if signature is None:
        raise HTTPException(status_code=415, detail="formato_invalido")
    extension, _mime = signature

    async with _theme_guard(event_id):
        team = await session.get(Team, team_id)
        if team is None:
            raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
        settings.logo_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4()}.{extension}"
        destination = settings.logo_dir / filename
        await asyncio.to_thread(destination.write_bytes, data)

        old_url = team.logo_url
        team.logo_url = f"/logos/{filename}"
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            await asyncio.to_thread(destination.unlink, True)
            raise
        await session.refresh(team)
        if old_url != team.logo_url:
            _remove_logo_file(old_url)
    return _team_dict(team)


@router.delete("/api/teams/{team_id}/logo")
async def delete_team_logo(
    team_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
    async with _theme_guard(team.event_id):
        team = await session.get(Team, team_id)
        if team is None:
            raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
        old_url = team.logo_url
        team.logo_url = None
        await session.commit()
        await session.refresh(team)
        _remove_logo_file(old_url)
    return _team_dict(team)


@router.delete("/api/teams/{team_id}", status_code=204)
async def delete_team(
    team_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
    async with _theme_guard(team.event_id):
        team = await session.get(Team, team_id)
        if team is None:
            raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
        usage = await session.scalar(
            select(func.count())
            .select_from(HeatLane)
            .where(HeatLane.team_id == team_id)
        )
        athletes = await session.scalar(
            select(func.count())
            .select_from(Athlete)
            .where(Athlete.team_id == team_id)
        )
        if usage or athletes:
            raise HTTPException(status_code=409, detail="equipe_em_uso")
        old_url = team.logo_url
        await session.delete(team)
        await session.commit()
        _remove_logo_file(old_url)
