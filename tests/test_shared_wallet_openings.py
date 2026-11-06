"""Opening snapshots through the existing wallet and confirmed linking seams."""
import asyncio

import pytest

from bot.shared_accounts.openings import OpeningImportRehearsal
from bot.shared_accounts.wallet import WalletConflict, WalletService
from tests.test_shared_account_links import commit_link, pair
from tests.test_shared_accounts import (
    ROOT,
    account_database,
    enable,
    login,
    preview_client,
    vk_launch,
)

__all__ = ['account_database']


async def identities(client, source, target):
    return [(await (await client.get(ROOT + '/me', headers=h)).json())['account']['id']
            for h in (source, target)]


async def test_snapshot_replay_after_merge_cannot_import_twice(monkeypatch):
    async with pair(monkeypatch) as (client, source, target):
        tg, vk = await identities(client, source, target)
        importer = OpeningImportRehearsal()
        await importer.apply(tg, 'telegram', 999999999, '1.125', 'snapshot-1', 'a' * 64)
        await importer.apply(vk, 'vk', 2001, '2.5000', 'snapshot-1', 'b' * 64)
        merged, _ = await commit_link(client, source, target)
        assert merged.status == 200
        assert (await importer.apply(vk, 'vk', 2001, '2.5', 'snapshot-1', 'b' * 64))['replayed']
        with pytest.raises(WalletConflict):
            await importer.apply(vk, 'vk', 2001, '2.5', 'new-snapshot', 'b' * 64)
        wallet = WalletService('sandbox')
        assert (await wallet.snapshot(vk))['balance']['available'] == '8.6250'
        assert (await wallet.reconcile(vk))['consistent']


async def test_zero_opening_is_claimed_and_later_snapshot_cannot_mint_money(monkeypatch):
    async with pair(monkeypatch) as (client, source, target):
        tg, _ = await identities(client, source, target)
        importer = OpeningImportRehearsal()
        result = await importer.apply(tg, 'telegram', 999999999, '0', 'zero', 'a' * 64)
        assert not result['replayed']
        assert (await importer.apply(tg, 'telegram', 999999999, '0.0000', 'zero', 'a' * 64))['replayed']
        for amount, snapshot, evidence in [('1', 'zero', 'a' * 64), ('0', 'changed', 'a' * 64), ('0', 'zero', 'b' * 64)]:
            with pytest.raises(WalletConflict):
                await importer.apply(tg, 'telegram', 999999999, amount, snapshot, evidence)
        assert (await WalletService('sandbox').snapshot(tg))['balance']['available'] == '2.0000'


async def test_import_claim_is_platform_scoped_and_checks_identity_ownership(monkeypatch):
    async with pair(monkeypatch) as (client, source, target):
        tg, vk = await identities(client, source, target)
        importer = OpeningImportRehearsal()
        with pytest.raises(PermissionError):
            await importer.apply(tg, 'vk', 2001, '500', 'other-owner', 'b' * 64)
        # A denied call must not claim the real owner's import key.
        assert not (await importer.apply(vk, 'vk', 2001, '1', 'own', 'b' * 64))['replayed']
        assert (await WalletService('live').snapshot(vk))['balance']['available'] == '0.0000'


async def test_parallel_imports_and_merged_spending_conserve_money(monkeypatch):
    from bot.shared_accounts.wallet import InsufficientFunds

    async with pair(monkeypatch) as (client, source, target):
        tg, vk = await identities(client, source, target)
        importer = OpeningImportRehearsal()
        results = await asyncio.gather(*[
            importer.apply(vk, 'vk', 2001, '2', 'parallel', 'a' * 64) for _ in range(6)
        ])
        assert sum(not r['replayed'] for r in results) == 1
        merged, _ = await commit_link(client, source, target)
        assert merged.status == 200
        wallet = WalletService('sandbox')
        results = await asyncio.gather(
            wallet.apply(tg, 'reserve', '5', 'spend:tg'),
            wallet.apply(vk, 'reserve', '5', 'spend:vk'), return_exceptions=True,
        )
        assert sum(isinstance(r, InsufficientFunds) for r in results) == 1
        snapshot = await wallet.snapshot(vk)
        assert snapshot['balance']['available'] == '2.0000'
        assert snapshot['balance']['reserved'] == '5.0000'
        assert (await wallet.reconcile(vk))['consistent']


async def test_import_racing_merge_and_late_refund_is_conserved(monkeypatch):
    async with pair(monkeypatch) as (client, source, target):
        _, vk = await identities(client, source, target)
        importer, wallet = OpeningImportRehearsal(), WalletService('sandbox')
        await wallet.apply(vk, 'reserve', '2', 'legacy:reserve')
        await wallet.apply(vk, 'capture', '2', 'legacy:capture', 'legacy:reserve')
        merged, _, _ = await asyncio.gather(
            commit_link(client, source, target),
            importer.apply(vk, 'vk', 2001, '4.125', 'race', 'c' * 64),
            wallet.apply(vk, 'refund', '2', 'late:refund', 'legacy:capture'),
        )
        assert merged[0].status == 200
        assert (await importer.apply(vk, 'vk', 2001, '4.1250', 'race', 'c' * 64))['replayed']
        assert (await wallet.apply(vk, 'refund', '2', 'late:refund', 'legacy:capture'))['replayed']
        with pytest.raises(WalletConflict):
            await wallet.apply(vk, 'refund', '0.0001', 'late:other-refund', 'legacy:capture')
        assert (await wallet.snapshot(vk))['balance']['available'] == '9.1250'
        assert (await wallet.reconcile(vk))['consistent']


