import asyncio

from fastapi import WebSocket

from .naming import mask_names


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        # Assinatura opcional por evento: None = recebe tudo (compat).
        self._subscriptions: dict[WebSocket, str | None] = {}
        # Modo de exibicao para assinantes publicos ("initials" mascara).
        self._name_modes: dict[WebSocket, str | None] = {}
        self._send_locks: dict[WebSocket, asyncio.Lock] = {}
        self._lock = asyncio.Lock()

    @property
    def count(self) -> int:
        return len(self.active_connections)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        self._subscriptions[websocket] = None
        self._name_modes[websocket] = None
        self._send_locks[websocket] = asyncio.Lock()

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        self._subscriptions.pop(websocket, None)
        self._name_modes.pop(websocket, None)
        self._send_locks.pop(websocket, None)

    def subscribe(
        self,
        websocket: WebSocket,
        event_id: str | None,
        name_mode: str | None = None,
    ) -> None:
        if websocket in self.active_connections:
            self._subscriptions[websocket] = event_id or None
            self._name_modes[websocket] = (
                name_mode if event_id and name_mode == "initials" else None
            )

    def update_name_mode(self, event_id: str, name_mode: str) -> None:
        for websocket, subscribed in self._subscriptions.items():
            if subscribed == event_id:
                self._name_modes[websocket] = (
                    name_mode if name_mode == "initials" else None
                )

    def _transform(self, websocket: WebSocket, message: dict) -> dict:
        if self._name_modes.get(websocket) == "initials":
            return mask_names(message, "initials")
        return message

    def _matches(self, websocket: WebSocket, message: dict) -> bool:
        subscribed = self._subscriptions.get(websocket)
        if not subscribed:
            return True
        event_id = message.get("event_id")
        if not event_id:
            payload = message.get("payload")
            if isinstance(payload, dict):
                event_id = payload.get("event_id")
        if not event_id:
            return True
        return event_id == subscribed

    async def _send_one(
        self, websocket: WebSocket, message: dict
    ) -> None:
        lock = self._send_locks.get(websocket)
        if lock is None:
            raise RuntimeError("conexao_encerrada")
        async with lock:
            await asyncio.wait_for(
                websocket.send_json(self._transform(websocket, message)),
                timeout=5,
            )

    async def _send_guarded(
        self, websocket: WebSocket, message: dict
    ) -> WebSocket | None:
        try:
            await self._send_one(websocket, message)
            return None
        except Exception:
            return websocket

    async def send_to(self, websocket: WebSocket, message: dict) -> None:
        await self._send_one(websocket, message)

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            connections = [
                connection
                for connection in list(self.active_connections)
                if self._matches(connection, message)
            ]
            results = await asyncio.gather(
                *(
                    self._send_guarded(connection, message)
                    for connection in connections
                )
            )
            for connection in results:
                if connection is not None:
                    self.disconnect(connection)
