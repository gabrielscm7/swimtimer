from datetime import datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..services import exports
from ..services.lookups import _get_event

router = APIRouter()


@router.get("/api/events/{event_id}/export/results.csv")
async def export_results_csv(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> Response:
    event = await _get_event(session, event_id)
    content = await exports.build_results_csv(session, event)
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="results-{event_id}.csv"'
        },
    )


@router.post("/api/events/{event_id}/export/bundle")
async def export_bundle(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> Response:
    event = await _get_event(session, event_id)
    content = await exports.build_bundle(session, event)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"swimtimer_{event_id[:8]}_{stamp}.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )
