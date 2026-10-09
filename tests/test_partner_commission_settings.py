import asyncio

import pytest

from bot import database
from bot import db as db_backend
from bot.partner_commission_settings import (
    PartnerCommissionConflict,
    PartnerCommissionError,
    get_partner_commission_setting,
    set_partner_commission_percent,
)

ADMIN = 999999999


async def _partner(telegram_id=89001):
    return await database.get_or_create_user(telegram_id)


async def test_default_is_30_with_no_magic_recipient_and_no_global_promotion(monkeypatch):
    monkeypatch.setenv('PARTNER_LEVEL1_PERCENT', '40')
    for telegram_id in [89001, 1608435230]:
        await _partner(telegram_id)
        settings = await get_partner_commission_setting(telegram_id)
        assert settings['effective_percent'] == 30
        assert settings['revision'] == 0 and settings['source'] == 'default'
    assert await get_partner_commission_setting(99901) is None


async def test_explicit_config_preserved_but_admin_override_wins(monkeypatch):
    await _partner()
    monkeypatch.setenv('PARTNER_LEVEL1_OVERRIDES_JSON', '{"89001":40}')
    assert (await get_partner_commission_setting(89001))['effective_percent'] == 40
    result = await set_partner_commission_percent(ADMIN, 89001, 0, expected_revision=0)
    assert result['changed'] and result['effective_percent'] == 0
    assert (await get_partner_commission_setting(89001))['source'] == 'admin'


@pytest.mark.parametrize('percent', [-1,101,float('nan'),float('inf'),True,'40',None,33.333,33.30000000000001,0.001])
async def test_invalid_input_does_not_mutate(percent):
    await _partner()
    with pytest.raises(PartnerCommissionError):
        await set_partner_commission_percent(ADMIN, 89001, percent, expected_revision=0)
    assert (await get_partner_commission_setting(89001))['revision'] == 0


async def test_authorization_unknown_user_and_noop_are_safe():
    await _partner()
    with pytest.raises(PermissionError):
        await set_partner_commission_percent(89001, 89001, 40, expected_revision=0)
    with pytest.raises(PartnerCommissionError):
        await set_partner_commission_percent(ADMIN, 89999, 40, expected_revision=0)
    first = await set_partner_commission_percent(ADMIN, 89001, 30, expected_revision=0)
    assert first['changed'] and first['revision'] == 1
    again = await set_partner_commission_percent(ADMIN, 89001, 30, expected_revision=1)
    assert not again['changed'] and again['revision'] == 1
    with pytest.raises(PartnerCommissionConflict):
        await set_partner_commission_percent(ADMIN, 89001, 40, expected_revision=0)
    async with db_backend.connect() as db:
        assert (await (await db.execute('SELECT COUNT(*) FROM partner_commission_audit')).fetchone())[0] == 1


async def test_concurrent_stale_updates_have_one_winner_and_one_audit():
    await _partner()
    results = await asyncio.gather(
        set_partner_commission_percent(ADMIN, 89001, 0, expected_revision=0),
        set_partner_commission_percent(ADMIN, 89001, 40, expected_revision=0),
        return_exceptions=True,
    )
    assert sum(isinstance(r, PartnerCommissionConflict) for r in results) == 1
    assert (await get_partner_commission_setting(89001))['revision'] == 1
    async with db_backend.connect() as db:
        assert (await (await db.execute('SELECT COUNT(*) FROM partner_commission_audit')).fetchone())[0] == 1
        with pytest.raises(Exception, match='append-only'):
            await db.execute('DELETE FROM partner_commission_audit')


async def test_future_invoices_freeze_manual_rate_and_zero_keeps_second_line(monkeypatch):
    root, partner, payer = [await _partner(t) for t in [89000,89001,89002]]
    async with db_backend.connect() as db:
        await db.execute('UPDATE users SET referred_by = ? WHERE id = ?', (root.id,partner.id))
        await db.execute('UPDATE users SET referred_by = ? WHERE id = ?', (partner.id,payer.id))
        await db.commit()
    await set_partner_commission_percent(ADMIN, 89000, 0, expected_revision=0)
    await set_partner_commission_percent(ADMIN, 89001, 40, expected_revision=0)
    await database.create_transaction('frozen40',payer.id,'frozen40','test',25,1000)
    await set_partner_commission_percent(ADMIN, 89001, 0, expected_revision=1)
    await database.create_transaction('frozen0',payer.id,'frozen0','test',25,1000)
    await set_partner_commission_percent(ADMIN, 89001, 30, expected_revision=2)
    first = await database.complete_payment_atomic('frozen40')
    zero = await database.complete_payment_atomic('frozen0')
    assert first['referral_bonus']['value'] == 400
    assert zero['referral_bonus']['value'] == 0
    assert zero['referral_bonus']['percent'] == 0
    assert first['referral_bonus']['level2_value'] == zero['referral_bonus']['level2_value'] == 70
    assert (await database.get_partner_overview(89001))['percent'] == 30
    assert (await database.complete_payment_atomic('frozen40'))['already_completed']
    report = await database.get_admin_finance_report()
    rates = {r['order_id']:r['level1_percent'] for r in report['partner_commissions']}
    assert rates['frozen40'] == 40 and rates['frozen0'] == 0


