"""Two-sided consent and money preservation at the authenticated link boundary."""
from contextlib import asynccontextmanager

from tests.test_shared_accounts import (
    ROOT,
    account_database,
    enable,
    login,
    preview_client,
    vk_launch,
)

__all__ = ['account_database']


@asynccontextmanager
async def pair(monkeypatch):
    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    async with preview_client() as client:
        await enable(client, vk_app_id=123, vk_admin_ids=[2001, 2002])
        telegram = await (await login(client)).json()
        vk = await (await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2001)})).json()
        source = {'Authorization': 'Bearer ' + telegram['session_token']}
        target = {'Authorization': 'Bearer ' + vk['session_token']}
        for headers, key, amount in [(source, 'seed:tg', '2'), (target, 'seed:vk', '3')]:
            assert (await client.post(ROOT + '/wallet', headers=headers, json={
                'action': 'credit', 'amount': amount, 'idempotency_key': key,
            })).status == 200
        yield client, source, target


async def test_link_requires_both_confirmations_and_merges_money_once(monkeypatch):
    async with pair(monkeypatch) as (client, source, target):
        created = await client.post(ROOT + '/links', headers=source, json={'target_platform': 'vk'})
        assert created.status == 200
        link = (await created.json())['link']
        assert len(link['token']) == 43
        path = ROOT + '/links/' + link['id']
        accepted = await client.post(path + '/accept', headers=target, json={'token': link['token']})
        assert accepted.status == 200
        state = (await accepted.json())['link']
        assert state['state'] == 'awaiting_confirmation'
        first = await client.post(path + '/confirm', headers=source, json={'expected_revision': state['revision']})
        state = (await first.json())['link']
        assert state['state'] == 'awaiting_confirmation'
        assert state['source_confirmed'] is True and state['target_confirmed'] is False
        merged = await client.post(path + '/confirm', headers=target, json={'expected_revision': state['revision']})
        assert merged.status == 200
        result = (await merged.json())['link']
        assert result['state'] == 'committed'
        telegram = await (await login(client)).json()
        vk = await (await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2001)})).json()
        assert telegram['account']['id'] == vk['account']['id'] == result['account_id']
        fresh = {'Authorization': 'Bearer ' + telegram['session_token']}
        profile = await (await client.get(ROOT + '/me', headers=fresh)).json()
        assert profile['preview']['linked_platforms'] == ['telegram', 'vk']
        balance = await (await client.get(ROOT + '/wallet', headers=fresh)).json()
        assert balance['balance']['available'] == '5.0000'
        replay = await client.post(path + '/confirm', headers=fresh, json={'expected_revision': 0})
        assert replay.status == 200
        assert (await (await client.get(ROOT + '/wallet', headers=fresh)).json())['balance']['available'] == '5.0000'


async def test_preview_get_and_wrong_token_cannot_bind_target(monkeypatch):
    async with pair(monkeypatch) as (client, source, target):
        result = await client.post(ROOT + '/links', headers=source, json={'target_platform': 'vk'})
        assert result.status == 200
        link = (await result.json())['link']
        path = ROOT + '/links/' + link['id']
        assert (await client.get(path + '?token=' + link['token'])).status == 401
        assert (await client.post(path + '/accept', headers=target, json={'token': 'x' * 43})).status == 401
        unchanged = await (await client.get(path, headers=source)).json()
        assert unchanged['link']['state'] == 'pending'
        assert unchanged['link']['revision'] == 0


async def commit_link(client, source, target):
    created = await (await client.post(ROOT + '/links', headers=source, json={'target_platform': 'vk'})).json()
    link = created['link']
    path = ROOT + '/links/' + link['id']
    accepted = await (await client.post(path + '/accept', headers=target, json={'token': link['token']})).json()
    first = await (await client.post(path + '/confirm', headers=source, json={'expected_revision': accepted['link']['revision']})).json()
    response = await client.post(path + '/confirm', headers=target, json={'expected_revision': first['link']['revision']})
    return response, path


async def test_merge_preserves_reservations_old_refunds_and_callback_idempotency(monkeypatch):
    from bot.shared_accounts.wallet import WalletConflict, WalletService

    async with pair(monkeypatch) as (client, source, target):
        old = (await (await client.get(ROOT + '/me', headers=target)).json())['account']['id']
        service = WalletService('sandbox')
        await service.apply(old, 'reserve', '2', 'job:old:reserve')
        await service.apply(old, 'capture', '1', 'job:old:capture', 'job:old:reserve')
        await service.apply(old, 'refund', '0.5', 'job:old:refund1', 'job:old:capture')
        merged, _ = await commit_link(client, source, target)
        assert merged.status == 200
        canonical = (await merged.json())['link']['account_id']
        assert (await service.apply(old, 'credit', '3', 'seed:vk'))['replayed'] is True
        await service.apply(old, 'release', '1', 'job:old:release', 'job:old:reserve')
        await service.apply(old, 'refund', '0.5', 'job:old:refund2', 'job:old:capture')
        import pytest
        with pytest.raises(WalletConflict):
            await service.apply(canonical, 'refund', '0.0001', 'job:old:extra', 'job:old:capture')
        balance = await service.snapshot(old)
        assert balance['balance']['available'] == '5.0000'
        assert balance['balance']['reserved'] == '0.0000'
        assert any(entry['operation_key'] == 'job:old:capture' for entry in balance['entries'])
        assert (await service.reconcile(old))['consistent'] is True
        assert (await client.post(ROOT + '/logout', headers=target)).status == 200


