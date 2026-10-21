from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.services import redis_service as module


@pytest.mark.asyncio
async def test_cache_recovers_when_redis_was_unavailable_on_first_use(monkeypatch):
    client = SimpleNamespace(ping=AsyncMock(side_effect=[ConnectionError('offline'), True]), get=AsyncMock(return_value='cached'), aclose=AsyncMock())
    monkeypatch.setattr(module, 'redis', SimpleNamespace(from_url=lambda *a, **kw: client))
    service = module.RedisService()
    assert await service.get('synthetic') is None
    if hasattr(service, '_retry_at'):
        monkeypatch.setattr(service, '_retry_at', 0)
    assert await service.get('synthetic') == 'cached'
    assert client.ping.await_count == 2
