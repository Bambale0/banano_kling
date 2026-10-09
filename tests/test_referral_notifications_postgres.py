"""Real adapter/transaction tests restricted to the disposable partner CI DB."""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database
from bot import db as db_backend
from bot import referral_notifications as notices
from bot.partner_policy import mark_generation_accepted
from tests.test_partner_policy_postgres import _bootstrap_policy_schema

pytestmark = pytest.mark.skipif(
    os.getenv('PARTNER_POSTGRES_TEST') != '1',
    reason='requires the dedicated disposable PostgreSQL partner job',
)


@pytest.mark.asyncio
async def test_pg_referral_receipts_atomic_and_concurrent(monkeypatch):
    await _bootstrap_policy_schema()
    partner = await database.get_or_create_user(98905001)
    buyer = await database.get_or_create_user(98905002)
    assert await database.process_referral(buyer.telegram_id, partner.referral_code)
    with monkeypatch.context() as temporary:
        temporary.setattr(database, 'mark_generation_accepted', AsyncMock(return_value=False))
        await database.add_generation_task(
            buyer.id, buyer.telegram_id, 'pg-referral-notice', 'image', 'test',
            cost=5, provider_accepted=True,
        )
    outcomes = await asyncio.gather(*(mark_generation_accepted('pg-referral-notice') for _ in range(8)))
    assert outcomes.count(True) == 1
    async with db_backend.connect() as db:
        rows = await (await db.execute(
            'SELECT kind FROM referral_notification_outbox WHERE referred_id = ?', (buyer.id,),
        )).fetchall()
        assert sorted(row[0] for row in rows) == ['attached', 'bonus']
        # Keep this test's mocked recipient isolation, without live Telegram.
        await db.execute('DELETE FROM referral_notification_outbox WHERE referred_id != ?', (buyer.id,))
        await db.commit()
    bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=123)))
    await asyncio.gather(*(notices.deliver_pending_referral_notification(bot) for _ in range(8)))
    while await notices.deliver_pending_referral_notification(bot):
        pass
    assert bot.send_message.await_count == 2
    texts = [call.kwargs['text'] for call in bot.send_message.await_args_list]
    assert 'Новый реферал' in texts[0]
    assert 'Начислен бонус' in texts[1]
    assert all(call.kwargs['chat_id'] == partner.telegram_id for call in bot.send_message.await_args_list)
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 3
    # Caller rollback removes a prepared receipt, and schema init never backfills.
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        await db.execute('DELETE FROM referral_notification_outbox WHERE referred_id = ?', (buyer.id,))
        await db.commit()
        await notices.enqueue_referral_notification(db, 'bonus', partner.id, buyer.id, 3)
        await db.rollback()
        await notices.init_referral_notification_schema(db)
        row = await (await db.execute('SELECT COUNT(*) FROM referral_notification_outbox')).fetchone()
        assert row[0] == 0
        await db.commit()


@pytest.mark.asyncio
async def test_pg_managed_templates_and_never_started_deferral():
    await _bootstrap_policy_schema()
    partner = await database.get_or_create_user(98905003, initial_telegram_chat_state='never_started')
    buyer = await database.get_or_create_user(98905004)
    await notices.save_referral_notification_settings(
        '{"max_attempts": 3, "attached_template": "Managed {identity}: {bonus}"}',
        admin_id=999999999,
    )
    try:
        assert await database.process_referral(buyer.telegram_id, partner.referral_code)
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=124)))
        assert not await notices.deliver_pending_referral_notification(bot)
        bot.send_message.assert_not_awaited()
        async with db_backend.connect() as db:
            row = await (await db.execute(
                'SELECT attempts, status FROM referral_notification_outbox WHERE referred_id = ?', (buyer.id,),
            )).fetchone()
            assert (row[0], row[1]) == (0, 'queued')
        assert await database.mark_telegram_chat_available(partner.telegram_id)
        assert await notices.deliver_pending_referral_notification(bot)
        bot.send_message.assert_awaited_once()
        assert bot.send_message.await_args.kwargs['text'].startswith('Managed ')
    finally:
        await notices.reset_referral_notification_settings(admin_id=999999999)


@pytest.mark.asyncio
async def test_pg_legacy_settings_audit_columns_migrate_without_losing_values():
    # This bootstrap verifies the disposable localhost banano_partner_test DB.
    await _bootstrap_policy_schema()
    async with db_backend.connect() as db:
        ddl = getattr(db, 'execute_native_ddl', db.execute)
        await ddl('ALTER TABLE bot_settings DROP COLUMN updated_by_telegram_id')
        await ddl('ALTER TABLE bot_settings DROP COLUMN updated_at')
        await db.execute("INSERT INTO bot_settings (key, value) VALUES ('legacy.fixture', 'preserved')")
        await notices.init_referral_notification_schema(db)
        await notices.init_referral_notification_schema(db)
        await db.commit()
    await notices.save_referral_notification_settings('{"max_attempts": 3}', admin_id=999999999)
    await notices.reset_referral_notification_settings(admin_id=999999999)
    async with db_backend.connect() as db:
        row = await (await db.execute(
            "SELECT value, updated_by_telegram_id, updated_at FROM bot_settings WHERE key = 'legacy.fixture'",
        )).fetchone()
        assert (row[0], row[1], row[2]) == ('preserved', None, None)
        row = await (await db.execute(
            'SELECT updated_by_telegram_id, updated_at FROM bot_settings WHERE key = ?',
            (notices.REFERRAL_NOTIFICATION_SETTINGS_KEY,),
        )).fetchone()
        assert row[0] == 999999999
        assert row[1] is not None
