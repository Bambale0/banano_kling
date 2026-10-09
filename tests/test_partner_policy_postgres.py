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
from bot.partner_commission_settings import set_partner_commission_percent
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


async def _bootstrap_policy_schema():
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


@pytest.mark.asyncio
async def test_pg_policy_schema_concurrent_invite_and_frozen_payment(monkeypatch):
    await _bootstrap_policy_schema()
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
    await set_partner_commission_percent(999999999, partner.telegram_id, 40, expected_revision=0)
    await database.create_transaction('pg-policy-payment', buyer.id, 'pg-policy-payment', 'test', 25, 1000)
    await set_partner_commission_percent(999999999, partner.telegram_id, 0, expected_revision=1)
    result = await database.complete_payment_atomic('pg-policy-payment')
    assert result['referral_bonus']['value'] == 400
    assert (await database.complete_payment_atomic('pg-policy-payment'))['already_completed'] is True


@pytest.mark.asyncio
async def test_pg_manual_rates_serialize_audit_and_invoice_snapshots():
    from bot.partner_commission_settings import (
        PartnerCommissionConflict,
        get_partner_commission_setting,
    )
    await _bootstrap_policy_schema()
    partner = await database.get_or_create_user(98903001)
    buyer = await database.get_or_create_user(98903002)
    assert await database.process_referral(buyer.telegram_id, partner.referral_code)
    assert (await get_partner_commission_setting(partner.telegram_id))['effective_percent'] == 30
    outcomes = await asyncio.gather(
        set_partner_commission_percent(999999999, partner.telegram_id, 40, expected_revision=0),
        set_partner_commission_percent(999999999, partner.telegram_id, 0, expected_revision=0),
        return_exceptions=True,
    )
    assert sum(isinstance(result, PartnerCommissionConflict) for result in outcomes) == 1
    current = await get_partner_commission_setting(partner.telegram_id)
    setting = await set_partner_commission_percent(999999999, partner.telegram_id, 40, expected_revision=current['revision'])
    # A concurrent admin change and invoice capture must resolve to one committed
    # per-recipient rate, never the global default or a later live setting.
    created, zero = await asyncio.gather(
        database.create_transaction('pg-manual-rate', buyer.id, 'pg-manual-rate', 'test', 25, 1000),
        set_partner_commission_percent(999999999, partner.telegram_id, 0, expected_revision=setting['revision']),
    )
    assert created and zero['effective_percent'] == 0
    async with db_backend.connect() as conn:
        terms = await (await conn.execute(
            "SELECT level1_overrides_json FROM partner_payment_terms WHERE order_id = ?", ('pg-manual-rate',),
        )).fetchone()
        frozen = json.loads(terms[0])[str(partner.telegram_id)]
        assert frozen in {0,40}
        audit = await (await conn.execute(
            'SELECT COUNT(*) FROM partner_commission_audit WHERE target_telegram_id = ?', (partner.telegram_id,),
        )).fetchone()
        assert audit[0] == zero['revision']
    await set_partner_commission_percent(999999999, partner.telegram_id, 30, expected_revision=zero['revision'])
    result = await database.complete_payment_atomic('pg-manual-rate')
    assert result['referral_bonus']['value'] == frozen * 10
    assert (await database.complete_payment_atomic('pg-manual-rate'))['already_completed']
    async with db_backend.connect() as conn:
        with pytest.raises(Exception, match='append-only'):
            await conn.execute('DELETE FROM partner_commission_audit WHERE target_telegram_id = ?', (partner.telegram_id,))


@pytest.mark.asyncio
async def test_pg_custom_decimal_roundtrip_noop_and_frozen_json():
    from bot.partner_commission_settings import (
        PartnerCommissionError,
        get_partner_commission_setting,
    )
    await _bootstrap_policy_schema()
    partner = await database.get_or_create_user(98904001)
    payer = await database.get_or_create_user(98904002)
    assert await database.process_referral(payer.telegram_id, partner.referral_code)
    saved = await set_partner_commission_percent(999999999, partner.telegram_id, 33.3, expected_revision=0)
    assert (await get_partner_commission_setting(partner.telegram_id))['effective_percent'] == 33.3
    assert not (await set_partner_commission_percent(999999999, partner.telegram_id, 33.3, expected_revision=saved['revision']))['changed']
    with pytest.raises(PartnerCommissionError):
        await set_partner_commission_percent(999999999, partner.telegram_id, 33.333, expected_revision=saved['revision'])
    assert await database.create_transaction('pg-custom-decimal', payer.id, 'pg-custom-decimal', 'test', 25, 1000)
    async with db_backend.connect() as conn:
        terms = await (await conn.execute('SELECT level1_overrides_json FROM partner_payment_terms WHERE order_id = ?', ('pg-custom-decimal',))).fetchone()
        assert json.loads(terms[0])[str(partner.telegram_id)] == 33.3
        stored = await (await conn.execute('SELECT first_line_basis_points FROM partner_commission_settings WHERE telegram_id = ?', (partner.telegram_id,))).fetchone()
        assert stored[0] == 3330 and isinstance(stored[0], int)
        count = await (await conn.execute('SELECT COUNT(*) FROM partner_commission_audit WHERE target_telegram_id = ?', (partner.telegram_id,))).fetchone()
        assert count[0] == 1
