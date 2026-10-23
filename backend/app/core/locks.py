import asyncio
from contextlib import asynccontextmanager
from weakref import WeakValueDictionary

# Locks por prova: serializam as transições de estado de uma mesma bateria
# (finish/lap/dq/undo/start/abort/finish) evitando corridas de escrita no
# SQLite. O processo roda com um único worker uvicorn, então locks em memória
# são suficientes; a constraint única em lap_event é a rede de segurança.
_heat_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_heat_locks_guard = asyncio.Lock()


async def _get_heat_lock(heat_id: str) -> asyncio.Lock:
    async with _heat_locks_guard:
        lock = _heat_locks.get(heat_id)
        if lock is None:
            lock = asyncio.Lock()
            _heat_locks[heat_id] = lock
        return lock


@asynccontextmanager
async def _heat_guard(heat_id: str):
    lock = await _get_heat_lock(heat_id)
    async with lock:
        yield


# Locks por evento: serializam mudanças de tema e limpeza de imagens, evitando
# que saves concorrentes apaguem arquivos ainda referenciados por outra
# requisição. Mesma premissa de um único worker uvicorn dos locks de bateria.
_theme_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_theme_locks_guard = asyncio.Lock()


async def _get_theme_lock(event_id: str) -> asyncio.Lock:
    async with _theme_locks_guard:
        lock = _theme_locks.get(event_id)
        if lock is None:
            lock = asyncio.Lock()
            _theme_locks[event_id] = lock
        return lock


@asynccontextmanager
async def _theme_guard(event_id: str):
    lock = await _get_theme_lock(event_id)
    async with lock:
        yield
