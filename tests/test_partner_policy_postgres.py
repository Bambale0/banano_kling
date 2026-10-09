"""Policy acceptance against the existing guarded, disposable PostgreSQL CI DB."""
import asyncio
import json
import os
from unittest.mock import AsyncMock

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from bot import database
from bot import db as db_backend
from bot.partner_policy import (
    init_partner_policy_tables,
    mark_generation_accepted,
    reconcile_pending_invite_bonuses,
)
from tests.test_partner_approval_postgres import (
    _bootstrap_production_like_partner_schema,
)

pytestmark = pytest.mark.skipif(
    os.environ.get('PARTNER_POSTGRES_TEST') != '1',
    reason='requires the dedicated disposable PostgreSQL partner job',
)


@pytest.mark.asyncio
async def test_pg_policy_schema_concurrent_invite_and_frozen_payment(monkeypatch):
    params = conninfo_to_dict(os.environ['DATABASE_URL'])
    assert params.get('dbname') == 'banano_partner_test'
    assert params.get('host') in {'localhost', '127.0.0.1'}
    assert db_backend.is_postgres()
    await _bootstrap_production_like_partner_schema()
    async with await psycopg.AsyncConnection.connect(os.environ['DATABASE_URL']) as conn:
        for name, definition in (
            ('task_id', 'TEXT'), ('telegram_id', 'BIGINT'), ('type', 'TEXT'),
            ('preset_id', 'TEXT'), ('model', 'TEXT'), ('duration', 'INTEGER'),
            ('aspect_ratio', 'TEXT'), ('prompt', 'TEXT'), ('request_data', 'TEXT'),
            ('result_url', 'TEXT'), ('updated_at', 'TIMESTAMP'), ('completed_at', 'TIMESTAMP'),
            ('source_feed_gen_id', 'BIGINT'), ('parent_generation_id', 'BIGINT'), ('action_type', 'TEXT'),
        ):
            await conn.execute(f'ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS {name} {definition}')
        await conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS policy_test_task_id ON generation_tasks(task_id)')
        for name, definition in (
            ('order_id', 'TEXT'), ('payment_id', 'TEXT'), ('provider', 'TEXT'),
            ('credits', 'INTEGER'), ('amount_rub', 'REAL'), ('promo_code_id', 'BIGINT'),
            ('promo_code', 'TEXT'), ('promo_bonus_credits', 'INTEGER DEFAULT 0'),
        ):
            await conn.execute(f'ALTER TABLE transactions ADD COLUMN IF NOT EXISTS {name} {definition}')
        await conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS policy_test_order_id ON transactions(order_id)')
        await conn.commit()
    # Exercise the adapter's native-DDL seam twice, not just schema SQL directly.
    async with db_backend.connect() as conn:
        await init_partner_policy_tables(conn)
        await init_partner_policy_tables(conn)
        await conn.commit()
    partner = await database.get_or_create_user(98902001)
    buyer = await database.get_or_create_user(98902002)
    assert await database.process_referral(buyer.telegram_id, partner.referral_code)
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 0
    assert await database.deduct_credits(buyer.telegram_id, 5)
    with monkeypatch.context() as temporary:
        temporary.setattr(database, 'mark_generation_accepted', AsyncMock(return_value=False))
        await database.add_generation_task(buyer.id, buyer.telegram_id, 'pg-policy-accepted', 'image', 'test', cost=5, provider_accepted=True)
    awarded = await asyncio.gather(*(mark_generation_accepted('pg-policy-accepted') for _ in range(8)))
    assert awarded.count(True) == 1
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 3
    assert await reconcile_pending_invite_bonuses() == 0
    task = await database.get_task_by_id('pg-policy-accepted')
    assert json.loads(task.request_data)['partner_repeat_reward_rub'] == 5
    await database.create_transaction('pg-policy-payment', buyer.id, 'pg-policy-payment', 'test', 25, 1000)
    monkeypatch.setenv('PARTNER_LEVEL1_PERCENT', '20')
    result = await database.complete_payment_atomic('pg-policy-payment')
    assert result['referral_bonus']['value'] == 400
    assert (await database.complete_payment_atomic('pg-policy-payment'))['already_completed'] is True
