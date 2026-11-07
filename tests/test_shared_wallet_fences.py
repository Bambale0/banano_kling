"""Legacy credit writers meet a durable fence in the same database transaction."""
import asyncio
import os
from decimal import Decimal

import pytest

from bot import database
from bot import db as db_backend
from bot.shared_accounts.auth import VerifiedIdentity
from bot.shared_accounts.store import create_session
from bot.shared_accounts.wallet import WalletConflict
from tests.test_shared_accounts import account_database

__all__ = ['account_database']


@pytest.fixture(autouse=True)
async def prepared_fence_schema(account_database, monkeypatch):
    from bot.shared_accounts.fences import ensure_fence_schema

    if db_backend.is_postgres():
        from bot import postgres_aiosqlite

        # Each parametrized test owns a fresh schema. The process-global startup
        # cache must not skip real legacy compatibility DDL for the new schema.
        monkeypatch.setattr(postgres_aiosqlite, '_HELPERS_READY', False)
    async with db_backend.connect() as db:
        await ensure_fence_schema(db)


async def owner(external_id=880031):
    user = await database.get_or_create_user(external_id)
    account, _, _ = await create_session(VerifiedIdentity('telegram', external_id), 600, 1)
    return user, account


async def test_freeze_blocks_real_credit_and_direct_sql_writers_but_allows_profile_updates():
    from bot.shared_accounts.fences import freeze_telegram_wallet

    user, account = await owner()
    await database.add_credits(user.telegram_id, 7)
    before = await database.get_or_create_user(user.telegram_id)
    receipt = await freeze_telegram_wallet(account.id, user.telegram_id, 'test:lineage', 'freeze:first')
    assert Decimal(receipt['raw_balance']) == Decimal(str(before.credits))
    async with db_backend.connect() as db:
        stored = await (await db.execute('SELECT credits FROM users WHERE id = ?', (user.id,))).fetchone()
    assert receipt['raw_balance'] == str(stored[0])
    assert not receipt['replayed']
    for amount in (2, -2):
        with pytest.raises((db_backend.IntegrityError, db_backend.OperationalError), match='legacy wallet is frozen'):
            async with db_backend.connect() as db:
                await db.execute('UPDATE users SET credits = credits + ? WHERE id = ?', (amount, user.id))
                await db.commit()
    with pytest.raises((db_backend.IntegrityError, db_backend.OperationalError), match='legacy wallet is frozen'):
        await database.add_credits(user.telegram_id, 1)
    with pytest.raises((db_backend.IntegrityError, db_backend.OperationalError), match='legacy wallet is frozen'):
        await database.deduct_credits(user.telegram_id, 1)
    async with db_backend.connect() as db:
        await db.execute('UPDATE users SET username = ? WHERE id = ?', ('new-profile', user.id))
        await db.commit()
    after = await database.get_or_create_user(user.telegram_id)
    assert after.credits == before.credits
    other, _ = await owner(880032)
    assert await database.add_credits(other.telegram_id, 1)


async def test_freeze_replays_once_and_conflicts_do_not_change_the_snapshot():
    from bot.shared_accounts.fences import freeze_telegram_wallet

    user, account = await owner()
    receipts = await asyncio.gather(*[
        freeze_telegram_wallet(account.id, user.telegram_id, 'test:lineage', 'freeze:race') for _ in range(4)
    ])
    assert sum(not r['replayed'] for r in receipts) == 1
    assert len({r['id'] for r in receipts}) == 1
    for lineage, key in [('other:lineage', 'freeze:race'), ('test:lineage', 'freeze:changed')]:
        with pytest.raises(WalletConflict):
            await freeze_telegram_wallet(account.id, user.telegram_id, lineage, key)
    replay = await freeze_telegram_wallet(account.id, user.telegram_id, 'test:lineage', 'freeze:race')
    assert replay['replayed']
    assert replay['raw_balance'] == receipts[0]['raw_balance']


async def test_frozen_identity_and_receipt_cannot_be_removed_or_rewritten():
    from bot.shared_accounts.fences import freeze_telegram_wallet

    user, account = await owner()
    await freeze_telegram_wallet(account.id, user.telegram_id, 'test:lineage', 'freeze:immutable')
    for sql in (
        'UPDATE users SET shared_wallet_fence_id = NULL WHERE id = ?',
        'UPDATE users SET telegram_id = 880099 WHERE id = ?',
        'DELETE FROM users WHERE id = ?',
        'UPDATE shared_telegram_wallet_fences SET raw_balance = 999 WHERE legacy_user_id = ?',
        'DELETE FROM shared_telegram_wallet_fences WHERE legacy_user_id = ?',
    ):
        with pytest.raises((db_backend.IntegrityError, db_backend.OperationalError), match='(frozen|immutable)'):
            async with db_backend.connect() as db:
                await db.execute(sql, (user.id,))
                await db.commit()


