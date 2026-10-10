import base64
import hashlib
import hmac
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database, wan3_prime_api
from bot.config import config
from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycle
from tests.test_wan3_prime_lifecycle import (
    Downloader,
    Prices,
    Probe,
    Provider,
    balance,
    body,
    user_actor,
)


def headers_for(task_id, timestamp):
    digest = hmac.new(b'test-webhook-key', f'{task_id}.{timestamp}'.encode(), hashlib.sha256).digest()
    return {'X-Webhook-Timestamp': str(timestamp), 'X-Webhook-Signature': base64.b64encode(digest).decode()}


def test_unconfigured_callback_security_falls_back_to_polling_without_url_secrets(monkeypatch):
    monkeypatch.setenv('WAN3_CALLBACK_BASE_URL', 'https://callbacks.example.test')
    monkeypatch.delenv('WAN3_CALLBACK_QUERY_LOGS_REDACTED', raising=False)
    monkeypatch.setattr(config, 'KIE_WEBHOOK_HMAC_KEY', '')
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=Provider())
    assert lifecycle._callback_url('wan3_test', 'never-log-this-secret') is None
    monkeypatch.setattr(config, 'KIE_WEBHOOK_HMAC_KEY', 'test-webhook-key')
    url = lifecycle._callback_url('wan3_test', 'never-log-this-secret')
    assert url.endswith('?intent=wan3_test') and 'secret' not in url and 'nonce=' not in url


@pytest.mark.asyncio
async def test_signed_callback_http_rejects_unsigned_and_expired_before_polling(monkeypatch):
    monkeypatch.setattr(config, 'KIE_WEBHOOK_HMAC_KEY', 'test-webhook-key')
    monkeypatch.delenv('WAN3_CALLBACK_QUERY_LOGS_REDACTED', raising=False)
    actor = await user_actor(100)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    quote = await lifecycle.quote(actor, body())
    launched = await lifecycle.launch(actor, body(), quote, 'signed-callback')
    provider.get_task_status = AsyncMock(return_value={'taskId': 'provider_1', 'state': 'waiting'})
    app = web.Application()
    app['wan3_prime_lifecycle'] = lifecycle
    app.router.add_post('/callback', wan3_prime_api._http_boundary(wan3_prime_api._callback_route))
    payload = {'data': {'taskId': 'provider_1'}}
    async with TestClient(TestServer(app)) as client:
        url = '/callback?intent=' + launched['task_id']
        assert (await client.post(url, json=payload)).status == 403
        expired = await client.post(url, json=payload, headers=headers_for('provider_1', int(time.time()) - 3600))
        assert expired.status == 403
        provider.get_task_status.assert_not_awaited()
        valid = await client.post(url, json=payload, headers=headers_for('provider_1', int(time.time())))
        assert valid.status == 200
        provider.get_task_status.assert_awaited_once()
        replay = await client.post(url, json=payload, headers=headers_for('provider_1', int(time.time())))
        assert replay.status == 200
        provider.get_task_status.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('deferred', [False, True, 'transport_error', 'malformed', 'wrong_task', 'wrong_model'])
async def test_signed_callback_settles_late_success_after_wait_timeout_exactly_once(monkeypatch, deferred):
    monkeypatch.setattr(config, 'KIE_WEBHOOK_HMAC_KEY', 'test-webhook-key')
    actor = await user_actor(100)
    provider = Provider()
    output = Path('static/uploads/wan3_prime/results/test-late-callback-result.mp4')
    lifecycle = Wan3PrimeLifecycle(
        probe=Probe(file_duration=5), preset_manager=Prices(), transport=provider,
        downloader=Downloader(output),
    )
    quote = await lifecycle.quote(actor, body())
    launched = await lifecycle.launch(actor, body(), quote, 'late-signed-callback')
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE wan3_prime_intents SET created_at = '2000-01-01' WHERE internal_task_id = ?",
            (launched['task_id'],),
        )
        await db.commit()
    provider.get_task_status = AsyncMock(return_value={'taskId': 'provider_1', 'state': 'waiting'})
    try:
        await lifecycle.reconcile_once(provider_task_id='provider_1')
        assert (await lifecycle.status(actor, launched['task_id']))['status'] == 'result_attention'
        # Beyond the finite automatic polling window, a signed callback still
        # obtains canonical state and can settle the original task.
        assert await lifecycle.reconcile_once() == 0
        assert provider.get_task_status.await_count == 1
        provider.get_task_status.return_value = {
            'taskId': 'provider_1', 'state': 'success',
            'response': {'resultUrls': ['https://kie.example.com/late-callback.mp4']},
        }
        app = web.Application()
        app['wan3_prime_lifecycle'] = lifecycle
        app.router.add_post('/callback', wan3_prime_api._http_boundary(wan3_prime_api._callback_route))
        payload = {'data': {'taskId': 'provider_1'}}
        callback_headers = headers_for('provider_1', int(time.time()))
        if deferred:
            async with database.db_backend.connect(database.DATABASE_PATH) as db:
                await db.execute("UPDATE wan3_prime_intents SET next_attempt_at = '2999-01-01' WHERE internal_task_id = ?",
                    (launched['task_id'],))
                await db.commit()
        async with TestClient(TestServer(app)) as client:
            response = await client.post('/callback?intent=' + launched['task_id'], json=payload, headers=callback_headers)
            assert response.status == 200
            replay = await client.post('/callback?intent=' + launched['task_id'], json=payload, headers=callback_headers)
            assert replay.status == 200
            if deferred:
                # Replays are acknowledged without bypassing the stored backoff.
                assert provider.get_task_status.await_count == 1
                assert (await lifecycle.status(actor, launched['task_id']))['status'] == 'result_attention'
                async with database.db_backend.connect(database.DATABASE_PATH) as db:
                    await db.execute("UPDATE wan3_prime_intents SET next_attempt_at = '2000-01-01' WHERE internal_task_id = ?",
                        (launched['task_id'],))
                    await db.commit()
                # Invalid/unavailable canonical observations cannot consume the
                # only durable late-completion notification.
                if isinstance(deferred, str):
                    canonical = provider.get_task_status.return_value
                    if deferred == 'transport_error':
                        provider.get_task_status.side_effect = TimeoutError('temporary provider outage')
                    else:
                        provider.get_task_status.return_value = {
                            'malformed': None,
                            'wrong_task': {'taskId': 'unrelated', 'state': 'success'},
                            'wrong_model': {'taskId': 'provider_1', 'model': 'unrelated', 'state': 'success'},
                        }[deferred]
                    assert await lifecycle.reconcile_once() == 0
                    pending = await lifecycle._intent(launched['task_id'])
                    assert pending['provider_state'].startswith('callback_pending:')
                    provider.get_task_status.side_effect = None
                    provider.get_task_status.return_value = canonical
                    async with database.db_backend.connect(database.DATABASE_PATH) as db:
                        await db.execute("UPDATE wan3_prime_intents SET next_attempt_at = '2000-01-01' WHERE internal_task_id = ?",
                            (launched['task_id'],))
                        await db.commit()
                # The durable callback marker survives the age cutoff until due.
                assert await lifecycle.reconcile_once() == 1
        completed = await lifecycle.status(actor, launched['task_id'])
        assert completed['status'] == 'completed'
        assert completed['error_code'] is None and completed['error_message'] is None
        assert output.exists()
        assert provider.get_task_status.await_count == (3 if isinstance(deferred, str) else 2)
        assert provider.creates == 1
        assert await balance(actor.user_id) == 90
    finally:
        output.unlink(missing_ok=True)

