"""Signed Mini App HTTP -> actual SQLite lifecycle -> provider boundary contracts."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database
from bot import wan3_prime_api as api
from bot.config import config
from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycle
from tests.test_wan3_prime_lifecycle import Prices, Probe, Provider, balance, user_actor


def signed_user(telegram_id):
    fields = {'auth_date': str(int(time.time())), 'user': json.dumps({'id': telegram_id})}
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