async def test_another_account_cannot_freeze_a_legacy_wallet():
    from bot.shared_accounts.fences import freeze_telegram_wallet

    user, _ = await owner()
    _, other = await owner(880032)
    with pytest.raises(PermissionError):
        await freeze_telegram_wallet(other.id, user.telegram_id, 'test:lineage', 'freeze:foreign')
    assert await database.add_credits(user.telegram_id, 1)


async def test_concurrent_credit_is_either_in_the_snapshot_or_rejected():
    from bot.shared_accounts.fences import freeze_telegram_wallet

    user, account = await owner()
    before = await database.get_or_create_user(user.telegram_id)
    frozen, credited = await asyncio.gather(
        freeze_telegram_wallet(account.id, user.telegram_id, 'test:lineage', 'freeze:credit-race'),
        database.add_credits(user.telegram_id, 1), return_exceptions=True,
    )
    assert isinstance(frozen, dict)
    after = await database.get_or_create_user(user.telegram_id)
    assert Decimal(frozen['raw_balance']) == Decimal(str(after.credits))
    assert after.credits == before.credits + (1 if credited is True else 0)
    if credited is not True:
        assert isinstance(credited, (db_backend.IntegrityError, db_backend.OperationalError))


async def test_rejected_credit_rolls_back_earlier_transaction_change_even_if_error_is_caught():
    from bot.shared_accounts.fences import freeze_telegram_wallet

    user, account = await owner()
    await freeze_telegram_wallet(account.id, user.telegram_id, 'test:lineage', 'freeze:rollback')
    async with db_backend.connect() as db:
        await db.execute('BEGIN IMMEDIATE')
        await db.execute('UPDATE users SET username = ? WHERE id = ?', ('payment-marked-before-credit', user.id))
        with pytest.raises((db_backend.IntegrityError, db_backend.OperationalError)):
            await db.execute('UPDATE users SET credits = credits + 1 WHERE id = ?', (user.id,))
        await db.commit()
    async with db_backend.connect() as db:
        row = await (await db.execute('SELECT username FROM users WHERE id = ?', (user.id,))).fetchone()
    assert row[0] != 'payment-marked-before-credit'


async def test_real_payment_completion_cannot_settle_into_frozen_legacy_credits():
    from bot.shared_accounts.fences import freeze_telegram_wallet

    user, account = await owner()
    assert await database.create_transaction('fence:payment', user.id, 'fake:payment', 'lava', 3, 30)
    await freeze_telegram_wallet(account.id, user.telegram_id, 'test:lineage', 'freeze:payment')
    before = await database.get_or_create_user(user.telegram_id)
    for _ in range(2):
        with pytest.raises((db_backend.IntegrityError, db_backend.OperationalError), match='legacy wallet is frozen'):
            await database.complete_payment_atomic('fence:payment')
        transaction = await database.get_transaction_by_order('fence:payment')
        assert transaction.status == 'pending'
    after = await database.get_or_create_user(user.telegram_id)
    assert after.credits == before.credits


async def test_sqlite_replace_cannot_remove_fence_through_any_user_unique_key():
    from bot.shared_accounts.fences import freeze_telegram_wallet

    if db_backend.is_postgres():
        pytest.skip('SQLite REPLACE deletion semantics; PostgreSQL uses row guards and uniqueness')
    user, account = await owner()
    other, _ = await owner(880032)
    await freeze_telegram_wallet(account.id, user.telegram_id, 'test:lineage', 'freeze:replace')
    async with db_backend.connect() as db:
        row = await (await db.execute('SELECT referral_code FROM users WHERE id = ?', (user.id,))).fetchone()
    for sql, params in (
        ('INSERT OR REPLACE INTO users(id, telegram_id, credits) VALUES (?, ?, 999)', (user.id, user.telegram_id)),
        ('INSERT OR REPLACE INTO users(telegram_id, credits, referral_code) VALUES (?, 999, ?)', (880099, row[0])),
        ('UPDATE OR REPLACE users SET referral_code = ? WHERE id = ?', (row[0], other.id)),
    ):
        async with db_backend.connect() as db:
            # Exercise writers with SQLite's defaults, not just our configured connector.
            await db.execute('PRAGMA foreign_keys=OFF')
            await db.execute('PRAGMA recursive_triggers=OFF')
            with pytest.raises(db_backend.IntegrityError, match='frozen'):
                await db.execute(sql, params)
                await db.commit()


