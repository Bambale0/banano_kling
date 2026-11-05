"""Money invariants through the authenticated administrator sandbox API."""
import asyncio
from contextlib import asynccontextmanager

import pytest

from bot import db as db_backend
from bot.shared_accounts.wallet import WalletService
from tests.test_shared_accounts import (
    ROOT,
    account_database,
    enable,
    login,
    preview_client,
)

__all__ = ['account_database']


@asynccontextmanager
async def funded_wallet(amount='10'):
    async with preview_client() as client:
        await enable(client)
        token = (await (await login(client)).json())['session_token']
        headers = {'Authorization': 'Bearer ' + token}

        async def command(action, value, key, reference=''):
            return await client.post(ROOT + '/wallet', headers=headers, json={
                'action': action, 'amount': value, 'idempotency_key': key, 'reference_key': reference,
            })

        assert (await command('credit', amount, 'funds')).status == 200
        yield client, headers, command


async def test_wallet_starts_empty_in_a_separate_sandbox():
    async with preview_client() as client:
        await enable(client)
        token = (await (await login(client)).json())['session_token']
        response = await client.get(ROOT + '/wallet', headers={'Authorization': 'Bearer ' + token})
        assert response.status == 200
        body = await response.json()
        assert body['scope'] == 'sandbox'
        assert body['balance'] == {'available': '0.0000', 'reserved': '0.0000', 'revision': 0}


async def test_domain_wallet_snapshot_is_exact_on_both_engines():
    async with preview_client() as client:
        await enable(client)
        account_id = (await (await login(client)).json())['account']['id']
        assert (await WalletService('sandbox').snapshot(account_id))['balance']['available'] == '0.0000'


async def test_exact_credits_and_retries_never_duplicate_money():
    async with preview_client() as client:
        await enable(client)
        token = (await (await login(client)).json())['session_token']
        headers = {'Authorization': 'Bearer ' + token}
        for key, amount in [('credit-1', '0.1000'), ('credit-2', '0.2000'), ('credit-2', '0.2000')]:
            response = await client.post(ROOT + '/wallet', headers=headers, json={
                'action': 'credit', 'amount': amount, 'idempotency_key': key,
            })
            assert response.status == 200
        data = await (await client.get(ROOT + '/wallet', headers=headers)).json()
        assert data['balance']['available'] == '0.3000'
        assert len(data['entries']) == 2


async def test_partial_capture_release_and_refund_preserve_money_once():
    async with preview_client() as client:
        await enable(client)
        token = (await (await login(client)).json())['session_token']
        headers = {'Authorization': 'Bearer ' + token}

        async def operation(action, amount, key, reference=''):
            result = await client.post(ROOT + '/wallet', headers=headers, json={
                'action': action, 'amount': amount, 'idempotency_key': key, 'reference_key': reference,
            })
            assert result.status == 200, await result.text()
            return await result.json()

        await operation('credit', '10', 'funds')
        reserved = await operation('reserve', '6', 'job-1')
        assert reserved['balance']['available'] == '4.0000'
        assert reserved['balance']['reserved'] == '6.0000'
        await operation('capture', '2', 'capture-1', 'job-1')
        released = await operation('release', '4', 'release-1', 'job-1')
        assert released['balance']['available'] == '8.0000'
        assert released['balance']['reserved'] == '0.0000'
        refunded = await operation('refund', '2', 'refund-1', 'capture-1')
        assert refunded['balance']['available'] == '10.0000'
        again = await operation('refund', '2', 'refund-1', 'capture-1')
        assert again['receipt']['replayed'] is True
        assert again['balance']['available'] == '10.0000'


async def test_reservation_cannot_spend_more_than_available():
    async with preview_client() as client:
        await enable(client)
        token = (await (await login(client)).json())['session_token']
        headers = {'Authorization': 'Bearer ' + token}
        await client.post(ROOT + '/wallet', headers=headers, json={'action': 'credit', 'amount': '5', 'idempotency_key': 'funds'})
        result = await client.post(ROOT + '/wallet', headers=headers, json={'action': 'reserve', 'amount': '6', 'idempotency_key': 'too-large'})
        assert result.status == 402
        balance = await (await client.get(ROOT + '/wallet', headers=headers)).json()
        assert balance['balance']['available'] == '5.0000'
        assert len(balance['entries']) == 1


