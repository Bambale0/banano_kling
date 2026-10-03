from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


@pytest.mark.asyncio
async def test_runtime_coexists_with_legacy_body_readers_and_rejects_banned_user(tmp_path, monkeypatch):
    from bot import database, miniapp
    from bot.config import config
    from bot.genjutsu.runtime import setup_genjutsu
    from bot.handlers.miniapp_regression_safety import install_miniapp_regression_safety

    monkeypatch.setattr(config, 'GENJUTSU_MEDIA_ROOT', str(tmp_path / 'private-media'))
    monkeypatch.setattr(config, 'GENJUTSU_PUBLIC_BASE_URL', '')
    monkeypatch.setattr(config, 'GENJUTSU_MEDIA_SIGNING_KEY', '')
    monkeypatch.setattr(config, 'HIGGSFIELD_API_KEY', '')
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(101, {})))
    banned = AsyncMock(return_value=False)
    monkeypatch.setattr(database, 'is_user_banned', banned)
    monkeypatch.setattr(config, 'is_admin', lambda uid: False)
    await database.get_or_create_user(101)
    install_miniapp_regression_safety()
    app = web.Application()
    app['bot'] = SimpleNamespace()
    setup_genjutsu(app)
    async def legacy(request):
        return web.json_response({'legacy': True})
    app.router.add_post('/mini-app/api/{tail:.*}', legacy)
    async with TestClient(TestServer(app)) as client:
        response = await client.post('/mini-app/api/genjutsu', json={'action': 'bootstrap', 'init_data': 'verified-by-test-seam'})
        assert response.status == 200
        body = await response.json()
        assert body['enabled'] is False
        assert body['configured'] is False
        assert set(body['catalog']) == {'motion_transfer', 'object_swap', 'restyle'}
        assert 'legacy' not in body
        banned.return_value = True
        response = await client.post('/mini-app/api/genjutsu', json={'action': 'bootstrap', 'init_data': 'verified-by-test-seam'})
        assert response.status == 403
        assert (await response.json())['code'] == 'user_banned'
        response = await client.post('/mini-app/api/genjutsu', json={'action': 'bootstrap'})
        assert response.status == 401
