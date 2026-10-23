import csv
import io
import time

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from openpyxl import Workbook
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models import Athlete, HeatLane, Team
from ..schemas import (
    AthleteCreate,
    AthleteImportResult,
    AthleteListResponse,
    AthleteResponse,
    AthleteUpdate,
    normalize_category,
    normalize_naipe,
)
from ..services.athlete_import import (
    _IMPORT_COLUMNS,
    _REQUIRED_COLUMNS,
    _cell,
    _detect_header,
    _parse_csv_rows,
    _parse_xlsx_rows,
)
from ..services.broadcast import manager
from ..services.inscricao import enforce_athlete_update
from ..services.lookups import _get_event

router = APIRouter()


def _athlete_dict(athlete: Athlete, team: Team | None = None) -> dict:
    return {
        "id": athlete.id,
        "event_id": athlete.event_id,
        "team_id": athlete.team_id,
        "name": athlete.name,
        "naipe": athlete.naipe,
        "category": athlete.category,
        "registration_code": athlete.registration_code,
        "created_at": athlete.created_at,
        "updated_at": athlete.updated_at,
        "team_name": team.name if team else None,
        "team_logo_url": team.logo_url if team else None,
    }


async def _get_athlete(session: AsyncSession, athlete_id: str) -> Athlete:
    athlete = await session.get(Athlete, athlete_id)
    if athlete is None:
        raise HTTPException(status_code=404, detail="atleta_nao_encontrado")
    return athlete


async def _validate_athlete_team(
    session: AsyncSession, event_id: str, team_id: str | None
) -> Team | None:
    if team_id is None:
        return None
    team = await session.get(Team, team_id)
    if team is None or team.event_id != event_id:
        raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
    return team


async def _broadcast_athletes_changed(event_id: str) -> None:
    await manager.broadcast(
        {
            "type": "athletes_changed",
            "scope": "event",
            "payload": {"event_id": event_id},
        }
    )


async def _athlete_duplicate_exists(
    session: AsyncSession,
    event_id: str,
    name: str,
    team_id: str | None,
    registration_code: str | None,
    *,
    exclude_id: str | None = None,
) -> bool:
    query = (
        select(func.count())
        .select_from(Athlete)
        .where(
            Athlete.event_id == event_id,
            func.lower(Athlete.name) == name.lower(),
            func.coalesce(Athlete.team_id, "") == (team_id or ""),
            func.coalesce(Athlete.registration_code, "")
            == (registration_code or ""),
        )
    )
    if exclude_id is not None:
        query = query.where(Athlete.id != exclude_id)
    return bool(await session.scalar(query))


@router.post(
    "/api/events/{event_id}/athletes",
    status_code=201,
    response_model=AthleteResponse,
)
async def create_athlete(
    event_id: str,
    payload: AthleteCreate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    await _get_event(session, event_id)
    team = await _validate_athlete_team(session, event_id, payload.team_id)
    if await _athlete_duplicate_exists(
        session,
        event_id,
        payload.name,
        payload.team_id,
        payload.registration_code,
    ):
        raise HTTPException(status_code=409, detail="atleta_duplicado")

    athlete = Athlete(
        event_id=event_id,
        team_id=payload.team_id,
        name=payload.name,
        naipe=payload.naipe,
        category=payload.category,
        registration_code=payload.registration_code,
        created_at=time.time(),
    )
    session.add(athlete)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="atleta_duplicado")
    await session.refresh(athlete)
    await _broadcast_athletes_changed(event_id)
    return _athlete_dict(athlete, team)


