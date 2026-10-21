from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.main import FallbackFSMStorage


@pytest.mark.asyncio
async def test_outage_writes_and_clear_survive_redis_recovery(monkeypatch):
    primary = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=2, user_id=2)
    untouched = StorageKey(bot_id=1, chat_id=3, user_id=3)
    await primary.set_state(key, 'old')
    await primary.set_data(key, {'old': True})
    await primary.set_data(untouched, {'keep': True})
    storage = FallbackFSMStorage(primary, MemoryStorage(), recovery_interval_seconds=0)
    real_set = primary.set_state
    monkeypatch.setattr(primary, 'set_state', AsyncMock(side_effect=ConnectionError('offline')))
    await storage.set_state(key, 'creating')
    await storage.set_data(key, {'prompt': 'new'})
    assert await storage.update_data(key, {'ratio': '1:1'}) == {'prompt': 'new', 'ratio': '1:1'}
    monkeypatch.setattr(primary, 'set_state', real_set)
    # Trigger recovery through the public storage contract; tests need no Redis.
    assert await storage.get_state(key) == 'creating'
    assert await primary.get_state(key) == 'creating'
    assert await primary.get_data(key) == {'prompt': 'new', 'ratio': '1:1'}
    assert await primary.get_data(untouched) == {'keep': True}
    await storage.set_state(key, None)
    await storage.set_data(key, {})
    assert await primary.get_state(key) is None
    assert await primary.get_data(key) == {}


@pytest.mark.asyncio
async def test_failed_recovery_retains_temporary_data(monkeypatch):
    primary = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=2, user_id=2)
    storage = FallbackFSMStorage(primary, MemoryStorage(), recovery_interval_seconds=0)
    real_set = primary.set_data
    monkeypatch.setattr(primary, 'set_data', AsyncMock(side_effect=ConnectionError('offline')))
    await storage.set_data(key, {'prompt': 'kept'})
    assert await storage.get_data(key) == {'prompt': 'kept'}
    monkeypatch.setattr(primary, 'set_data', real_set)
    assert await storage.get_data(key) == {'prompt': 'kept'}
    assert await primary.get_data(key) == {'prompt': 'kept'}


@pytest.mark.asyncio
async def test_fallback_update_preserves_existing_redis_fields_after_recovery(monkeypatch):
    primary = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=2, user_id=2)
    await primary.set_data(key, {'prompt': 'keep'})
    storage = FallbackFSMStorage(primary, MemoryStorage(), recovery_interval_seconds=0)
    update = primary.update_data
    monkeypatch.setattr(primary, 'update_data', AsyncMock(side_effect=ConnectionError('offline')))
    await storage.update_data(key, {'ratio': '1:1'})
    monkeypatch.setattr(primary, 'update_data', update)
    assert await storage.get_data(key) == {'prompt': 'keep', 'ratio': '1:1'}
    assert await primary.get_data(key) == {'prompt': 'keep', 'ratio': '1:1'}


@pytest.mark.asyncio
async def test_hung_primary_cannot_block_other_users_indefinitely(monkeypatch):
    import asyncio

    from bot.config import config
    monkeypatch.setattr(config, 'REDIS_OPERATION_TIMEOUT_SECONDS', 0.02, raising=False)
    primary = MemoryStorage()
    async def hang(*args, **kwargs):
        await asyncio.Event().wait()
    monkeypatch.setattr(primary, 'get_state', hang)
    storage = FallbackFSMStorage(primary, MemoryStorage())
    keys = [StorageKey(bot_id=1, chat_id=chat_id, user_id=chat_id) for chat_id in [2, 3]]
    assert await asyncio.wait_for(asyncio.gather(*(storage.get_state(key) for key in keys)), timeout=0.5) == [None, None]


@pytest.mark.asyncio
async def test_recovery_makes_incremental_progress_when_backlog_exceeds_timeout(monkeypatch):
    import asyncio

    from bot.config import config
    monkeypatch.setattr(config, 'REDIS_OPERATION_TIMEOUT_SECONDS', 0.025)
    primary = MemoryStorage()
    real_set = primary.set_data
    monkeypatch.setattr(primary, 'set_data', AsyncMock(side_effect=ConnectionError('offline')))
    storage = FallbackFSMStorage(primary, MemoryStorage(), recovery_interval_seconds=0)
    keys = [StorageKey(bot_id=1, chat_id=i, user_id=i) for i in range(3, 9)]
    for key in keys:
        await storage.set_data(key, {'prompt': str(key.user_id)})
    async def slow_set(key, data):
        await asyncio.sleep(0.01)
        await real_set(key, data)
    monkeypatch.setattr(primary, 'set_data', slow_set)
    for _ in range(10):
        assert await storage.get_data(keys[0]) == {'prompt': str(keys[0].user_id)}
    # This is the destination backend's public seam: the backlog actually drains.
    for key in keys:
        assert await primary.get_data(key) == {'prompt': str(key.user_id)}
