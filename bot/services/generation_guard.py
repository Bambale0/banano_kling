"""User-level generation submit locks.

These locks prevent rapid duplicate submits while a generation request is being
validated, charged, and handed off to an upstream provider. They intentionally
do not hold until provider completion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from bot.services.redis_service import redis_service


@dataclass(frozen=True)
class GenerationLock:
    key: str
    token: str


@dataclass
class GenerationLockGuard:
    backend: Any
    ttl_seconds: int = 15 * 60

    def key(self, telegram_id: int) -> str:
        return f"generation:user:{telegram_id}"

    async def acquire(self, telegram_id: int) -> GenerationLock | None:
        key = self.key(telegram_id)
        token = uuid4().hex
        acquire_with_value = getattr(self.backend, "acquire_lock_value", None)
        if acquire_with_value:
            acquired = await acquire_with_value(key, token, self.ttl_seconds)
        else:
            acquired = await self.backend.acquire_lock(key, self.ttl_seconds)
        if not acquired:
            return None
        return GenerationLock(key=key, token=token)

    async def release(self, lock: GenerationLock | int | None) -> None:
        if lock is None:
            return
        if isinstance(lock, GenerationLock):
            release_with_value = getattr(self.backend, "release_lock_value", None)
            if release_with_value:
                await release_with_value(lock.key, lock.token)
            else:
                await self.backend.release_lock(lock.key)
            return
        # Backward-compatible escape hatch for old call sites/tests.
        await self.backend.release_lock(self.key(lock))


generation_lock_guard = GenerationLockGuard(redis_service)
