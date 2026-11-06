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

    from bot.postgres_pool import close_postgres_pool

    parsed = urlsplit(dsn)
    assert parsed.hostname in {'localhost', '127.0.0.1'}
    assert parsed.path == '/banano_shared_test'
    schema = 'shared_preview_' + uuid4().hex
    await close_postgres_pool()
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute('CREATE SCHEMA ' + schema)
        await connection.execute('SET search_path TO ' + schema)
        # Exercise the actual application bootstrap plus its compatibility layer,
        # whose startup also prepares legacy generation/credit columns.
        await connection.execute((Path(__file__).parents[1] / 'schema_postgres.sql').read_text())
    query = parse_qsl(parsed.query) + [('options', '-csearch_path=' + schema)]
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
        assert profile_data['preview']['telegram_linked'] is False
        again = await (await login(client)).json()
        assert again['account']['id'] == session['account']['id']
        assert 'credits' not in session['account']  # No invented/migrated wallet.
        assert (await client.post(ROOT + '/logout', headers=headers)).status == 200
        assert (await client.get(ROOT + '/me', headers=headers)).status == 401


async def test_enabled_preview_still_rejects_ordinary_telegram_user():
    async with preview_client() as client:
        await enable(client)
        assert (await login(client, 1001)).status == 403


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


async def test_vk_administrator_needs_own_platform_allowlist(monkeypatch):
    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    async with preview_client() as client:
        await enable(client, vk_app_id=123, vk_admin_ids=[2001])
        response = await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2001)})
        assert response.status == 200
        data = await response.json()
        assert data['account']['identity'] == {'platform': 'vk', 'external_id': 2001}
        # A VK number equal to a Telegram administrator is not a VK administrator.
        denied = await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(ADMIN)})
        assert denied.status == 403
        telegram = await (await login(client)).json()
        assert telegram['account']['id'] != data['account']['id']


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


async def test_vk_removal_revokes_access_without_waiting_for_expiry(monkeypatch):
    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    async with preview_client() as client:
        await enable(client, vk_app_id=123, vk_admin_ids=[2001])
        data = await (await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2001)})).json()
        headers = {'Authorization': 'Bearer ' + data['session_token']}
        await client.put(ROOT + '/settings', json={'init_data': telegram_launch(), 'expected_revision': 1, 'settings': {'vk_admin_ids': []}})
        assert (await client.get(ROOT + '/me', headers=headers)).status == 401


async def test_expired_session_is_rejected(monkeypatch):
    async with preview_client() as client:
        await enable(client)
        token = (await (await login(client)).json())['session_token']
        now = time.time()
        monkeypatch.setattr('bot.shared_accounts.store.time.time', lambda: now + 3601)
        assert (await client.get(ROOT + '/me', headers={'Authorization': 'Bearer ' + token})).status == 401


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
