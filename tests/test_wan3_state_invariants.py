import asyncio
from datetime import UTC, datetime, timedelta
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
async def test_late_ready_result_after_wait_timeout_is_saved_settled_and_delivered_once():
    actor = await user_actor(100)
    provider = Provider()
    output = Path('static/uploads/wan3_prime/results/test-late-timeout-result.mp4')
    lifecycle = Wan3PrimeLifecycle(
        probe=Probe(file_duration=5), preset_manager=Prices(), transport=provider,
        downloader=Downloader(output),
    )
    bot = SimpleNamespace(
        send_video=AsyncMock(return_value=SimpleNamespace(message_id=91)),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=92)),
    )
    lifecycle.telegram_bot = bot
    quote = await lifecycle.quote(actor, body())
    launched = await lifecycle.launch(actor, body(), quote, 'late-timeout-result')
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE wan3_prime_intents SET created_at = ? WHERE internal_task_id = ?",
            ((datetime.now(UTC) - timedelta(hours=3)).replace(tzinfo=None).isoformat(sep=" "), launched['task_id']),
        )
        await db.commit()
    provider.statuses['provider_1'] = {'taskId': 'provider_1', 'state': 'waiting'}
    try:
        await lifecycle.reconcile_once(provider_task_id='provider_1')
        assert (await lifecycle.status(actor, launched['task_id']))['status'] == 'result_attention'
        provider.statuses['provider_1'] = {
            'taskId': 'provider_1', 'state': 'success',
            'response': {'resultUrls': ['https://kie.example.com/late.mp4']},
        }
        assert await lifecycle.reconcile_once() == 1
        state = await lifecycle.status(actor, launched['task_id'])
        assert state['status'] == 'completed'
        assert state['error_code'] is None and state['error_message'] is None
        assert output.exists()
        assert bot.send_video.await_count == 1
        assert await balance(actor.user_id) == 90
        assert provider.creates == 1
        assert await lifecycle.reconcile_once(provider_task_id='provider_1') == 0
        assert bot.send_video.await_count == 1
        assert await balance(actor.user_id) == 90
        assert provider.creates == 1
    finally:
        output.unlink(missing_ok=True)


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



@pytest.mark.asyncio
async def test_timeout_attention_does_not_starve_active_tasks_and_ages_out(monkeypatch):
    monkeypatch.setenv('WAN3_PROVIDER_MAX_PENDING_SECONDS', '7200')
    monkeypatch.setenv('WAN3_ATTENTION_POLL_WINDOW_SECONDS', '86400')
    actor = await user_actor(100)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    quote = await lifecycle.quote(actor, body())
    tasks = []
    for index in range(3):
        provider.create_result = {'success': True, 'task_id': f'priority_{index}'}
        tasks.append(await lifecycle.launch(actor, body(), quote, f'priority-{index}'))
    now = datetime.now(UTC).replace(tzinfo=None)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        for index, age in ((0, timedelta(hours=3)), (1, timedelta(days=3))):
            await db.execute("UPDATE wan3_prime_intents SET status = 'result_attention', "
                "error_code = 'provider_wait_timeout', created_at = ?, updated_at = '2000-01-01', "
                "next_attempt_at = NULL WHERE internal_task_id = ?",
                ((now - age).isoformat(sep=' '), tasks[index]['task_id']))
        await db.commit()
    provider.get_task_status = AsyncMock(side_effect=lambda task_id: {'taskId': task_id, 'state': 'waiting'})
    await lifecycle.reconcile_once(limit=1)
    provider.get_task_status.assert_awaited_once_with('priority_2')
    provider.get_task_status.reset_mock()
    await lifecycle.reconcile_once(limit=50)
    provider.get_task_status.assert_awaited_once_with('priority_0')
    assert (await lifecycle.status(actor, tasks[1]['task_id']))['status'] == 'result_attention'
    assert await balance(actor.user_id) == 70 and provider.creates == 3
    # Expiration stops only background polling, never an explicit canonical check.
    provider.get_task_status.reset_mock()
    await lifecycle.reconcile_once(provider_task_id='priority_1')
    provider.get_task_status.assert_awaited_once_with('priority_1')
    assert await balance(actor.user_id) == 70 and provider.creates == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(('late_seconds', 'expected_delay'), [(60, 300), (2400, 1200), (20000, 3600)])
async def test_timeout_attention_backoff_grows_to_configured_ceiling(monkeypatch, late_seconds, expected_delay):
    monkeypatch.setenv('WAN3_PROVIDER_MAX_PENDING_SECONDS', '7200')
    monkeypatch.setenv('WAN3_ATTENTION_POLL_INITIAL_SECONDS', '300')
    monkeypatch.setenv('WAN3_ATTENTION_POLL_MAX_SECONDS', '3600')
    actor = await user_actor(100)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    quote = await lifecycle.quote(actor, body())
    launched = await lifecycle.launch(actor, body(), quote, 'attention-backoff')
    created = (datetime.now(UTC) - timedelta(seconds=7200 + late_seconds)).replace(tzinfo=None)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE wan3_prime_intents SET status = 'result_attention', "
            "error_code = 'provider_wait_timeout', created_at = ? WHERE internal_task_id = ?",
            (created.isoformat(sep=' '), launched['task_id']))
        await db.commit()
    provider.get_task_status = AsyncMock(return_value={'taskId': 'provider_1', 'state': 'waiting'})
    await lifecycle.reconcile_once()
    row = await lifecycle._intent(launched['task_id'])
    retry = row['next_attempt_at']
    if isinstance(retry, str):
        retry = datetime.fromisoformat(retry)
    remaining = (retry.replace(tzinfo=UTC) - datetime.now(UTC)).total_seconds()
    assert expected_delay - 5 <= remaining <= expected_delay + 5
    await lifecycle.reconcile_once()
    provider.get_task_status.assert_awaited_once()
    assert await balance(actor.user_id) == 90 and provider.creates == 1


@pytest.mark.asyncio
async def test_late_callback_marker_is_consumed_but_newer_inflight_callback_is_preserved():
    actor = await user_actor(100)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    quote = await lifecycle.quote(actor, body())
    launched = await lifecycle.launch(actor, body(), quote, 'callback-marker')
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE wan3_prime_intents SET status = 'result_attention', "
            "error_code = 'provider_wait_timeout', created_at = '2000-01-01', "
            "provider_state = 'callback_pending:old' WHERE internal_task_id = ?", (launched['task_id'],))
        await db.commit()
    old_poll_row = await lifecycle._intent(launched['task_id'])
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE wan3_prime_intents SET provider_state = 'callback_pending:new' "
            "WHERE internal_task_id = ?", (launched['task_id'],))
        await db.commit()
    await lifecycle._defer_provider(old_poll_row, state='waiting')
    assert (await lifecycle._intent(launched['task_id']))['provider_state'] == 'callback_pending:new'
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE wan3_prime_intents SET next_attempt_at = '2000-01-01' WHERE internal_task_id = ?",
            (launched['task_id'],))
        await db.commit()
    provider.get_task_status = AsyncMock(return_value={'taskId': 'provider_1', 'state': 'waiting'})
    await lifecycle.reconcile_once()
    assert (await lifecycle._intent(launched['task_id']))['provider_state'] == 'waiting'
    # No new callback: the old task cannot keep polling beyond the finite window.
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE wan3_prime_intents SET next_attempt_at = '2000-01-01' WHERE internal_task_id = ?",
            (launched['task_id'],))
        await db.commit()
    await lifecycle.reconcile_once()
    provider.get_task_status.assert_awaited_once()
    assert provider.creates == 1 and await balance(actor.user_id) == 90