async def test_failed_audit_rolls_back_setting_and_preserves_balances():
    partner = await _partner()
    async with db_backend.connect() as db:
        await db.execute("CREATE TRIGGER audit_write_failure BEFORE INSERT ON partner_commission_audit BEGIN SELECT RAISE(ABORT, 'synthetic audit failure'); END")
        await db.commit()
    with pytest.raises(Exception, match='synthetic audit failure'):
        await set_partner_commission_percent(ADMIN, partner.telegram_id, 40, expected_revision=0)
    setting = await get_partner_commission_setting(partner.telegram_id)
    assert setting['effective_percent'] == 30 and setting['revision'] == 0
    unchanged = await database.get_or_create_user(partner.telegram_id)
    assert unchanged.credits == partner.credits and unchanged.partner_balance_rub == partner.partner_balance_rub


async def test_zero_first_line_does_not_disable_invitation_or_repeat_rewards():
    inviter, invited = [await _partner(t) for t in [89201,89202]]
    await set_partner_commission_percent(ADMIN, inviter.telegram_id, 0, expected_revision=0)
    assert await database.process_referral(invited.telegram_id, inviter.referral_code)
    assert await database.deduct_credits(invited.telegram_id, 5)
    assert await database.add_generation_task(invited.id, invited.telegram_id, 'zero-policy-generation', 'image', 'test', cost=5, provider_accepted=True)
    assert (await database.get_or_create_user(inviter.telegram_id)).referral_earned == 3
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        assert await database._credit_prompt_repeat_reward_in_db(db, author_id=inviter.id, repeater_id=invited.id, source_type='feed', source_id=1, repeat_task_id='zero-policy-generation', credits_spent=5)
        await db.commit()
    assert (await database.get_or_create_user(inviter.telegram_id)).partner_balance_rub == 5


async def test_admin_rate_snapshot_survives_referral_attachment_after_invoice():
    partner, payer = [await _partner(t) for t in [89301,89302]]
    await set_partner_commission_percent(ADMIN, partner.telegram_id, 40, expected_revision=0)
    await database.create_transaction('unattached-invoice',payer.id,'unattached-invoice','test',25,1000)
    await set_partner_commission_percent(ADMIN, partner.telegram_id, 0, expected_revision=1)
    assert await database.process_referral(payer.telegram_id, partner.referral_code)
    result = await database.complete_payment_atomic('unattached-invoice')
    assert result['referral_bonus']['value'] == 400
    assert (await database.get_partner_overview(partner.telegram_id))['percent'] == 0


async def test_previous_version_invoice_terms_are_not_rewritten_by_admin_assignment():
    partner, payer = [await _partner(t) for t in [89401,89402]]
    async with db_backend.connect() as db:
        await db.execute('UPDATE users SET referred_by = ? WHERE id = ?', (partner.id,payer.id))
        await db.execute("INSERT INTO transactions(order_id,user_id,payment_id,provider,credits,amount_rub,status) VALUES ('previous-policy',?,'previous-policy','test',25,1000,'pending')", (payer.id,))
        await db.execute("INSERT INTO partner_payment_terms(order_id,level1_percent,level2_percent,level1_overrides_json) VALUES ('previous-policy',40,7,'{}')")
        await db.commit()
    await set_partner_commission_percent(ADMIN, partner.telegram_id, 0, expected_revision=0)
    result = await database.complete_payment_atomic('previous-policy')
    assert result['referral_bonus']['value'] == 400
    assert (await database.get_partner_overview(partner.telegram_id))['percent'] == 0


@pytest.mark.parametrize('percent,points', [(0,0),(33.3,3330),(40,4000),(99.99,9999),(100,10000)])
async def test_exact_hundredths_roundtrip_and_repeated_save_are_a_true_noop(percent, points):
    partner = await _partner(89501)
    saved = await set_partner_commission_percent(ADMIN, partner.telegram_id, percent, expected_revision=0)
    loaded = await get_partner_commission_setting(partner.telegram_id)
    assert loaded['effective_percent'] == percent
    assert not (await set_partner_commission_percent(ADMIN, partner.telegram_id, percent, expected_revision=saved['revision']))['changed']
    async with db_backend.connect() as db:
        row = await (await db.execute('SELECT first_line_basis_points FROM partner_commission_settings WHERE telegram_id = ?', (partner.telegram_id,))).fetchone()
        assert row[0] == points and isinstance(row[0],int)
        assert (await (await db.execute('SELECT COUNT(*) FROM partner_commission_audit')).fetchone())[0] == 1
