import asyncio

import pytest

from bot import database
from bot import db as db_backend
from bot.partner_commission_settings import set_partner_commission_percent


@pytest.mark.asyncio
async def test_new_purchase_rates_and_recipient_exception():
    for index, (recipient, expected) in enumerate([(70101, 400), (1608435230, 300)]):
        parent = await database.get_or_create_user(70200 + index)
        partner = await database.get_or_create_user(recipient)
        buyer = await database.get_or_create_user(70300 + index)
        if index == 0:
            await set_partner_commission_percent(999999999, recipient, 40, expected_revision=0)
        async with db_backend.connect() as conn:
            await conn.execute('UPDATE users SET referred_by = ? WHERE id = ?', (parent.id, partner.id))
            await conn.execute('UPDATE users SET referred_by = ? WHERE id = ?', (partner.id, buyer.id))
            await conn.commit()
        await database.create_transaction(f'policy-{index}', buyer.id, f'payment-{index}', 'test', 25, 1000)
        result = await database.complete_payment_atomic(f'policy-{index}')
        assert result['referral_bonus']['value'] == expected
        assert result['referral_bonus']['level2_value'] == 70
        again = await database.complete_payment_atomic(f'policy-{index}')
        assert again['already_completed'] is True
        updated = await database.get_or_create_user(recipient)
        assert updated.partner_balance_rub == expected
        assert (await database.get_partner_overview(recipient))['percent'] == expected / 10


@pytest.mark.asyncio
async def test_legacy_pending_payment_keeps_original_rate():
    partner = await database.get_or_create_user(70401)
    buyer = await database.get_or_create_user(70402)
    async with db_backend.connect() as conn:
        await conn.execute('UPDATE users SET referred_by = ? WHERE id = ?', (partner.id, buyer.id))
        await conn.execute("INSERT INTO transactions(order_id, user_id, payment_id, provider, credits, amount_rub, status) VALUES ('legacy', ?, 'legacy', 'test', 25, 1000, 'pending')", (buyer.id,))
        await conn.commit()
    result = await database.complete_payment_atomic('legacy')
    assert result['referral_bonus']['value'] == 300


@pytest.mark.asyncio
async def test_referral_attachment_does_not_credit_inviter(monkeypatch):
    from bot.services import referral_service
    monkeypatch.setattr(referral_service, "DATABASE_PATH", database.DATABASE_PATH)
    partner = await database.get_or_create_user(70501)
    buyer = await database.get_or_create_user(70502)
    result = await referral_service.process_referral_click(buyer.telegram_id, partner.referral_code, source='test')
    assert result.attached, result.reason
    assert not result.notify_partner
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 0
    assert (await database.get_or_create_user(buyer.telegram_id)).credits == 5


async def _attached(monkeypatch, referrer=71101, invited=71102):
    from bot.services import referral_service
    monkeypatch.setattr(referral_service, 'DATABASE_PATH', database.DATABASE_PATH)
    partner = await database.get_or_create_user(referrer)
    buyer = await database.get_or_create_user(invited)
    assert (await referral_service.process_referral_click(buyer.telegram_id, partner.referral_code, source='test')).attached
    return partner, buyer


@pytest.mark.asyncio
async def test_accepted_generation_credits_inviter_once_after_starter_debit(monkeypatch):
    from bot.partner_policy import mark_generation_accepted
    partner, buyer = await _attached(monkeypatch)
    assert await database.deduct_credits(buyer.telegram_id, 5)
    from unittest.mock import AsyncMock
    with monkeypatch.context() as temporary:
        temporary.setattr(database, 'mark_generation_accepted', AsyncMock(return_value=False))
        await database.add_generation_task(buyer.id, buyer.telegram_id, 'real-task', 'image', 'test', cost=5, provider_accepted=True)
    assert (await database.get_or_create_user(partner.telegram_id)).credits == 5
    results = await asyncio.gather(*(mark_generation_accepted('real-task') for _ in range(8)))
    assert results.count(True) == 1
    assert (await database.get_or_create_user(partner.telegram_id)).credits == 8
    assert (await database.get_or_create_user(buyer.telegram_id)).credits == 0
    await database.add_generation_task(buyer.id, buyer.telegram_id, 'real-task-2', 'video', 'test', cost=5, provider_accepted=True)
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 3


@pytest.mark.asyncio
async def test_rejected_placeholder_and_failed_launch_do_not_qualify(monkeypatch):
    from bot.partner_policy import mark_generation_accepted
    partner, buyer = await _attached(monkeypatch)
    await database.add_generation_task(buyer.id, buyer.telegram_id, 'placeholder', 'image', 'test', cost=5)
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 0
    await database.complete_video_task('placeholder', None)
    assert await mark_generation_accepted('placeholder') is False
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 0


@pytest.mark.asyncio
async def test_historical_referrals_and_pre_invitation_tasks_are_not_backfilled(monkeypatch):
    from bot.partner_policy import mark_generation_accepted
    from bot.services import referral_service
    monkeypatch.setattr(referral_service, 'DATABASE_PATH', database.DATABASE_PATH)
    partner = await database.get_or_create_user(71201)
    buyer = await database.get_or_create_user(71202)
    await database.add_generation_task(buyer.id, buyer.telegram_id, 'pre-invitation', 'image', 'test', cost=5)
    assert (await referral_service.process_referral_click(buyer.telegram_id, partner.referral_code)).attached
    assert await mark_generation_accepted('pre-invitation') is False
    old = await database.get_or_create_user(71203)
    async with db_backend.connect() as conn:
        await conn.execute('UPDATE users SET referred_by = ? WHERE id = ?', (partner.id, old.id))
        await conn.execute('INSERT INTO referrals(referrer_id, referred_id, bonus_credits) VALUES (?, ?, 3)', (partner.id, old.id))
        await conn.commit()
    await database.add_generation_task(old.id, old.telegram_id, 'historical-invite', 'image', 'test', cost=5, provider_accepted=True)
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('disqualifier', ['self', 'cycle', 'ancestry_cycle', 'banned_inviter', 'banned_invited', 'admin', 'admin_replay', 'zero'])
async def test_qualification_keeps_security_guards(monkeypatch, disqualifier):
    from bot.partner_policy import mark_generation_accepted
    partner, buyer = await _attached(monkeypatch)
    task_type, cost, action = 'image', 5, None
    async with db_backend.connect() as conn:
        if disqualifier == 'self':
            await conn.execute('UPDATE users SET referred_by = ? WHERE id = ?', (buyer.id, buyer.id))
        if disqualifier == 'cycle':
            await conn.execute('UPDATE users SET referred_by = ? WHERE id = ?', (buyer.id, partner.id))
        if disqualifier == 'ancestry_cycle':
            await conn.execute('UPDATE users SET referred_by = ? WHERE id = ?', (partner.id, partner.id))
        if disqualifier.startswith('banned'):
            await conn.execute('UPDATE users SET is_banned = 1 WHERE id = ?', (partner.id if disqualifier == 'banned_inviter' else buyer.id,))
        await conn.commit()
    if disqualifier == 'admin':
        from bot.config import config
        monkeypatch.setattr(config, 'is_admin', lambda telegram_id: telegram_id == buyer.telegram_id)
    elif disqualifier == 'admin_replay':
        action = 'admin_replay'
    elif disqualifier == 'zero':
        cost = 0
    elif disqualifier in {'audio', 'character'}:
        task_type = disqualifier
    await database.add_generation_task(buyer.id, buyer.telegram_id, 'guarded', task_type, 'test', cost=cost, action_type=action)
    assert await mark_generation_accepted('guarded') is False
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 0


@pytest.mark.asyncio
async def test_generation_failure_after_acceptance_does_not_recredit_invite(monkeypatch):
    from bot.partner_policy import mark_generation_accepted
    partner, buyer = await _attached(monkeypatch)
    await database.add_generation_task(buyer.id, buyer.telegram_id, 'accepted-then-failed', 'image', 'test', cost=5, provider_accepted=True)
    await database.complete_video_task('accepted-then-failed', None)
    assert await mark_generation_accepted('accepted-then-failed') is False
    await database.add_generation_task(buyer.id, buyer.telegram_id, 'retry', 'image', 'test', cost=5, provider_accepted=True)
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 3


