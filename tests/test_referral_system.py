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

        referrer = await db.get_or_create_user(1001)
        referred = await db.get_or_create_user(2002)

        ok = await db.process_referral(referred.telegram_id, referrer.referral_code)

        assert ok is True

        updated_referred = await db.get_or_create_user(referred.telegram_id)
        stats = await db.get_referral_stats(referrer.telegram_id)

        assert updated_referred.referred_by == referrer.id
        assert updated_referred.credits == 15
        assert stats["referrals_count"] == 1
        assert stats["referral_earned"] == 0

    asyncio.run(run())


def test_first_payment_bonus_is_awarded_once(tmp_path, monkeypatch):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "referrals.db")

        await db.init_db()

        referrer = await db.get_or_create_user(3003)
        referred = await db.get_or_create_user(4004)
        await db.process_referral(referred.telegram_id, referrer.referral_code)

        bonus1 = await db.credit_first_payment_referral_bonus(referred.telegram_id, 100)
        bonus2 = await db.credit_first_payment_referral_bonus(referred.telegram_id, 200)

        updated_referred = await db.get_or_create_user(referred.telegram_id)
        updated_referrer = await db.get_or_create_user(referrer.telegram_id)

        assert bonus1["mode"] == "banana"
        assert bonus1["value"] == 10
        assert bonus2["mode"] == "none"
        assert bonus2["value"] == 0
        assert updated_referred.has_paid is True
        assert updated_referrer.referral_earned == 10

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

        assert result["mode"] == "partner"
        assert result["value"] == 450.0
        assert result["percent"] == 45
        updated_master = await db.get_master_partner_user()
        assert updated_master.partner_balance_rub == 450.0
        assert overview["is_partner"] is True
        assert overview["balance_rub"] == 450.0

    asyncio.run(run())


def test_partner_bonus_uses_50_percent_after_300k_turnover(tmp_path, monkeypatch):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "partner_tier.db")

        await db.init_db()

        master = await db.get_master_partner_user()
        await db.accept_partner_agreement(master.telegram_id)

        import aiosqlite

        async with aiosqlite.connect(db.DATABASE_PATH) as conn:
            await conn.execute(
                "UPDATE users SET partner_total_revenue_rub = ?, partner_tier = ? WHERE id = ?",
                (300_000, "gold", master.id),
            )
            await conn.commit()

        referred = await db.get_or_create_user(8108)
        await db.process_referral(referred.telegram_id, master.referral_code)

        result = await db.credit_first_payment_referral_bonus(
            referred.telegram_id, 100, transaction_amount_rub=1000
        )
        overview = await db.get_partner_overview(master.telegram_id)

        assert result["mode"] == "partner"
        assert result["value"] == 500.0
        assert result["percent"] == 50
        assert overview["tier"] == "gold"
        assert overview["percent"] == 50

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

        ok = await db.create_partner_withdrawal(
            master.telegram_id, 200.0, "bank_card", "1234 **** 5678"
        )
        overview = await db.get_partner_overview(master.telegram_id)

        assert isinstance(ok, int)
        assert ok > 0
        assert overview["balance_rub"] == 250.0

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
        assert user_stats["referral_earned"] == 0
        assert admin_stats["total_referrals"] == 1

    asyncio.run(run())
