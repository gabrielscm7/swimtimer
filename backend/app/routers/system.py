import time

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..services.backup import backup_service
from ..services.broadcast import _active_heat_count, manager

START_TIME = time.time()

router = APIRouter()


@router.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": "2.4.0"}


@router.get("/api/time")
async def server_time() -> dict:
    return {"now": time.time()}


@router.get("/api/status")
async def server_status(session: AsyncSession = Depends(get_db)) -> dict:
    return {
        "uptime": time.time() - START_TIME,
        "connected_clients": manager.count,
        "active_heats": await _active_heat_count(session),
        **backup_service.status(),
    }