async def test_postgres_old_repeatable_read_writer_cannot_ignore_committed_freeze():
    from bot.shared_accounts.fences import ensure_fence_schema, freeze_telegram_wallet

    if not db_backend.is_postgres():
        pytest.skip('PostgreSQL MVCC contract')
    import psycopg

    user, account = await owner()
    async with db_backend.connect() as db:
        await ensure_fence_schema(db)
    async with await psycopg.AsyncConnection.connect(os.environ['DATABASE_URL']) as stale:
        await stale.execute('BEGIN ISOLATION LEVEL REPEATABLE READ')
        await stale.execute('SELECT credits FROM users WHERE id = %s', (user.id,))
        await freeze_telegram_wallet(account.id, user.telegram_id, 'test:lineage', 'freeze:mvcc')
        with pytest.raises(psycopg.errors.SerializationFailure):
            await stale.execute('UPDATE users SET credits = credits + 1 WHERE id = %s', (user.id,))
        await stale.rollback()


async def test_failed_marker_transition_rolls_back_receipt_and_same_key_can_retry():
    from bot.shared_accounts.fences import ensure_fence_schema, freeze_telegram_wallet

    user, account = await owner()
    async with db_backend.connect() as db:
        await ensure_fence_schema(db)
        execute = getattr(db, 'execute_native_ddl', db.execute)
        if db_backend.is_postgres():
            await execute('''CREATE FUNCTION test_reject_fence() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF NEW.shared_wallet_fence_id IS NOT NULL THEN RAISE EXCEPTION 'test freeze failure'; END IF;
                RETURN NEW; END $$''')
            await execute('''CREATE TRIGGER test_reject_fence BEFORE UPDATE ON users
                FOR EACH ROW EXECUTE FUNCTION test_reject_fence()''')
        else:
            await execute('''CREATE TRIGGER test_reject_fence BEFORE UPDATE ON users
                WHEN NEW.shared_wallet_fence_id IS NOT NULL
                BEGIN SELECT RAISE(ROLLBACK, 'test freeze failure'); END''')
        await db.commit()
    with pytest.raises((db_backend.IntegrityError, db_backend.OperationalError), match='test freeze failure'):
        await freeze_telegram_wallet(account.id, user.telegram_id, 'test:lineage', 'freeze:retry')
    async with db_backend.connect() as db:
        assert (await (await db.execute('SELECT COUNT(*) FROM shared_telegram_wallet_fences')).fetchone())[0] == 0
        assert (await (await db.execute('SELECT shared_wallet_fence_id FROM users WHERE id = ?', (user.id,))).fetchone())[0] is None
        await getattr(db, 'execute_native_ddl', db.execute)(
            'DROP TRIGGER test_reject_fence ON users' if db_backend.is_postgres() else 'DROP TRIGGER test_reject_fence')
        await db.commit()
    assert await database.add_credits(user.telegram_id, 1)
    assert not (await freeze_telegram_wallet(account.id, user.telegram_id, 'test:lineage', 'freeze:retry'))['replayed']


async def test_freeze_refuses_disabled_or_same_named_stale_guard():
    from bot.shared_accounts.fences import freeze_telegram_wallet

    user, account = await owner()
    async with db_backend.connect() as db:
        execute = getattr(db, 'execute_native_ddl', db.execute)
        if db_backend.is_postgres():
            await execute('ALTER TABLE users DISABLE TRIGGER shared_telegram_credit_rows')
        else:
            await execute('DROP TRIGGER shared_telegram_credit_update')
            await execute('''CREATE TRIGGER shared_telegram_credit_update
                BEFORE UPDATE ON users BEGIN SELECT 1; END''')
        await db.commit()
    with pytest.raises(WalletConflict, match='guard'):
        await freeze_telegram_wallet(account.id, user.telegram_id, 'test:lineage', 'freeze:drift')
    async with db_backend.connect() as db:
        assert (await (await db.execute('SELECT COUNT(*) FROM shared_telegram_wallet_fences')).fetchone())[0] == 0


async def test_receipt_cannot_be_replaced_even_with_recursive_triggers_disabled():
    from bot.shared_accounts.fences import freeze_telegram_wallet

    if db_backend.is_postgres():
        pytest.skip('SQLite replacement semantics')
    user, account = await owner()
    await freeze_telegram_wallet(account.id, user.telegram_id, 'test:lineage', 'freeze:receipt-replace')
    async with db_backend.connect() as db:
        await db.execute('PRAGMA recursive_triggers=OFF')
        with pytest.raises(db_backend.IntegrityError, match='immutable'):
            await db.execute('''INSERT OR REPLACE INTO shared_telegram_wallet_fences
                SELECT id, legacy_user_id, telegram_id, account_id, source_lineage, operation_key,
                '999', storage_type, guard_digest, created_at FROM shared_telegram_wallet_fences''')
            await db.commit()