async def test_accept_is_not_consent_and_third_identity_cannot_take_invitation(monkeypatch):
    async with pair(monkeypatch) as (client, source, target):
        link = (await (await client.post(ROOT + '/links', headers=source, json={'target_platform': 'vk'})).json())['link']
        path = ROOT + '/links/' + link['id']
        other_session = await (await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2002)})).json()
        other = {'Authorization': 'Bearer ' + other_session['session_token']}
        assert (await client.get(path, headers=other)).status == 403
        result = await (await client.post(path + '/accept', headers=target, json={'token': link['token']})).json()
        assert result['link']['source_confirmed'] is False
        assert result['link']['target_confirmed'] is False
        assert (await client.post(path + '/accept', headers=other, json={'token': link['token']})).status == 409
        assert (await client.post(path + '/confirm', headers=other, json={'expected_revision': 1})).status == 403
        assert (await client.post(path + '/confirm', headers=source, json={'expected_revision': 0})).status == 409
        assert (await client.post(path + '/cancel', headers=target, json={'expected_revision': 1})).status == 403
        assert (await client.post(path + '/cancel', headers=source, json={'expected_revision': 1})).status == 200
        assert (await client.post(path + '/confirm', headers=target, json={'expected_revision': 2})).status == 410


async def test_expired_invitation_is_read_only_and_hash_is_the_only_stored_secret(monkeypatch):
    import time

    from bot import db as db_backend

    async with pair(monkeypatch) as (client, source, target):
        link = (await (await client.post(ROOT + '/links', headers=source, json={'target_platform': 'vk'})).json())['link']
        path = ROOT + '/links/' + link['id']
        async with db_backend.connect() as db:
            row = await (await db.execute('SELECT token_hash FROM shared_account_links WHERE id = ?', (link['id'],))).fetchone()
            assert row[0] != link['token'] and len(row[0]) == 64
            await db.execute('UPDATE shared_account_links SET expires_at_epoch = ? WHERE id = ?', (int(time.time()) - 1, link['id']))
            await db.commit()
        assert (await client.post(path + '/accept', headers=target, json={'token': link['token']})).status == 410
        assert (await client.get(path, headers=source)).status == 410


async def test_internal_transfer_keys_cannot_be_claimed_by_clients(monkeypatch):
    async with pair(monkeypatch) as (client, source, target):
        link = (await (await client.post(ROOT + '/links', headers=source, json={'target_platform': 'vk'})).json())['link']
        for suffix in ('in', 'out'):
            result = await client.post(ROOT + '/wallet', headers=target, json={
                'action': 'credit', 'amount': '1', 'idempotency_key': f'link:{link["id"]}:sandbox:{suffix}',
            })
            assert result.status == 400
        accepted = await (await client.post(ROOT + '/links/accept', headers=target, json={'token': link['token']})).json()
        assert accepted['link']['source_identity'] == {'platform': 'telegram', 'external_id': '999999999'}
        assert accepted['link']['target_identity'] == {'platform': 'vk', 'external_id': '2001'}


async def test_reverse_vk_to_telegram_link(monkeypatch):
    async with pair(monkeypatch) as (client, telegram, vk):
        created = await (await client.post(ROOT + '/links', headers=vk, json={'target_platform': 'telegram'})).json()
        path = ROOT + '/links/' + created['link']['id']
        accepted = await (await client.post(ROOT + '/links/accept', headers=telegram, json={'token': created['link']['token']})).json()
        first = await (await client.post(path + '/confirm', headers=telegram, json={'expected_revision': accepted['link']['revision']})).json()
        result = await client.post(path + '/confirm', headers=vk, json={'expected_revision': first['link']['revision']})
        assert result.status == 200 and (await result.json())['link']['state'] == 'committed'


async def test_merge_racing_late_callbacks_conserves_balance(monkeypatch):
    import asyncio

    from bot.shared_accounts.wallet import WalletService

    async with pair(monkeypatch) as (client, source, target):
        old = (await (await client.get(ROOT + '/me', headers=target)).json())['account']['id']
        service = WalletService('sandbox')
        await service.apply(old, 'reserve', '2', 'race:reserve')
        await service.apply(old, 'capture', '1', 'race:capture', 'race:reserve')
        merged, _, _, _, _ = await asyncio.gather(
            commit_link(client, source, target),
            service.apply(old, 'credit', '0.5', 'race:payment'),
            service.apply(old, 'reserve', '0.5', 'race:newjob'),
            service.apply(old, 'refund', '1', 'race:refund', 'race:capture'),
            service.apply(old, 'release', '1', 'race:release', 'race:reserve'),
        )
        assert merged[0].status == 200
        snapshot = await service.snapshot(old)
        assert snapshot['balance']['available'] == '5.0000'
        assert snapshot['balance']['reserved'] == '0.5000'


