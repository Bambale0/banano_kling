"""Product ownership must come from verified Telegram legacy provenance only."""
import pytest

from bot import db as db_backend
from bot.database import get_or_create_user
from bot.shared_accounts.auth import VerifiedIdentity
from bot.shared_accounts.errors import AuthenticationError
from bot.shared_accounts.store import Account, create_session
from tests.test_shared_accounts import account_database

__all__ = ['account_database']


async def actor_for(platform, external_id):
    account, _, _ = await create_session(VerifiedIdentity(platform, external_id), 60, 1)
    return account


async def test_actor_keeps_verified_vk_identity_and_no_synthetic_telegram_owner():
    from bot.shared_accounts.actor import resolve_actor
    user = await get_or_create_user(1001)
    account = await actor_for('vk', 2001)
    async with db_backend.connect() as db:
        await db.execute('INSERT INTO shared_account_legacy_links VALUES (?, ?, ?)', ('vk', user.id, account.id))
        await db.commit()
    actor = await resolve_actor(account)
    assert actor.account_id == account.id
    assert actor.identity == VerifiedIdentity('vk', 2001)
    assert actor.owner_user_id is None and actor.telegram_id is None
    with pytest.raises(AuthenticationError):
        actor.require_telegram_owner()


async def test_actor_resolves_existing_owner_without_confusing_external_id():
    from bot.shared_accounts.actor import resolve_actor
    user = await get_or_create_user(1001)
    account = await actor_for('telegram', 1001)
    actor = await resolve_actor(account)
    assert actor.owner_user_id == user.id
    assert actor.telegram_id == 1001
    assert actor.require_telegram_owner() == 1001


@pytest.mark.parametrize('case', ['mismatch', 'dangling', 'ambiguous', 'forged'])
async def test_actor_fails_closed_for_invalid_owner_provenance(case):
    from bot.shared_accounts.actor import resolve_actor
    user = await get_or_create_user(1001)
    other = await get_or_create_user(1002)
    account = await actor_for('telegram', 1001)
    async with db_backend.connect() as db:
        if case == 'mismatch':
            await db.execute('UPDATE shared_account_legacy_links SET legacy_user_id = ?', (other.id,))
        elif case == 'dangling':
            await db.execute('UPDATE shared_account_legacy_links SET legacy_user_id = ?', (999999,))
        elif case == 'ambiguous':
            await db.execute('INSERT INTO shared_account_legacy_links VALUES (?, ?, ?)', ('telegram', other.id, account.id))
        await db.commit()
    if case == 'forged':
        account = Account(account.id, VerifiedIdentity('vk', 1001))
    with pytest.raises(AuthenticationError):
        await resolve_actor(account)
    if case != 'forged':
        from bot.shared_accounts.store import linked_telegram_id
        with pytest.raises(AuthenticationError):
            await linked_telegram_id(account.id)
    assert user.id != 1001


@pytest.mark.parametrize('valid_provenance', [False, True])
async def test_merge_rejects_conflicting_product_owners_before_mutation(monkeypatch, valid_provenance):
    from unittest.mock import AsyncMock

    from bot.shared_accounts import links
    from tests.test_shared_account_links import commit_link, pair
    from tests.test_shared_accounts import ADMIN, ROOT

    first = await get_or_create_user(ADMIN)
    second = await get_or_create_user(1002)
    async with pair(monkeypatch) as (client, source, target):
        vk_id = (await (await client.get(ROOT + '/me', headers=target)).json())['account']['id']
        async with db_backend.connect() as db:
            await db.execute('INSERT INTO shared_account_legacy_links VALUES (?, ?, ?)', ('telegram', second.id, vk_id))
            if valid_provenance:
                await db.execute('INSERT INTO shared_account_identities(platform, external_id, account_id) VALUES (?, ?, ?)',
                                 ('telegram', 1002, vk_id))
            await db.commit()
        before = await ownership_snapshot()
        commercial = AsyncMock()
        monkeypatch.setattr(links, 'merge_commercial_terms', commercial)
        response, _ = await commit_link(client, source, target)
        assert response.status == 409
        expected = ('Different product owners require reconciliation' if valid_provenance
                    else 'Product ownership requires reconciliation')
        assert (await response.json())['error'] == expected
        commercial.assert_not_awaited()
        assert await ownership_snapshot() == before
        async with db_backend.connect() as db:
            rows = await (await db.execute('SELECT legacy_user_id, account_id FROM shared_account_legacy_links WHERE source = ?', ('telegram',))).fetchall()
            assert len(rows) == 2
            assert len({row[1] for row in rows}) == 2
            assert {row[0] for row in rows} == {first.id, second.id}
            assert (await (await db.execute("SELECT COUNT(*) FROM shared_accounts WHERE status = 'merged'")).fetchone())[0] == 0


async def test_session_cannot_ignore_conflicting_legacy_binding():
    user = await get_or_create_user(1001)
    other = await actor_for('vk', 2001)
    async with db_backend.connect() as db:
        await db.execute('INSERT INTO shared_account_legacy_links VALUES (?, ?, ?)', ('telegram', user.id, other.id))
        await db.commit()
    with pytest.raises(AuthenticationError):
        await actor_for('telegram', 1001)
    async with db_backend.connect() as db:
        assert (await (await db.execute("SELECT COUNT(*) FROM shared_account_sessions WHERE platform = 'telegram'")).fetchone())[0] == 0


async def test_linked_actor_preserves_owner_but_not_telegram_admin_role(monkeypatch):
    from bot.shared_accounts.actor import resolve_actor
    from bot.shared_accounts.policy import PreviewPolicy
    from tests.test_shared_account_links import commit_link, pair
    from tests.test_shared_accounts import ADMIN

    user = await get_or_create_user(ADMIN)
    async with pair(monkeypatch) as (client, source, target):
        response, _ = await commit_link(client, source, target)
        assert response.status == 200
        account = await actor_for('vk', 2001)
        actor = await resolve_actor(account)
        assert actor.owner_user_id == user.id
        assert actor.telegram_id == ADMIN
        assert actor.identity == VerifiedIdentity('vk', 2001)
        assert not actor.is_administrator(PreviewPolicy())


async def ownership_snapshot():
    tables = ('shared_accounts', 'shared_account_identities', 'shared_account_legacy_links',
              'shared_wallets', 'shared_wallet_entries', 'shared_wallet_reservations')
    async with db_backend.connect() as db:
        return {table: sorted([tuple(row) for row in await (await db.execute('SELECT * FROM ' + table)).fetchall()], key=repr)
                for table in tables}


async def test_duplicate_platform_rejected_before_commercial_mutation(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.shared_accounts import links
    from tests.test_shared_account_links import commit_link, pair
    from tests.test_shared_accounts import ROOT

    async with pair(monkeypatch) as (client, source, target):
        vk_id = (await (await client.get(ROOT + '/me', headers=target)).json())['account']['id']
        async with db_backend.connect() as db:
            await db.execute('INSERT INTO shared_account_identities(platform, external_id, account_id) VALUES (?, ?, ?)',
                             ('telegram', 1002, vk_id))
            await db.commit()
        before = await ownership_snapshot()
        commercial = AsyncMock()
        monkeypatch.setattr(links, 'merge_commercial_terms', commercial)
        response, _ = await commit_link(client, source, target)
        assert response.status == 409
        assert (await response.json())['error'] == 'An account already has a different identity on this platform'
        commercial.assert_not_awaited()
        assert await ownership_snapshot() == before
