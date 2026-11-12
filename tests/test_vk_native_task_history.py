"""Shared Mini App task history backed by native VK, not surrogate TG ID."""
import hashlib
import hmac
import json
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.shared_accounts.actor import PlatformActor
from bot.shared_accounts.native_tasks import VkNativeTasksAdapter, VkNativeTaskService
from bot.shared_accounts.vk_native import (
    fetch_native_vk_task_history,
)

SECRET = 'test-vk-native-task-secret'
ACTOR = PlatformActor(
    platform='vk', external_id=123, shared_account_id='vk-uuid',
    linked_platforms=('vk',), linked_telegram_id=None,
)
TELEGRAM_ACTOR = PlatformActor(
    platform='telegram', external_id=123, shared_account_id='tg-uuid',
    linked_platforms=('telegram',), linked_telegram_id=123,
)


def raw_task(task_id=9, *, model='native-kling'):
    return {'task_id': task_id, 'task_type': 'video', 'model': model,
            'status': 'completed', 'cost': 2.5,
            'result_url': 'https://media.example/video.mp4',
            'created_at': '2026-11-11 06:00:00'}


@pytest.mark.asyncio
async def test_native_vk_task_history_hmac_ownership_and_common_task_contract(monkeypatch):
    recorded = []

    async def history(request):
        body = await request.read()
        ts = request.headers['X-Internal-Timestamp']
        expected = hmac.new(SECRET.encode(), b'\n'.join([
            ts.encode(), b'POST', request.path.encode(), body,
        ]), hashlib.sha256).hexdigest()
        assert hmac.compare_digest(request.headers['X-Internal-Signature'], expected)
        assert abs(int(ts) - int(time.time())) <= 30
        assert request.path == '/internal/v1/miniapp/users/123/tasks/history'
        payload = json.loads(body)
        recorded.append(payload)
        if payload.get('cursor') == 9:
            return web.json_response({'ok': True, 'tasks': [raw_task(8)],
                                      'next_cursor': None, 'cursor_reset': False})
        return web.json_response({'ok': True, 'tasks': [raw_task(9)],
                                  'next_cursor': 9, 'cursor_reset': False})

    app = web.Application()
    app.router.add_post('/internal/v1/miniapp/users/123/tasks/history', history)
    async with TestClient(TestServer(app)) as client:
        monkeypatch.setenv('INTERNAL_API_SECRET', SECRET)
        monkeypatch.setenv('VK_NATIVE_INTERNAL_ORIGIN', f'http://127.0.0.1:{client.server.port}')
        service = VkNativeTaskService()
        first = await service.history(ACTOR)
        assert first['ok'] is True
        assert first['recent_tasks'][0]['task_id'] == 'vk:9'
        assert first['recent_tasks'][0]['type'] == 'video'
        assert first['recent_tasks'][0]['prompt_preview'] == ''
        assert first['next_cursor'] == 'vk:9'
        second = await service.history(ACTOR, 'vk:9')
        assert second['recent_tasks'][0]['task_id'] == 'vk:8'
        assert second['next_cursor'] is None
        assert recorded == [{}, {'cursor': 9}]
        with pytest.raises(TypeError):
            await service.history(ACTOR, 9)
        with pytest.raises(ValueError):
            await service.history(ACTOR, '9')
        with pytest.raises(ValueError):
            await service.history(ACTOR, 'tg:9')
        with pytest.raises(PermissionError):
            await service.history(TELEGRAM_ACTOR)
        assert len(recorded) == 2


