from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import engine, init_db
from .routers import (
    athletes,
    events,
    heats,
    lanes,
    provas,
    system,
    teams,
    ws,
)


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

app.include_router(system.router)
app.include_router(events.router)
app.include_router(teams.router)
app.include_router(athletes.router)
app.include_router(provas.router)
app.include_router(heats.router)
app.include_router(lanes.router)
app.include_router(ws.router)


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