@pytest.mark.asyncio
async def test_repeat_reward_is_rubles_and_new_terms_are_frozen(monkeypatch):
    author = await database.get_or_create_user(71301)
    buyer = await database.get_or_create_user(71302)
    await database.add_generation_task(buyer.id, buyer.telegram_id, 'new-repeat', 'image', 'test', cost=2)
    monkeypatch.setenv('PARTNER_REPEAT_REWARD_RUB', '9')
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        assert await database._credit_prompt_repeat_reward_in_db(conn, author_id=author.id, repeater_id=buyer.id, source_type='feed', source_id=123, repeat_task_id='new-repeat', credits_spent=2)
        await conn.commit()
    updated = await database.get_or_create_user(author.telegram_id)
    assert updated.credits == 5
    assert updated.prompt_repeat_balance_rub == 5
    assert updated.partner_balance_rub == 5


@pytest.mark.asyncio
async def test_legacy_repeat_retains_ten_rubles():
    author = await database.get_or_create_user(71401)
    buyer = await database.get_or_create_user(71402)
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        await conn.execute("INSERT INTO generation_tasks(user_id, telegram_id, task_id, type, preset_id, cost) VALUES (?, ?, 'legacy-repeat', 'image', 'test', 2)", (buyer.id, buyer.telegram_id))
        assert await database._credit_prompt_repeat_reward_in_db(conn, author_id=author.id, repeater_id=buyer.id, source_type='feed', source_id=123, repeat_task_id='legacy-repeat', credits_spent=2)
        await conn.commit()
    assert (await database.get_or_create_user(author.telegram_id)).partner_balance_rub == 10


@pytest.mark.asyncio
async def test_payment_terms_are_frozen_when_invoice_created(monkeypatch):
    partner = await database.get_or_create_user(71501)
    buyer = await database.get_or_create_user(71502)
    async with db_backend.connect() as conn:
        await conn.execute('UPDATE users SET referred_by = ? WHERE id = ?', (partner.id, buyer.id))
        await conn.commit()
    await set_partner_commission_percent(999999999, partner.telegram_id, 40, expected_revision=0)
    await database.create_transaction('frozen', buyer.id, 'frozen', 'test', 25, 1000)
    await set_partner_commission_percent(999999999, partner.telegram_id, 20, expected_revision=1)
    result = await database.complete_payment_atomic('frozen')
    assert result['referral_bonus']['value'] == 400


@pytest.mark.asyncio
async def test_bonus_failure_never_fails_generation_and_reconciles_durable_acceptance(monkeypatch):
    from bot import partner_policy
    partner, buyer = await _attached(monkeypatch)
    real_credit = partner_policy._credit_accepted_invite_bonus
    async def broken_credit(_task):
        raise RuntimeError('temporary bonus failure')
    monkeypatch.setattr(partner_policy, '_credit_accepted_invite_bonus', broken_credit)
    assert await database.add_generation_task(buyer.id, buyer.telegram_id, 'durable', 'image', 'test', cost=5, provider_accepted=True)
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 0
    # Subsequent provider failure must not erase that the launch was accepted.
    await database.complete_video_task('durable', None)
    monkeypatch.setattr(partner_policy, '_credit_accepted_invite_bonus', real_credit)
    assert await partner_policy.reconcile_pending_invite_bonuses() == 1
    assert await partner_policy.reconcile_pending_invite_bonuses() == 0
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 3


@pytest.mark.asyncio
async def test_default_terms_survive_referral_attaching_after_invoice_creation(monkeypatch):
    partner = await database.get_or_create_user(1608435230)
    buyer = await database.get_or_create_user(71602)
    await database.create_transaction('later-referral', buyer.id, 'later-referral', 'test', 25, 1000)
    assert await database.process_referral(buyer.telegram_id, partner.referral_code)
    monkeypatch.setenv('PARTNER_LEVEL1_OVERRIDES_JSON', '{}')
    result = await database.complete_payment_atomic('later-referral')
    assert result['referral_bonus']['value'] == 300


@pytest.mark.asyncio
async def test_legacy_attachment_defers_bonus_and_current_schema_init_is_idempotent():
    partner = await database.get_or_create_user(71701)
    buyer = await database.get_or_create_user(71702)
    assert await database.process_referral(buyer.telegram_id, partner.referral_code)
    await database.init_db()
    await database.init_db()
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 0
    await database.add_generation_task(buyer.id, buyer.telegram_id, 'legacy-entry-new-invite', 'image', 'test', cost=2, provider_accepted=True)
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 3


