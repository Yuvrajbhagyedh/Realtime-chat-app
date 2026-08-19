from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import redis.asyncio as redis

from app.config import settings

redis_client: Any = None

PRESENCE_TTL = 45
TYPING_TTL = 4
CHANNEL = "chat:events"


class MemoryPipeline:
    def __init__(self, store: "MemoryRedis") -> None:
        self._store = store
        self._ops: list[str] = []

    def exists(self, key: str) -> "MemoryPipeline":
        self._ops.append(key)
        return self

    async def execute(self) -> list[int]:
        return [await self._store.exists(key) for key in self._ops]


class MemoryPubSub:
    def __init__(self, store: "MemoryRedis") -> None:
        self._store = store
        self._queue: asyncio.Queue = asyncio.Queue()

    async def subscribe(self, _channel: str) -> None:
        self._store._subs.append(self._queue)

    async def unsubscribe(self, _channel: str) -> None:
        if self._queue in self._store._subs:
            self._store._subs.remove(self._queue)

    async def aclose(self) -> None:
        await self.unsubscribe("")

    async def listen(self):
        while True:
            yield await self._queue.get()


class MemoryRedis:
    """In-process stand-in used when Redis is not installed."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}
        self._subs: list[asyncio.Queue] = []

    def _get(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expires = item
        if expires is not None and time.monotonic() > expires:
            self._data.pop(key, None)
            return None
        return value

    async def ping(self) -> bool:
        return True

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._data[key] = (value, time.monotonic() + ttl)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def exists(self, key: str) -> int:
        return 1 if self._get(key) is not None else 0

    async def publish(self, _channel: str, message: str) -> None:
        for queue in list(self._subs):
            await queue.put({"type": "message", "data": message})

    def pipeline(self) -> MemoryPipeline:
        return MemoryPipeline(self)

    def pubsub(self) -> MemoryPubSub:
        return MemoryPubSub(self)

    async def aclose(self) -> None:
        self._subs.clear()
        self._data.clear()


async def init_redis() -> Any:
    global redis_client
    if settings.use_memory_broker:
        redis_client = MemoryRedis()
        return redis_client
    client = redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.ping()
        redis_client = client
    except Exception:
        await client.aclose()
        redis_client = MemoryRedis()
    return redis_client


def get_redis() -> Any:
    assert redis_client is not None
    return redis_client


async def close_redis() -> None:
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None


async def set_online(user_id: int) -> None:
    await get_redis().setex(f"presence:{user_id}", PRESENCE_TTL, "1")


async def set_offline(user_id: int) -> None:
    await get_redis().delete(f"presence:{user_id}")


async def is_online(user_id: int) -> bool:
    return bool(await get_redis().exists(f"presence:{user_id}"))


async def online_map(user_ids: list[int]) -> dict[int, bool]:
    if not user_ids:
        return {}
    pipe = get_redis().pipeline()
    for uid in user_ids:
        pipe.exists(f"presence:{uid}")
    results = await pipe.execute()
    return {uid: bool(flag) for uid, flag in zip(user_ids, results)}


async def set_typing(conversation_id: int, user_id: int) -> None:
    await get_redis().setex(f"typing:{conversation_id}:{user_id}", TYPING_TTL, "1")


async def publish(event: dict[str, Any]) -> None:
    await get_redis().publish(CHANNEL, json.dumps(event, default=str))
