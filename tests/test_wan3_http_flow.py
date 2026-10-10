"""Signed Mini App HTTP -> actual SQLite lifecycle -> provider boundary contracts."""
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

from bot import database
from bot import wan3_prime_api as api
from bot.config import config
from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycle
from tests.test_wan3_prime_lifecycle import Prices, Probe, Provider, balance, user_actor


def signed_user(telegram_id, *, auth_date=None):
    fields = {'auth_date': str(int(time.time()) if auth_date is None else auth_date), 'user': json.dumps({'id': telegram_id})}
    key = hmac.new(b'WebAppData', config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields['hash'] = hmac.new(key, '\n'.join(f'{k}={v}' for k, v in sorted(fields.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario,media', [
    ('text', {}), ('first_frame', {'first_frame_url': 'https://owned.test/first.png'}),
    ('first_last', {'first_frame_url': 'https://owned.test/first.png', 'last_frame_url': 'https://owned.test/last.png'}),
    ('reference', {'reference_audio_urls': ['https://owned.test/only.mp3']}),
    ('edit', {'reference_video_urls': ['https://owned.test/source.mp4'], 'reference_image_urls': ['https://owned.test/subject.png']}),
    ('file', {'reference_file_urls': ['https://owned.test/brief.txt']}),
    ('link', {'reference_link_urls': ['https://owned.test/page']}),
])
async def test_all_modes_signed_quote_launch_idempotency_status_and_owner_recipe(scenario, media, monkeypatch):
    # Real signed authentication, real balance/reservation/task storage. The
    # upstream transport and read-only metadata probe are the only fakes.
    actor = await user_actor(100, telegram_id=971284001)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    await lifecycle.init_schema()
    app = web.Application()
    app['wan3_prime_lifecycle'] = lifecycle
    for path, handler in [('quote', api._quote_route), ('generate', api._launch_route), ('status', api._status_route), ('recipe', api._recipe_route)]:
        app.router.add_post('/' + path, api._http_boundary(handler))
    async with TestClient(TestServer(app)) as client:
        auth = {'init_data': signed_user(actor.telegram_id)}
        recipe = {'model': 'wan_3_prime', 'scenario': scenario, 'prompt': 'Make the requested video',
                  'duration': 5, 'resolution': '720P', 'seed': 0, 'audio': False, 'nsfw_checker': True, **media}
        before = await balance(actor.user_id)
        response = await client.post('/quote', json={**auth, 'recipe': recipe})
        assert response.status == 200, await response.text()
        quote = await response.json()
        assert provider.creates == 0 and await balance(actor.user_id) == before
        payload = {**auth, 'recipe': recipe, 'quote_hash': quote['quote_hash'], 'idempotency_key': 'http-mode-key'}
        result = await (await client.post('/generate', json=payload)).json()
        repeated = await (await client.post('/generate', json=payload)).json()
        assert result['status'] == 'accepted' and result['task_id'] == repeated['task_id']
        assert provider.creates == 1 and provider.recipe.scenario == scenario
        assert provider.recipe.seed == 0 and provider.recipe.audio is False
        assert provider.recipe.nsfw_checker is True
        state = await (await client.post('/status', json={**auth, 'task_id': result['task_id']})).json()
        assert state['provider_task_id'] == 'provider_1'
        restore = await (await client.post('/recipe', json={**auth, 'task_id': result['task_id']})).json()
        assert restore['recipe']['scenario'] == scenario
        invalid = await client.post('/status', json={'init_data': 'user=spoof', 'task_id': result['task_id']})
        assert invalid.status == 401
        malformed = await client.post('/status', data='[broken')
        assert malformed.status == 400
        assert (await malformed.json())['ok'] is False
        task = await database.get_task_by_id(result['task_id'])
        assert task.telegram_id == actor.telegram_id


@pytest.mark.asyncio
@pytest.mark.parametrize(('kind', 'filename', 'content_type'), [
    ('image', 'frame.png', 'image/png'),
    ('video', 'source.mp4', 'video/mp4'),
    ('audio', 'voice.mp3', 'audio/mpeg'),
    ('file', 'brief.pdf', 'application/pdf'),
])
async def test_real_multipart_chunk_accepts_frontend_start_fallback_for_all_upload_kinds(
    kind, filename, content_type, monkeypatch,
):
    actor = await user_actor(100, telegram_id=971284002)
    save_chunk = AsyncMock()
    monkeypatch.setattr(api.wan3_prime_storage, 'save_chunk', save_chunk)
    app = web.Application()
    app.router.add_post('/upload/chunk', api._http_boundary(api._upload_chunk_route))
    form = FormData()
    form.add_field('init_data', signed_user(actor.telegram_id))
    form.add_field('start_param_fallback', 'ref-safe')
    form.add_field('upload_id', f'{kind}-upload')
    form.add_field('index', '0')
    form.add_field('total', '1')
    form.add_field('chunk', b'synthetic-bytes', filename=filename, content_type=content_type)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            '/upload/chunk',
            data=form,
            headers={'X-Telegram-Init-Data': signed_user(actor.telegram_id)},
        )
        status = response.status
        response_text = await response.text()
    assert status == 200, response_text
    save_chunk.assert_awaited_once()
    saved_actor = save_chunk.await_args.args[0]
    assert saved_actor.user_id == actor.user_id
    assert saved_actor.telegram_id == actor.telegram_id
    assert save_chunk.await_args.kwargs == {
        'upload_id': f'{kind}-upload', 'index': 0, 'total': 1, 'chunk': b'synthetic-bytes',
    }


@pytest.mark.asyncio
@pytest.mark.parametrize('auth_kind', ['missing', 'expired', 'forged'])
async def test_upload_cancel_signed_http_rejects_missing_expired_or_forged_auth(auth_kind, monkeypatch):
    actor = await user_actor(100, telegram_id=971284101)
    cancel = AsyncMock()
    monkeypatch.setattr(api.wan3_prime_storage, 'cancel_upload', cancel)
    app = web.Application()
    app.router.add_post('/upload/cancel', api._http_boundary(api._upload_cancel_route))
    payload = {'upload_id': 'a' * 32, 'user_id': actor.user_id, 'telegram_id': actor.telegram_id}
    if auth_kind == 'expired':
        payload['init_data'] = signed_user(actor.telegram_id, auth_date=1)
    elif auth_kind == 'forged':
        payload['init_data'] = signed_user(actor.telegram_id).replace(str(actor.telegram_id), '971284102', 1)
    async with TestClient(TestServer(app)) as client:
        response = await client.post('/upload/cancel', json=payload)
        assert response.status == 401, await response.text()
        assert (await response.json())['code'] in {'auth_required', 'auth_invalid'}
    cancel.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_signed_http_init_replay_owner_cancel_and_foreign_ids_are_safe(monkeypatch, tmp_path):
    from bot.services import wan3_prime_storage as storage_module

    monkeypatch.setattr(storage_module, 'CHUNK_ROOT', tmp_path / 'chunks')
    monkeypatch.setattr(storage_module, 'UPLOAD_ROOT', tmp_path / 'references')
    owner = await user_actor(100, telegram_id=971284103)
    foreign = await user_actor(100, telegram_id=971284104)
    await api.wan3_prime_storage.init_schema()
    app = web.Application()
    app.router.add_post('/upload/init', api._http_boundary(api._upload_init_route))
    app.router.add_post('/upload/cancel', api._http_boundary(api._upload_cancel_route))
    init_body = {'upload_id': 'b' * 32, 'kind': 'file', 'filename': 'Файл.txt', 'size': 4, 'content_type': 'text/plain'}
    owner_auth = {'init_data': signed_user(owner.telegram_id)}
    foreign_auth = {'init_data': signed_user(foreign.telegram_id), 'user_id': owner.user_id, 'telegram_id': owner.telegram_id}
    async with TestClient(TestServer(app)) as client:
        first = await client.post('/upload/init', json={**init_body, **owner_auth})
        assert first.status == 200, await first.text()
        original = await first.json()
        repeated = await client.post('/upload/init', json={**init_body, **owner_auth})
        assert repeated.status == 200, await repeated.text()
        assert await repeated.json() == original
        collision = await client.post('/upload/init', json={**init_body, **foreign_auth})
        assert collision.status == 409
        assert (await collision.json())['code'] == 'upload_session_conflict'
        denied = await client.post('/upload/cancel', json={**foreign_auth, 'upload_id': init_body['upload_id']})
        unknown = await client.post('/upload/cancel', json={**foreign_auth, 'upload_id': 'c' * 32})
        assert denied.status == unknown.status == 200
        assert await denied.json() == await unknown.json() == {'ok': True, 'status': 'not_found'}
        async with database.db_backend.connect(database.DATABASE_PATH) as db:
            row = await (await db.execute('SELECT status, user_id FROM wan3_prime_upload_sessions WHERE upload_id = ?', (init_body['upload_id'],))).fetchone()
        assert row[0] == 'open' and int(row[1]) == owner.user_id
        for _ in range(2):
            cancelled = await client.post('/upload/cancel', json={**owner_auth, 'upload_id': init_body['upload_id']})
            assert cancelled.status == 200
            assert await cancelled.json() == {'ok': True, 'status': 'cancelled'}
        fenced = await client.post('/upload/init', json={**init_body, **owner_auth})
        assert fenced.status == 409
        assert (await fenced.json())['code'] == 'upload_session_conflict'
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        rows = await (await db.execute('SELECT status, user_id FROM wan3_prime_upload_sessions')).fetchall()
        media_count = await (await db.execute('SELECT COUNT(*) FROM wan3_prime_media')).fetchone()
    assert len(rows) == 1 and rows[0][0] == 'cancelled' and int(rows[0][1]) == owner.user_id
    assert media_count[0] == 0
    assert await balance(owner.user_id) == await balance(foreign.user_id) == 100

