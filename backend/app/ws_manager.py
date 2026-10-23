import asyncio

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        # Assinatura opcional por evento: None = recebe tudo (compat).
        self._subscriptions: dict[WebSocket, str | None] = {}
        self._lock = asyncio.Lock()

    @property
    def count(self) -> int:
        return len(self.active_connections)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        self._subscriptions[websocket] = None

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        self._subscriptions.pop(websocket, None)

    def subscribe(
        self, websocket: WebSocket, event_id: str | None
    ) -> None:
        if websocket in self.active_connections:
            self._subscriptions[websocket] = event_id or None

    def _matches(self, websocket: WebSocket, message: dict) -> bool:
        subscribed = self._subscriptions.get(websocket)
        if not subscribed:
            return True
        event_id = message.get("event_id")
        if not event_id:
            return True
        return event_id == subscribed

    async def send_to(self, websocket: WebSocket, message: dict) -> None:
        await websocket.send_json(message)

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            dead: list[WebSocket] = []
            for connection in list(self.active_connections):
                if not self._matches(connection, message):
                    continue
                try:
                    await connection.send_json(message)
                except Exception:
                    dead.append(connection)
            for connection in dead:
                self.disconnect(connection)
