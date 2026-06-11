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


@pytest.mark.asyncio
async def test_first_payment_partner_bonus_is_idempotent(tmp_path, monkeypatch):
    db = _reload_database(monkeypatch, tmp_path / "partner_first_payment.db")
    await db.init_db()
    referrer = await db.get_or_create_user(5005)
    await db.accept_partner_agreement(5005)
    await db.get_or_create_user(6006)
    assert await db.process_referral(6006, referrer.referral_code, signup_bonus=0)

    first = await db.credit_first_payment_referral_bonus(
        6006, transaction_credits=50, transaction_amount_rub=100
    )
    second = await db.credit_first_payment_referral_bonus(
        6006, transaction_credits=50, transaction_amount_rub=100
    )

    assert first == {
        "mode": "partner",
        "value": 30.0,
        "percent": 30,
        "levels": [
            {
                "telegram_id": 5005,
                "level": 1,
                "value": 30.0,
                "percent": 30,
            }
        ],
    }
    assert second == {"mode": "none", "value": 0, "percent": 0}

    overview = await db.get_partner_overview(5005)
    assert overview["balance_rub"] == 30.0
    assert overview["total_revenue_rub"] == 100.0
    rows = await db.get_credit_transactions(5005)
    assert [(r["amount"], r["reason"], r["external_id"]) for r in rows] == [
        (3000, "referral_first_payment_partner_bonus", "first_payment_partner:6006:level1")
    ]
