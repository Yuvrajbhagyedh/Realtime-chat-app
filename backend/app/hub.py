from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from app.redis_client import CHANNEL, get_redis, publish, set_offline, set_online


class Hub:
    """Local WebSocket registry plus Redis pub/sub fan-out across workers."""

    def __init__(self) -> None:
        self._sockets: dict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._listener: asyncio.Task | None = None

    async def start(self) -> None:
        self._listener = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._listener:
            self._listener.cancel()
            try:
                await self._listener
            except asyncio.CancelledError:
                pass

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._sockets[user_id].add(ws)
        await set_online(user_id)
        await publish({"type": "presence", "user_id": user_id, "status": "online"})

    async def disconnect(self, user_id: int, ws: WebSocket) -> None:
        async with self._lock:
            sockets = self._sockets.get(user_id)
            if sockets:
                sockets.discard(ws)
                if not sockets:
                    self._sockets.pop(user_id, None)
                    still_connected = False
                else:
                    still_connected = True
            else:
                still_connected = False
        if not still_connected:
            await set_offline(user_id)
            await publish({"type": "presence", "user_id": user_id, "status": "offline"})

    async def heartbeat(self, user_id: int) -> None:
        await set_online(user_id)

    async def send_to_users(self, user_ids: list[int], event: dict[str, Any]) -> None:
        event = {**event, "target_user_ids": user_ids}
        await publish(event)

    async def _emit_local(self, event: dict[str, Any]) -> None:
        targets = event.get("target_user_ids")
        async with self._lock:
            if targets is None:
                pairs = list(self._sockets.items())
            else:
                pairs = [(uid, self._sockets[uid]) for uid in targets if uid in self._sockets]
            sockets = [(uid, ws) for uid, group in pairs for ws in group]
        stale: list[tuple[int, WebSocket]] = []
        payload = json.dumps(event, default=str)
        for uid, ws in sockets:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append((uid, ws))
        for uid, ws in stale:
            await self.disconnect(uid, ws)

    async def _listen(self) -> None:
        pubsub = get_redis().pubsub()
        await pubsub.subscribe(CHANNEL)
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                await self._emit_local(event)
        finally:
            await pubsub.unsubscribe(CHANNEL)
            await pubsub.aclose()


hub = Hub()
