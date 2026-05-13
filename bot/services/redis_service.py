"""Optional Redis reliability helpers.

The production bot can run without Redis while deployment is being prepared.
When REDIS_URL and redis-py are available, RedisService provides cross-process
idempotency keys, locks, and simple rate counters. NullRedisService keeps unit
tests and local runs deterministic without network dependencies.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class NullRedisService:
    """In-memory fallback implementing the same async API as RedisService."""

    _keys: dict[str, float] = field(default_factory=dict)
    _locks: dict[str, float] = field(default_factory=dict)
    _counters: dict[str, tuple[int, float]] = field(default_factory=dict)

    def _purge(self) -> None:
        now = time.time()
        self._keys = {k: exp for k, exp in self._keys.items() if exp > now}
        self._locks = {k: v for k, v in self._locks.items() if (v[1] if isinstance(v, tuple) else v) > now}
        self._counters = {k: v for k, v in self._counters.items() if v[1] > now}

    async def mark_once(self, key: str, ttl_seconds: int) -> bool:
        self._purge()
        if key in self._keys:
            return False
        self._keys[key] = time.time() + ttl_seconds
        return True

    async def acquire_lock(self, key: str, ttl_seconds: int) -> bool:
        return await self.acquire_lock_value(key, "1", ttl_seconds)

    async def acquire_lock_value(self, key: str, value: str, ttl_seconds: int) -> bool:
        self._purge()
        if key in self._locks:
            return False
        self._locks[key] = (value, time.time() + ttl_seconds)
        return True

    async def release_lock(self, key: str) -> None:
        self._locks.pop(key, None)

    async def release_lock_value(self, key: str, value: str) -> None:
        current = self._locks.get(key)
        if current and current[0] == value:
            self._locks.pop(key, None)

    async def increment_rate(self, key: str, window_seconds: int) -> int:
        self._purge()
        now = time.time()
        count, expires = self._counters.get(key, (0, now + window_seconds))
        if expires <= now:
            count, expires = 0, now + window_seconds
        count += 1
        self._counters[key] = (count, expires)
        return count

    async def close(self) -> None:
        return None


class RedisService:
    """Redis-backed reliability primitives."""

    def __init__(self, url: str):
        try:
            import redis.asyncio as redis  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("redis package is not installed") from exc
        self.url = url
        self.client = redis.from_url(url, decode_responses=True)

    async def mark_once(self, key: str, ttl_seconds: int) -> bool:
        return bool(await self.client.set(key, "1", ex=ttl_seconds, nx=True))

    async def acquire_lock(self, key: str, ttl_seconds: int) -> bool:
        return await self.acquire_lock_value(key, "1", ttl_seconds)

    async def acquire_lock_value(self, key: str, value: str, ttl_seconds: int) -> bool:
        return bool(await self.client.set(f"lock:{key}", value, ex=ttl_seconds, nx=True))

    async def release_lock(self, key: str) -> None:
        await self.client.delete(f"lock:{key}")

    async def release_lock_value(self, key: str, value: str) -> None:
        script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        end
        return 0
        """
        await self.client.eval(script, 1, f"lock:{key}", value)

    async def increment_rate(self, key: str, window_seconds: int) -> int:
        pipe = self.client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        result = await pipe.execute()
        return int(result[0])

    async def close(self) -> None:
        await self.client.aclose()


def create_redis_service(url: Optional[str] = None):
    url = url if url is not None else os.getenv("REDIS_URL", "")
    if not url:
        logger.info("REDIS_URL is not set; using in-memory NullRedisService")
        return NullRedisService()
    try:
        return RedisService(url)
    except RuntimeError as exc:
        logger.warning("Redis unavailable (%s); using in-memory NullRedisService", exc)
        return NullRedisService()


redis_service = create_redis_service()
