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
