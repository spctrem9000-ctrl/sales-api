import json
from typing import Dict, List
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        # Map company_id -> list of WebSockets
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, company_id: int):
        await websocket.accept()
        if company_id not in self.active_connections:
            self.active_connections[company_id] = []
        self.active_connections[company_id].append(websocket)

    def disconnect(self, websocket: WebSocket, company_id: int):
        if company_id in self.active_connections:
            if websocket in self.active_connections[company_id]:
                self.active_connections[company_id].remove(websocket)
            if not self.active_connections[company_id]:
                del self.active_connections[company_id]

    async def _send_with_timeout(self, connection: WebSocket, message_text: str, company_id: int):
        import asyncio
        try:
            await asyncio.wait_for(connection.send_text(message_text), timeout=3.0)
        except Exception:
            self.disconnect(connection, company_id)

    async def broadcast_to_company(self, company_id: int, message: dict):
        import asyncio
        if company_id not in self.active_connections:
            return
            
        connections = list(self.active_connections[company_id])
        print(f"Broadcasting to {len(connections)} active connections in company {company_id}: {message}")
        message_text = json.dumps(message)
        tasks = []
        for connection in connections:
            tasks.append(asyncio.create_task(self._send_with_timeout(connection, message_text, company_id)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

manager = ConnectionManager()