@pytest.mark.asyncio
async def test_native_vk_task_detail_never_leaks_original_recipe_or_other_actor(monkeypatch):
    requests = []

    async def detail(request):
        payload = await request.json()
        requests.append((request.path, payload))
        if payload['task_id'] == 777:
            return web.json_response({'error':'task_not_found'}, status=404)
        return web.json_response({'ok':True, 'task':raw_task(payload['task_id'])})

    app = web.Application()
    app.router.add_post('/internal/v1/miniapp/users/123/tasks/detail', detail)
    async with TestClient(TestServer(app)) as client:
        monkeypatch.setenv('INTERNAL_API_SECRET', SECRET)
        monkeypatch.setenv('VK_NATIVE_INTERNAL_ORIGIN', f'http://127.0.0.1:{client.server.port}')
        svc = VkNativeTaskService()
        data = await svc.detail(ACTOR, 'vk:9')
        task = data['task']
        assert task['task_id']=='vk:9'
        assert task['prompt'] == ''
        assert task['prompt_hidden'] is True
        assert task['prompt_actions_allowed'] is False
        assert task['result_url'].endswith('/video.mp4')
        assert (await svc.detail(ACTOR, 'vk:777')) is None
        with pytest.raises(PermissionError):
            await svc.detail(TELEGRAM_ACTOR, 'vk:9')
        with pytest.raises(ValueError):
            await svc.detail(ACTOR, 'tg:9')
        assert requests == [
            ('/internal/v1/miniapp/users/123/tasks/detail', {'task_id': 9}),
            ('/internal/v1/miniapp/users/123/tasks/detail', {'task_id': 777}),
        ]


@pytest.mark.asyncio
async def test_partial_adapter_does_not_advertise_full_ui_capability(monkeypatch):
    adapter = VkNativeTasksAdapter()
    assert adapter.ready_operations == frozenset({'tasks'})
    assert 'bootstrap' not in adapter.ready_operations
    # No endpoint adapter may invent full readiness by omitting essential
    # video/Motion/payment/referral/gallery operations.
    from aiohttp import web

    from bot.shared_accounts.gateway import full_vk_adapter
    app = web.Application()
    app['vk_full_app_adapter'] = adapter
    monkeypatch.setenv('VK_FULL_APP_PARITY_ENABLED', '1')
    assert full_vk_adapter(app) is None


@pytest.mark.asyncio
async def test_native_vk_bridge_fails_closed_on_unexpected_payload(monkeypatch):
    app = web.Application()
    async def bad(_request):
        return web.json_response({'ok':True, 'tasks':[raw_task(1)],
                                  'next_cursor': True, 'cursor_reset':False})
    app.router.add_post('/internal/v1/miniapp/users/123/tasks/history', bad)
    async with TestClient(TestServer(app)) as client:
        monkeypatch.setenv('INTERNAL_API_SECRET', SECRET)
        monkeypatch.setenv('VK_NATIVE_INTERNAL_ORIGIN', f'http://127.0.0.1:{client.server.port}')
        with pytest.raises(RuntimeError, match='invalid'):
            await fetch_native_vk_task_history(123)

@pytest.mark.asyncio
async def test_linked_vk_session_native_tasks_never_fall_back_to_telegram(monkeypatch):
    """Linking Telegram must not switch the owner of native VK task reads."""
    from unittest.mock import AsyncMock

    from bot.shared_accounts import gateway

    linked_vk = PlatformActor(
        platform='vk', external_id=123, shared_account_id='linked',
        linked_platforms=('vk', 'telegram'), linked_telegram_id=987654,
    )
    resolver = AsyncMock(return_value=linked_vk)
    monkeypatch.setattr(gateway, 'resolve_platform_actor', resolver)
    monkeypatch.setenv('VK_NATIVE_TASKS_ENABLED', '1')
    monkeypatch.delenv('VK_FULL_APP_PARITY_ENABLED', raising=False)
    native = AsyncMock(return_value=web.json_response({'source': 'vk', 'tasks': []}))
    legacy = AsyncMock(return_value=web.json_response({'source': 'telegram'}))

    class Adapter:
        ready_operations = frozenset({'tasks'})
        handle = native

    app = web.Application(middlewares=[gateway.vk_miniapp_gateway('/mini-app')])
    app['vk_native_tasks_adapter'] = Adapter()
    app.router.add_post('/mini-app/api/task-history', legacy)
    async with TestClient(TestServer(app)) as client:
        response = await client.post('/mini-app/api/task-history', json={
            'init_data': 'vk_session:opaque-verified-token',
        })
        assert response.status == 200
        assert (await response.json())['source'] == 'vk'
    resolver.assert_awaited_once()
    native.assert_awaited_once()
    assert native.await_args.kwargs['actor'].external_id == 123
    legacy.assert_not_awaited()
