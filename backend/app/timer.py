import asyncio
import contextlib
import time

from .ws_manager import ConnectionManager


class CompetitionTimer:
    def __init__(self) -> None:
        self.competition_id: str | None = None
        self.duration_s: int = 0
        self.manager: ConnectionManager | None = None
        self._task: asyncio.Task | None = None
        self._elapsed: float = 0.0
        self._run_started: float | None = None
        self._running: bool = False

    @property
    def is_running(self) -> bool:
        return self._running

    def elapsed(self) -> float:
        if self._running and self._run_started is not None:
            return self._elapsed + (time.time() - self._run_started)
        return self._elapsed

    def get_state(self) -> dict:
        elapsed = self.elapsed()
        remaining = max(0.0, self.duration_s - elapsed) if self.duration_s else 0.0
        return {
            "elapsed_s": int(elapsed),
            "remaining_s": int(remaining),
        }

    async def start(
        self,
        competition_id: str,
        duration_s: int,
        manager: ConnectionManager,
    ) -> None:
        if self.competition_id != competition_id:
            self._elapsed = 0.0
        self.competition_id = competition_id
        self.duration_s = duration_s
        self.manager = manager
        if self._running and self._task and not self._task.done():
            return
        self._run_started = time.time()
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def pause(self) -> None:
        if self._running and self._run_started is not None:
            self._elapsed += time.time() - self._run_started
        self._running = False
        self._run_started = None
        await self._cancel_task()

    async def reset(self) -> None:
        self._running = False
        self._run_started = None
        self._elapsed = 0.0
        self.duration_s = 0
        self.competition_id = None
        await self._cancel_task()

    async def _cancel_task(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def _run(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(1)
                if not self._running:
                    break
                state = self.get_state()
                if self.manager is not None:
                    await self.manager.broadcast({"type": "tick", **state})
                if self.duration_s and self.elapsed() >= self.duration_s:
                    self._elapsed = float(self.duration_s)
                    self._running = False
                    self._run_started = None
                    break
        except asyncio.CancelledError:
            raise
