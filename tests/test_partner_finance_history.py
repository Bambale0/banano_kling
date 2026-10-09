import pytest

from bot import database
from bot import db as db_backend


async def _payment(order, payer, *, legacy=False):
    if legacy:
        async with db_backend.connect() as conn:
            await conn.execute(
                """INSERT INTO transactions(order_id,user_id,payment_id,provider,credits,amount_rub,status)
                   VALUES (?, ?, ?, 'test', 25, 1000, 'pending')""", (order, payer.id, order),
            )
            await conn.commit()
    else:
        await database.create_transaction(order, payer.id, order, "test", 25, 1000)
    result = await database.complete_payment_atomic(order)
    assert result["ok"]


async def _chain(partner_id=881001, root_id=881002, payer_id=881003):
    root = await database.get_or_create_user(root_id)
    partner = await database.get_or_create_user(partner_id)
    payer = await database.get_or_create_user(payer_id)
    async with db_backend.connect() as conn:
        await conn.execute("UPDATE users SET referred_by = ? WHERE id = ?", (root.id, partner.id))
        await conn.execute("UPDATE users SET referred_by = ? WHERE id = ?", (partner.id, payer.id))
        await conn.commit()
    return root, partner, payer


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy,partner_id,expected", [(True, 881001, 300), (False, 881001, 400), (False, 1608435230, 300)])
@pytest.mark.parametrize("keep_ledger", [True, False])
async def test_finance_export_preserves_legacy_new_and_exception_commissions(monkeypatch, legacy, partner_id, expected, keep_ledger):
    _root, partner, payer = await _chain(partner_id=partner_id)
    await _payment("history", payer, legacy=legacy)
    if not keep_ledger:
        async with db_backend.connect() as conn:
            await conn.execute("DELETE FROM partner_commissions WHERE order_id = 'history'")
            await conn.commit()
    monkeypatch.setenv("PARTNER_LEVEL1_PERCENT", "65")
    monkeypatch.setenv("PARTNER_LEVEL2_PERCENT", "11")
    monkeypatch.setenv("PARTNER_LEVEL1_OVERRIDES_JSON", "{}")
    report = await database.get_admin_finance_report()
    row = report["partner_commissions"][0]
    assert row["level1_commission_rub"] == expected
    assert row["level1_percent"] == expected / 10
    assert row["level2_commission_rub"] == 70
    assert row["level2_percent"] == 7
    assert row["level1_commission_source"] == ("ledger" if keep_ledger else "legacy_terms" if legacy else "frozen_terms")
    assert (await database.get_or_create_user(partner.telegram_id)).partner_balance_rub == expected


@pytest.mark.asyncio
async def test_finance_export_uses_recorded_amount_instead_of_recalculating():
    _, _, payer = await _chain()
    await _payment("adjusted", payer)
    async with db_backend.connect() as conn:
        await conn.execute("UPDATE partner_commissions SET percent = 17, amount_rub = 171.11 WHERE order_id = 'adjusted' AND level = 1")
        await conn.commit()
    report = await database.get_admin_finance_report()
    row = report["partner_commissions"][0]
    assert row["level1_percent"] == 17
    assert row["level1_commission_rub"] == 171.11
    assert row["level1_commission_source"] == "ledger"


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [True, False])
async def test_finance_export_preserves_admin_second_level_exclusion(legacy):
    _, _, payer = await _chain(partner_id=999999999)
    await _payment("admin", payer, legacy=legacy)
    report = await database.get_admin_finance_report()
    row = report["partner_commissions"][0]
    assert row["level2_percent"] == 0
    assert row["level2_commission_rub"] == 0
    assert row["level2_commission_source"] == "not_eligible"