@pytest.mark.parametrize('name,value', [('PARTNER_LEVEL2_PERCENT', '-1'), ('PARTNER_REPEAT_REWARD_RUB', 'inf'), ('PARTNER_LEVEL1_OVERRIDES_JSON', '[]'), ('PARTNER_LEVEL1_OVERRIDES_JSON', '{"1608435230":101}')])
def test_invalid_policy_fails_closed(monkeypatch, name, value):
    from bot.partner_policy import get_partner_policy
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        get_partner_policy()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['audio', 'character'])
async def test_other_paid_generation_types_qualify(monkeypatch, kind):
    partner, buyer = await _attached(monkeypatch)
    assert await database.deduct_credits(buyer.telegram_id, 2)
    await database.add_generation_task(buyer.id, buyer.telegram_id, f'accepted-{kind}', kind, 'test', cost=2, provider_accepted=True)
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 3


@pytest.mark.asyncio
async def test_schema_uses_native_ddl_when_adapter_requires_it():
    from bot.partner_policy import init_partner_policy_tables
    from bot.postgres_aiosqlite import translate_sql
    statements = []
    class NativeConnection:
        async def execute_native_ddl(self, sql):
            statements.append(sql)
        async def execute(self, sql):
            raise AssertionError('translated DDL must not silently disappear')
    await init_partner_policy_tables(NativeConnection())
    assert len(statements) >= 7
    assert all(translate_sql(sql) is None for sql in statements if sql.strip().startswith(('CREATE TABLE', 'CREATE INDEX')))
    assert any('partner_commission_settings' in sql for sql in statements)
    assert any('append-only' in sql for sql in statements)
    assert 'last_checked_at' in statements[1]


@pytest.mark.asyncio
async def test_compact_acceptance_survives_callback_outage_and_earlier_free_task(monkeypatch):
    import json
    from unittest.mock import AsyncMock

    from bot.partner_policy import reconcile_pending_invite_bonuses
    partner, buyer = await _attached(monkeypatch)
    with monkeypatch.context() as temporary:
        temporary.setattr(database, 'mark_generation_accepted', AsyncMock(return_value=False))
        await database.add_generation_task(buyer.id, buyer.telegram_id, 'free-first', 'image', 'test', cost=0, provider_accepted=True)
        await database.add_generation_task(buyer.id, buyer.telegram_id, 'paid-next', 'video', 'test', cost=2, provider_accepted=True)
    task = await database.get_task_by_id('paid-next')
    async with db_backend.connect() as conn:
        await conn.execute('UPDATE generation_tasks SET request_data = ? WHERE id = ?', (json.dumps(json.loads(task.request_data), separators=(',', ':')), task.id))
        await conn.commit()
    assert await reconcile_pending_invite_bonuses() == 1
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 3


