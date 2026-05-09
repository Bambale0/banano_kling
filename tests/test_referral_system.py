"""Тесты партнёрской системы."""

import asyncio
import importlib
from pathlib import Path

import pytest


def _reload_database(monkeypatch, db_path: Path):
    """Перезагружает bot.database с временной БД."""
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    import bot.database as database

    return importlib.reload(database)


def test_user_gets_referral_code_and_code_is_unique(tmp_path, monkeypatch):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "referrals.db")

        await db.init_db()

        user1 = await db.get_or_create_user(111)
        user2 = await db.get_or_create_user(222)

        assert user1.referral_code
        assert user2.referral_code
        assert user1.referral_code != user2.referral_code

    asyncio.run(run())


def test_process_referral_adds_bonus_and_links_user(tmp_path, monkeypatch):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "referrals.db")

        await db.init_db()

        master = await db.get_master_partner_user()
        referred = await db.get_or_create_user(2002)

        ok = await db.process_referral(referred.telegram_id, master.referral_code)

        assert ok is True

        updated_referred = await db.get_or_create_user(referred.telegram_id)
        updated_master = await db.get_master_partner_user()
        stats = await db.get_referral_stats(master.telegram_id)

        assert updated_referred.referred_by == master.id
        # new user already got PARTNER_NEW_USER_BONUS=15 at registration; process_referral gives signup_bonus=0 more
        assert updated_referred.credits == db.PARTNER_NEW_USER_BONUS
        # inviter gets PARTNER_INVITER_BONUS credits into referral_earned
        assert updated_master.referral_earned == db.PARTNER_INVITER_BONUS
        assert stats["referrals_count"] == 1

    asyncio.run(run())


def test_commission_awarded_every_payment(tmp_path, monkeypatch):
    """Commission is credited on every payment, not just the first."""
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "referrals.db")

        await db.init_db()

        referrer = await db.get_or_create_user(3003)
        referred = await db.get_or_create_user(4004)
        await db.process_referral(referred.telegram_id, referrer.referral_code)

        # First payment: 100 credits, no rub amount → 30% of 100 credits = 30
        bonus1 = await db.credit_first_payment_referral_bonus(referred.telegram_id, 100)
        # Second payment: 200 credits → 30% of 200 = 60
        bonus2 = await db.credit_first_payment_referral_bonus(referred.telegram_id, 200)

        updated_referred = await db.get_or_create_user(referred.telegram_id)
        updated_referrer = await db.get_or_create_user(referrer.telegram_id)

        assert bonus1["mode"] == "partner"
        assert bonus1["value"] == round(100 * db.PARTNER_LEVEL1_PERCENT / 100, 2)
        assert bonus2["mode"] == "partner"
        assert bonus2["value"] == round(200 * db.PARTNER_LEVEL1_PERCENT / 100, 2)
        assert updated_referred.has_paid is True
        expected_total = round(100 * db.PARTNER_LEVEL1_PERCENT / 100 + 200 * db.PARTNER_LEVEL1_PERCENT / 100, 2)
        assert updated_referrer.partner_balance_rub == expected_total

    asyncio.run(run())


def test_partner_acceptance_and_partner_bonus(tmp_path, monkeypatch):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "partner.db")

        await db.init_db()

        referred = await db.get_or_create_user(8008)
        master = await db.get_master_partner_user()
        await db.accept_partner_agreement(master.telegram_id)
        await db.process_referral(referred.telegram_id, master.referral_code)

        result = await db.credit_first_payment_referral_bonus(
            referred.telegram_id, 100, transaction_amount_rub=1000
        )
        overview = await db.get_partner_overview(master.telegram_id)

        expected = round(1000 * db.PARTNER_LEVEL1_PERCENT / 100, 2)
        assert result["mode"] == "partner"
        assert result["value"] == expected
        updated_master = await db.get_master_partner_user()
        assert updated_master.partner_balance_rub == expected
        assert overview["is_partner"] is True
        assert overview["balance_rub"] == expected

    asyncio.run(run())


def test_partner_withdrawal_creates_request(tmp_path, monkeypatch):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "partner_withdraw.db")

        await db.init_db()

        master = await db.get_master_partner_user()
        await db.accept_partner_agreement(master.telegram_id)

        referred = await db.get_or_create_user(9010)
        await db.process_referral(referred.telegram_id, master.referral_code)
        await db.credit_first_payment_referral_bonus(
            referred.telegram_id, 100, transaction_amount_rub=1000
        )
        # master gets 30% of 1000 = 300 rub
        expected_balance = round(1000 * db.PARTNER_LEVEL1_PERCENT / 100, 2)

        # Pass min_amount_rub=0 to bypass the config minimum in tests
        withdraw_amount = round(expected_balance * 2 / 3, 2)
        ok = await db.create_partner_withdrawal(
            master.telegram_id, withdraw_amount, "bank_card", "1234 **** 5678",
            min_amount_rub=0.0,
        )
        overview = await db.get_partner_overview(master.telegram_id)

        assert ok is not None  # returns dict on success
        # balance_rub shows available (total - pending)
        assert overview["balance_rub"] == round(expected_balance - withdraw_amount, 2)
        assert overview["pending_rub"] == withdraw_amount

    asyncio.run(run())


def test_stats_include_referrals(tmp_path, monkeypatch):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "referrals.db")

        await db.init_db()

        referred = await db.get_or_create_user(6006)
        master = await db.get_master_partner_user()
        await db.process_referral(referred.telegram_id, master.referral_code)

        user_stats = await db.get_user_stats(master.telegram_id)
        admin_stats = await db.get_admin_stats()

        assert user_stats["referrals_count"] == 1
        assert admin_stats["total_referrals"] == 1

    asyncio.run(run())
