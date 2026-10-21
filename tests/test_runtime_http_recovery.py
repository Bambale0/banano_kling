import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from psycopg import OperationalError

from bot.services.runtime_http import database_availability_middleware


@pytest.mark.asyncio
async def test_database_disconnect_returns_retryable_json_and_next_request_recovers():
    calls = 0
    async def bootstrap(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OperationalError('connection lost with sensitive database details')
        return web.json_response({'ok': True})
    app = web.Application(middlewares=[database_availability_middleware])
    app.router.add_post('/mini-app/api/bootstrap', bootstrap)
    async with TestClient(TestServer(app)) as client:
        first = await client.post('/mini-app/api/bootstrap')
        assert first.status == 503
        assert first.headers['Retry-After'] == '2'
        assert (await first.json())['code'] == 'database_unavailable'
        assert 'sensitive' not in await first.text()
        second = await client.post('/mini-app/api/bootstrap')
        assert second.status == 200
        assert calls == 2  # A POST is never implicitly replayed by middleware.


@pytest.mark.asyncio
async def test_real_bootstrap_translates_database_outage_without_returning_private_details(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot import miniapp
    monkeypatch.setattr(miniapp, '_miniapp_payload', AsyncMock(return_value={'init_data': 'synthetic'}))
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(side_effect=OperationalError('sensitive connection detail')))
    response = await miniapp.miniapp_bootstrap(SimpleNamespace(app={}))
    assert response.status == 503
    assert response.headers['Retry-After'] == '2'
    assert 'sensitive' not in response.text