@pytest.mark.parametrize('amount', [0.1, True, None, '-1', 'NaN', 'Infinity', 'bad', '1.00001', '0.30000000000000004'])
async def test_opening_requires_reviewed_exact_amount(monkeypatch, amount):
    async with pair(monkeypatch) as (client, source, target):
        tg, _ = await identities(client, source, target)
        importer = OpeningImportRehearsal()
        with pytest.raises((ValueError, TypeError)):
            await importer.apply(tg, 'telegram', 999999999, amount, 'exact', 'd' * 64)
        # Rejected data cannot burn the claim.
        await importer.apply(tg, 'telegram', 999999999, '0.3', 'exact', 'd' * 64)
        assert (await WalletService('sandbox').snapshot(tg))['balance']['available'] == '2.3000'


async def test_opening_overflow_rolls_back_claim_and_ledger(monkeypatch):
    from bot.shared_accounts.wallet import MAX_UNITS, format_units

    async with pair(monkeypatch) as (client, source, target):
        tg, _ = await identities(client, source, target)
        importer = OpeningImportRehearsal()
        with pytest.raises(ValueError):
            await importer.apply(tg, 'telegram', 999999999, format_units(MAX_UNITS), 'overflow', 'e' * 64)
        assert not (await importer.apply(tg, 'telegram', 999999999, '1', 'ok', 'e' * 64))['replayed']
        assert (await WalletService('sandbox').snapshot(tg))['balance']['available'] == '3.0000'


async def test_failed_opening_claim_rolls_back_the_credit(monkeypatch):
    from bot import db as db_backend

    async with pair(monkeypatch) as (client, source, target):
        tg, _ = await identities(client, source, target)
        async with db_backend.connect() as db:
            execute = getattr(db, 'execute_native_ddl', db.execute)
            if db_backend.is_postgres():
                await execute('ALTER TABLE shared_wallet_opening_claims ADD CONSTRAINT test_reject_opening CHECK(amount_units < 0) NOT VALID')
            else:
                await execute("CREATE TRIGGER test_reject_opening BEFORE INSERT ON shared_wallet_opening_claims BEGIN SELECT RAISE(ABORT, 'synthetic claim failure'); END")
            await db.commit()
        with pytest.raises(Exception, match='test_reject_opening|synthetic claim failure'):
            await OpeningImportRehearsal().apply(tg, 'telegram', 999999999, '1', 'failed', 'f' * 64)
        wallet = WalletService('sandbox')
        assert (await wallet.snapshot(tg))['balance']['available'] == '2.0000'
        assert (await wallet.reconcile(tg))['consistent']


async def test_claim_is_immutable_and_legacy_refund_needs_capture_bridge(monkeypatch):
    from bot import db as db_backend

    async with pair(monkeypatch) as (client, source, target):
        tg, _ = await identities(client, source, target)
        await OpeningImportRehearsal().apply(tg, 'telegram', 999999999, '1', 'claim', 'a' * 64)
        for statement in ('DELETE FROM shared_wallet_opening_claims', 'UPDATE shared_wallet_opening_claims SET amount_units = 2'):
            async with db_backend.connect() as db:
                with pytest.raises(Exception, match='append-only'):
                    await db.execute(statement)
                await db.rollback()
        wallet = WalletService('sandbox')
        with pytest.raises(WalletConflict):
            await wallet.apply(tg, 'refund', '1', 'legacy:refund', 'missing:legacy:capture')
        assert (await wallet.snapshot(tg))['balance']['available'] == '3.0000'


async def test_equal_numeric_platform_ids_have_independent_openings(monkeypatch):
    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    async with preview_client() as client:
        await enable(client, vk_app_id=123, vk_admin_ids=[999999999])
        tg_session = await (await login(client)).json()
        vk_session = await (await client.post(ROOT + '/session', json={
            'platform': 'vk', 'launch_data': vk_launch(999999999),
        })).json()
        tg, vk = tg_session['account']['id'], vk_session['account']['id']
        assert tg != vk
        importer = OpeningImportRehearsal()
        await importer.apply(tg, 'telegram', 999999999, '1.125', 'same-ids', 'a' * 64)
        await importer.apply(vk, 'vk', 999999999, '2.5', 'same-ids', 'b' * 64)
        merged, _ = await commit_link(client,
            {'Authorization': 'Bearer ' + tg_session['session_token']},
            {'Authorization': 'Bearer ' + vk_session['session_token']})
        assert merged.status == 200
        wallet = WalletService('sandbox')
        assert (await wallet.snapshot(vk))['balance']['available'] == '3.6250'
        assert (await wallet.reconcile(vk))['consistent']


@pytest.mark.parametrize('other_amount,other_snapshot,other_evidence', [
    ('2', 'one', 'a' * 64), ('1', 'two', 'a' * 64), ('1', 'one', 'b' * 64),
])
async def test_conflicting_concurrent_imports_claim_source_only_once(monkeypatch, other_amount, other_snapshot, other_evidence):
    async with pair(monkeypatch) as (client, source, target):
        tg, _ = await identities(client, source, target)
        importer = OpeningImportRehearsal()
        results = await asyncio.gather(
            importer.apply(tg, 'telegram', 999999999, '1', 'one', 'a' * 64),
            importer.apply(tg, 'telegram', 999999999, other_amount, other_snapshot, other_evidence),
            return_exceptions=True,
        )
        assert sum(isinstance(r, WalletConflict) for r in results) == 1
        wallet = WalletService('sandbox')
        snapshot = await wallet.snapshot(tg)
        expected = {'3.0000', '4.0000'} if other_amount == '2' else {'3.0000'}
        assert snapshot['balance']['available'] in expected
        assert sum(entry['kind'] == 'opening' for entry in snapshot['entries']) == 1
        assert (await wallet.reconcile(tg))['consistent']