async def test_conflicting_idempotency_key_is_rejected_without_side_effects():
    async with funded_wallet() as (client, headers, command):
        assert (await command('credit', '11', 'funds')).status == 409
        data = await (await client.get(ROOT + '/wallet', headers=headers)).json()
        assert data['balance']['available'] == '10.0000'
        assert len(data['entries']) == 1


async def test_parallel_duplicate_credit_is_one_entry():
    async with funded_wallet() as (client, headers, command):
        results = await asyncio.gather(*[command('credit', '3.125', 'payment-one') for _ in range(8)])
        assert all(r.status == 200 for r in results)
        data = await (await client.get(ROOT + '/wallet', headers=headers)).json()
        assert data['balance']['available'] == '13.1250'
        assert len(data['entries']) == 2


async def test_parallel_reservations_do_not_overspend():
    async with funded_wallet() as (client, headers, command):
        results = await asyncio.gather(command('reserve', '7', 'job-one'), command('reserve', '7', 'job-two'))
        assert sorted(r.status for r in results) == [200, 402]
        data = await (await client.get(ROOT + '/wallet', headers=headers)).json()
        assert data['balance']['available'] == '3.0000'
        assert data['balance']['reserved'] == '7.0000'


async def test_capture_racing_release_can_only_settle_once():
    async with funded_wallet() as (client, headers, command):
        await command('reserve', '6', 'job-one')
        results = await asyncio.gather(command('capture', '6', 'capture-one', 'job-one'), command('release', '6', 'release-one', 'job-one'))
        assert sorted(r.status for r in results) == [200, 409]
        data = await (await client.get(ROOT + '/wallet', headers=headers)).json()
        assert data['balance']['reserved'] == '0.0000'
        assert data['balance']['available'] in {'4.0000', '10.0000'}
        assert len(data['entries']) == 3


async def test_refunds_cannot_exceed_capture_even_with_different_keys():
    async with funded_wallet() as (client, headers, command):
        await command('reserve', '5', 'job-one')
        await command('capture', '5', 'capture-one', 'job-one')
        results = await asyncio.gather(command('refund', '5', 'refund-one', 'capture-one'), command('refund', '5', 'refund-two', 'capture-one'))
        assert sorted(r.status for r in results) == [200, 409]
        data = await (await client.get(ROOT + '/wallet', headers=headers)).json()
        assert data['balance']['available'] == '10.0000'
        assert len(data['entries']) == 4


@pytest.mark.parametrize('amount', [0, -1, True, None, 0.1, 'NaN', 'Infinity', '-1', '0.00001', '1e-100000000', '1e100000000', '1.' + '0' * 100 + '1'])
async def test_invalid_and_inexact_amounts_never_change_money(amount):
    async with funded_wallet() as (client, headers, command):
        response = await command('credit', amount, 'invalid-amount')
        assert response.status == 400
        data = await (await client.get(ROOT + '/wallet', headers=headers)).json()
        assert data['balance']['available'] == '10.0000'
        assert len(data['entries']) == 1


async def test_ledger_rows_are_append_only():
    async with funded_wallet() as (client, headers, _command):
        for statement in ['UPDATE shared_wallet_entries SET amount_units = 1', 'DELETE FROM shared_wallet_entries']:
            async with db_backend.connect() as db:
                with pytest.raises(Exception, match='append-only'):
                    await db.execute(statement)
                await db.rollback()
        data = await (await client.get(ROOT + '/wallet', headers=headers)).json()
        assert len(data['entries']) == 1
        assert data['entries'][0]['amount'] == '10.0000'


async def test_failed_ledger_insert_rolls_back_reservation_and_balance():
    async with funded_wallet() as (client, headers, command):
        async with db_backend.connect() as db:
            execute = getattr(db, 'execute_native_ddl', db.execute)
            if db_backend.is_postgres():
                await execute('ALTER TABLE shared_wallet_entries ADD CONSTRAINT test_reject_wallet_entry CHECK(amount_units < 0) NOT VALID')
            else:
                await execute("CREATE TRIGGER test_reject_wallet_entry BEFORE INSERT ON shared_wallet_entries BEGIN SELECT RAISE(ABORT, 'synthetic journal failure'); END")
            await db.commit()
        assert (await command('reserve', '6', 'fail-reserve')).status == 503
        data = await (await client.get(ROOT + '/wallet', headers=headers)).json()
        assert data['balance']['available'] == '10.0000'
        assert data['balance']['reserved'] == '0.0000'
        assert len(data['entries']) == 1