@router.get(
    "/api/events/{event_id}/athletes",
    response_model=AthleteListResponse,
)
async def list_athletes(
    event_id: str,
    q: str | None = Query(default=None, max_length=120),
    team_id: str | None = Query(default=None),
    naipe: str | None = Query(default=None),
    category: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> dict:
    await _get_event(session, event_id)
    conditions = [Athlete.event_id == event_id]

    if q and q.strip():
        conditions.append(Athlete.name.ilike(f"%{q.strip()}%"))
    if team_id:
        conditions.append(Athlete.team_id == team_id)
    if naipe:
        normalized = normalize_naipe(naipe)
        if normalized not in ("M", "F"):
            raise HTTPException(status_code=400, detail="naipe_invalido")
        conditions.append(Athlete.naipe == normalized)
    if category:
        conditions.append(
            Athlete.category == normalize_category(category)
        )

    total = await session.scalar(
        select(func.count()).select_from(Athlete).where(*conditions)
    )
    result = await session.execute(
        select(Athlete)
        .where(*conditions)
        .order_by(Athlete.name, Athlete.id)
        .limit(limit)
        .offset(offset)
    )
    athletes = list(result.scalars().all())

    team_ids = {athlete.team_id for athlete in athletes if athlete.team_id}
    teams: dict[str, Team] = {}
    if team_ids:
        result = await session.execute(
            select(Team).where(Team.id.in_(team_ids))
        )
        teams = {team.id: team for team in result.scalars().all()}

    return {
        "items": [
            _athlete_dict(athlete, teams.get(athlete.team_id))
            for athlete in athletes
        ],
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
    }


@router.get("/api/athletes/{athlete_id}", response_model=AthleteResponse)
async def get_athlete(
    athlete_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    athlete = await _get_athlete(session, athlete_id)
    team = await session.get(Team, athlete.team_id) if athlete.team_id else None
    return _athlete_dict(athlete, team)


@router.patch("/api/athletes/{athlete_id}", response_model=AthleteResponse)
async def update_athlete(
    athlete_id: str,
    payload: AthleteUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    athlete = await _get_athlete(session, athlete_id)
    data = payload.model_dump(
        exclude_unset=True, exclude={"force", "override_reason"}
    )
    if "name" in data and not data["name"]:
        raise HTTPException(status_code=422, detail="nome_obrigatorio")

    if "team_id" in data:
        await _validate_athlete_team(
            session, athlete.event_id, data["team_id"]
        )

    new_name = data.get("name", athlete.name)
    new_team_id = data["team_id"] if "team_id" in data else athlete.team_id
    new_registration_code = (
        data["registration_code"]
        if "registration_code" in data
        else athlete.registration_code
    )
    if (
        "name" in data
        or "team_id" in data
        or "registration_code" in data
    ):
        if await _athlete_duplicate_exists(
            session,
            athlete.event_id,
            new_name,
            new_team_id,
            new_registration_code,
            exclude_id=athlete.id,
        ):
            raise HTTPException(status_code=409, detail="atleta_duplicado")

    if "naipe" in data or "category" in data:
        await enforce_athlete_update(
            session,
            athlete=athlete,
            naipe=data.get("naipe", athlete.naipe),
            category=(
                data["category"] if "category" in data else athlete.category
            ),
            force=payload.force,
            override_reason=payload.override_reason,
            request=request,
        )

    for field, value in data.items():
        setattr(athlete, field, value)
    athlete.updated_at = time.time()

    # Mantem a copia desnormalizada das raias em sincronia para os clientes
    # (fiscal/supervisor/publico) que leem participant_name diretamente.
    await session.execute(
        update(HeatLane)
        .where(HeatLane.athlete_id == athlete.id)
        .values(participant_name=athlete.name, team_id=athlete.team_id)
    )
    await session.commit()
    await session.refresh(athlete)
    team = await session.get(Team, athlete.team_id) if athlete.team_id else None
    await _broadcast_athletes_changed(athlete.event_id)
    return _athlete_dict(athlete, team)


@router.delete("/api/athletes/{athlete_id}", status_code=204)
async def delete_athlete(
    athlete_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    athlete = await _get_athlete(session, athlete_id)
    usage = await session.scalar(
        select(func.count())
        .select_from(HeatLane)
        .where(HeatLane.athlete_id == athlete.id)
    )
    if usage:
        raise HTTPException(status_code=409, detail="atleta_em_uso")
    event_id = athlete.event_id
    await session.delete(athlete)
    await session.commit()
    await _broadcast_athletes_changed(event_id)


@router.post(
    "/api/events/{event_id}/athletes/import",
    response_model=AthleteImportResult,
)
async def import_athletes(
    event_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
) -> dict:
    await _get_event(session, event_id)

    filename = (file.filename or "").lower()
    if filename.endswith(".xlsx"):
        fmt = "xlsx"
    elif filename.endswith(".csv") or filename.endswith(".txt"):
        fmt = "csv"
    else:
        raise HTTPException(status_code=415, detail="formato_invalido")

    data = await file.read(settings.MAX_IMPORT_BYTES + 1)
    if len(data) > settings.MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="arquivo_muito_grande")
    if not data:
        raise HTTPException(status_code=400, detail="arquivo_vazio")
    if fmt == "xlsx" and not data.startswith(b"PK\x03\x04"):
        raise HTTPException(status_code=415, detail="formato_invalido")

    if fmt == "xlsx":
        try:
            rows = _parse_xlsx_rows(data)
        except Exception:
            raise HTTPException(
                status_code=400, detail="planilha_invalida"
            )
    else:
        rows = _parse_csv_rows(data)

    header_index, header_map = _detect_header(rows)
    missing = [
        column
        for column in _REQUIRED_COLUMNS
        if column not in header_map
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"colunas_obrigatorias:{','.join(missing)}",
        )

    data_rows = len(rows) - header_index - 1
    if data_rows > settings.MAX_IMPORT_ROWS:
        raise HTTPException(status_code=413, detail="planilha_muito_grande")

    result = await session.execute(
        select(Team).where(Team.event_id == event_id)
    )
    teams_by_key = {
        team.name.casefold(): team for team in result.scalars().all()
    }
    result = await session.execute(
        select(
            Athlete.name, Athlete.team_id, Athlete.registration_code
        ).where(Athlete.event_id == event_id)
    )
    existing_keys = {
        (name.casefold(), team_id or "", registration_code or "")
        for name, team_id, registration_code in result.all()
    }

    errors: list[dict] = []
    pending: list[Athlete] = []
    created_teams = 0
    skipped = 0
    now = time.time()

    name_col = header_map["NOME"]
    team_col = header_map["EQUIPE"]
    naipe_col = header_map["NAIPE"]
    category_col = header_map["CATEGORIA"]
    registration_col = header_map.get("REGISTRO")

    for index, row in enumerate(rows):
        if index <= header_index:
            continue
        line = index + 1

        name = _cell(row, name_col)
        team_name = _cell(row, team_col)
        naipe_raw = _cell(row, naipe_col)
        category_raw = _cell(row, category_col)
        registration_raw = _cell(row, registration_col)

        if (
            not name
            and not team_name
            and not naipe_raw
            and not category_raw
            and not registration_raw
        ):
            skipped += 1
            continue
        if not name:
            errors.append(
                {"line": line, "field": "nome", "message": "nome_obrigatorio"}
            )
            continue
        naipe = normalize_naipe(naipe_raw)
        if naipe not in ("M", "F"):
            errors.append(
                {"line": line, "field": "naipe", "message": "naipe_invalido"}
            )
            continue

        team_id: str | None = None
        if team_name:
            key = team_name.casefold()
            team = teams_by_key.get(key)
            if team is None:
                team = Team(event_id=event_id, name=team_name)
                session.add(team)
                await session.flush()
                teams_by_key[key] = team
                created_teams += 1
            team_id = team.id

        registration_code = registration_raw or None
        duplicate_key = (
            name.casefold(),
            team_id or "",
            registration_code or "",
        )
        if duplicate_key in existing_keys:
            errors.append(
                {"line": line, "field": "nome", "message": "atleta_duplicado"}
            )
            continue
        existing_keys.add(duplicate_key)

        pending.append(
            Athlete(
                event_id=event_id,
                team_id=team_id,
                name=name,
                naipe=naipe,
                category=normalize_category(category_raw),
                registration_code=registration_code,
                created_at=now,
            )
        )

    session.add_all(pending)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="importacao_conflito")

    await _broadcast_athletes_changed(event_id)
    return {
        "created_athletes": len(pending),
        "created_teams": created_teams,
        "skipped": skipped,
        "errors": errors,
    }


def _attachment_response(
    content: bytes, filename: str, media_type: str
) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@router.get("/api/events/{event_id}/athletes/import-template")
async def download_athletes_template(
    event_id: str,
    format: str = Query(default="csv", pattern="^(csv|xlsx)$"),
    session: AsyncSession = Depends(get_db),
) -> Response:
    await _get_event(session, event_id)
    if format == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(list(_IMPORT_COLUMNS))
        sheet.append(
            ["Maria Silva", "Equipe A", "F", "SUB-12", "A-001"]
        )
        buffer = io.BytesIO()
        workbook.save(buffer)
        return _attachment_response(
            buffer.getvalue(),
            "modelo_atletas.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    return _attachment_response(
        ("\ufeff" + ",".join(_IMPORT_COLUMNS) + "\n"
         "Maria Silva,Equipe A,F,SUB-12,A-001\n").encode("utf-8"),
        "modelo_atletas.csv",
        "text/csv; charset=utf-8",
    )


@router.get("/api/events/{event_id}/athletes/export")
async def export_athletes(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> Response:
    await _get_event(session, event_id)
    result = await session.execute(
        select(Athlete, Team.name)
        .outerjoin(Team, Athlete.team_id == Team.id)
        .where(Athlete.event_id == event_id)
        .order_by(Athlete.name)
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_IMPORT_COLUMNS)
    for athlete, team_name in result.all():
        writer.writerow(
            [
                athlete.name,
                team_name or "",
                athlete.naipe,
                athlete.category or "",
                athlete.registration_code or "",
            ]
        )
    return _attachment_response(
        ("\ufeff" + buffer.getvalue()).encode("utf-8"),
        "atletas.csv",
        "text/csv; charset=utf-8",
    )
