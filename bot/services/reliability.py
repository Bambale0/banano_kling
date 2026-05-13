"""Runtime reliability helpers for idempotency, locks, and rate limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bot.services.redis_service import redis_service


@dataclass
class RuntimeReliability:
    backend: Any

    async def mark_provider_event(self, provider: str, task_id: str, status: str, ttl_seconds: int = 7 * 24 * 3600) -> bool:
        return await self.backend.mark_once(f"provider:{provider}:{task_id}:{status}", ttl_seconds)

    async def mark_telegram_update(self, update_id: int, ttl_seconds: int = 24 * 3600) -> bool:
        return await self.backend.mark_once(f"telegram:update:{update_id}", ttl_seconds)

    async def acquire_generation_lock(self, telegram_id: int, ttl_seconds: int = 15 * 60) -> bool:
        return await self.backend.acquire_lock(f"generation:user:{telegram_id}", ttl_seconds)

    async def release_generation_lock(self, telegram_id: int) -> None:
        await self.backend.release_lock(f"generation:user:{telegram_id}")

    async def increment_user_rate(self, telegram_id: int, action: str, window_seconds: int = 60) -> int:
        return await self.backend.increment_rate(f"rate:{action}:user:{telegram_id}", window_seconds)


runtime_reliability = RuntimeReliability(redis_service)