async def test_client_cannot_select_live_scope_or_another_owner():
    async with funded_wallet() as (client, headers, _command):
        result = await client.post(ROOT + '/wallet', headers=headers, json={
            'action': 'credit', 'amount': '1', 'idempotency_key': 'sandbox-only',
            'scope': 'live', 'account_id': 'victim-account',
        })
        data = await result.json()
        assert result.status == 200
        assert data['scope'] == 'sandbox'
        assert data['balance']['available'] == '11.0000'


async def test_wallet_requires_current_administrator_session():
    async with preview_client() as client:
        assert (await client.get(ROOT + '/wallet')).status == 404
        await enable(client)
        assert (await client.post(ROOT + '/wallet', json={'action': 'credit', 'amount': '10', 'idempotency_key': 'fake', 'is_admin': True})).status == 401


async def test_reconciliation_detects_mutable_wallet_drift_without_repairing_it():
    async with funded_wallet() as (client, headers, _command):
        account = (await (await client.get(ROOT + '/me', headers=headers)).json())['account']['id']
        service = WalletService('sandbox')
        assert (await service.reconcile(account))['consistent'] is True
        async with db_backend.connect() as db:
            await db.execute('UPDATE shared_wallets SET available_units = available_units + 1 WHERE scope = ? AND account_id = ?', ('sandbox', account))
            await db.commit()
        report = await service.reconcile(account)
        assert report['consistent'] is False
        assert report['issues'] == ['available_ledger_mismatch']
        assert (await service.snapshot(account))['balance']['available'] == '10.0001'


async def test_reconciliation_tracks_partial_settlement_and_refund():
    async with funded_wallet() as (client, headers, command):
        account = (await (await client.get(ROOT + '/me', headers=headers)).json())['account']['id']
        for action, amount, key, reference in [
            ('reserve', '6', 'check:reserve', ''), ('capture', '2', 'check:capture', 'check:reserve'),
            ('release', '1', 'check:release', 'check:reserve'), ('refund', '1', 'check:refund', 'check:capture'),
        ]:
            assert (await command(action, amount, key, reference)).status == 200
        assert await WalletService('sandbox').reconcile(account) == {
            'scope': 'sandbox', 'consistent': True, 'issues': [], 'ledger_entries': 5,
            'open_reservations': 1, 'balance': {'available': '6.0000', 'reserved': '3.0000', 'revision': 5},
        }


async def test_reconciliation_http_is_admin_only_and_sandbox_scoped():
    async with funded_wallet() as (client, headers, _):
        report = await client.get(ROOT + '/wallet/reconcile?scope=live', headers=headers)
        assert report.status == 200
        assert (await report.json())['scope'] == 'sandbox'
        assert (await client.get(ROOT + '/wallet/reconcile')).status == 401


async def test_reconciliation_detects_reservation_counter_drift():
    async with funded_wallet() as (client, headers, command):
        assert (await command('reserve', '4', 'drift:reserve')).status == 200
        account = (await (await client.get(ROOT + '/me', headers=headers)).json())['account']['id']
        async with db_backend.connect() as db:
            await db.execute('UPDATE shared_wallet_reservations SET released_units = 1 WHERE scope = ? AND reservation_key = ?', ('sandbox', 'drift:reserve'))
            await db.commit()
        report = await WalletService('sandbox').reconcile(account)
        assert report['issues'] == ['reservation_balance_mismatch', 'reservation_settlement_mismatch']


async def test_reconciliation_detects_operation_amount_delta_disagreement():
    async with funded_wallet() as (client, headers, _):
        account = (await (await client.get(ROOT + '/me', headers=headers)).json())['account']['id']
        async with db_backend.connect() as db:
            # Valid CHECK constraints but economically wrong: a malformed writer
            # grants two units while declaring a one-unit credit.
            await db.execute('''INSERT INTO shared_wallet_entries(scope, operation_key, account_id, request_hash, kind,
                amount_units, reference_key, available_delta, reserved_delta, available_after, reserved_after, sequence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                             ('sandbox', 'corrupt:credit', account, 'not-a-real-request-hash', 'credit', 10000, '', 20000, 0, 120000, 0, 2))
            await db.execute('UPDATE shared_wallets SET available_units = 120000, revision = 2 WHERE scope = ? AND account_id = ?', ('sandbox', account))
            await db.commit()
        report = await WalletService('sandbox').reconcile(account)
        assert report['consistent'] is False
        assert report['issues'] == ['ledger_operation_delta_mismatch']
