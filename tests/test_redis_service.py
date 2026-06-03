"""Unit tests for optional Redis reliability helpers."""

import pytest

from bot.services.redis_service import NullRedisService


@pytest.mark.asyncio
async def test_null_redis_idempotency_allows_first_and_blocks_second():
    service = NullRedisService()

    assert await service.mark_once("event:1", ttl_seconds=60) is True
    assert await service.mark_once("event:1", ttl_seconds=60) is False


@pytest.mark.asyncio
async def test_null_redis_lock_release():
    service = NullRedisService()

    assert await service.acquire_lock("user:1", ttl_seconds=60) is True
    assert await service.acquire_lock("user:1", ttl_seconds=60) is False
    await service.release_lock("user:1")
    assert await service.acquire_lock("user:1", ttl_seconds=60) is True
