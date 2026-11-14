"""Shared-account preview through the authenticated HTTP boundary."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import db as db_backend
from bot.shared_accounts.api import setup_shared_account_routes

ADMIN = 999999999
ROOT = '/mini-app/api/account-preview'


@pytest.fixture(autouse=True, params=['sqlite', 'postgres'])
async def account_database(request, monkeypatch, isolated_database):
    if request.param == 'sqlite':
        yield
        return
    dsn = os.environ.get('SHARED_ACCOUNTS_TEST_DSN')
    if not dsn:
        pytest.skip('requires explicitly isolated shared-account PostgreSQL')
    import psycopg

    from bot import postgres_aiosqlite
    from bot.handlers import trend_success_compat
    from bot.postgres_pool import close_postgres_pool

    parsed = urlsplit(dsn)
    assert parsed.hostname in {'localhost', '127.0.0.1'}
    assert parsed.path == '/banano_shared_test'
    schema = 'shared_preview_' + uuid4().hex
    await close_postgres_pool()
    # Each case creates a new schema: rerun the normal runtime compatibility DDL
    # instead of reusing the previous schema's process-wide readiness cache.
    monkeypatch.setattr(postgres_aiosqlite, '_HELPERS_READY', False)
    monkeypatch.setattr(postgres_aiosqlite, '_HELPERS_LOCK', None)
    # The process-wide trend success DDL cache belongs to a database schema.
    # Every test creates a brand-new PG schema; reusing this readiness marker
    # silently skips trend_generation_runs DDL on the second case.
    monkeypatch.setattr(trend_success_compat, '_SCHEMA_READY', False)
    monkeypatch.setattr(trend_success_compat, '_SCHEMA_LOCK', None)
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute('CREATE SCHEMA ' + schema)
        await connection.execute('SET search_path TO ' + schema)
        # Exercise the actual application bootstrap plus its compatibility layer,
        # whose startup also prepares legacy generation/credit columns.
        await connection.execute((Path(__file__).parents[1] / 'schema_postgres.sql').read_text())
    # Runtime JSON compatibility functions intentionally live in public.
    query = parse_qsl(parsed.query) + [('options', '-csearch_path=' + schema + ',public')]
    monkeypatch.setenv('DATABASE_URL', urlunsplit(parsed._replace(query=urlencode(query))))
    try:
        yield
    finally:
        await close_postgres_pool()
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute('DROP SCHEMA ' + schema + ' CASCADE')


def telegram_launch(user_id=ADMIN, timestamp=None):
    fields = {'auth_date': str(int(time.time()) if timestamp is None else timestamp), 'user': json.dumps({'id': user_id})}
    key = hmac.new(b'WebAppData', b'test:fake-bot-token', hashlib.sha256).digest()
    fields['hash'] = hmac.new(key, '\n'.join(f'{k}={v}' for k, v in sorted(fields.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@asynccontextmanager
async def preview_client():
    app = web.Application()
    setup_shared_account_routes(app, '/mini-app')
    async with TestClient(TestServer(app)) as client:
        yield client


async def test_vk_public_login_link_is_disabled_when_app_is_not_public():
    async with preview_client() as client:
        r = await client.get(ROOT + '/vk-login', allow_redirects=False)
        assert r.status == 404
        assert not r.headers.get('Location')
        assert r.headers.get('Cache-Control') == 'no-store'


async def test_vk_public_login_link_redirects_to_configured_app_without_trusting_request():
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        r = await client.get(ROOT + '/vk-login?next=https://evil.example/&vk_app_id=999',
                             allow_redirects=False)
        assert r.status == 303
        assert r.headers['Location'] == 'https://vk.com/app123'
        assert r.headers['Cache-Control'] == 'no-store'
        assert r.headers['Referrer-Policy'] == 'no-referrer'
        assert not r.cookies


async def test_vk_login_preserves_verified_bot_community_context():
    # The previous redirect lost the -community suffix. A signed VK app
    # launched from bot keyboard must not return in personal-developer mode.
    async with preview_client() as client:
        await enable(client, vk_app_id=123, vk_community_id=239915802)
        result = await client.get(
            ROOT + '/vk-login?vk_community_id=777&vk_app_id=999&next=https://evil.example/',
            allow_redirects=False,
        )
        assert result.status == 303
        assert result.headers['Location'] == 'https://vk.com/app123_-239915802'
        assert result.headers['Referrer-Policy'] == 'no-referrer'


async def test_vk_public_login_link_never_uses_an_unconfigured_app():
    async with preview_client() as client:
        await enable(client)
        r = await client.get(ROOT + '/vk-login', allow_redirects=False)
        assert r.status == 404
        assert not r.headers.get('Location')


async def test_preview_is_disabled_by_default():
    async with preview_client() as client:
        response = await client.post(ROOT + '/session', json={'platform': 'telegram', 'launch_data': telegram_launch()})
        assert response.status == 404
        assert response.headers['Cache-Control'] == 'no-store'


async def test_ordinary_user_cannot_enable_preview_with_client_admin_flag():
    async with preview_client() as client:
        response = await client.put(ROOT + '/settings', json={
            'init_data': telegram_launch(1001), 'is_admin': True,
            'expected_revision': 0, 'settings': {'enabled': True},
        })
        assert response.status == 403


async def test_unsigned_settings_request_is_rejected():
    async with preview_client() as client:
        response = await client.put(ROOT + '/settings', json={
            'telegram_id': ADMIN, 'expected_revision': 0, 'settings': {'enabled': True},
        })
        assert response.status == 401


async def enable(client, **settings):
    response = await client.put(ROOT + '/settings', json={
        'init_data': telegram_launch(), 'expected_revision': 0,
        'settings': {'enabled': True, **settings},
    })
    assert response.status == 200, await response.text()
    return (await response.json())['settings']


async def login(client, user_id=ADMIN):
    return await client.post(ROOT + '/session', json={
        'platform': 'telegram', 'launch_data': telegram_launch(user_id),
    })


async def test_admin_can_login_and_reuse_a_platform_neutral_account(monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_USERNAME', 'Neuromixx_bot')
    async with preview_client() as client:
        await enable(client)
        first = await login(client)
        assert first.status == 200
        session = await first.json()
        assert session['account']['identity'] == {'platform': 'telegram', 'external_id': ADMIN}
        token = session['session_token']
        headers = {'Authorization': 'Bearer ' + token}
        profile = await client.get(ROOT + '/me', headers=headers)
        assert profile.status == 200
        profile_data = await profile.json()
        assert profile_data['account']['id'] == session['account']['id']
        assert profile_data['preview']['telegram_bot_username'] == 'Neuromixx_bot'
        assert profile_data['preview']['vk_community_id'] is None
        assert profile_data['preview']['telegram_linked'] is False
        assert profile_data['preview']['linked_platforms'] == ['telegram']
        again = await (await login(client)).json()
        assert again['account']['id'] == session['account']['id']
        assert 'credits' not in session['account']  # No invented/migrated wallet.
        assert (await client.post(ROOT + '/logout', headers=headers)).status == 200
        assert (await client.get(ROOT + '/me', headers=headers)).status == 401


async def test_vk_only_session_reveals_configured_native_chat_without_telegram(monkeypatch):
    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    async with preview_client() as client:
        await enable(client, vk_app_id=123, vk_community_id=239915802)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        assert signed.status == 200
        headers = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        profile = await (await client.get(ROOT + '/me', headers=headers)).json()
        assert profile['preview']['vk_community_id'] == 239915802
        assert profile['preview']['telegram_linked'] is False
        assert (await client.get(ROOT + '/wallet', headers=headers)).status == 403


async def test_vk_native_state_uses_only_signed_actor_identity_without_telegram(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.shared_accounts import api

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    native = AsyncMock(return_value={
        'registered': True, 'balance': 12.5, 'is_blocked': False,
        'tasks': [{'task_id': 7, 'task_type': 'photo', 'model': 'nano_banana_pro',
                   'status': 'completed', 'cost': 2.5, 'result_url': None,
                   'created_at': '2026-11-09 12:00:00'}],
    })
    monkeypatch.setattr(api, 'fetch_native_vk_state', native, raising=False)
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        assert signed.status == 200
        headers = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        result = await client.get(ROOT + '/vk-native-state?vk_user_id=9999', headers=headers)
        assert result.status == 200, await result.text()
        assert (await result.json())['balance'] == 12.5
        native.assert_awaited_once_with(2001)
        assert (await client.get(ROOT + '/vk-native-state')).status == 401

        telegram = await login(client, 1001)
        other = {'Authorization': 'Bearer ' + (await telegram.json())['session_token']}
        assert (await client.get(ROOT + '/vk-native-state', headers=other)).status == 403
        native.assert_awaited_once_with(2001)


async def test_vk_commerce_api_resolves_native_owner_and_refuses_telegram(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.shared_accounts import api

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    native = AsyncMock(return_value={
        'ok': True, 'registered': True, 'balance': 31.5,
        'payment_packages': [], 'payments': [],
        'referrals': {'first_level_count': 1, 'second_level_count': 0, 'earned_rub': 7.0},
    })
    monkeypatch.setattr(api, 'fetch_native_vk_commerce', native, raising=False)
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        assert signed.status == 200
        bearer = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        result = await client.get(ROOT + '/vk-commerce?vk_user_id=999999', headers=bearer)
        assert result.status == 200, await result.text()
        assert result.headers['Cache-Control'] == 'no-store'
        assert (await result.json())['balance'] == 31.5
        native.assert_awaited_once_with(2001)
        assert (await client.get(ROOT + '/vk-commerce')).status == 401
        telegram = await login(client, 1001)
        other = {'Authorization': 'Bearer ' + (await telegram.json())['session_token']}
        assert (await client.get(ROOT + '/vk-commerce', headers=other)).status == 403
        native.assert_awaited_once_with(2001)


async def test_vk_invoice_creation_disabled_by_default_and_requires_vk_actor(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.shared_accounts import api

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    monkeypatch.delenv('VK_MINIAPP_CHECKOUT_ENABLED', raising=False)
    native = AsyncMock(return_value=(200, {'ok': True, 'status': 'ready',
                                         'payment_url': 'https://lava.top/p/1'}))
    monkeypatch.setattr(api, 'create_native_vk_invoice', native, raising=False)
    order = {'package_id': '250', 'payment_method': 'CARD',
             'customer_email': 'user@example.com',
             'client_request_id': 'abc123def456xyz789'}
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        vk_login = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        vk_headers = {'Authorization': 'Bearer ' + (await vk_login.json())['session_token']}
        assert (await client.post(ROOT + '/vk-invoice', json=order)).status == 401
        telegram = await login(client, 1001)
        tg_headers = {'Authorization': 'Bearer ' + (await telegram.json())['session_token']}
        assert (await client.post(ROOT + '/vk-invoice', json=order, headers=tg_headers)).status == 403
        assert (await client.post(ROOT + '/vk-invoice', json=order, headers=vk_headers)).status == 404
        native.assert_not_awaited()


async def test_vk_invoice_uses_verified_vk_actor_and_native_hmac_only(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.shared_accounts import api

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    monkeypatch.setenv('VK_MINIAPP_CHECKOUT_ENABLED', '1')
    native = AsyncMock(return_value=(200, {
        'ok': True, 'status': 'ready', 'amount_rub': 250, 'credits': 25,
        'payment_url': 'https://lava.top/p/1',
    }))
    monkeypatch.setattr(api, 'create_native_vk_invoice', native, raising=False)
    order = {'package_id': '250', 'payment_method': 'CARD',
             'customer_email': 'user@example.com',
             'client_request_id': 'abc123def456xyz789'}
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        headers = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        actual = await client.post(ROOT + '/vk-invoice?vk_user_id=99999',
                                   json=order, headers=headers)
        assert actual.status == 200
        assert (await actual.json())['payment_url'] == 'https://lava.top/p/1'
        native.assert_awaited_once_with(2001, order)
        bad = await client.post(ROOT + '/vk-invoice', json={**order, 'vk_user_id':9999},
                                headers=headers)
        assert bad.status == 400
        native.assert_awaited_once_with(2001, order)


async def test_vk_invoice_loopback_signs_exact_body_and_keeps_provider_status(monkeypatch):
    import hashlib
    import hmac
    import json

    from bot.shared_accounts.vk_native import create_native_vk_invoice

    monkeypatch.setenv('INTERNAL_API_SECRET', 'native-checkout-probe')
    app = web.Application()
    native_path = '/internal/v1/miniapp/users/2001/commerce/invoices'
    expected_payload = {'package_id': '250', 'payment_method': 'SBP',
                        'customer_email': 'real@example.org',
                        'client_request_id': 'abc123def456xyz789'}

    async def native(request):
        raw = await request.read()
        stamp = request.headers['X-Internal-Timestamp']
        check = hmac.new(
            b'native-checkout-probe',
            b'\n'.join([stamp.encode(), b'POST', request.path.encode(), raw]),
            hashlib.sha256,
        ).hexdigest()
        assert hmac.compare_digest(request.headers['X-Internal-Signature'], check)
        assert abs(int(stamp) - int(time.time())) < 30
        assert json.loads(raw) == expected_payload
        return web.json_response({'ok': True, 'status': 'ready', 'amount_rub':250,
                                  'credits':25, 'payment_url':'https://lava.top/p/safe'})

    app.router.add_post(native_path, native)
    async with TestClient(TestServer(app)) as client:
        monkeypatch.setenv('VK_NATIVE_INTERNAL_ORIGIN', f'http://127.0.0.1:{client.server.port}')
        status, result = await create_native_vk_invoice(2001, expected_payload)
        assert status == 200 and result['payment_url'] == 'https://lava.top/p/safe'
        with pytest.raises(ValueError):
            await create_native_vk_invoice(0, expected_payload)
    # Confirm hard failure never forwards a caller-selected VK ID.
    assert 'vk_user_id' not in str(expected_payload)



async def test_vk_model_catalog_bound_to_signed_vk_actor_and_no_telegram(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.shared_accounts import api

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    native = AsyncMock(return_value={
        'ok': True,
        'photo_models': [{'id':'nano_banana_pro','label':'Nano Banana Pro',
                          'ratios':['1:1'],'resolutions':['2K'],'max_references':4}],
        'video_models': [],
    })
    monkeypatch.setattr(api,'fetch_native_vk_models',native,raising=False)
    async with preview_client() as client:
        await enable(client,vk_app_id=123)
        vk_login = await client.post(ROOT+'/session', json={
            'platform':'vk','launch_data':vk_launch(2001),
        })
        header={'Authorization':'Bearer '+(await vk_login.json())['session_token']}
        result=await client.get(ROOT+'/vk-models?vk_user_id=999999',headers=header)
        assert result.status==200
        assert (await result.json())['photo_models'][0]['id']=='nano_banana_pro'
        native.assert_awaited_once_with(2001)
        assert (await client.get(ROOT+'/vk-models')).status==401
        telegram=await login(client,1001)
        other={'Authorization':'Bearer '+(await telegram.json())['session_token']}
        assert (await client.get(ROOT+'/vk-models',headers=other)).status==403
        native.assert_awaited_once_with(2001)


async def test_vk_model_catalog_loopback_hmac_rejects_untrusted_schema(monkeypatch):
    import hashlib
    import hmac

    from bot.shared_accounts.vk_native import fetch_native_vk_models

    monkeypatch.setenv('INTERNAL_API_SECRET','native-model-catalog')
    app=web.Application()
    route='/internal/v1/miniapp/users/2001/models'
    async def native(request):
        ts=request.headers['X-Internal-Timestamp']
        msg=f'{ts}\nGET\n{request.path}\n'.encode()
        expected=hmac.new(b'native-model-catalog',msg,hashlib.sha256).hexdigest()
        assert hmac.compare_digest(request.headers['X-Internal-Signature'],expected)
        assert abs(int(ts)-int(time.time())) < 30
        return web.json_response({'ok':True,'photo_models':[],'video_models':[]})
    app.router.add_get(route,native)
    async with TestClient(TestServer(app)) as client:
        monkeypatch.setenv('VK_NATIVE_INTERNAL_ORIGIN',f'http://127.0.0.1:{client.server.port}')
        assert (await fetch_native_vk_models(2001))['ok']
        with pytest.raises(ValueError):
            await fetch_native_vk_models(0)


async def test_vk_commerce_hmac_loopback_and_proof_shape(monkeypatch):
    import hashlib
    import hmac

    from bot.shared_accounts.vk_native import fetch_native_vk_commerce

    monkeypatch.setenv('INTERNAL_API_SECRET', 'test-native-read')
    origin_path = '/internal/v1/miniapp/users/2001/commerce'
    fake = web.Application()

    async def native(request):
        ts = request.headers.get('X-Internal-Timestamp', '')
        expected = hmac.new(b'test-native-read', f'{ts}\nGET\n{request.path}\n'.encode(), hashlib.sha256).hexdigest()
        assert hmac.compare_digest(request.headers.get('X-Internal-Signature', ''), expected)
        assert abs(int(ts) - int(time.time())) < 30
        return web.json_response({
            'ok': True, 'registered': True, 'balance': 20.0,
            'payment_packages': [{'id': '250', 'price_rub': 250, 'credits': 25,
                                  'lava_offer_id': 'test-public-offer', 'methods': ['lava_card']}],
            'payments': [{'amount_rub': 250, 'status': 'paid', 'created_at': '2026-11-11'}],
            'referrals': {'first_level_count': 1, 'second_level_count': 0, 'earned_rub': 70.0},
        })

    fake.router.add_get(origin_path, native)
    async with TestClient(TestServer(fake)) as client:
        monkeypatch.setenv('VK_NATIVE_INTERNAL_ORIGIN', f'http://127.0.0.1:{client.server.port}')
        value = await fetch_native_vk_commerce(2001)
        assert value['balance'] == 20.0
        assert value['referrals']['earned_rub'] == 70.0
        with pytest.raises(ValueError):
            await fetch_native_vk_commerce(0)


async def test_vk_native_state_signed_internal_rpc_uses_fixed_loopback_origin(monkeypatch):
    from bot.shared_accounts.vk_native import fetch_native_vk_state

    monkeypatch.setenv('INTERNAL_API_SECRET', 'test-bridge')
    fake = web.Application()
    async def state(request):
        import hashlib
        import hmac
        timestamp = request.headers.get('X-Internal-Timestamp', '')
        signature = request.headers.get('X-Internal-Signature', '')
        string = f'{timestamp}\nGET\n{request.path}\n'.encode()
        expected = hmac.new(b'test-bridge', string, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(signature, expected)
        return web.json_response({'registered': False, 'balance': None,
                                  'is_blocked': False, 'tasks': []})
    fake.router.add_get('/internal/v1/miniapp/users/2001/state', state)
    async with TestClient(TestServer(fake)) as client:
        port = client.server.port
        monkeypatch.setenv('VK_NATIVE_INTERNAL_ORIGIN', f'http://127.0.0.1:{port}')
        result = await fetch_native_vk_state(2001)
        assert result['registered'] is False
    monkeypatch.setenv('VK_NATIVE_INTERNAL_ORIGIN', 'https://evil.example')
    with pytest.raises(RuntimeError):
        await fetch_native_vk_state(2001)


async def test_vk_only_public_trends_without_telegram(monkeypatch):
    from bot import database

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    monkeypatch.setenv('VK_MINIAPP_WRITES_ENABLED', '1')
    author = await database.get_or_create_user(97100001)
    trend = await database.create_prompt(
        author_id=author.id, title='Портрет',
        description='Вариант портрета',
        prompt_text='Unpublished recipe detail test only',
        tags=['trend'], category='photo', model='banana_pro',
        generation_settings={'kind': 'image', 'model': 'banana_pro', 'quality': '2K',
                             'ratio': '1:1', 'user_fields': [
            {'key': 'age', 'label': 'Возраст', 'original_value': '37'}]},
    )
    await database.approve_prompt(trend['id'])
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        headers = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        response = await client.get(ROOT + '/trends', headers=headers)
        assert response.status == 200, await response.text()
        data = await response.json()
        cards = [item for group in data['categories'] for item in group['items']]
        match = next(x for x in cards if x['id'] == trend['id'])
        assert match['generation_type'] == 'image'
        assert match['can_repeat_in_app'] is True
        assert 'model' not in match and 'generation_settings' not in match
        assert 'prompt_text' not in match
        assert 'author_id' not in match
        assert '37' not in str(data)
        category_page = await client.get(
            ROOT + '/trends?view=category&category_id=unassigned&page=1',
            headers=headers,
        )
        assert category_page.status == 200, await category_page.text()
        listing = await category_page.json()
        assert next(x for x in listing['items'] if x['id'] == trend['id'])['can_repeat_in_app'] is True
        assert 'Unpublished recipe detail' not in str(listing)
        for query in ('?view=category&category_id=abc', '?view=category&category_id=unassigned&page=1001'):
            assert (await client.get(ROOT + '/trends' + query, headers=headers)).status == 400
        assert (await client.get(ROOT + '/trends')).status == 401
        monkeypatch.delenv('VK_MINIAPP_WRITES_ENABLED')
        disabled = await (await client.get(ROOT + '/trends', headers=headers)).json()
        assert all(not card['can_repeat_in_app'] for group in disabled['categories'] for card in group['items'])


async def test_vk_only_feed_does_not_expose_foreign_source_or_identity(monkeypatch):
    from unittest.mock import AsyncMock

    from bot import database

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    get_feed = AsyncMock(return_value=[{
        'id': 123, 'gen_type': 'video', 'likes_count': 8,
        'preview_url': 'https://example.test/preview.jpg',
        'result_url': 'https://example.test/video.mp4',
        'prompt': 'nonpublic recipe',
        'reference_images': ['https://example.test/reference.jpg'],
        'author_telegram_id': 99111,
        'is_mine': True,
    }])
    monkeypatch.setattr(database, 'get_feed_generations', get_feed)
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        auth = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        headers = {'Authorization': 'Bearer ' + (await auth.json())['session_token']}
        response = await client.get(ROOT + '/trends?view=feed', headers=headers)
        assert response.status == 200
        payload = await response.json()
        assert payload['items'] == [{
            'id': 123, 'generation_type': 'video',
            'preview_url': 'https://example.test/preview.jpg',
            'result_url': 'https://example.test/video.mp4',
            'likes_count': 8, 'can_repeat_in_app': False, 'can_like_in_app': False,
            'share_link': 'https://vk.com/app123#feed_123',
        }]
        assert 'nonpublic recipe' not in str(payload)
        assert 'author_telegram_id' not in str(payload)
        assert 'reference_images' not in str(payload)
        assert get_feed.await_args.kwargs['viewer_user_id'] is None
        assert get_feed.await_args.kwargs['include_unavailable'] is False
        assert (await client.get(ROOT + '/trends?view=private', headers=headers)).status == 400
        telegram = await login(client, 1001)
        tg_headers = {'Authorization': 'Bearer ' + (await telegram.json())['session_token']}
        assert (await client.get(ROOT + '/trends', headers=tg_headers)).status == 403


async def test_enabled_preview_allows_ordinary_telegram_linking_but_not_admin_surfaces():
    async with preview_client() as client:
        await enable(client)
        session = await login(client, 1001)
        assert session.status == 200
        token = (await session.json())['session_token']
        headers = {'Authorization': 'Bearer ' + token}
        profile = await client.get(ROOT + '/me', headers=headers)
        assert profile.status == 200
        assert (await profile.json())['preview']['linked_platforms'] == ['telegram']
        assert (await client.post(ROOT + '/links', headers=headers, json={'target_platform': 'vk'})).status == 200
        assert (await client.get(
            ROOT + '/settings', headers={'X-Telegram-Init-Data': telegram_launch(1001)}
        )).status == 403
        assert (await client.get(ROOT + '/wallet', headers=headers)).status == 403
        assert (await client.get(ROOT + '/commerce', headers=headers)).status == 403


async def test_expired_telegram_launch_is_rejected_with_safe_diagnostics(caplog):
    async with preview_client() as client:
        await enable(client)
        expired = telegram_launch(timestamp=int(time.time()) - 900)
        with caplog.at_level('INFO', logger='bot.shared_accounts.api'):
            response = await client.get(ROOT + '/settings', headers={'X-Telegram-Init-Data': expired})
        assert response.status == 401
        assert (await response.json())['error'] == 'Expired launch credentials'
        assert 'shared_account_authentication_rejected' in caplog.text
        assert 'reason=Expired launch credentials' in caplog.text
        assert expired not in caplog.text


async def test_disable_revokes_existing_sessions_immediately():
    async with preview_client() as client:
        await enable(client)
        token = (await (await login(client)).json())['session_token']
        response = await client.put(ROOT + '/settings', json={
            'init_data': telegram_launch(), 'expected_revision': 1,
            'settings': {'enabled': False},
        })
        assert response.status == 200
        assert (await client.get(ROOT + '/me', headers={'Authorization': 'Bearer ' + token})).status == 404


async def test_concurrent_settings_save_has_one_winner():
    async with preview_client() as client:
        responses = await asyncio.gather(*[
            client.put(ROOT + '/settings', json={
                'init_data': telegram_launch(), 'expected_revision': 0,
                'settings': {'enabled': value},
            }) for value in [True, False]
        ])
        assert sorted(r.status for r in responses) == [200, 409]


def vk_launch(user_id, app_id=123, timestamp=None):
    fields = {'vk_app_id': str(app_id), 'vk_user_id': str(user_id), 'vk_ts': str(timestamp or int(time.time()))}
    digest = hmac.new(b'test-vk-app-secret', urlencode(sorted(fields.items())).encode(), hashlib.sha256).digest()
    fields['sign'] = base64.urlsafe_b64encode(digest).decode().rstrip('=')
    return urlencode(fields)


async def test_vk_user_does_not_need_the_administrator_allowlist(monkeypatch):
    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    async with preview_client() as client:
        await enable(client, vk_app_id=123, vk_admin_ids=[2001])
        administrator = await client.post(
            ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2001)}
        )
        assert administrator.status == 200
        administrator_data = await administrator.json()
        assert administrator_data['account']['identity'] == {'platform': 'vk', 'external_id': 2001}

        ordinary = await client.post(
            ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(ADMIN)}
        )
        assert ordinary.status == 200
        ordinary_data = await ordinary.json()
        ordinary_headers = {'Authorization': 'Bearer ' + ordinary_data['session_token']}
        assert (await client.get(ROOT + '/me', headers=ordinary_headers)).status == 200
        assert (await client.get(ROOT + '/wallet', headers=ordinary_headers)).status == 403
        assert (await client.get(ROOT + '/commerce', headers=ordinary_headers)).status == 403

        telegram = await (await login(client)).json()
        assert telegram['account']['id'] != administrator_data['account']['id']
        assert telegram['account']['id'] != ordinary_data['account']['id']


async def test_vk_signature_wrong_app_tamper_and_expiry_are_rejected(monkeypatch):
    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    async with preview_client() as client:
        await enable(client, vk_app_id=123, vk_admin_ids=[2001])
        for launch in [vk_launch(2001, app_id=124), vk_launch(2001).replace('vk_user_id=2001', 'vk_user_id=2002'), vk_launch(2001, timestamp=int(time.time()) - 700), vk_launch(2001) + '&vk_user_id=2001']:
            response = await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': launch})
            assert response.status == 401


async def test_parallel_logins_resolve_to_one_account():
    async with preview_client() as client:
        await enable(client)
        responses = await asyncio.gather(*[login(client) for _ in range(5)])
        assert all(r.status == 200 for r in responses)
        data = [await r.json() for r in responses]
        assert len({r['account']['id'] for r in data}) == 1
        assert len({r['session_token'] for r in data}) == 5


async def test_tokens_are_hashed_at_rest_and_not_accepted_in_query_string():
    async with preview_client() as client:
        await enable(client)
        token = (await (await login(client)).json())['session_token']
        async with db_backend.connect() as db:
            stored = (await (await db.execute('SELECT token_hash FROM shared_account_sessions')).fetchone())[0]
        assert stored != token
        assert stored == hashlib.sha256(token.encode()).hexdigest()
        assert (await client.get(ROOT + '/me?session_token=' + token)).status == 401


async def test_vk_administrator_removal_keeps_public_access_after_revision_refresh(monkeypatch):
    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    async with preview_client() as client:
        await enable(client, vk_app_id=123, vk_admin_ids=[2001])
        old = await (await client.post(
            ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2001)}
        )).json()
        old_headers = {'Authorization': 'Bearer ' + old['session_token']}
        changed = await client.put(ROOT + '/settings', json={
            'init_data': telegram_launch(), 'expected_revision': 1, 'settings': {'vk_admin_ids': []},
        })
        assert changed.status == 200
        assert (await client.get(ROOT + '/me', headers=old_headers)).status == 401

        fresh = await client.post(
            ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2001)}
        )
        assert fresh.status == 200
        fresh_headers = {'Authorization': 'Bearer ' + (await fresh.json())['session_token']}
        assert (await client.get(ROOT + '/me', headers=fresh_headers)).status == 200
        assert (await client.get(ROOT + '/wallet', headers=fresh_headers)).status == 403


async def test_expired_session_is_rejected(monkeypatch):
    async with preview_client() as client:
        await enable(client)
        token = (await (await login(client)).json())['session_token']
        now = time.time()
        monkeypatch.setattr('bot.shared_accounts.store.time.time', lambda: now + 3601)
        assert (await client.get(ROOT + '/me', headers={'Authorization': 'Bearer ' + token})).status == 401


async def test_new_login_prunes_only_expired_sessions(monkeypatch):
    async with preview_client() as client:
        await enable(client)
        first = await (await login(client)).json()
        second = await (await login(client)).json()
        await client.post(
            ROOT + '/logout', headers={'Authorization': 'Bearer ' + second['session_token']}
        )
        now = time.time()
        async with db_backend.connect() as db:
            await db.execute(
                'UPDATE shared_account_sessions SET expires_at_epoch = ? WHERE token_hash = ?',
                (int(now) - 1, hashlib.sha256(first['session_token'].encode()).hexdigest()),
            )
            await db.commit()
        monkeypatch.setattr('bot.shared_accounts.store.time.time', lambda: now)
        assert (await login(client)).status == 200
        async with db_backend.connect() as db:
            rows = await (await db.execute(
                'SELECT token_hash, revoked_at_epoch FROM shared_account_sessions ORDER BY created_at_epoch'
            )).fetchall()
        assert len(rows) == 2
        assert hashlib.sha256(first['session_token'].encode()).hexdigest() not in {row[0] for row in rows}
        assert hashlib.sha256(second['session_token'].encode()).hexdigest() in {row[0] for row in rows}


@pytest.mark.parametrize('change', [
    {'enabled': 'true'}, {'session_ttl_seconds': True}, {'session_ttl_seconds': 0},
    {'vk_admin_ids': '2001'}, {'revision': 100}, {'public_enabled': True},
    {'vk_app_id': True}, {'vk_admin_ids': [True]},
])
async def test_invalid_policy_does_not_change_revision(change):
    async with preview_client() as client:
        await enable(client)
        response = await client.put(ROOT + '/settings', json={'init_data': telegram_launch(), 'expected_revision': 1, 'settings': change})
        assert response.status == 400
        current = await client.get(ROOT + '/settings', headers={'X-Telegram-Init-Data': telegram_launch()})
        assert (await current.json())['settings']['revision'] == 1


async def test_preview_does_not_change_legacy_balance_or_create_fake_telegram_user(monkeypatch):
    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    async with db_backend.connect() as db:
        await db.execute('INSERT INTO users(telegram_id, credits) VALUES (?, ?)', (ADMIN, 17.125))
        await db.commit()
    async with preview_client() as client:
        await enable(client, vk_app_id=123, vk_admin_ids=[2001])
        assert (await login(client)).status == 200
        assert (await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2001)})).status == 200
    async with db_backend.connect() as db:
        rows = await (await db.execute('SELECT telegram_id, credits FROM users')).fetchall()
        assert [(r[0], r[1]) for r in rows] == [(ADMIN, 17.125)]
        assert (await (await db.execute('SELECT COUNT(*) FROM shared_account_legacy_links')).fetchone())[0] == 1


async def test_failed_settings_audit_rolls_back_configuration():
    async with preview_client() as client:
        await enable(client)
        # Simulate storage failure at the audit boundary, on both database engines.
        async with db_backend.connect() as db:
            execute = getattr(db, 'execute_native_ddl', db.execute)
            await execute('DROP TABLE shared_account_policy_audit')
            await execute('CREATE TABLE shared_account_policy_audit (id TEXT PRIMARY KEY CHECK(id = \'reject-all-writes\'))')
            await db.commit()
        response = await client.put(ROOT + '/settings', json={'init_data': telegram_launch(), 'expected_revision': 1, 'settings': {'enabled': False}})
        assert response.status == 503
        settings = await client.get(ROOT + '/settings', headers={'X-Telegram-Init-Data': telegram_launch()})
        assert (await settings.json())['settings']['enabled'] is True
        assert (await settings.json())['settings']['revision'] == 1


async def test_reenabling_preview_does_not_resurrect_old_session():
    async with preview_client() as client:
        await enable(client)
        token = (await (await login(client)).json())['session_token']
        for revision, enabled in [(1, False), (2, True)]:
            result = await client.put(ROOT + '/settings', json={'init_data': telegram_launch(), 'expected_revision': revision, 'settings': {'enabled': enabled}})
            assert result.status == 200
        assert (await client.get(ROOT + '/me', headers={'Authorization': 'Bearer ' + token})).status == 401
        assert (await login(client)).status == 200


async def test_telegram_tamper_stale_future_and_duplicate_launch_are_rejected():
    now = int(time.time())
    launches = [
        telegram_launch().replace(str(ADMIN), '1001'),
        telegram_launch(timestamp=now - 700),
        telegram_launch(timestamp=now + 120),
        telegram_launch() + '&auth_date=' + str(now),
        'auth_date=' + str(now) + '&user=%7B%22id%22%3A999999999%7D',
    ]
    async with preview_client() as client:
        await enable(client)
        for launch in launches:
            assert (await client.post(ROOT + '/session', json={'platform': 'telegram', 'launch_data': launch})).status == 401
            assert (await client.get(ROOT + '/settings', headers={'X-Telegram-Init-Data': launch})).status == 401


async def test_equal_external_ids_on_both_platforms_remain_different_accounts(monkeypatch):
    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    async with preview_client() as client:
        await enable(client, vk_app_id=123, vk_admin_ids=[ADMIN])
        telegram = await (await login(client)).json()
        vk = await (await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(ADMIN)})).json()
        assert telegram['account']['id'] != vk['account']['id']


async def test_vk_only_native_photo_submit_uses_verified_actor_not_telegram(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.shared_accounts import api

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    monkeypatch.setenv('VK_MINIAPP_WRITES_ENABLED', '1')
    submit = AsyncMock(return_value={'task_id': 41, 'cost': 2.5})
    monkeypatch.setattr(api, 'submit_native_vk_image', submit, raising=False)
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        headers = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        payload = {
            'model': 'nano_banana_pro', 'prompt': 'Blue vase', 'aspect': '1:1',
            'resolution': '2K', 'client_request_id': 'idempotency-test-00001',
            'expected_cost': 2.5,
        }
        unauthorized = await client.post(ROOT + '/vk-image', json=payload)
        assert unauthorized.status == 401
        telegram = await login(client, 1001)
        other_headers = {'Authorization': 'Bearer ' + (await telegram.json())['session_token']}
        assert (await client.post(ROOT + '/vk-image', json=payload, headers=other_headers)).status == 403
        paid = await client.post(ROOT + '/vk-image', headers=headers, json={**payload, 'vk_user_id': 99999})
        assert paid.status == 400
        submit.assert_not_awaited()
        paid = await client.post(ROOT + '/vk-image', headers=headers, json=payload)
        assert paid.status == 200, await paid.text()
        assert (await paid.json())['task_id'] == 41
        submit.assert_awaited_once_with(2001, {**payload, 'reference_photos': []})


async def test_vk_native_photo_submit_disabled_fail_closed(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.shared_accounts import api

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    monkeypatch.delenv('VK_MINIAPP_WRITES_ENABLED', raising=False)
    submit = AsyncMock(return_value={'task_id': 1, 'cost': 2})
    monkeypatch.setattr(api, 'submit_native_vk_image', submit, raising=False)
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        headers = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        assert (await client.post(ROOT + '/vk-image', json={}, headers=headers)).status == 404
        submit.assert_not_awaited()


async def test_vk_trend_image_executes_hidden_approved_recipe_without_exposing_prompt(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock

    from bot import database
    from bot.shared_accounts import api

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    monkeypatch.setenv('VK_MINIAPP_WRITES_ENABLED', '1')
    submit = AsyncMock(return_value={'task_id': 81, 'cost': 2.5})
    monkeypatch.setattr(api, 'submit_native_vk_image', submit, raising=False)
    from bot.config import config
    from bot.shared_accounts import vk_image_refs
    monkeypatch.setattr(config, 'STATIC_BASE_URL', 'https://example.test')
    monkeypatch.setattr(vk_image_refs, 'ROOT', tmp_path / 'vk-refs' / 'image')
    image_folder = vk_image_refs.ROOT / '2001'
    image_folder.mkdir(parents=True)
    filename = 'a' * 32 + '.jpg'
    (image_folder / filename).write_bytes(b'owned-image')
    owned_image = 'https://example.test/uploads/vk-refs/image/2001/' + filename
    author = await database.get_or_create_user(97100001)
    trend = await database.create_prompt(
        author_id=author.id, title='Тренд для VK',
        description='Проверка', prompt_text='A private sunset on a lake',
        tags=['trend'], category='photo', model='banana_pro',
        generation_settings={'kind': 'image', 'model': 'banana_pro', 'ratio': '1:1', 'quality': '2K',
                             'user_input': 'photo', 'count': 1},
    )
    await database.approve_prompt(trend['id'])
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        headers = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        payload = {'trend_id': trend['id'], 'reference_urls': [owned_image], 'user_values': {},
                   'client_request_id': 'trend-idempotent-00001', 'expected_cost': 2.5}
        r = await client.post(ROOT + '/vk-trend', json=payload, headers=headers)
        assert r.status == 200, await r.text()
        assert 'A private sunset' not in await r.text()
        submit.assert_awaited_once_with(2001, {
            'model': 'nano_banana_pro', 'prompt': 'A private sunset on a lake',
            'aspect': '1:1', 'resolution': '2K', 'client_request_id': 'trend-idempotent-00001',
            'reference_photos': [owned_image], 'expected_cost': 2.5,
        })
        assert (await client.post(ROOT + '/vk-trend', json={**payload, 'reference_urls': ['https://example.test/photo.jpg']},
                                  headers=headers)).status == 400


async def test_vk_native_upload_is_jpeg_sanitized_owner_scoped_and_not_telegram(monkeypatch, tmp_path):
    import io

    from aiohttp import FormData
    from PIL import Image

    from bot.config import config
    from bot.handlers.miniapp_regression_safety import install_miniapp_regression_safety
    from bot.shared_accounts import vk_image_refs

    # Production installs the legacy JSON guard globally. Keep that real
    # integration in this regression even when this test is run in isolation.
    install_miniapp_regression_safety()
    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    monkeypatch.setenv('VK_MINIAPP_WRITES_ENABLED', '1')
    monkeypatch.setattr(config, 'STATIC_BASE_URL', 'https://example.test')
    monkeypatch.setattr(vk_image_refs, 'ROOT', tmp_path / 'vk-refs' / 'image')
    # CI runners can have less free space than the production storage floor.
    # Keep image validation deterministic; quota/floor rejection has its own test.
    from types import SimpleNamespace
    monkeypatch.setattr(
        vk_image_refs.os, 'statvfs',
        lambda _path: SimpleNamespace(f_bavail=100 * 1024**3, f_frsize=1),
    )
    image = Image.new('RGB', (32, 28), (255, 0, 0))
    output = io.BytesIO()
    image.save(output, format='PNG')
    binary = output.getvalue()
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        headers = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        form = FormData()
        form.add_field('image', binary, filename='face.png', content_type='image/png')
        rejected = await client.post(ROOT + '/vk-image-upload', data=form)
        assert rejected.status == 401
        assert rejected.headers.get('Connection', '').lower() == 'close'
        form = FormData()
        form.add_field('image', binary, filename='face.png', content_type='image/png')
        uploaded = await client.post(ROOT + '/vk-image-upload', data=form, headers=headers)
        assert uploaded.status == 200, await uploaded.text()
        url = (await uploaded.json())['url']
        assert url.startswith('https://example.test/uploads/vk-refs/image/2001/')
        assert vk_image_refs.verified_image_urls(2001, [url]) == [url]
        with Image.open(vk_image_refs.ROOT / '2001' / url.rsplit('/', 1)[1]) as saved:
            assert saved.format == 'JPEG' and saved.size == (32, 28)
        with pytest.raises(ValueError):
            vk_image_refs.verified_image_urls(2002, [url])
        with pytest.raises(ValueError):
            vk_image_refs.verified_image_urls(2001, ['https://evil.example/uploads/vk-refs/image/2001/' + 'a' * 32 + '.jpg'])
        form = FormData()
        form.add_field('image', b'spoofed-jpeg', filename='bad.jpg', content_type='image/jpeg')
        bad = await client.post(ROOT + '/vk-image-upload', data=form, headers=headers)
        assert bad.status == 400


async def test_signed_native_write_rpc_rejects_tampering_and_nonlocal_origin(monkeypatch):
    from bot.shared_accounts.vk_native import submit_native_vk_image

    monkeypatch.setenv('INTERNAL_API_SECRET', 'test-bridge')
    monkeypatch.setenv('VK_MINIAPP_WRITES_ENABLED', '1')
    fake = web.Application()
    async def image(request):
        timestamp = request.headers.get('X-Internal-Timestamp', '')
        signature = request.headers.get('X-Internal-Signature', '')
        body = await request.read()
        expected = hmac.new(
            b'test-bridge',
            b'\n'.join([timestamp.encode(), b'POST', request.path.encode(), body]),
            hashlib.sha256,
        ).hexdigest()
        assert hmac.compare_digest(signature, expected)
        assert json.loads(body)['prompt'] == 'blue vase'
        return web.json_response({'ok': True, 'task_id': 71, 'cost': 2.5})
    fake.router.add_post('/internal/v1/miniapp/users/2001/generations/image', image)
    async with TestClient(TestServer(fake)) as client:
        monkeypatch.setenv('VK_NATIVE_INTERNAL_ORIGIN', 'http://127.0.0.1:' + str(client.server.port))
        result = await submit_native_vk_image(2001, {'prompt': 'blue vase'})
        assert result == {'task_id': 71, 'cost': 2.5}
    monkeypatch.setenv('VK_NATIVE_INTERNAL_ORIGIN', 'https://evil.example')
    with pytest.raises(RuntimeError):
        await submit_native_vk_image(2001, {'prompt': 'blue vase'})


@pytest.mark.parametrize('native_status', [400, 402, 403, 409])
async def test_vk_native_generation_preserves_actionable_rejections(monkeypatch, native_status):
    """The app must distinguish bad quotes, empty balance, bans and retries."""
    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    monkeypatch.setenv('VK_MINIAPP_WRITES_ENABLED', '1')
    monkeypatch.setenv('INTERNAL_API_SECRET', 'test-bridge')
    native = web.Application()

    async def reject(request):
        await request.read()
        # Native diagnostics are not safe public error messages.
        return web.json_response({'error': 'private native diagnostic'}, status=native_status)

    native.router.add_post('/internal/v1/miniapp/users/2001/generations/image', reject)
    async with TestClient(TestServer(native)) as bridge, preview_client() as client:
        monkeypatch.setenv('VK_NATIVE_INTERNAL_ORIGIN', 'http://127.0.0.1:' + str(bridge.server.port))
        await enable(client, vk_app_id=123)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        headers = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        result = await client.post(ROOT + '/vk-image', headers=headers, json={
            'model': 'nano_banana_pro', 'prompt': 'Blue vase', 'aspect': '1:1',
            'resolution': '2K', 'reference_photos': [],
            'client_request_id': 'native-rejection-000001', 'expected_cost': 2.5,
        })
        assert result.status == native_status, await result.text()
        assert 'private native diagnostic' not in await result.text()


async def test_linked_vk_cannot_spend_a_second_native_wallet(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.shared_accounts import api
    from tests.test_shared_account_links import pair

    monkeypatch.setenv('VK_MINIAPP_WRITES_ENABLED', '1')
    submit = AsyncMock(return_value={'task_id': 81, 'cost': 2.5})
    monkeypatch.setattr(api, 'submit_native_vk_image', submit)
    async with pair(monkeypatch) as (client, source, target):
        created = await client.post(ROOT + '/links', headers=source, json={
            'target_platform': 'vk', 'confirm_source': True,
        })
        invitation = (await created.json())['link']
        linked = await client.post(ROOT + '/links/accept', headers=target, json={
            'token': invitation['token'], 'confirm': True,
        })
        assert (await linked.json())['link']['state'] == 'committed'
        fresh = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        headers = {'Authorization': 'Bearer ' + (await fresh.json())['session_token']}
        payload = {'model': 'nano_banana_pro', 'prompt': 'Blue vase', 'aspect': '1:1',
                   'resolution': '2K', 'reference_photos': [],
                   'client_request_id': 'linked-native-000001', 'expected_cost': 2.5}
        for route in ('vk-image', 'vk-trend', 'vk-image-upload'):
            denied = await client.post(ROOT + '/' + route, headers=headers, json=payload)
            assert denied.status == 403, await denied.text()
        submit.assert_not_awaited()


async def test_vk_image_upload_rejects_unowned_references_and_stale_auth(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock

    from bot.config import config
    from bot.shared_accounts import api, vk_image_refs

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    monkeypatch.setenv('VK_MINIAPP_WRITES_ENABLED', '1')
    monkeypatch.setattr(config, 'STATIC_BASE_URL', 'https://example.test')
    monkeypatch.setattr(vk_image_refs, 'ROOT', tmp_path / 'vk-refs' / 'image')
    stored = vk_image_refs.ROOT / '2001'
    stored.mkdir(parents=True)
    filename = 'a' * 32 + '.jpg'
    (stored / filename).write_bytes(b'owned')
    owner_url = 'https://example.test/uploads/vk-refs/image/2001/' + filename
    submit = AsyncMock(return_value={'task_id': 81, 'cost': 2.5})
    monkeypatch.setattr(api, 'submit_native_vk_image', submit, raising=False)
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2002),
        })
        headers = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        payload = {'model': 'nano_banana_pro', 'prompt': 'Blue vase',
                   'aspect': '1:1', 'resolution': '2K', 'reference_photos': [owner_url],
                   'client_request_id': 'unique-00000000000001', 'expected_cost': 2.5}
        rejected = await client.post(ROOT + '/vk-image', json=payload, headers=headers)
        assert rejected.status == 400
        submit.assert_not_awaited()
        assert (await client.post(ROOT + '/logout', headers=headers)).status == 200
        assert (await client.post(ROOT + '/vk-image', json=payload, headers=headers)).status == 401


async def test_vk_image_upload_enforces_storage_quota_and_disk_floor(monkeypatch, tmp_path):
    import io

    from PIL import Image

    from bot.config import config
    from bot.shared_accounts import vk_image_refs

    monkeypatch.setattr(config, 'STATIC_BASE_URL', 'https://example.test')
    monkeypatch.setattr(vk_image_refs, 'ROOT', tmp_path / 'vk-refs' / 'image')
    from types import SimpleNamespace
    monkeypatch.setattr(
        vk_image_refs.os, 'statvfs',
        lambda _path: SimpleNamespace(f_bavail=100 * 1024**3, f_frsize=1),
    )
    image = Image.new('RGB', (24, 24), 'orange')
    blob = io.BytesIO()
    image.save(blob, format='PNG')
    monkeypatch.setenv('VK_MINIAPP_REF_MAX_FILES_PER_USER', '1')
    url = await vk_image_refs.save_vk_image(2001, blob.getvalue())
    assert vk_image_refs.verified_image_urls(2001, [url]) == [url]
    with pytest.raises(ValueError, match='Maximum uploaded'):
        await vk_image_refs.save_vk_image(2001, blob.getvalue())
    monkeypatch.setenv('VK_MINIAPP_REF_MAX_FILES_PER_USER', '100')
    monkeypatch.setenv('VK_MINIAPP_REF_MIN_FREE_BYTES', str(2**60))
    with pytest.raises(ValueError, match='temporarily full'):
        await vk_image_refs.save_vk_image(2001, blob.getvalue())
    assert len(list((vk_image_refs.ROOT / '2001').iterdir())) == 1


async def test_vk_only_direct_trend_link_requires_signature_and_hides_recipe(monkeypatch):
    from bot import database

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    user = await database.get_or_create_user(97101111)
    prompt = await database.create_prompt(
        author_id=user.id, title='Deep link for VK',
        description='Public test', prompt_text='Private owned prompt',
        tags=['trend'], category='photo', model='banana_pro',
        generation_settings={'kind': 'image', 'model': 'banana_pro',
                             'ratio': '1:1', 'quality': '2K', 'count': 1},
        is_public=True,
    )
    await database.approve_prompt(prompt['id'])
    link_query = '?view=item&trend_id=' + str(prompt['id'])
    async with preview_client() as client:
        await enable(client, vk_app_id=123, vk_community_id=239915802)
        no_token = await client.get(ROOT + '/trends' + link_query)
        assert no_token.status == 401
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        headers = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        item = await client.get(ROOT + '/trends' + link_query, headers=headers)
        assert item.status == 200, await item.text()
        payload = await item.json()
        assert payload['item']['id'] == prompt['id']
        assert payload['item']['title'] == 'Deep link for VK'
        assert payload['item']['share_link'] == 'https://vk.com/app123_-239915802#prompt_' + str(prompt['id'])
        assert 'Private owned prompt' not in str(payload)
        assert 'prompt_text' not in str(payload)
        assert 'reference_urls' not in str(payload)
        for invalid in ['0', '-1', 'abc', '1' * 100]:
            result = await client.get(ROOT + '/trends?view=item&trend_id=' + invalid, headers=headers)
            assert result.status == 400
        missing = await client.get(ROOT + '/trends?view=item&trend_id=987654321', headers=headers)
        assert missing.status == 404
        tg = await login(client, 1001)
        tg_headers = {'Authorization': 'Bearer ' + (await tg.json())['session_token']}
        assert (await client.get(ROOT + '/trends' + link_query, headers=tg_headers)).status == 403


async def test_vk_repeat_cannot_run_hidden_or_uncategorized_private_trend(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock

    from bot import database, trend_catalog
    from bot.shared_accounts import api

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    monkeypatch.setenv('VK_MINIAPP_WRITES_ENABLED', '1')
    native = AsyncMock(return_value={'task_id': 99, 'cost': 2.5})
    monkeypatch.setattr(api, 'submit_native_vk_image', native)
    from bot.config import config
    from bot.shared_accounts import vk_image_refs
    monkeypatch.setattr(config, 'STATIC_BASE_URL', 'https://example.test')
    monkeypatch.setattr(vk_image_refs, 'ROOT', tmp_path / 'vk-refs' / 'image')
    image_folder = vk_image_refs.ROOT / '2001'
    image_folder.mkdir(parents=True)
    (image_folder / ('b' * 32 + '.jpg')).write_bytes(b'owned-test-reference')
    owned_image = 'https://example.test/uploads/vk-refs/image/2001/' + 'b' * 32 + '.jpg'
    author = await database.get_or_create_user(97101688)
    prompt = await database.create_prompt(
        author_id=author.id, title='Hidden admin photo trend',
        description='Private hidden', prompt_text='Private source image',
        tags=['trend'], category='photo', model='banana_pro',
        generation_settings={'kind': 'image', 'model': 'banana_pro', 'ratio': '1:1',
                             'quality': '2K', 'user_input': 'photo', 'count': 1},
        is_public=True,
    )
    await database.approve_prompt(prompt['id'])
    category = await trend_catalog.create_category('Do not show', '🔐')
    await trend_catalog.set_trend_categories(prompt['id'], [category['id']])
    active = next(item for item in await trend_catalog.list_catalog(is_admin=True)
                  if item['id'] == category['id'])
    await trend_catalog.update_category(category['id'], active['revision'], is_visible=False)

    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        headers = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        preview = await client.get(
            ROOT + '/trends?view=item&trend_id=' + str(prompt['id']), headers=headers,
        )
        assert preview.status == 404
        paid = await client.post(ROOT + '/vk-trend', headers=headers, json={
            'trend_id': prompt['id'], 'reference_urls': [owned_image], 'user_values': {},
            'client_request_id': 'hidden-trend-claim-12345', 'expected_cost': 2.5,
        })
        assert paid.status in {400, 404}
        native.assert_not_awaited()


async def test_vk_only_feed_link_uses_publication_not_trend_and_never_leaks_recipe(monkeypatch):
    from unittest.mock import AsyncMock

    from bot import database

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    private_card = {
        'id': 370766, 'task_id': 'private-task-id', 'gen_type': 'video',
        'model': 'seedance_2_5', 'preview_url': 'https://assets.example/preview.mp4',
        'preview_poster_url': 'https://assets.example/poster.jpg',
        'result_url': 'https://assets.example/video.mp4',
        'result_urls': ['https://assets.example/video.mp4'],
        'likes_count': 9, 'shares_count': 3, 'comments_count': 1,
        'aspect_ratio': '9:16', 'duration': 8,
        'prompt': 'HIDDEN_AUTHORED_PROMPT_DO_NOT_LEAK',
        'reference_videos': ['https://assets.example/PRIVATE_INPUT.mp4'],
        'reference_images': ['https://assets.example/PRIVATE_INPUT.jpg'],
        'prompt_hidden': True, 'references_hidden': True,
        'feed_references_visible': False, 'prompt_actions_allowed': False,
        'author_referral_code': 'PRIVATE_REFERRAL_CODE',
        'author': 'Public author', 'feed_blurred': False,
        'publication_scope': 'feed', 'is_adult_content': False,
        'internal_api_key': 'PRIVATE_INTERNAL_KEY',
    }
    fetch = AsyncMock(return_value=private_card)
    monkeypatch.setattr(database, 'get_feed_generation_card', fetch)
    link = '?view=feed_item&gen_id=370766'
    async with preview_client() as client:
        await enable(client, vk_app_id=123, vk_community_id=239915802)
        assert (await client.get(ROOT + '/trends' + link)).status == 401
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        assert signed.status == 200
        headers = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        item = await client.get(ROOT + '/trends' + link, headers=headers)
        assert item.status == 200, await item.text()
        data = await item.json()
        assert data['item']['id'] == 370766
        assert data['item']['generation_type'] == 'video'
        assert data['item']['model'] == 'seedance_2_5'
        assert data['item']['share_link'] == 'https://vk.com/app123_-239915802#feed_370766'
        assert data['item']['can_repeat_in_app'] is False
        for secret in ('HIDDEN_AUTHORED_PROMPT', 'PRIVATE_INPUT', 'PRIVATE_REFERRAL_CODE', 'PRIVATE_INTERNAL_KEY'):
            assert secret not in str(data)
        assert 'prompt' not in data['item']
        assert 'reference_images' not in data['item']
        assert 'reference_videos' not in data['item']
        fetch.assert_awaited_with(370766, viewer_user_id=None, include_unavailable=True)
        for bad in ('0', '-9', 'abc', '1' * 200):
            assert (await client.get(ROOT + '/trends?view=feed_item&gen_id=' + bad, headers=headers)).status == 400
        fetch.return_value = None
        assert (await client.get(ROOT + '/trends' + link, headers=headers)).status == 404
        tg = await login(client, 1001)
        tg_headers = {'Authorization': 'Bearer ' + (await tg.json())['session_token']}
        assert (await client.get(ROOT + '/trends' + link, headers=tg_headers)).status == 403


async def test_vk_feed_and_trend_link_ids_are_independent_domains(monkeypatch):
    from unittest.mock import AsyncMock

    from bot import database, trend_catalog

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    feed = AsyncMock(return_value={
        'id': 11, 'gen_type': 'image', 'model': 'banana_pro',
        'preview_url': None, 'result_url': 'https://assets.example/image.jpg',
        'likes_count': 0, 'prompt': 'SECRET', 'prompt_hidden': True,
    })
    trend = AsyncMock(return_value={
        'id': 11, 'title': 'Curated trend', 'description': 'Trend description',
        'generation_settings': {'kind': 'image', 'model': 'banana_pro'},
        'preview_url': None, 'preview_poster_url': None,
    })
    monkeypatch.setattr(database, 'get_feed_generation_card', feed)
    monkeypatch.setattr(trend_catalog, 'public_trend_by_id', trend)
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        headers = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        feed_result = await client.get(ROOT + '/trends?view=feed_item&gen_id=11', headers=headers)
        trend_result = await client.get(ROOT + '/trends?view=item&trend_id=11', headers=headers)
        assert feed_result.status == 200
        assert trend_result.status == 200
        assert (await feed_result.json())['item']['share_link'].endswith('#feed_11')
        assert (await trend_result.json())['item']['share_link'].endswith('#prompt_11')
        feed.assert_awaited_once()
        trend.assert_awaited_once()


async def test_vk_common_shell_capability_requires_all_server_adapters(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    monkeypatch.setenv('VK_FULL_APP_PARITY_ENABLED', '1')
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        assert signed.status == 200
        auth = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        profile = await client.get(ROOT + '/me', headers=auth)
        assert profile.status == 200
        payload = await profile.json()
        assert payload['preview']['telegram_linked'] is False
        assert payload['preview']['full_app_ready'] is False
        # Flags cannot make an incomplete backend silently expose the full
        # studio. The backend, not the browser, must register ALL adapters.
        client.app['vk_full_app_adapter'] = SimpleNamespace(ready_operations={
            'bootstrap', 'photo', 'trends', 'feed',
        })
        profile = await client.get(ROOT + '/me', headers=auth)
        assert (await profile.json())['preview']['full_app_ready'] is False
        client.app['vk_full_app_adapter'] = SimpleNamespace(
            ready_operations=frozenset({
                'bootstrap', 'photo', 'video', 'trends', 'feed',
                'services', 'profile', 'payments', 'referrals', 'tasks',
            }),
            handle=lambda request, *, actor: web.json_response({'ok': True}),
        )
        profile = await client.get(ROOT + '/me', headers=auth)
        assert (await profile.json())['preview']['full_app_ready'] is True
        monkeypatch.delenv('VK_FULL_APP_PARITY_ENABLED')
        profile = await client.get(ROOT + '/me', headers=auth)
        assert (await profile.json())['preview']['full_app_ready'] is False


async def test_platform_actor_is_signed_and_never_invents_telegram_wallet(monkeypatch):
    from bot.shared_accounts.actor import resolve_platform_actor
    from bot.shared_accounts.errors import AuthenticationError
    from bot.shared_accounts.store import revoke_session

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        vk = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        assert vk.status == 200
        vk_token = (await vk.json())['session_token']
        tg = await login(client, 2001)
        tg_token = (await tg.json())['session_token']
        vk_actor = await resolve_platform_actor(vk_token, expected_platform='vk')
        tg_actor = await resolve_platform_actor(tg_token, expected_platform='telegram')

        assert vk_actor.platform == 'vk' and vk_actor.external_id == 2001
        assert tg_actor.platform == 'telegram' and tg_actor.external_id == 2001
        assert vk_actor.shared_account_id != tg_actor.shared_account_id
        assert vk_actor.owner_key == 'vk:2001' and tg_actor.owner_key == 'telegram:2001'
        assert vk_actor.wallet_platform == 'vk' and tg_actor.wallet_platform == 'telegram'
        assert vk_actor.linked_telegram_id is None
        with pytest.raises(PermissionError):
            await resolve_platform_actor(tg_token, expected_platform='vk')
        with pytest.raises(PermissionError):
            await resolve_platform_actor(vk_token, expected_platform='telegram')

        await revoke_session(vk_token)
        with pytest.raises(AuthenticationError):
            await resolve_platform_actor(vk_token, expected_platform='vk')
        assert (await resolve_platform_actor(tg_token)).platform == 'telegram'


async def test_platform_actor_for_vk_only_does_not_touch_legacy_telegram_users(monkeypatch):
    from bot import db as db_backend
    from bot.shared_accounts.actor import resolve_platform_actor

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        async with db_backend.connect() as db:
            before = (await (await db.execute('SELECT count(*) FROM users')).fetchone())[0]
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(34567),
        })
        assert signed.status == 200
        token = (await signed.json())['session_token']
        actor = await resolve_platform_actor(token, expected_platform='vk')
        assert actor.linked_telegram_id is None
        assert actor.account_id == actor.shared_account_id
        async with db_backend.connect() as db:
            after = (await (await db.execute('SELECT count(*) FROM users')).fetchone())[0]
        assert before == after


async def test_platform_actor_keeps_verified_wallet_platform_after_optional_link(monkeypatch):
    from bot.shared_accounts.actor import resolve_platform_actor
    from tests.test_shared_account_links import pair

    async with pair(monkeypatch) as (client, source, target):
        invitation_response = await client.post(ROOT + '/links', headers=source, json={
            'target_platform': 'vk', 'confirm_source': True,
        })
        assert invitation_response.status == 200
        invitation = (await invitation_response.json())['link']
        linked = await client.post(ROOT + '/links/accept', headers=target, json={
            'token': invitation['token'], 'confirm': True,
        })
        assert linked.status == 200
        assert (await linked.json())['link']['state'] == 'committed'
        vk_session = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        assert vk_session.status == 200
        bearer = (await vk_session.json())['session_token']
        actor = await resolve_platform_actor(bearer)
        assert actor.platform == 'vk'
        assert actor.external_id == 2001
        assert actor.linked_platforms == ('telegram', 'vk')
        # Identity linking does not imply a legacy Telegram user exists.
        # The adapter must never create one to make a UI gate pass.
        assert actor.linked_telegram_id is None
        assert actor.wallet_platform == 'vk'
        assert actor.owner_key == 'vk:2001'
        assert actor.shared_account_id == (await vk_session.json())['account']['id']


async def test_native_vk_tasks_are_serialized_for_shared_ui_without_telegram(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.shared_accounts import api

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    native_state = {
        'registered': True, 'balance': 43.75, 'is_blocked': False,
        'tasks': [
            {'task_id': 27, 'task_type': 'photo', 'model': 'nano_banana_pro',
             'status': 'completed', 'cost': 2.5, 'result_url': 'https://example.test/image.jpg',
             'created_at': '2026-11-11 10:00:00'},
            {'task_id': 25, 'task_type': 'video', 'model': 'v3_std',
             'status': 'processing', 'cost': 11.0, 'result_url': None,
             'created_at': '2026-11-11 09:00:00'},
        ],
    }
    fetch = AsyncMock(return_value=native_state)
    monkeypatch.setattr(api, 'fetch_native_vk_state', fetch)
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        response = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        bearer = {'Authorization': 'Bearer ' + (await response.json())['session_token']}
        native = await client.get(ROOT + '/vk-native-state', headers=bearer)
        assert native.status == 200, await native.text()
        payload = await native.json()
        assert payload['balance'] == 43.75
        assert payload['tasks'] == native_state['tasks']
        assert payload['recent_tasks'] == [
            {'task_id': 'vk:27', 'type': 'image', 'model': 'nano_banana_pro',
             'model_label': 'nano_banana_pro', 'aspect_ratio': '',
             'status': 'completed', 'cost': 2.5, 'result_url': 'https://example.test/image.jpg',
             'created_at': '2026-11-11 10:00:00', 'prompt_preview': ''},
            {'task_id': 'vk:25', 'type': 'video', 'model': 'v3_std',
             'model_label': 'v3_std', 'aspect_ratio': '',
             'status': 'pending', 'cost': 11.0, 'result_url': None,
             'created_at': '2026-11-11 09:00:00', 'prompt_preview': ''},
        ]
        fetch.assert_awaited_once_with(2001)
        tg = await login(client, 2001)
        tg_bearer = {'Authorization': 'Bearer ' + (await tg.json())['session_token']}
        assert (await client.get(ROOT + '/vk-native-state', headers=tg_bearer)).status == 403
        fetch.assert_awaited_once()


def test_native_task_serializer_rejects_unsafe_or_wrongly_typed_rows():
    from bot.shared_accounts.task_view import serialize_native_vk_tasks

    for invalid in (
        [{'task_id': '20', 'task_type': 'photo', 'status': 'completed', 'cost': 2.5}],
        [{'task_id': 20, 'task_type': 'photo', 'status': 'done', 'cost': 2.5}],
        [{'task_id': 20, 'task_type': 'photo', 'status': 'completed', 'cost': -10}],
        [{'task_id': 20, 'task_type': 'photo', 'status': 'completed', 'cost': float('nan')}],
        [{'task_id': 20, 'task_type': 'payment', 'status': 'completed', 'cost': 2.5}],
    ):
        with pytest.raises(ValueError):
            serialize_native_vk_tasks(invalid)
    with pytest.raises(ValueError):
        serialize_native_vk_tasks('not a list')
    # Native VK also stores video-reference and Motion Control tasks. These
    # are video cards in the shared Mini App, never hidden from VK history.
    valid = [{'task_id': 77, 'task_type': 'ref_video', 'model': 'kling',
              'status': 'completed', 'cost': 8.0,
              'created_at': '2026-11-11 14:02:00', 'result_url': None},
             {'task_id': 78, 'task_type': 'motion_control', 'model': 'motion',
              'status': 'processing', 'cost': 10.0,
              'created_at': '2026-11-11 14:03:00', 'result_url': None},
             {'task_id': 79, 'task_type': 'unknown_future', 'model': 'other',
              'status': 'completed', 'cost': 0,
              'created_at': '2026-11-11 14:03:00', 'result_url': None}]
    projection = serialize_native_vk_tasks(valid, strict=False)
    assert [row['task_id'] for row in projection] == ['vk:77', 'vk:78']
    assert all(row['type'] == 'video' for row in projection)



@pytest.mark.asyncio
async def test_platform_gateway_routes_signed_vk_to_shared_app_without_telegram(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.shared_accounts.gateway import (
        VK_FULL_APP_OPERATIONS,
        vk_miniapp_gateway,
    )

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    monkeypatch.setenv('VK_FULL_APP_PARITY_ENABLED', '1')
    legacy = AsyncMock(return_value=web.json_response({'source': 'telegram-legacy'}))
    native = AsyncMock(return_value=web.json_response({'source': 'vk-native'}))
    class Adapter:
        ready_operations = VK_FULL_APP_OPERATIONS
        handle = native

    app = web.Application(middlewares=[vk_miniapp_gateway('/mini-app')])
    app['vk_full_app_adapter'] = Adapter()
    setup_shared_account_routes(app, '/mini-app')
    app.router.add_post('/mini-app/api/bootstrap', legacy)
    async with TestClient(TestServer(app)) as client:
        await enable(client, vk_app_id=123)
        login = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        assert login.status == 200
        token = (await login.json())['session_token']
        payload = {'init_data': 'vk_session:' + token}
        native_response = await client.post('/mini-app/api/bootstrap', json=payload)
        assert native_response.status == 200
        assert (await native_response.json())['source'] == 'vk-native'
        native.assert_awaited_once()
        _, kwargs = native.await_args
        assert kwargs['actor'].platform == 'vk'
        assert kwargs['actor'].external_id == 2001
        assert kwargs['actor'].linked_telegram_id is None
        assert kwargs['actor'].wallet_platform == 'vk'
        legacy.assert_not_awaited()

        telegram_response = await client.post('/mini-app/api/bootstrap', json={
            'init_data': telegram_launch(1001),
        })
        assert telegram_response.status == 200
        assert (await telegram_response.json())['source'] == 'telegram-legacy'
        legacy.assert_awaited_once()


@pytest.mark.asyncio
async def test_platform_gateway_rejects_invalid_vk_session_and_unready_adapter(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.shared_accounts.gateway import vk_miniapp_gateway

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    monkeypatch.setenv('VK_FULL_APP_PARITY_ENABLED', '1')
    legacy = AsyncMock(return_value=web.json_response({'legacy': True}))
    app = web.Application(middlewares=[vk_miniapp_gateway('/mini-app')])
    setup_shared_account_routes(app, '/mini-app')
    app.router.add_post('/mini-app/api/bootstrap', legacy)
    async with TestClient(TestServer(app)) as client:
        await enable(client, vk_app_id=123)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        token = (await signed.json())['session_token']
        # Enabling the flag without a complete ready adapter must fail closed.
        result = await client.post('/mini-app/api/bootstrap', json={'init_data':'vk_session:'+token})
        assert result.status == 503
        legacy.assert_not_awaited()
        invalid = await client.post('/mini-app/api/bootstrap', json={
            'init_data': 'vk_session:' + 'a' * 43,
        })
        assert invalid.status == 401
        spoof = await client.post('/mini-app/api/bootstrap', json={
            'init_data': 'vk_session:' + token,
            'telegram_id': 2001,
        })
        assert spoof.status == 400
        legacy.assert_not_awaited()
        for identity_field in ('user_id', 'vk_user_id', 'owner_key'):
            denied = await client.post('/mini-app/api/bootstrap', json={
                'init_data': 'vk_session:' + token,
                identity_field: 2001,
            })
            assert denied.status == 400
        legacy.assert_not_awaited()
        # Conflicting header and body credentials must not select one actor
        # while passing the other credential to the native handler.
        conflict = await client.post(
            '/mini-app/api/bootstrap', json={'init_data': telegram_launch(1001)},
            headers={'X-Telegram-Init-Data': 'vk_session:' + token},
        )
        assert conflict.status == 400
        legacy.assert_not_awaited()
        header_spoof = await client.post(
            '/mini-app/api/bootstrap', json={'vk_user_id': 9999},
            headers={'X-Telegram-Init-Data': 'vk_session:' + token},
        )
        assert header_spoof.status == 400
        legacy.assert_not_awaited()
        # Opaque signed VK bearer must never be accepted in a URL query:
        # query strings leak via logs, referrers and browser history.
        query_token = await client.post(
            '/mini-app/api/bootstrap?init_data=vk_session:' + token, json={},
        )
        assert query_token.status == 400
        legacy.assert_not_awaited()

        monkeypatch.setenv('VK_FULL_APP_PARITY_ENABLED', '0')
        # Even with the full adapter disabled, a bearer in a URL must not
        # reach the legacy handler (logs, proxies and browser history leak it).
        off_query = await client.post(
            '/mini-app/api/bootstrap?init_data=vk_session:' + token, json={},
        )
        assert off_query.status == 400
        legacy.assert_not_awaited()
        # Proxies and access logs capture every query key, not just init_data.
        # Never let a bearer disguised as a different parameter through.
        for query in ('session', 'token', 'next'):
            leaked = await client.post(
                '/mini-app/api/bootstrap?' + query + '=vk_session:' + token, json={},
            )
            assert leaked.status == 400
        legacy.assert_not_awaited()
        fallback = await client.post('/mini-app/api/bootstrap', json={
            'init_data': 'vk_session:' + token,
        })
        # Native bootstrap is disabled; it must fail closed, not silently
        # enter the Telegram-owned legacy endpoint with a VK credential.
        assert fallback.status == 503
        legacy.assert_not_awaited()

def test_actual_miniapp_setup_installs_single_shared_vk_gateway():
    from bot import miniapp

    app = web.Application()
    miniapp.setup_miniapp_routes(app)
    middleware_names = [
        getattr(callback, "__qualname__", "")
        for callback in app.middlewares
    ]
    assert sum("vk_miniapp_gateway.<locals>.middleware" in name
               for name in middleware_names) == 1
    assert any("cors" in name for name in middleware_names)
    assert any("json_errors" in name for name in middleware_names)


@pytest.mark.asyncio
async def test_partial_native_vk_history_uses_same_route_without_opening_full_shell(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot.shared_accounts.gateway import vk_miniapp_gateway
    from bot.shared_accounts.native_tasks import VkNativeTasksAdapter

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    monkeypatch.setenv('VK_NATIVE_TASKS_ENABLED', '1')
    monkeypatch.delenv('VK_FULL_APP_PARITY_ENABLED', raising=False)

    native_service = SimpleNamespace(
        history=AsyncMock(return_value={
            'ok': True, 'recent_tasks': [{'task_id': 'vk:22'}],
            'next_cursor': None, 'cursor_reset': False,
        }),
        detail=AsyncMock(return_value={
            'ok': True, 'task': {
                'task_id': 'vk:22', 'prompt': '',
                'prompt_hidden': True,
            },
        }),
    )
    legacy = AsyncMock(side_effect=lambda request: web.json_response({'legacy': True}))
    app = web.Application(middlewares=[vk_miniapp_gateway('/mini-app')])
    app['vk_native_tasks_adapter'] = VkNativeTasksAdapter(native_service)
    setup_shared_account_routes(app, '/mini-app')
    app.router.add_post('/mini-app/api/task-history', legacy)
    app.router.add_post('/mini-app/api/task-detail', legacy)

    async with TestClient(TestServer(app)) as client:
        print('TRACE_NATIVE_TASK_GATE','        await enable(client, vk_app_id=123)',flush=True)
        await enable(client, vk_app_id=123)
        print('TRACE_NATIVE_TASK_GATE',"        signed = await client.post(ROOT + '/sess",flush=True)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        assert signed.status == 200
        token = (await signed.json())['session_token']
        auth = {'init_data': 'vk_session:' + token}

        # Old separate shell remains blocked, but this one native domain
        # already answers using the SAME route/DTO as Telegram.
        print('TRACE_NATIVE_TASK_GATE',"        preview = await client.get(ROOT + '/me',",flush=True)
        preview = await client.get(ROOT + '/me', headers={
            'Authorization': 'Bearer ' + token,
        })
        assert (await preview.json())['preview']['full_app_ready'] is False
        print('TRACE_NATIVE_TASK_GATE',"        response = await client.post('/mini-app/",flush=True)
        response = await client.post('/mini-app/api/task-history', json=auth)
        assert response.status == 200
        assert (await response.json())['recent_tasks'][0]['task_id'] == 'vk:22'
        native_service.history.assert_awaited_once()
        actual_actor = native_service.history.await_args.args[0]
        assert actual_actor.platform == 'vk' and actual_actor.external_id == 2001
        assert actual_actor.linked_telegram_id is None
        print('TRACE_NATIVE_TASK_GATE',"        detail = await client.post('/mini-app/ap",flush=True)
        detail = await client.post('/mini-app/api/task-detail',
                                   json={**auth, 'task_id': 'vk:22'})
        assert detail.status == 200
        assert (await detail.json())['task']['prompt_hidden'] is True
        legacy.assert_not_awaited()

        print('TRACE_NATIVE_TASK_GATE',"        malicious = await client.post('/mini-app",flush=True)
        malicious = await client.post('/mini-app/api/task-history',
                                      json={**auth, 'telegram_id': 2001})
        assert malicious.status == 400
        print('TRACE_NATIVE_TASK_GATE',"        invalid = await client.post('/mini-app/a",flush=True)
        invalid = await client.post('/mini-app/api/task-history',
                                    json={'init_data': 'vk_session:invalid'})
        assert invalid.status == 401
        assert native_service.history.await_count == 1
        assert legacy.await_count == 0

        print('TRACE_NATIVE_TASK_GATE',"        tg = await client.post('/mini-app/api/ta",flush=True)
        tg = await client.post('/mini-app/api/task-history', json={
            'init_data': telegram_launch(1001),
        })
        assert tg.status == 200
        assert (await tg.json())['legacy'] is True
        legacy.assert_awaited_once()

        monkeypatch.setenv('VK_NATIVE_TASKS_ENABLED', '0')
        print('TRACE_NATIVE_TASK_GATE',"        fallback = await client.post('/mini-app/",flush=True)
        fallback = await client.post('/mini-app/api/task-history', json=auth)
        # Disabling the native task adapter must not silently project a
        # signed VK actor into Telegram's legacy task history.
        assert fallback.status == 503
        assert legacy.await_count == 1


async def test_native_vk_video_quote_signed_identity_contract(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.shared_accounts import api

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    monkeypatch.setenv('VK_MINIAPP_VIDEO_WRITES_ENABLED', '1')
    bridge = AsyncMock(return_value={'task_id': 0, 'cost': 12.5, 'quote_only': True})
    monkeypatch.setattr(api, 'submit_native_vk_video', bridge, raising=False)
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        assert signed.status == 200
        token = (await signed.json())['session_token']
        headers = {'Authorization': 'Bearer ' + token}
        payload = {'model': 'v3_std', 'prompt': 'A blue vase',
                   'aspect': '16:9', 'duration': 5, 'quote_only': True}
        denied = await client.post(ROOT + '/vk-video', json=payload)
        assert denied.status == 401
        tg = await login(client, 1001)
        tg_headers = {'Authorization': 'Bearer ' + (await tg.json())['session_token']}
        denied = await client.post(ROOT + '/vk-video', headers=tg_headers, json=payload)
        assert denied.status == 403
        denied = await client.post(ROOT + '/vk-video', headers=headers,
                                   json={**payload, 'vk_user_id': 9999})
        assert denied.status == 400
        bridge.assert_not_awaited()
        quote = await client.post(ROOT + '/vk-video', headers=headers, json=payload)
        assert quote.status == 200, await quote.text()
        assert (await quote.json())['quote_only'] is True
        bridge.assert_awaited_once_with(2001, {**payload, 'reference_photos': []})


async def test_native_vk_video_disabled_even_if_photo_enabled(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.shared_accounts import api

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    monkeypatch.setenv('VK_MINIAPP_WRITES_ENABLED', '1')
    monkeypatch.delenv('VK_MINIAPP_VIDEO_WRITES_ENABLED', raising=False)
    bridge = AsyncMock()
    monkeypatch.setattr(api, 'submit_native_vk_video', bridge, raising=False)
    async with preview_client() as client:
        await enable(client, vk_app_id=123)
        signed = await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(2001),
        })
        headers = {'Authorization': 'Bearer ' + (await signed.json())['session_token']}
        result = await client.post(ROOT + '/vk-video', headers=headers, json={
            'model': 'v3_std', 'prompt': 'A vase', 'aspect': '16:9',
            'duration': 5, 'quote_only': True,
        })
        assert result.status == 404
        bridge.assert_not_awaited()


async def test_native_vk_video_bridge_hmac_exact_body_and_loopback(monkeypatch):
    import hashlib
    import hmac

    from bot.shared_accounts.vk_native import submit_native_vk_video

    monkeypatch.setenv('VK_MINIAPP_VIDEO_WRITES_ENABLED', '1')
    monkeypatch.setenv('INTERNAL_API_SECRET', 'video-bridge-test-secret')
    capture = []

    async def quote(request):
        raw = await request.read()
        timestamp = request.headers['X-Internal-Timestamp']
        signature = request.headers['X-Internal-Signature']
        expected = hmac.new(
            b'video-bridge-test-secret',
            b'\n'.join([timestamp.encode(), b'POST', request.path.encode(), raw]),
            hashlib.sha256,
        ).hexdigest()
        assert hmac.compare_digest(signature, expected)
        assert request.path.endswith('/users/2001/generations/video')
        capture.append(raw)
        return web.json_response({'ok': True, 'task_id': 0, 'cost': 9.5, 'quote_only': True})

    server = web.Application()
    server.router.add_post('/internal/v1/miniapp/users/2001/generations/video', quote)
    async with TestClient(TestServer(server)) as client:
        monkeypatch.setenv('VK_NATIVE_INTERNAL_ORIGIN', f'http://127.0.0.1:{client.server.port}')
        result = await submit_native_vk_video(2001, {
            'model': 'v3_std', 'prompt': 'Синее море',
            'aspect': '16:9', 'duration': 5, 'quote_only': True,
        })
        assert result == {'task_id': 0, 'cost': 9.5, 'quote_only': True}
        assert len(capture) == 1
        with pytest.raises(ValueError):
            await submit_native_vk_video(2001, {'prompt': 'x' * 40000})
    monkeypatch.setenv('VK_NATIVE_INTERNAL_ORIGIN', 'https://other.example')
    with pytest.raises(RuntimeError):
        await submit_native_vk_video(2001, {'quote_only': True})
