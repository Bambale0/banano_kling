"""Тесты партнёрской системы."""

import asyncio
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot import db as db_backend
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


def test_process_referral_click_records_attached_event(tmp_path, monkeypatch):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "referral_clicks.db")
        from bot.services import referral_service as referral_service_module

        referral_service = importlib.reload(referral_service_module)

        await db.init_db()

        referrer = await db.get_or_create_user(4101)
        referred = await db.get_or_create_user(4102)

        result = await referral_service.process_referral_click(
            referred.telegram_id,
            referrer.referral_code,
            source="test",
            start_param=f"ref_{referrer.referral_code}",
        )

        assert result.attached is True

        async with db_backend.connect(db.DATABASE_PATH) as conn:
            conn.row_factory = db_backend.Row
            cursor = await conn.execute(
                """
                SELECT clicked_code, reason, attached, source, start_param
                FROM referral_events
                WHERE visitor_telegram_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (referred.telegram_id,),
            )
            row = await cursor.fetchone()

        assert row is not None
        assert row["clicked_code"] == referrer.referral_code
        assert row["reason"] == "attached"
        assert row["attached"] in (1, True)
        assert row["source"] == "test"
        assert row["start_param"] == f"ref_{referrer.referral_code}"

    asyncio.run(run())


@pytest.mark.asyncio
async def test_referral_notification_uses_username_not_telegram_id():
    from bot.handlers.common import _notify_partner_about_new_referral

    bot = SimpleNamespace(send_message=AsyncMock())
    referred = SimpleNamespace(
        id=123456789,
        username="uvas_m",
        full_name="vasilina <3",
    )

    await _notify_partner_about_new_referral(
        bot,
        referrer_telegram_id=987654321,
        referred=referred,
    )

    bot.send_message.assert_awaited_once()
    text = bot.send_message.await_args.args[1]

    assert "@uvas_m" in text
    assert "123456789" not in text
    assert "ID <code>" not in text
    assert "vasilina &lt;3" in text


@pytest.mark.asyncio
async def test_referral_notification_uses_stored_username_when_missing_from_update():
    from bot.handlers.common import _notify_partner_about_new_referral

    bot = SimpleNamespace(send_message=AsyncMock())
    referred = SimpleNamespace(id=123456789, username=None, full_name="")
    stored_referred = SimpleNamespace(
        username="stored_user",
        first_name="Stored",
        last_name="Referral",
    )

    with patch(
        "bot.handlers.common.get_or_create_user",
        AsyncMock(return_value=stored_referred),
    ):
        await _notify_partner_about_new_referral(
            bot,
            referrer_telegram_id=987654321,
            referred=referred,
        )

    text = bot.send_message.await_args.args[1]

    assert "@stored_user" in text
    assert "Stored Referral" in text
    assert "123456789" not in text
    assert "ID <code>" not in text


def test_process_referral_rejects_user_with_completed_payment(tmp_path, monkeypatch):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "referrals.db")

        await db.init_db()

        referrer = await db.get_or_create_user(3001)
        referred = await db.get_or_create_user(3002)
        await db.create_transaction(
            order_id="paid-before-referral",
            user_id=referred.id,
            payment_id="paid-before-referral-payment",
            provider="yookassa",
            credits=25,
            amount_rub=250,
            status="completed",
        )

        ok = await db.process_referral(referred.telegram_id, referrer.referral_code)

        updated_referred = await db.get_or_create_user(referred.telegram_id)
        updated_referrer = await db.get_or_create_user(referrer.telegram_id)
        stats = await db.get_referral_stats(referrer.telegram_id)

        assert ok is False
        assert updated_referred.referred_by is None
        assert updated_referrer.referral_earned == 0
        assert stats["referrals_count"] == 0

    asyncio.run(run())


def test_process_referral_keeps_first_referrer(tmp_path, monkeypatch):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "referrals.db")

        await db.init_db()

        first_referrer = await db.get_or_create_user(3201)
        second_referrer = await db.get_or_create_user(3202)
        referred = await db.get_or_create_user(3203)

        assert await db.process_referral(referred.telegram_id, first_referrer.referral_code)
        assert not await db.process_referral(referred.telegram_id, second_referrer.referral_code)

        updated_referred = await db.get_or_create_user(referred.telegram_id)
        updated_first = await db.get_or_create_user(first_referrer.telegram_id)
        updated_second = await db.get_or_create_user(second_referrer.telegram_id)

        assert updated_referred.referred_by == first_referrer.id
        assert updated_first.referral_earned == db.PARTNER_INVITER_BONUS
        assert updated_second.referral_earned == 0

    asyncio.run(run())


def test_process_referral_rejects_referral_cycles(tmp_path, monkeypatch):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "referrals.db")

        await db.init_db()

        referrer = await db.get_or_create_user(3301)
        referred = await db.get_or_create_user(3302)

        assert await db.process_referral(referred.telegram_id, referrer.referral_code)
        assert not await db.process_referral(referrer.telegram_id, referred.referral_code)

        updated_referrer = await db.get_or_create_user(referrer.telegram_id)
        updated_referred = await db.get_or_create_user(referred.telegram_id)

        assert updated_referrer.referred_by is None
        assert updated_referred.referred_by == referrer.id

    asyncio.run(run())


def test_process_referral_allows_new_user_when_referrer_ancestry_is_already_cyclic(
    tmp_path, monkeypatch
):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "referrals.db")

        await db.init_db()

        root = await db.get_or_create_user(3401)
        parent = await db.get_or_create_user(3402)
        referrer = await db.get_or_create_user(3403)
        referred = await db.get_or_create_user(3404)

        async with db_backend.connect(db.DATABASE_PATH) as conn:
            await conn.execute(
                "UPDATE users SET referred_by = ? WHERE id = ?",
                (parent.id, root.id),
            )
            await conn.execute(
                "UPDATE users SET referred_by = ? WHERE id = ?",
                (root.id, parent.id),
            )
            await conn.execute(
                "UPDATE users SET referred_by = ? WHERE id = ?",
                (parent.id, referrer.id),
            )
            await conn.commit()

        assert await db.process_referral(referred.telegram_id, referrer.referral_code)

        updated_referred = await db.get_or_create_user(referred.telegram_id)
        updated_referrer = await db.get_or_create_user(referrer.telegram_id)

        assert updated_referred.referred_by == referrer.id
        assert updated_referrer.referral_earned == db.PARTNER_INVITER_BONUS

    asyncio.run(run())


def test_unreferred_payment_marks_user_paid(tmp_path, monkeypatch):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "referrals.db")

        await db.init_db()

        buyer = await db.get_or_create_user(3101)

        result = await db.credit_first_payment_referral_bonus(
            buyer.telegram_id, 25, transaction_amount_rub=250
        )

        updated_buyer = await db.get_or_create_user(buyer.telegram_id)

        assert result["mode"] == "none"
        assert updated_buyer.has_paid is True

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


@pytest.mark.asyncio
async def test_complete_transaction_notifies_referrer_about_purchase():
    from bot import database
    from bot.handlers.payments import _complete_transaction

    referrer = await database.get_or_create_user(4101)
    referred = await database.get_or_create_user(4102)
    await database.process_referral(referred.telegram_id, referrer.referral_code)
    await database.update_user_profile(
        referred.telegram_id,
        username="buyer_user",
        first_name="Buyer",
        last_name="User",
    )
    referred = await database.get_or_create_user(referred.telegram_id)

    await database.create_transaction(
        order_id="notify-referrer-order",
        user_id=referred.id,
        payment_id="notify-referrer-payment",
        provider="yookassa",
        credits=50,
        amount_rub=160,
        status="pending",
    )
    bot = SimpleNamespace(send_message=AsyncMock())

    result = await _complete_transaction("notify-referrer-order", bot=bot)

    assert result["ok"] is True
    assert result["already_completed"] is False
    bot.send_message.assert_awaited_once()
    target_id, text = bot.send_message.await_args.args[:2]
    assert target_id == referrer.telegram_id
    assert "Покупка реферала" in text
    assert "@buyer_user" in text
    assert "Buyer User" in text
    assert "<code>50</code>🍌" in text
    assert "<code>48</code> ₽" in text


@pytest.mark.asyncio
async def test_complete_transaction_respects_disabled_referrer_purchase_notifications():
    from bot import database
    from bot.handlers.payments import _complete_transaction

    referrer = await database.get_or_create_user(4201)
    referred = await database.get_or_create_user(4202)
    await database.process_referral(referred.telegram_id, referrer.referral_code)
    await database.save_user_settings(
        referrer.telegram_id,
        referral_purchase_notifications_enabled=False,
    )

    await database.create_transaction(
        order_id="silent-referrer-order",
        user_id=referred.id,
        payment_id="silent-referrer-payment",
        provider="yookassa",
        credits=25,
        amount_rub=100,
        status="pending",
    )
    bot = SimpleNamespace(send_message=AsyncMock())

    result = await _complete_transaction("silent-referrer-order", bot=bot)

    assert result["ok"] is True
    bot.send_message.assert_not_awaited()
    updated_referrer = await database.get_or_create_user(referrer.telegram_id)
    assert updated_referrer.partner_balance_rub == 30


@pytest.mark.asyncio
async def test_lava_reconcile_completes_paid_pending_transaction(monkeypatch):
    from bot import database
    from bot.handlers import payments

    user = await database.get_or_create_user(4301)
    initial_credits = user.credits
    await database.create_transaction(
        order_id="lava-paid-order",
        user_id=user.id,
        payment_id="lava-paid-invoice",
        provider="lava",
        credits=50,
        amount_rub=500,
        status="pending",
    )
    monkeypatch.setattr(payments.lava_service, "api_key", "test")
    monkeypatch.setattr(
        payments.lava_service,
        "get_invoice",
        AsyncMock(return_value={"status": "COMPLETED"}),
    )
    bot = SimpleNamespace(send_message=AsyncMock())

    results = await payments.reconcile_lava_pending_transactions(limit=10, bot=bot)

    assert results == [
        {
            "order_id": "lava-paid-order",
            "payment_id": "lava-paid-invoice",
            "status": "completed",
            "action": "completed",
        }
    ]
    updated_user = await database.get_or_create_user(user.telegram_id)
    assert updated_user.credits == initial_credits + 50
    transaction = await database.get_transaction_by_order("lava-paid-order")
    assert transaction.status == "completed"
    bot.send_message.assert_awaited_once()
    assert "Оплата Lava успешно обработана" in bot.send_message.await_args.args[1]


@pytest.mark.asyncio
async def test_lava_reconcile_marks_failed_pending_transaction(monkeypatch):
    from bot import database
    from bot.handlers import payments

    user = await database.get_or_create_user(4302)
    initial_credits = user.credits
    await database.create_transaction(
        order_id="lava-failed-order",
        user_id=user.id,
        payment_id="lava-failed-invoice",
        provider="lava",
        credits=50,
        amount_rub=500,
        status="pending",
    )
    monkeypatch.setattr(payments.lava_service, "api_key", "test")
    monkeypatch.setattr(
        payments.lava_service,
        "get_invoice",
        AsyncMock(return_value={"status": "FAILED"}),
    )
    bot = SimpleNamespace(send_message=AsyncMock())

    results = await payments.reconcile_lava_pending_transactions(limit=10, bot=bot)

    assert results == [
        {
            "order_id": "lava-failed-order",
            "payment_id": "lava-failed-invoice",
            "status": "failed",
            "action": "failed",
        }
    ]
    updated_user = await database.get_or_create_user(user.telegram_id)
    assert updated_user.credits == initial_credits
    transaction = await database.get_transaction_by_order("lava-failed-order")
    assert transaction.status == "failed"
    bot.send_message.assert_not_awaited()


def test_lava_webhook_payload_helpers_accept_success_and_failed_variants():
    from bot.services.lava_service import LavaService

    assert LavaService.is_success_webhook(
        {"eventType": "payment.success", "status": "success"}
    )
    assert LavaService.is_success_webhook(
        {"payload": {"invoiceId": "invoice-1", "status": "COMPLETED"}}
    )
    assert LavaService.is_failed_webhook(
        {"eventType": "payment.failed", "status": "failed"}
    )
    assert LavaService.webhook_contract_id(
        {"payload": {"invoiceId": "invoice-1"}}
    ) == "invoice-1"


@pytest.mark.asyncio
async def test_lava_webhook_completes_transaction_by_order_id(monkeypatch):
    from bot import database
    from bot.handlers import payments as payments_module
    from bot.handlers.payments import handle_lava_webhook

    async def _fake_status(_transaction, _contract_id):
        return "completed"

    monkeypatch.setattr(payments_module, "_resolve_lava_provider_status", _fake_status)

    user = await database.get_or_create_user(4303)
    initial_credits = user.credits
    await database.create_transaction(
        order_id="lava-webhook-order",
        user_id=user.id,
        payment_id="lava-webhook-invoice",
        provider="lava",
        credits=75,
        amount_rub=700,
        status="pending",
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    request = SimpleNamespace(
        read=AsyncMock(
            return_value=(
                b'{"eventType":"payment.success","status":"success",'
                b'"clientUtm":{"order_id":"lava-webhook-order"}}'
            )
        ),
        app={"bot": bot},
    )

    response = await handle_lava_webhook(request)

    assert response.status == 200
    updated_user = await database.get_or_create_user(user.telegram_id)
    assert updated_user.credits == initial_credits + 75
    transaction = await database.get_transaction_by_order("lava-webhook-order")
    assert transaction.status == "completed"
    bot.send_message.assert_awaited_once()


def test_commission_awarded_to_level1_and_level2(tmp_path, monkeypatch):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "referrals.db")

        await db.init_db()

        level2_partner = await db.get_or_create_user(3501)
        level1_partner = await db.get_or_create_user(3502)
        buyer = await db.get_or_create_user(3503)

        assert await db.process_referral(
            level1_partner.telegram_id,
            level2_partner.referral_code,
        )
        assert await db.process_referral(
            buyer.telegram_id,
            level1_partner.referral_code,
        )

        result = await db.credit_referral_commission(
            buyer.telegram_id,
            100,
            transaction_amount_rub=1000,
        )

        updated_level1 = await db.get_or_create_user(level1_partner.telegram_id)
        updated_level2 = await db.get_or_create_user(level2_partner.telegram_id)

        assert result["mode"] == "partner"
        assert result["value"] == 300
        assert result["level2_value"] == 70
        assert updated_level1.partner_balance_rub == 300
        assert updated_level1.partner_total_revenue_rub == 1000
        assert updated_level2.partner_balance_rub == 70
        assert updated_level2.partner_total_revenue_rub == 1000

    asyncio.run(run())


def test_partner_commission_does_not_increase_for_legacy_gold_or_silver(tmp_path, monkeypatch):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "referrals.db")

        await db.init_db()

        referrer = await db.get_or_create_user(3601)
        buyer = await db.get_or_create_user(3602)
        await db.process_referral(buyer.telegram_id, referrer.referral_code)

        async with db_backend.connect(db.DATABASE_PATH) as conn:
            await conn.execute(
                "UPDATE users SET partner_total_revenue_rub = ?, partner_tier = ? WHERE id = ?",
                (75_000.0, "gold", referrer.id),
            )
            await conn.commit()

        result = await db.credit_referral_commission(
            buyer.telegram_id,
            100,
            transaction_amount_rub=1000,
        )
        updated_referrer = await db.get_or_create_user(referrer.telegram_id)

        assert result["mode"] == "partner"
        assert result["percent"] == db.PARTNER_LEVEL1_PERCENT
        assert result["value"] == 300
        assert result["referrer_tier"] == "basic"
        assert updated_referrer.partner_balance_rub == 300
        assert updated_referrer.partner_tier == "basic"

    asyncio.run(run())


def test_partner_overview_counts_only_payments_after_referral(tmp_path, monkeypatch):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "referrals.db")

        await db.init_db()

        referrer = await db.get_or_create_user(7007)
        referred = await db.get_or_create_user(7008)
        assert await db.process_referral(referred.telegram_id, referrer.referral_code)

        async with db_backend.connect(db.DATABASE_PATH) as conn:
            conn.row_factory = db_backend.Row
            referral_row = await (
                await conn.execute(
                    """
                    SELECT created_at
                    FROM referrals
                    WHERE referrer_id = ? AND referred_id = ?
                    """,
                    (referrer.id, referred.id),
                )
            ).fetchone()
            referral_at = referral_row["created_at"]

            await conn.execute(
                """
                INSERT INTO transactions
                    (order_id, user_id, payment_id, provider, credits, amount_rub, status, created_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, 'completed', datetime(?, '-1 minute')),
                    (?, ?, ?, ?, ?, ?, 'completed', datetime(?, '+1 minute'))
                """,
                (
                    "pre-referral-payment",
                    referred.id,
                    "pre-referral-payment-id",
                    "yookassa",
                    25,
                    250,
                    referral_at,
                    "post-referral-payment",
                    referred.id,
                    "post-referral-payment-id",
                    "yookassa",
                    50,
                    500,
                    referral_at,
                ),
            )
            await conn.commit()

        overview = await db.get_partner_overview(referrer.telegram_id)
        details = await db.get_admin_partner_details(referrer.telegram_id)

        assert overview["total_payments"] == 1
        assert overview["monthly_revenue"] == 500
        assert details["referrals"][0]["payments_count"] == 1
        assert details["referrals"][0]["spent_rub"] == 500

    asyncio.run(run())


def test_admin_partner_payment_report_includes_only_level1_payments_after_referral(
    tmp_path, monkeypatch
):
    async def run():
        db = _reload_database(monkeypatch, tmp_path / "partner_report.db")

        await db.init_db()

        referrer = await db.get_or_create_user(7107)
        referred = await db.get_or_create_user(7108)
        assert await db.process_referral(referred.telegram_id, referrer.referral_code)

        async with db_backend.connect(db.DATABASE_PATH) as conn:
            conn.row_factory = db_backend.Row
            referral_row = await (
                await conn.execute(
                    """
                    SELECT created_at
                    FROM referrals
                    WHERE referrer_id = ? AND referred_id = ?
                    """,
                    (referrer.id, referred.id),
                )
            ).fetchone()
            referral_at = referral_row["created_at"]

            await conn.execute(
                """
                INSERT INTO transactions
                    (order_id, user_id, payment_id, provider, credits, amount_rub, status, created_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, 'completed', datetime(?, '-1 minute')),
                    (?, ?, ?, ?, ?, ?, 'completed', datetime(?, '+1 minute'))
                """,
                (
                    "partner-report-pre",
                    referred.id,
                    "partner-report-pre-payment",
                    "yookassa",
                    25,
                    250,
                    referral_at,
                    "partner-report-post",
                    referred.id,
                    "partner-report-post-payment",
                    "yookassa",
                    50,
                    500,
                    referral_at,
                ),
            )
            await conn.commit()

        report = await db.get_admin_partner_payment_report(referrer.telegram_id)

        assert report["payments_summary"]["payments_count"] == 1
        assert report["payments_summary"]["paid_rub"] == 500
        assert report["payments"][0]["order_id"] == "partner-report-post"
        assert report["payments"][0]["referred_telegram_id"] == referred.telegram_id
        assert report["referrals"][0]["payments_count"] == 1
        assert report["referrals"][0]["spent_rub"] == 500

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
