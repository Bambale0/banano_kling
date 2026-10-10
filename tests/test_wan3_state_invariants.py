import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database
from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycle
from bot.services.wan3_prime_media import Wan3PrimeValidationError
from bot.services.wan3_prime_storage import wan3_prime_storage
from tests.test_wan3_prime_lifecycle import (
    Downloader,
    Prices,
    Probe,
    Provider,
    balance,
    body,
    user_actor,
)


@pytest.mark.asyncio
async def test_capacity_cannot_miss_a_concurrent_settlement(monkeypatch):
    from bot.services import wan3_prime_result_retention as retention

    monkeypatch.setenv('WAN3_RESULT_MAX_BYTES', '10')
    monkeypatch.setenv('WAN3_RESULT_GLOBAL_QUOTA_BYTES', '15')
    scanned = False
    def scan():
        nonlocal scanned
        scanned = True
        return 0
    async def query(*args):
        # The old task settles just after an early filesystem scan. Counting
        # reservations first must conservatively include its reserved output.
        return SimpleNamespace(fetchone=AsyncMock(return_value=(1 if scanned else 2,)))
    monkeypatch.setattr(retention, '_result_bytes', scan)
    with pytest.raises(Wan3PrimeValidationError) as error:
        await retention.assert_result_capacity(SimpleNamespace(execute=query))
    assert error.value.status == 503


@pytest.mark.asyncio
@pytest.mark.parametrize('canonical', [None, {'taskId': 'provider_1', 'state': 'waiting'}])
async def test_old_provider_task_has_operator_resolution_without_automatic_refund(monkeypatch, canonical):
    from bot.config import config
    from bot.services.wan3_prime_recovery import unresolved_operations

    actor = await user_actor(100)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    quote = await lifecycle.quote(actor, body())
    launched = await lifecycle.launch(actor, body(), quote, 'stalled-task')
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE wan3_prime_intents SET created_at = '2000-01-01' WHERE internal_task_id = ?", (launched['task_id'],))
        await db.commit()
    provider.get_task_status = AsyncMock(return_value=canonical)
    await lifecycle.reconcile_once(provider_task_id='provider_1')
    state = await lifecycle.status(actor, launched['task_id'])
    assert state['status'] == 'result_attention'
    assert state['error_code'] == 'provider_wait_timeout'
    assert await balance(actor.user_id) == 90 and provider.creates == 1
    assert launched['task_id'] in [item['internal_task_id'] for item in await unresolved_operations()]
    monkeypatch.setattr(config, 'is_admin', lambda value: value == 999999999)
    await lifecycle.resolve_unknown_refund(launched['task_id'], admin_telegram_id=999999999, reason='provider support confirmed permanently stalled')
    assert await balance(actor.user_id) == 100


@pytest.mark.asyncio
async def test_provider_reason_is_retained_privately_without_secrets():
    actor = await user_actor(100)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    quote = await lifecycle.quote(actor, body())
    launched = await lifecycle.launch(actor, body(), quote, 'diagnostic-reason')
    await lifecycle._terminal_failure(launched['task_id'], 'input_rejected',
        'Source image copyright rejected; Authorization: Bearer fake-secret-for-test https://private.example/ref.png?token=hidden')
    record = await lifecycle._intent(launched['task_id'])
    assert 'copyright rejected' in record['error_message']
    assert 'fake-secret-for-test' not in record['error_message']
    assert 'private.example' not in record['error_message']
    public = await lifecycle.status(actor, launched['task_id'])
    assert public['error_message'] == 'Generation failed. Reserve was refunded.'


@pytest.mark.asyncio
@pytest.mark.parametrize('scope', ['feed', 'profile'])
async def test_publication_keeps_result_pinned_until_copy_commits(tmp_path, monkeypatch, scope):
    from bot.handlers import publication_scope_compat
    from bot.services import feed_persist

    monkeypatch.chdir(tmp_path)
    actor = await user_actor(100)
    provider = Provider()
    path = Path('static/uploads/wan3_prime/results/publish-race.mp4')
    lifecycle = Wan3PrimeLifecycle(probe=Probe(file_duration=5), preset_manager=Prices(), transport=provider, downloader=Downloader(path))
    quote = await lifecycle.quote(actor, body())
    launched = await lifecycle.launch(actor, body(), quote, 'publish-race')
    provider.statuses['provider_1'] = {'taskId': 'provider_1', 'state': 'success', 'resultUrls': ['https://owned.test/file.mp4']}
    await lifecycle.reconcile_once(provider_task_id='provider_1')
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE generation_tasks SET completed_at = '2000-01-01' WHERE task_id = ?", (launched['task_id'],))
        await db.execute("UPDATE wan3_prime_intents SET delivery_status = 'delivered' WHERE internal_task_id = ?", (launched['task_id'],))
        await db.commit()
    copying, proceed = asyncio.Event(), asyncio.Event()
    async def persist(urls, **kwargs):
        copying.set()
        await proceed.wait()
        assert path.exists(), 'Result disappeared between publication read and persistence'
        return list(urls)
    monkeypatch.setattr(feed_persist, 'persist_feed_result_urls', persist)
    publisher = database.share_to_feed if scope == 'feed' else publication_scope_compat.share_to_profile
    publication = asyncio.create_task(publisher(launched['task_id'], actor.user_id))
    await asyncio.wait_for(copying.wait(), timeout=3)
    cleanup = asyncio.create_task(wan3_prime_storage.cleanup_expired())
    await asyncio.sleep(0.05)
    proceed.set()
    result, _ = await asyncio.wait_for(asyncio.gather(publication, cleanup), timeout=5)
    assert result and path.exists()
