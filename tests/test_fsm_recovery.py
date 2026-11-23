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


@pytest.mark.asyncio
async def test_one_user_redis_failure_does_not_hide_healthy_users_state(monkeypatch):
    from bot.config import config

    monkeypatch.setattr(config, "REDIS_OPERATION_TIMEOUT_SECONDS", 0.05)
    primary = MemoryStorage()
    affected = StorageKey(bot_id=1, chat_id=99, user_id=99)
    healthy = StorageKey(bot_id=1, chat_id=100, user_id=100)
    await primary.set_state(healthy, "editing")
    real_get_state = primary.get_state

    async def single_user_failure(key):
        if key == affected:
            raise ConnectionError("per-user backend failure")
        return await real_get_state(key)

    monkeypatch.setattr(primary, "get_state", single_user_failure)
    storage = FallbackFSMStorage(primary, MemoryStorage(), recovery_interval_seconds=60)
    assert await storage.get_state(affected) is None
    assert await storage.get_state(healthy) == "editing"


@pytest.mark.asyncio
async def test_slow_primary_for_one_user_does_not_queue_another_user(monkeypatch):
    import asyncio

    from bot.config import config

    monkeypatch.setattr(config, "REDIS_OPERATION_TIMEOUT_SECONDS", 0.3)
    primary = MemoryStorage()
    slow = StorageKey(bot_id=1, chat_id=110, user_id=110)
    fast = StorageKey(bot_id=1, chat_id=111, user_id=111)
    await primary.set_state(fast, "ready")
    started = asyncio.Event()
    release = asyncio.Event()
    real_get_state = primary.get_state

    async def slow_get_state(key):
        if key == slow:
            started.set()
            await release.wait()
        return await real_get_state(key)

    monkeypatch.setattr(primary, "get_state", slow_get_state)
    storage = FallbackFSMStorage(primary, MemoryStorage())
    slow_task = asyncio.create_task(storage.get_state(slow))
    try:
        await asyncio.wait_for(started.wait(), timeout=0.15)
        assert await asyncio.wait_for(storage.get_state(fast), timeout=0.1) == "ready"
    finally:
        release.set()
        await asyncio.wait_for(slow_task, timeout=0.5)


@pytest.mark.asyncio
async def test_recovery_of_one_user_does_not_block_unaffected_user(monkeypatch):
    import asyncio

    from bot.config import config

    monkeypatch.setattr(config, "REDIS_OPERATION_TIMEOUT_SECONDS", 0.4)
    primary = MemoryStorage()
    affected = StorageKey(bot_id=1, chat_id=210, user_id=210)
    healthy = StorageKey(bot_id=1, chat_id=211, user_id=211)
    await primary.set_state(healthy, "saved")
    real_set_state = primary.set_state
    monkeypatch.setattr(primary, "set_state", AsyncMock(side_effect=ConnectionError("offline")))
    storage = FallbackFSMStorage(primary, MemoryStorage(), recovery_interval_seconds=0)
    await storage.set_state(affected, "temporary")

    entered = asyncio.Event()
    release = asyncio.Event()

    async def recovering_set_state(key, state):
        if key == affected:
            entered.set()
            await release.wait()
        await real_set_state(key, state)

    monkeypatch.setattr(primary, "set_state", recovering_set_state)
    recovering = asyncio.create_task(storage.get_state(affected))
    try:
        await asyncio.wait_for(entered.wait(), timeout=0.25)
        assert await asyncio.wait_for(storage.get_state(healthy), timeout=0.1) == "saved"
    finally:
        release.set()
        assert await asyncio.wait_for(recovering, timeout=0.5) == "temporary"
    assert await primary.get_state(affected) == "temporary"
