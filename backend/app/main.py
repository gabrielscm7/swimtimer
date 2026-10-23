import csv
import io
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import database
from .config import settings
from .core.errors import LaneActionError
from .core.locks import _heat_guard
from .database import engine, get_db, init_db
from .models import (
    Athlete,
    Event,
    Heat,
    HeatLane,
    LapEvent,
    Prova,
    Team,
)
from .schemas import (
    AthleteCreate,
    AthleteImportResult,
    AthleteListResponse,
    AthleteResponse,
    AthleteUpdate,
    EventCreate,
    EventUpdate,
    HeatCreate,
    HeatUpdate,
    HeatLaneConfigRequest,
    LaneActionRequest,
    LaneUpdate,
    OrderIdsRequest,
    ProvaCreate,
    ProvaUpdate,
    TeamCreate,
    TeamResponse,
    TeamUpdate,
    normalize_category,
    normalize_naipe,
)
from .services.athlete_import import (
    _IMPORT_COLUMNS,
    _cell,
    _detect_header,
    _parse_csv_rows,
    _parse_xlsx_rows,
)
from .services.broadcast import (
    _active_heat_count,
    _broadcast_heat,
    _broadcast_ready,
    _broadcast_server_status,
    _heat_state_message,
    _prova_state_message,
    manager,
)
from .services.lane_actions import (
    _anchor_heat,
    _client_ip,
    _do_finish,
    _do_lap,
    _drop_anchor,
    _log_action,
    _maybe_finish_heat,
)
from .services.lookups import (
    _get_event,
    _get_heat,
    _get_lane,
    _get_prova,
    _validate_reorder_ids,
)
from .services.logos import _remove_logo_file, _sniff_image
from .services.payloads import (
    _classification_payload,
    _event_payload,
    _heat_lanes,
    _heat_payload,
    _lane_payload,
    _participant_lanes,
    _prova_heats,
    _prova_payload,
    _provas_payload,
    _sync_prova_status,
    _team_athlete_counts,
    _team_dict,
)

START_TIME = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.logo_dir.mkdir(parents=True, exist_ok=True)
    await init_db()
    yield
    await engine.dispose()


