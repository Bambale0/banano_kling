import pytest

from bot.services.generation_guard import GenerationLockGuard
from bot.services.redis_service import NullRedisService


@pytest.mark.asyncio
async def test_generation_lock_guard_prevents_concurrent_submit_and_releases():
    backend = NullRedisService()
    guard = GenerationLockGuard(backend)

    acquired = await guard.acquire(123)
    assert acquired is not None
    duplicate = await guard.acquire(123)
    assert duplicate is None

    await guard.release(acquired)
    assert await guard.acquire(123) is not None


@pytest.mark.asyncio
async def test_generation_lock_guard_uses_distinct_users():
    backend = NullRedisService()
    guard = GenerationLockGuard(backend)

    assert await guard.acquire(1) is not None
    assert await guard.acquire(2) is not None


@pytest.mark.asyncio
async def test_generation_lock_release_is_owner_token_checked():
    backend = NullRedisService()
    guard = GenerationLockGuard(backend, ttl_seconds=1)

    first = await guard.acquire(123)
    assert first is not None
    # Simulate expiry and a later request acquiring a new token.
    backend._locks.clear()
    second = await guard.acquire(123)
    assert second is not None

    await guard.release(first)
    assert await guard.acquire(123) is None

    await guard.release(second)
    assert await guard.acquire(123) is not None
