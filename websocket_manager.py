import json
from typing import List
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def _send_with_timeout(self, connection: WebSocket, message_text: str):
        import asyncio
        try:
            await asyncio.wait_for(connection.send_text(message_text), timeout=3.0)
        except Exception:
            self.disconnect(connection)

    async def broadcast(self, message: dict):
        import asyncio
        print(f"Broadcasting to {len(self.active_connections)} active connections: {message}")
        message_text = json.dumps(message)
        tasks = []
        for connection in list(self.active_connections):
            tasks.append(asyncio.create_task(self._send_with_timeout(connection, message_text)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

manager = ConnectionManager()