@pytest.mark.asyncio
async def test_ineligible_pending_claim_cannot_starve_next_valid_claim(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.partner_policy import reconcile_pending_invite_bonuses
    blocked_partner, blocked_buyer = await _attached(monkeypatch, 71801, 71802)
    partner, buyer = await _attached(monkeypatch, 71803, 71804)
    with monkeypatch.context() as temporary:
        temporary.setattr(database, 'mark_generation_accepted', AsyncMock(return_value=False))
        await database.add_generation_task(blocked_buyer.id, blocked_buyer.telegram_id, 'blocked-accepted', 'image', 'test', cost=2, provider_accepted=True)
        await database.add_generation_task(buyer.id, buyer.telegram_id, 'valid-accepted', 'image', 'test', cost=2, provider_accepted=True)
    async with db_backend.connect() as conn:
        await conn.execute('UPDATE users SET is_banned = 1 WHERE id = ?', (blocked_partner.id,))
        await conn.commit()
    assert await reconcile_pending_invite_bonuses(limit=1) == 0
    assert await reconcile_pending_invite_bonuses(limit=1) == 1
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 3


@pytest.mark.asyncio
async def test_client_supplied_acceptance_and_reward_metadata_is_ignored(monkeypatch):
    import json

    from bot.partner_policy import mark_generation_accepted
    partner, buyer = await _attached(monkeypatch)
    await database.add_generation_task(buyer.id, buyer.telegram_id, 'spoofed', 'image', 'test', cost=2, request_data={'partner_policy_version': 2, 'partner_generation_accepted': True, 'partner_repeat_reward_rub': 1000, 'partner_invite_eligible': True})
    task = await database.get_task_by_id('spoofed')
    metadata = json.loads(task.request_data)
    assert metadata['partner_generation_accepted'] is False
    assert metadata['partner_repeat_reward_rub'] == 5
    assert await mark_generation_accepted('spoofed') is False
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 0


@pytest.mark.asyncio
async def test_prompt_repeat_freezes_amount_and_deduplicates_provider_aliases(monkeypatch):
    import json

    from bot import trend_api
    author = await database.get_or_create_user(71901)
    buyer = await database.get_or_create_user(71902)
    prompt = await database.create_prompt(author_id=author.id, prompt_text='Test prompt', title='Test trend')
    await database.approve_prompt(prompt['id'])
    await database.add_generation_task(buyer.id, buyer.telegram_id, 'original-provider-id', 'image', 'test', cost=2, provider_accepted=True)
    monkeypatch.setenv('PARTNER_REPEAT_REWARD_RUB', '9')
    await trend_api._record_trend_use(prompt['id'], buyer.id, credits_spent=2, repeat_task_id='original-provider-id')
    task = await database.get_task_by_id('original-provider-id')
    metadata = json.loads(task.request_data)
    metadata['task_id_aliases'] = ['original-provider-id', 'new-provider-id']
    async with db_backend.connect() as conn:
        await conn.execute('UPDATE generation_tasks SET task_id = ?, request_data = ? WHERE id = ?', ('new-provider-id', json.dumps(metadata), task.id))
        await conn.commit()
    await trend_api._record_trend_use(prompt['id'], buyer.id, credits_spent=2, repeat_task_id='new-provider-id')
    await trend_api._record_trend_use(prompt['id'], buyer.id, credits_spent=2, repeat_task_id='original-provider-id')
    updated = await database.get_or_create_user(author.telegram_id)
    assert updated.partner_balance_rub == 5
    async with db_backend.connect() as conn:
        cursor = await conn.execute('SELECT amount_rub FROM prompt_repeat_events WHERE repeater_id = ?', (buyer.id,))
        assert await cursor.fetchall() == [(5.0,)]


@pytest.mark.asyncio
async def test_recovered_legacy_receipt_preserves_ten_ruble_terms():
    import json
    buyer = await database.get_or_create_user(72001)
    metadata = {'video_repeat_receipt': True, 'repeat_receipt_phase': 'launching'}
    async with db_backend.connect() as conn:
        await conn.execute("INSERT INTO generation_tasks(user_id, telegram_id, task_id, type, preset_id, cost, status, request_data) VALUES (?, ?, 'legacy-receipt', 'video', 'test', 2, 'processing', ?)", (buyer.id, buyer.telegram_id, json.dumps(metadata)))
        await conn.commit()
    assert await database.recover_private_video_repeat_acceptance('legacy-receipt', buyer.id, 'recovered-provider')
    task = await database.get_task_by_id('recovered-provider')
    assert json.loads(task.request_data)['partner_repeat_reward_rub'] == 10


@pytest.mark.asyncio
async def test_admin_invite_history_shows_only_granted_bonus(monkeypatch):
    _partner, buyer = await _attached(monkeypatch)
    before = await database.get_admin_finance_report()
    row = next(row for row in before['referrals_l1'] if row['referred_telegram_id'] == buyer.telegram_id)
    assert row['bonus_credits'] == 0
    await database.add_generation_task(buyer.id, buyer.telegram_id, 'history-bonus', 'image', 'test', cost=2, provider_accepted=True)
    after = await database.get_admin_finance_report()
    row = next(row for row in after['referrals_l1'] if row['referred_telegram_id'] == buyer.telegram_id)
    assert row['bonus_credits'] == 3


@pytest.mark.asyncio
async def test_reconcile_uses_canonical_task_id_when_provider_id_is_numeric(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.partner_policy import reconcile_pending_invite_bonuses

    partner, buyer = await _attached(monkeypatch)
    other = await database.get_or_create_user(72101)
    with monkeypatch.context() as temporary:
        temporary.setattr(database, 'mark_generation_accepted', AsyncMock(return_value=False))
        await database.add_generation_task(buyer.id, buyer.telegram_id, 'real-canonical', 'image', 'test', cost=2, provider_accepted=True)
    target = await database.get_task_by_id('real-canonical')
    # A provider ID can be a number that coincides with another row's internal ID.
    await database.add_generation_task(other.id, other.telegram_id, str(target.id), 'image', 'test', cost=0)
    assert await reconcile_pending_invite_bonuses() == 1
    assert (await database.get_or_create_user(partner.telegram_id)).referral_earned == 3
