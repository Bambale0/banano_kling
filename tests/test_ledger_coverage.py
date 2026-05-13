import importlib

import pytest


def _reload_database(monkeypatch, db_path):
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    import bot.database as database
    return importlib.reload(database)


@pytest.mark.asyncio
async def test_process_referral_signup_bonus_is_in_credit_ledger(tmp_path, monkeypatch):
    db = _reload_database(monkeypatch, tmp_path / "referral_signup.db")
    await db.init_db()
    referrer = await db.get_or_create_user(1001)
    await db.get_or_create_user(2002)

    assert await db.process_referral(2002, referrer.referral_code, signup_bonus=5)

    rows = await db.get_credit_transactions(2002)
    assert [(r["amount"], r["reason"], r["external_id"]) for r in rows] == [
        (5, "referral_signup_bonus", f"referral_signup:2002:{referrer.id}")
    ]


@pytest.mark.asyncio
async def test_first_payment_banana_referral_bonus_is_in_credit_ledger(tmp_path, monkeypatch):
    db = _reload_database(monkeypatch, tmp_path / "first_payment_referral.db")
    await db.init_db()
    referrer = await db.get_or_create_user(3003)
    await db.get_or_create_user(4004)
    assert await db.process_referral(4004, referrer.referral_code, signup_bonus=0)

    result = await db.credit_first_payment_referral_bonus(4004, transaction_credits=50, transaction_amount_rub=100)

    assert result == {"mode": "banana", "value": 5, "percent": 10}
    rows = await db.get_credit_transactions(3003)
    assert [(r["amount"], r["reason"], r["external_id"]) for r in rows] == [
        (5, "referral_first_payment_bonus", "first_payment:4004")
    ]