app = FastAPI(title="SwimTimer", version="2.4.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Eventos
# --------------------------------------------------------------------------- #
@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": "2.4.0"}


@app.get("/api/time")
async def server_time() -> dict:
    return {"now": time.time()}


@app.get("/api/status")
async def server_status(session: AsyncSession = Depends(get_db)) -> dict:
    return {
        "uptime": time.time() - START_TIME,
        "connected_clients": manager.count,
        "active_heats": await _active_heat_count(session),
    }


@app.get("/api/events")
async def list_events(
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = select(Event).order_by(Event.created_at.desc()).offset(offset)
    if limit is not None:
        query = query.limit(limit)
    result = await session.execute(query)
    return [
        await _event_payload(session, event, include_teams=True)
        for event in result.scalars().all()
    ]


@app.post("/api/events", status_code=201)
async def create_event(
    payload: EventCreate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    event = Event(
        name=payload.name,
        location=payload.location,
        date=payload.date,
        pool_length_m=payload.pool_length_m,
        status="draft",
        created_at=time.time(),
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    await _broadcast_server_status()
    return await _event_payload(session, event, include_teams=True)


@app.get("/api/events/{event_id}")
async def get_event(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    event = await _get_event(session, event_id)
    return await _event_payload(session, event, include_teams=True)


@app.patch("/api/events/{event_id}")
async def update_event(
    event_id: str,
    payload: EventUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    event = await _get_event(session, event_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(event, field, value)
    await session.commit()
    await session.refresh(event)
    return await _event_payload(session, event, include_teams=True)


@app.delete("/api/events/{event_id}", status_code=204)
async def delete_event(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    event = await _get_event(session, event_id)
    if event.status != "draft":
        raise HTTPException(status_code=409, detail="evento_nao_esta_draft")
    heat_ids = select(Heat.id).where(Heat.event_id == event_id)
    lane_ids = select(HeatLane.id).where(HeatLane.heat_id.in_(heat_ids))
    await session.execute(delete(LapEvent).where(LapEvent.lane_id.in_(lane_ids)))
    await session.execute(delete(HeatLane).where(HeatLane.heat_id.in_(heat_ids)))
    await session.execute(delete(Athlete).where(Athlete.event_id == event_id))
    await session.execute(delete(Heat).where(Heat.event_id == event_id))
    await session.execute(delete(Prova).where(Prova.event_id == event_id))
    await session.execute(delete(Team).where(Team.event_id == event_id))
    await session.delete(event)
    await session.commit()
    await _broadcast_server_status()


# --------------------------------------------------------------------------- #
# Equipes
# --------------------------------------------------------------------------- #
@app.post(
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


@app.get("/api/events/{event_id}/teams", response_model=list[TeamResponse])
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


@app.patch("/api/teams/{team_id}", response_model=TeamResponse)
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


@app.post("/api/teams/{team_id}/logo")
async def upload_team_logo(
    team_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
) -> dict:
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="equipe_nao_encontrada")

    data = await file.read(settings.MAX_LOGO_BYTES + 1)
    if len(data) > settings.MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail="arquivo_muito_grande")
    if not data:
        raise HTTPException(status_code=400, detail="arquivo_vazio")
    signature = _sniff_image(data)
    if signature is None:
        raise HTTPException(status_code=415, detail="formato_invalido")
    extension, _mime = signature

    settings.logo_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}.{extension}"
    destination = settings.logo_dir / filename
    destination.write_bytes(data)

    old_url = team.logo_url
    team.logo_url = f"/logos/{filename}"
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        destination.unlink(missing_ok=True)
        raise
    await session.refresh(team)
    if old_url != team.logo_url:
        _remove_logo_file(old_url)
    return _team_dict(team)


@app.delete("/api/teams/{team_id}/logo")
async def delete_team_logo(
    team_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
    old_url = team.logo_url
    team.logo_url = None
    await session.commit()
    await session.refresh(team)
    _remove_logo_file(old_url)
    return _team_dict(team)


@app.delete("/api/teams/{team_id}", status_code=204)
async def delete_team(
    team_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
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
    await session.delete(team)
    await session.commit()


# --------------------------------------------------------------------------- #
# Atletas
# --------------------------------------------------------------------------- #
def _athlete_dict(athlete: Athlete, team: Team | None = None) -> dict:
    return {
        "id": athlete.id,
        "event_id": athlete.event_id,
        "team_id": athlete.team_id,
        "name": athlete.name,
        "naipe": athlete.naipe,
        "category": athlete.category,
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
        )
    )
    if exclude_id is not None:
        query = query.where(Athlete.id != exclude_id)
    return bool(await session.scalar(query))


@app.post(
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
        session, event_id, payload.name, payload.team_id
    ):
        raise HTTPException(status_code=409, detail="atleta_duplicado")

    athlete = Athlete(
        event_id=event_id,
        team_id=payload.team_id,
        name=payload.name,
        naipe=payload.naipe,
        category=payload.category,
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


@app.get(
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


@app.get("/api/athletes/{athlete_id}", response_model=AthleteResponse)
async def get_athlete(
    athlete_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    athlete = await _get_athlete(session, athlete_id)
    team = await session.get(Team, athlete.team_id) if athlete.team_id else None
    return _athlete_dict(athlete, team)


@app.patch("/api/athletes/{athlete_id}", response_model=AthleteResponse)
async def update_athlete(
    athlete_id: str,
    payload: AthleteUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    athlete = await _get_athlete(session, athlete_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and not data["name"]:
        raise HTTPException(status_code=422, detail="nome_obrigatorio")

    if "team_id" in data:
        await _validate_athlete_team(
            session, athlete.event_id, data["team_id"]
        )

    new_name = data.get("name", athlete.name)
    new_team_id = data["team_id"] if "team_id" in data else athlete.team_id
    if "name" in data or "team_id" in data:
        if await _athlete_duplicate_exists(
            session,
            athlete.event_id,
            new_name,
            new_team_id,
            exclude_id=athlete.id,
        ):
            raise HTTPException(status_code=409, detail="atleta_duplicado")

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


@app.delete("/api/athletes/{athlete_id}", status_code=204)
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


# ---------------- Importacao / exportacao de planilhas ---------------- #


@app.post(
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
        column for column in _IMPORT_COLUMNS if column not in header_map
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
        select(Athlete.name, Athlete.team_id).where(
            Athlete.event_id == event_id
        )
    )
    existing_keys = {
        (name.casefold(), team_id or "") for name, team_id in result.all()
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

    for index, row in enumerate(rows):
        if index <= header_index:
            continue
        line = index + 1

        name = _cell(row, name_col)
        team_name = _cell(row, team_col)
        naipe_raw = _cell(row, naipe_col)
        category_raw = _cell(row, category_col)

        if not name and not team_name and not naipe_raw and not category_raw:
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

        duplicate_key = (name.casefold(), team_id or "")
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


@app.get("/api/events/{event_id}/athletes/import-template")
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
        sheet.append(["Maria Silva", "Equipe A", "F", "SUB-12"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        return _attachment_response(
            buffer.getvalue(),
            "modelo_atletas.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    return _attachment_response(
        ("\ufeff" + ",".join(_IMPORT_COLUMNS) + "\n"
         "Maria Silva,Equipe A,F,SUB-12\n").encode("utf-8"),
        "modelo_atletas.csv",
        "text/csv; charset=utf-8",
    )


@app.get("/api/events/{event_id}/athletes/export")
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
            ]
        )
    return _attachment_response(
        ("\ufeff" + buffer.getvalue()).encode("utf-8"),
        "atletas.csv",
        "text/csv; charset=utf-8",
    )


# --------------------------------------------------------------------------- #
# Provas
# --------------------------------------------------------------------------- #
async def _next_prova_order(session: AsyncSession, event_id: str) -> int:
    result = await session.execute(
        select(func.max(Prova.order_num)).where(Prova.event_id == event_id)
    )
    return int(result.scalar_one() or 0) + 1


async def _create_prova_record(
    session: AsyncSession, event_id: str, payload: ProvaCreate
) -> Prova:
    if payload.order_num is not None:
        order_num = payload.order_num
        result = await session.execute(
            select(Prova.id).where(
                Prova.event_id == event_id, Prova.order_num == order_num
            )
        )
        if result.first() is not None:
            raise HTTPException(status_code=400, detail="order_num_duplicado")
    else:
        order_num = await _next_prova_order(session, event_id)

    prova = Prova(
        event_id=event_id,
        name=payload.name,
        order_num=order_num,
        stroke=payload.stroke,
        distance_m=payload.distance_m,
        category=payload.category,
        naipe=payload.naipe,
        consolidate_results=payload.consolidate_results,
        classification_criterion=payload.classification_criterion,
        status="scheduled",
        created_at=time.time(),
    )
    session.add(prova)
    return prova


@app.post("/api/events/{event_id}/provas", status_code=201)
async def create_prova(
    event_id: str,
    payload: ProvaCreate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _heat_guard(f"event:{event_id}"):
        session.expire_all()
        await _get_event(session, event_id)
        prova = await _create_prova_record(session, event_id, payload)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=400, detail="order_num_duplicado")
        await session.refresh(prova)
    await _broadcast_server_status()
    return await _prova_payload(session, prova)


@app.get("/api/events/{event_id}/provas")
async def list_provas(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_event(session, event_id)
    result = await session.execute(
        select(Prova)
        .where(Prova.event_id == event_id)
        .order_by(Prova.order_num)
    )
    return await _provas_payload(
        session, list(result.scalars().all()), include_heats=True
    )


@app.get("/api/provas/{prova_id}")
async def get_prova(
    prova_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    prova = await _get_prova(session, prova_id)
    return await _prova_payload(session, prova)


@app.patch("/api/provas/{prova_id}")
async def update_prova(
    prova_id: str,
    payload: ProvaUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    prova = await _get_prova(session, prova_id)
    async with _heat_guard(f"event:{prova.event_id}"):
        session.expire_all()
        prova = await _get_prova(session, prova_id)
        heats = await _prova_heats(session, prova.id)
        started = any(heat.status != "scheduled" for heat in heats)
        data = payload.model_dump(exclude_unset=True)
        operational = {
            "order_num",
            "consolidate_results",
            "classification_criterion",
            "distance_m",
        }
        if started and operational & set(data):
            raise HTTPException(status_code=409, detail="prova_ja_iniciada")

        new_order = data.get("order_num")
        if new_order is not None and new_order != prova.order_num:
            result = await session.execute(
                select(Prova.id).where(
                    Prova.event_id == prova.event_id,
                    Prova.order_num == new_order,
                    Prova.id != prova.id,
                )
            )
            if result.first() is not None:
                raise HTTPException(
                    status_code=400, detail="order_num_duplicado"
                )
        for field, value in data.items():
            setattr(prova, field, value)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=400, detail="order_num_duplicado")
        await session.refresh(prova)
        await _sync_prova_status(session, prova.id)
        await session.commit()
        await session.refresh(prova)
        payload_out = await _prova_payload(session, prova)
    await manager.broadcast(_prova_state_message(payload_out))
    return payload_out


@app.put("/api/events/{event_id}/provas/order")
async def reorder_provas(
    event_id: str,
    payload: OrderIdsRequest,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Reordena todas as provas do evento em uma unica transacao."""
    async with _heat_guard(f"event:{event_id}"):
        session.expire_all()
        await _get_event(session, event_id)
        result = await session.execute(
            select(Prova).where(Prova.event_id == event_id)
        )
        provas = list(result.scalars().all())
        _validate_reorder_ids(payload.ids, {prova.id for prova in provas})
        if any(prova.status != "scheduled" for prova in provas):
            raise HTTPException(status_code=409, detail="prova_ja_iniciada")

        # Desloca temporariamente para liberar 1..N sem violar o indice unico.
        offset = 100000
        await session.execute(
            update(Prova)
            .where(Prova.event_id == event_id)
            .values(order_num=Prova.order_num + offset),
            execution_options={"synchronize_session": False},
        )
        session.expire_all()
        for index, prova_id in enumerate(payload.ids):
            prova = await session.get(Prova, prova_id)
            prova.order_num = index + 1
        await session.commit()

        result = await session.execute(
            select(Prova)
            .where(Prova.event_id == event_id)
            .order_by(Prova.order_num)
        )
        provas = list(result.scalars().all())
        payloads = await _provas_payload(
            session, provas, include_heats=True
        )

    for prova_payload in payloads:
        await manager.broadcast(_prova_state_message(prova_payload))
    return payloads


@app.delete("/api/provas/{prova_id}", status_code=204)
async def delete_prova(
    prova_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    prova = await _get_prova(session, prova_id)
    async with _heat_guard(f"event:{prova.event_id}"):
        session.expire_all()
        prova = await _get_prova(session, prova_id)
        heats = await _prova_heats(session, prova.id)
        if any(heat.status != "scheduled" for heat in heats):
            raise HTTPException(
                status_code=409, detail="prova_possui_baterias_iniciadas"
            )
        heat_ids = [heat.id for heat in heats]
        if heat_ids:
            lane_ids = select(HeatLane.id).where(
                HeatLane.heat_id.in_(heat_ids)
            )
            await session.execute(
                delete(LapEvent).where(LapEvent.lane_id.in_(lane_ids))
            )
            await session.execute(
                delete(HeatLane).where(HeatLane.heat_id.in_(heat_ids))
            )
            await session.execute(delete(Heat).where(Heat.id.in_(heat_ids)))
        await session.delete(prova)
        await session.commit()
    await _broadcast_server_status()


@app.get("/api/provas/{prova_id}/classification")
async def get_prova_classification(
    prova_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    prova = await _get_prova(session, prova_id)
    return await _classification_payload(session, prova)


@app.post("/api/provas/{prova_id}/heats", status_code=201)
async def create_heat_in_prova(
    prova_id: str,
    payload: HeatCreate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    if payload.heat_type == "bateria" and payload.distance_m is None:
        raise HTTPException(status_code=400, detail="distance_m_obrigatorio")
    if payload.heat_type == "maratona" and payload.duration_s is None:
        raise HTTPException(status_code=400, detail="duration_s_obrigatorio")

    async with _heat_guard(f"prova:{prova_id}"):
        session.expire_all()
        prova = await _get_prova(session, prova_id)
        if payload.order_num is not None:
            order_num = payload.order_num
            result = await session.execute(
                select(Heat.id).where(
                    Heat.prova_id == prova_id,
                    Heat.order_num == order_num,
                )
            )
            if result.first() is not None:
                raise HTTPException(
                    status_code=400, detail="order_num_duplicado"
                )
        else:
            result = await session.execute(
                select(func.max(Heat.order_num)).where(
                    Heat.prova_id == prova_id
                )
            )
            order_num = int(result.scalar_one() or 0) + 1

        heat = Heat(
            event_id=prova.event_id,
            prova_id=prova_id,
            name=payload.name,
            order_num=order_num,
            heat_type=payload.heat_type,
            distance_m=payload.distance_m,
            duration_s=payload.duration_s,
            status="scheduled",
        )
        session.add(heat)
        await _sync_prova_status(session, prova_id)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=400, detail="order_num_duplicado")
        await session.refresh(heat)
        await session.refresh(prova)

    await _broadcast_server_status()
    await manager.broadcast(
        _prova_state_message(await _prova_payload(session, prova))
    )
    return await _heat_payload(session, heat)


@app.get("/api/provas/{prova_id}/heats")
async def list_heats_in_prova(
    prova_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_prova(session, prova_id)
    heats = await _prova_heats(session, prova_id)
    return [await _heat_payload(session, heat) for heat in heats]


# --------------------------------------------------------------------------- #
# Baterias (heats)
# --------------------------------------------------------------------------- #
@app.get("/api/events/{event_id}/heats")
async def list_heats(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_event(session, event_id)
    result = await session.execute(
        select(Heat)
        .join(Prova, Heat.prova_id == Prova.id)
        .where(Heat.event_id == event_id)
        .order_by(Prova.order_num, Heat.order_num)
    )
    return [
        await _heat_payload(session, heat)
        for heat in result.scalars().all()
    ]


@app.patch("/api/heats/{heat_id}")
async def update_heat(
    heat_id: str,
    payload: HeatUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    heat = await _get_heat(session, heat_id)
    async with _heat_guard(f"prova:{heat.prova_id}"):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status not in ("scheduled", "ready_check"):
            raise HTTPException(status_code=409, detail="prova_ja_iniciada")
        data = payload.model_dump(exclude_unset=True)
        new_order = data.get("order_num")
        if new_order is not None and new_order != heat.order_num:
            result = await session.execute(
                select(Heat.id).where(
                    Heat.prova_id == heat.prova_id,
                    Heat.order_num == new_order,
                    Heat.id != heat.id,
                )
            )
            if result.first() is not None:
                raise HTTPException(
                    status_code=400, detail="order_num_duplicado"
                )
        for field, value in data.items():
            setattr(heat, field, value)
        await _sync_prova_status(session, heat.prova_id)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=400, detail="order_num_duplicado")
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        return await _heat_payload(session, heat)


@app.put("/api/provas/{prova_id}/heats/order")
async def reorder_heats(
    prova_id: str,
    payload: OrderIdsRequest,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Reordena todas as baterias de uma prova em uma unica transacao."""
    async with _heat_guard(f"prova:{prova_id}"):
        session.expire_all()
        prova = await _get_prova(session, prova_id)
        result = await session.execute(
            select(Heat).where(Heat.prova_id == prova_id)
        )
        heats = list(result.scalars().all())
        _validate_reorder_ids(payload.ids, {heat.id for heat in heats})
        if any(
            heat.status not in ("scheduled", "ready_check")
            for heat in heats
        ):
            raise HTTPException(status_code=409, detail="prova_ja_iniciada")

        offset = 100000
        await session.execute(
            update(Heat)
            .where(Heat.prova_id == prova_id)
            .values(order_num=Heat.order_num + offset),
            execution_options={"synchronize_session": False},
        )
        session.expire_all()
        for index, heat_id in enumerate(payload.ids):
            heat = await session.get(Heat, heat_id)
            heat.order_num = index + 1
        await session.commit()

        await session.refresh(prova)
        payload_out = await _prova_payload(session, prova)

    await manager.broadcast(_prova_state_message(payload_out))
    return payload_out["heats"]


@app.delete("/api/heats/{heat_id}", status_code=204)
async def delete_heat(
    heat_id: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    heat = await _get_heat(session, heat_id)
    prova_id = heat.prova_id
    async with _heat_guard(f"prova:{prova_id}"):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status != "scheduled":
            raise HTTPException(
                status_code=409, detail="prova_nao_esta_scheduled"
            )
        lane_ids = select(HeatLane.id).where(HeatLane.heat_id == heat_id)
        await session.execute(
            delete(LapEvent).where(LapEvent.lane_id.in_(lane_ids))
        )
        await session.execute(
            delete(HeatLane).where(HeatLane.heat_id == heat_id)
        )
        await session.delete(heat)
        await session.flush()
        await _sync_prova_status(session, prova_id)
        await session.commit()
        prova = await session.get(Prova, prova_id)
        payload_out = (
            _prova_state_message(await _prova_payload(session, prova))
            if prova is not None
            else None
        )
    await _broadcast_server_status()
    if payload_out is not None:
        await manager.broadcast(payload_out)


@app.post("/api/heats/{heat_id}/open-ready-check")
async def open_ready_check(
    heat_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status not in ("scheduled", "ready_check"):
            raise HTTPException(status_code=409, detail="prova_nao_esta_scheduled")
        heat.status = "ready_check"
        await _sync_prova_status(session, heat.prova_id)
        await session.commit()
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        return await _heat_payload(session, heat)


@app.post("/api/heats/{heat_id}/start")
async def start_heat(
    heat_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        direct_start = heat.status == "scheduled" and heat.heat_type == "maratona"
        if heat.status != "ready_check" and not direct_start:
            raise HTTPException(
                status_code=400, detail="prova_nao_esta_em_ready_check"
            )

        lanes = await _heat_lanes(session, heat.id)
        participants = _participant_lanes(lanes)
        if not participants:
            raise HTTPException(status_code=400, detail="sem_participantes")
        if not direct_start:
            pending = [
                lane.lane_number for lane in participants if lane.status != "ready"
            ]
            if pending:
                listed = ", ".join(str(number) for number in pending)
                raise HTTPException(
                    status_code=400, detail=f"raias_pendentes: {listed}"
                )

        started_at = time.time()
        heat.status = "active"
        heat.started_at = started_at
        heat.finished_at = None
        for lane in participants:
            lane.status = "active"
        _anchor_heat(heat)
        _log_action(
            session,
            action="start",
            received_at=started_at,
            effective_ts=started_at,
            event_id=heat.event_id,
            heat_id=heat.id,
            source_ip=_client_ip(request),
        )
        await _sync_prova_status(session, heat.prova_id)
        await session.commit()
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        await _broadcast_server_status()
        return await _heat_payload(session, heat)


@app.post("/api/heats/{heat_id}/abort")
async def abort_heat(
    heat_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status not in ("ready_check", "active"):
            raise HTTPException(status_code=409, detail="prova_nao_esta_ativa")
        now = time.time()
        heat.status = "scheduled"
        heat.started_at = None
        heat.finished_at = None
        _drop_anchor(heat.id)
        result = await session.execute(
            update(HeatLane)
            .where(HeatLane.heat_id == heat.id, HeatLane.status == "active")
            .values(status="ready")
        )
        _log_action(
            session,
            action="abort",
            received_at=now,
            effective_ts=now,
            event_id=heat.event_id,
            heat_id=heat.id,
            source_ip=_client_ip(request),
        )
        await _sync_prova_status(session, heat.prova_id)
        await session.commit()
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        await _broadcast_server_status()
        return await _heat_payload(session, heat)


@app.post("/api/heats/{heat_id}/finish")
async def finish_heat(
    heat_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status == "finished":
            return await _heat_payload(session, heat)
        if heat.status == "scheduled":
            raise HTTPException(status_code=409, detail="prova_nao_iniciada")
        now = time.time()
        heat.status = "finished"
        heat.finished_at = now
        _drop_anchor(heat.id)
        _log_action(
            session,
            action="finish_heat",
            received_at=now,
            effective_ts=now,
            event_id=heat.event_id,
            heat_id=heat.id,
            source_ip=_client_ip(request),
        )
        await _sync_prova_status(session, heat.prova_id)
        await session.commit()
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        await _broadcast_server_status()
        return await _heat_payload(session, heat)


# --------------------------------------------------------------------------- #
# Raias
# --------------------------------------------------------------------------- #
@app.post("/api/heats/{heat_id}/lanes")
async def configure_lanes(
    heat_id: str,
    payload: HeatLaneConfigRequest,
    session: AsyncSession = Depends(get_db),
) -> dict:
    numbers = [item.lane_number for item in payload.lanes]
    if len(numbers) != len(set(numbers)):
        raise HTTPException(status_code=400, detail="raias_duplicadas")

    async with _heat_guard(heat_id):
        session.expire_all()
        heat = await _get_heat(session, heat_id)
        if heat.status not in ("scheduled", "ready_check"):
            raise HTTPException(status_code=409, detail="prova_ja_iniciada")

        existing = {
            lane.lane_number: lane for lane in await _heat_lanes(session, heat.id)
        }
        for item in payload.lanes:
            athlete = None
            if item.athlete_id is not None:
                athlete = await session.get(Athlete, item.athlete_id)
                if athlete is None or athlete.event_id != heat.event_id:
                    raise HTTPException(
                        status_code=404, detail="atleta_nao_encontrado"
                    )
            else:
                if item.team_id is not None:
                    team = await session.get(Team, item.team_id)
                    if team is None or team.event_id != heat.event_id:
                        raise HTTPException(
                            status_code=404, detail="equipe_nao_encontrada"
                        )
            participant_name = (
                athlete.name if athlete else item.participant_name
            )
            team_id = athlete.team_id if athlete else item.team_id
            lane = existing.get(item.lane_number)
            if lane is None:
                lane = HeatLane(
                    heat_id=heat.id,
                    lane_number=item.lane_number,
                    participant_name=participant_name,
                    athlete_id=item.athlete_id,
                    team_id=team_id,
                    status="assigned",
                )
                session.add(lane)
            else:
                lane.participant_name = participant_name
                lane.athlete_id = item.athlete_id
                lane.team_id = team_id
                lane.status = "assigned"
        await session.commit()
        await session.refresh(heat)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        return await _heat_payload(session, heat)


@app.patch("/api/lanes/{lane_id}")
async def update_lane(
    lane_id: str,
    payload: LaneUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    lane = await _get_lane(session, lane_id)
    async with _heat_guard(lane.heat_id):
        session.expire_all()
        lane = await _get_lane(session, lane_id)
        heat = await _get_heat(session, lane.heat_id)
        if heat.status not in ("scheduled", "ready_check"):
            raise HTTPException(status_code=409, detail="prova_ja_iniciada")
        data = payload.model_dump(exclude_unset=True)
        if data.get("athlete_id") is not None:
            athlete = await session.get(Athlete, data["athlete_id"])
            if athlete is None or athlete.event_id != heat.event_id:
                raise HTTPException(
                    status_code=404, detail="atleta_nao_encontrado"
                )
            data["participant_name"] = athlete.name
            data["team_id"] = athlete.team_id
        if data.get("team_id") is not None:
            team = await session.get(Team, data["team_id"])
            if team is None or team.event_id != heat.event_id:
                raise HTTPException(status_code=404, detail="equipe_nao_encontrada")
        for field, value in data.items():
            setattr(lane, field, value)
        if data:
            lane.status = "assigned"
        await session.commit()
        await session.refresh(lane)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        return await _lane_payload(session, lane, heat)


@app.post("/api/lanes/{lane_id}/ready")
async def lane_ready(
    lane_id: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    lane = await _get_lane(session, lane_id)
    async with _heat_guard(lane.heat_id):
        session.expire_all()
        lane = await _get_lane(session, lane_id)
        heat = await _get_heat(session, lane.heat_id)
        if heat.status != "ready_check":
            raise HTTPException(
                status_code=400, detail="prova_nao_esta_em_ready_check"
            )
        lane.status = "ready"
        await session.commit()
        await session.refresh(lane)
        await _broadcast_heat(session, heat)
        await _broadcast_ready(session, heat)
        return await _lane_payload(session, lane, heat)


@app.post("/api/lanes/{lane_id}/finish")
async def lane_finish(
    lane_id: str,
    request: Request,
    payload: LaneActionRequest | None = None,
    session: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await _do_finish(
            session,
            lane_id,
            op_id=payload.op_id if payload else None,
            client_ts=payload.client_ts if payload else None,
            source_ip=_client_ip(request),
        )
    except LaneActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@app.post("/api/lanes/{lane_id}/lap")
async def lane_lap(
    lane_id: str,
    request: Request,
    payload: LaneActionRequest | None = None,
    session: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await _do_lap(
            session,
            lane_id,
            op_id=payload.op_id if payload else None,
            client_ts=payload.client_ts if payload else None,
            source_ip=_client_ip(request),
        )
    except LaneActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@app.post("/api/lanes/{lane_id}/dq")
async def lane_dq(
    lane_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    lane = await _get_lane(session, lane_id)
    async with _heat_guard(lane.heat_id):
        session.expire_all()
        lane = await _get_lane(session, lane_id)
        heat = await _get_heat(session, lane.heat_id)
        if heat.status != "active":
            raise HTTPException(status_code=400, detail="prova_nao_ativa")
        now = time.time()
        lane.status = "dq"
        all_finished = await _maybe_finish_heat(session, heat)
        _log_action(
            session,
            action="dq",
            received_at=now,
            effective_ts=now,
            event_id=heat.event_id,
            heat_id=heat.id,
            lane_id=lane.id,
            source_ip=_client_ip(request),
        )
        await session.commit()
        await session.refresh(lane)
        await _broadcast_heat(session, heat)
        if all_finished:
            await _broadcast_server_status()
        return await _lane_payload(session, lane, heat)


@app.delete("/api/lanes/{lane_id}/lap/last")
async def undo_last_lap(
    lane_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    lane = await _get_lane(session, lane_id)
    async with _heat_guard(lane.heat_id):
        session.expire_all()
        lane = await _get_lane(session, lane_id)
        heat = await _get_heat(session, lane.heat_id)
        result = await session.execute(
            select(LapEvent)
            .where(LapEvent.lane_id == lane_id, LapEvent.is_undo.is_(False))
            .order_by(LapEvent.recorded_at.desc())
            .limit(1)
        )
        event = result.scalars().first()
        if event is None:
            raise HTTPException(status_code=404, detail="nenhum_lap")
        now = time.time()
        if now - event.recorded_at >= 30.0:
            raise HTTPException(status_code=400, detail="fora_do_prazo")
        event.is_undo = True
        if lane.status == "active":
            result = await session.execute(
                select(func.count(LapEvent.id)).where(
                    LapEvent.lane_id == lane.id, LapEvent.is_undo.is_(False)
                )
            )
            if int(result.scalar_one()) == 0:
                lane.status = "assigned"
        _log_action(
            session,
            action="undo_lap",
            received_at=now,
            effective_ts=now,
            event_id=heat.event_id,
            heat_id=heat.id,
            lane_id=lane.id,
            source_ip=_client_ip(request),
            payload={
                "lap_event_id": event.id,
                "lap_number": event.lap_number,
                "recorded_at": event.recorded_at,
            },
        )
        await session.commit()
        await _broadcast_heat(session, heat)
        return {"status": "undone", "lane_id": lane.id}


# --------------------------------------------------------------------------- #
# WebSocket (broadcast global com escopos)
# --------------------------------------------------------------------------- #
async def _handle_ws_message(data: dict, websocket: WebSocket) -> None:
    message_type = data.get("type")
    if message_type == "ping":
        await manager.send_to(websocket, {"type": "pong"})
        return
    if message_type == "finish":
        handler = _do_finish
    elif message_type == "lap":
        handler = _do_lap
    else:
        return

    op_id = data.get("op_id")
    lane_id = data.get("lane_id")
    if not lane_id:
        await manager.send_to(
            websocket,
            {"type": "error", "op_id": op_id, "message": "lane_id_ausente"},
        )
        return
    source_ip = websocket.client.host if websocket.client else None
    async with database.AsyncSessionLocal() as session:
        try:
            result = await handler(
                session,
                lane_id,
                op_id=op_id,
                client_ts=data.get("client_ts"),
                source_ip=source_ip,
            )
            await manager.send_to(
                websocket,
                {
                    "type": "ack",
                    "op_id": op_id,
                    "ok": True,
                    "result": result,
                },
            )
        except LaneActionError as exc:
            await session.rollback()
            await manager.send_to(
                websocket,
                {
                    "type": "error",
                    "op_id": op_id,
                    "message": exc.detail,
                    "lane_id": lane_id,
                },
            )
        except Exception:
            await session.rollback()
            await manager.send_to(
                websocket,
                {
                    "type": "error",
                    "op_id": op_id,
                    "message": "erro_interno",
                    "lane_id": lane_id,
                },
            )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        await _broadcast_server_status()
        async with database.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Heat)
                .where(Heat.status.in_(("ready_check", "active")))
                .order_by(Heat.order_num)
            )
            active_heats = list(result.scalars().all())
            for heat in active_heats:
                await manager.send_to(
                    websocket,
                    _heat_state_message(await _heat_payload(session, heat)),
                )
            seen_provas: set[str] = set()
            for heat in active_heats:
                if heat.prova_id in seen_provas:
                    continue
                seen_provas.add(heat.prova_id)
                prova = await session.get(Prova, heat.prova_id)
                if prova is not None:
                    await manager.send_to(
                        websocket,
                        _prova_state_message(
                            await _prova_payload(session, prova)
                        ),
                    )
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                raise
            except Exception:
                await manager.send_to(
                    websocket, {"type": "error", "message": "mensagem_invalida"}
                )
                continue
            try:
                await _handle_ws_message(data, websocket)
            except Exception:
                await manager.send_to(
                    websocket, {"type": "error", "message": "erro_interno"}
                )
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await _broadcast_server_status()
    except Exception:
        manager.disconnect(websocket)
        await _broadcast_server_status()


# --------------------------------------------------------------------------- #
# Frontend estático (montado por último para não capturar /api e /ws)
# --------------------------------------------------------------------------- #
settings.logo_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/logos",
    StaticFiles(directory=str(settings.logo_dir)),
    name="logos",
)

_frontend_dir = settings.frontend_dir
if _frontend_dir.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_frontend_dir), html=True),
        name="frontend",
    )
