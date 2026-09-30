import asyncio

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_to(self, websocket: WebSocket, message: dict) -> None:
        await websocket.send_json(message)

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            dead: list[WebSocket] = []
            for connection in list(self.active_connections):
                try:
                    await connection.send_json(message)
                except Exception:
                    dead.append(connection)
            for connection in dead:
                self.disconnect(connection)