async def test_conflicting_existing_platform_identity_rolls_back_merge(monkeypatch):
    from bot import db as db_backend

    async with pair(monkeypatch) as (client, source, target):
        source_id = (await (await client.get(ROOT + '/me', headers=source)).json())['account']['id']
        async with db_backend.connect() as db:
            await db.execute('INSERT INTO shared_account_identities(platform, external_id, account_id) VALUES (?, ?, ?)', ('vk', 9999, source_id))
            await db.commit()
        merged, _ = await commit_link(client, source, target)
        assert merged.status == 409
        assert (await (await client.get(ROOT + '/wallet', headers=source)).json())['balance']['available'] == '2.0000'
        assert (await (await client.get(ROOT + '/wallet', headers=target)).json())['balance']['available'] == '3.0000'


async def test_account_merge_overflow_rolls_back_wallets_identities_and_consent(monkeypatch):
    from bot.shared_accounts.wallet import MAX_UNITS, WalletService, format_units

    async with pair(monkeypatch) as (client, source, target):
        source_id = (await (await client.get(ROOT + '/me', headers=source)).json())['account']['id']
        service = WalletService('sandbox')
        await service.apply(source_id, 'credit', format_units(MAX_UNITS - 20000), 'capacity:fill')
        merged, path = await commit_link(client, source, target)
        assert merged.status == 400
        assert (await service.snapshot(source_id))['balance']['available'] == format_units(MAX_UNITS)
        assert (await (await client.get(ROOT + '/wallet', headers=target)).json())['balance']['available'] == '3.0000'
        state = (await (await client.get(path, headers=source)).json())['link']
        assert state['source_confirmed'] is True
        assert state['target_confirmed'] is False
        assert state['revision'] == 2


async def test_global_operation_key_cannot_credit_two_accounts_during_race(monkeypatch):
    import asyncio

    from bot.shared_accounts.wallet import WalletConflict, WalletService

    async with pair(monkeypatch) as (client, source, target):
        source_id = (await (await client.get(ROOT + '/me', headers=source)).json())['account']['id']
        target_id = (await (await client.get(ROOT + '/me', headers=target)).json())['account']['id']
        service = WalletService('sandbox')
        results = await asyncio.gather(
            service.apply(source_id, 'credit', '1', 'global:duplicate'),
            service.apply(target_id, 'credit', '1', 'global:duplicate'), return_exceptions=True,
        )
        assert sum(isinstance(result, WalletConflict) for result in results) == 1
        left = await service.snapshot(source_id)
        right = await service.snapshot(target_id)
        from decimal import Decimal
        assert Decimal(left['balance']['available']) + Decimal(right['balance']['available']) == 6


async def test_concurrent_final_confirmation_and_cancel_have_one_terminal_result(monkeypatch):
    import asyncio

    async with pair(monkeypatch) as (client, source, target):
        created = (await (await client.post(ROOT + '/links', headers=source, json={'target_platform': 'vk'})).json())['link']
        path = ROOT + '/links/' + created['id']
        accepted = (await (await client.post(path + '/accept', headers=target, json={'token': created['token']})).json())['link']
        confirmed = (await (await client.post(path + '/confirm', headers=source, json={'expected_revision': accepted['revision']})).json())['link']
        results = await asyncio.gather(
            client.post(path + '/confirm', headers=target, json={'expected_revision': confirmed['revision']}),
            client.post(path + '/cancel', headers=source, json={'expected_revision': confirmed['revision']}),
        )
        assert all(result.status in {200, 401, 410} for result in results)
        fresh = await (await login(client)).json()
        state = await client.get(path, headers={'Authorization': 'Bearer ' + fresh['session_token']})
        if state.status == 410:
            assert any(result.status == 410 for result in results)
        else:
            assert (await state.json())['link']['state'] == 'committed'


async def test_reconciliation_detects_orphan_reservation_on_merged_alias(monkeypatch):
    from bot import db as db_backend
    from bot.shared_accounts.wallet import WalletService

    async with pair(monkeypatch) as (client, source, target):
        result, _ = await commit_link(client, source, target)
        canonical = (await result.json())['link']['account_id']
        async with db_backend.connect() as db:
            alias = await (await db.execute("SELECT id FROM shared_accounts WHERE status = 'merged' AND merged_into = ?", (canonical,))).fetchone()
            await db.execute('INSERT INTO shared_wallet_reservations(scope, reservation_key, account_id, amount_units) VALUES (?, ?, ?, ?)', ('sandbox', 'corrupt:alias', alias[0], 10000))
            await db.commit()
        report = await WalletService('sandbox').reconcile(canonical)
        assert report['consistent'] is False
        assert 'reservation_not_canonical' in report['issues']
        assert 'reservation_ledger_mismatch' in report['issues']
        assert report['open_reservations'] == 1
