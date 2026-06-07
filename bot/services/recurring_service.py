from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from aiogram import Bot

from bot.config import config
from bot.database import (
    add_credits_once,
    create_transaction,
    get_or_create_user,
    list_due_recurring_subscriptions,
    mark_recurring_charge_failed,
    mark_recurring_charge_success,
)
from bot.services.admin_config_service import admin_package_config_service
from bot.services.subscription_service import subscription_service
from bot.services.tbank_service import tbank_service

logger = logging.getLogger(__name__)


def next_retry_at() -> str:
    return (datetime.utcnow() + timedelta(hours=config.RECURRING_PAYMENTS_RETRY_HOURS)).isoformat(
        timespec="seconds"
    )


def _renewal_order_id(telegram_id: int, package_id: str) -> str:
    return f"r{telegram_id}_{int(time.time())}_{package_id}"[:36]


async def renew_recurring_subscription(row: dict[str, Any], bot: Bot | None = None) -> bool:
    package = await admin_package_config_service.get_package(str(row["package_id"]))
    if not package or package.get("hidden"):
        await mark_recurring_charge_failed(
            int(row["id"]),
            error="package_unavailable",
            next_charge_at=next_retry_at(),
        )
        return False
    if not subscription_service.is_subscription_package(package):
        await mark_recurring_charge_failed(
            int(row["id"]),
            error="package_is_not_subscription",
            next_charge_at=next_retry_at(),
        )
        return False

    telegram_id = int(row["telegram_id"])
    total_credits = int(package.get("credits") or 0) + int(package.get("bonus_credits") or 0)
    amount_rub = int(package["price_rub"])
    order_id = _renewal_order_id(telegram_id, str(package["id"]))
    amount_kop = amount_rub * 100

    result = await tbank_service.init_payment(
        amount=amount_kop,
        order_id=order_id,
        description=f"Автопродление {package['name']}",
        customer_key=str(telegram_id),
        success_url=config.TBANK_SUCCESS_URL or "https://t.me/",
        fail_url=config.TBANK_SUCCESS_URL or "https://t.me/",
        notification_url=config.tbank_notification_url,
    )
    is_success = (
        result.get("Success") != False if result and "Success" in result else bool(result)
    )
    payment_id = result.get("PaymentId") or result.get("payment_id") if result else None
    if not result or not is_success or not payment_id:
        await mark_recurring_charge_failed(
            int(row["id"]),
            error=(result or {}).get("Message", "init_failed"),
            next_charge_at=next_retry_at(),
        )
        return False

    charge = await tbank_service.charge_recurrent(
        payment_id=str(payment_id),
        rebill_id=str(row["rebill_id"]),
    )
    charge_success = (
        charge.get("Success") != False if charge and "Success" in charge else bool(charge)
    )
    if not charge or not charge_success:
        await mark_recurring_charge_failed(
            int(row["id"]),
            error=(charge or {}).get("Message", "charge_failed"),
            next_charge_at=next_retry_at(),
        )
        return False

    user = await get_or_create_user(telegram_id)
    await create_transaction(
        order_id=order_id,
        user_id=user.id,
        payment_id=str(payment_id),
        provider="tbank_recurring",
        credits=total_credits,
        amount_rub=amount_rub,
        original_amount_rub=amount_rub,
        status="completed",
    )
    await add_credits_once(
        telegram_id,
        total_credits,
        reason="recurring_payment_completed",
        external_id=order_id,
        metadata={"provider": "tbank_recurring", "amount_rub": amount_rub},
    )
    subscription = await subscription_service.activate_from_package(telegram_id, package)
    next_charge_at = (
        subscription["expires_at"]
        if subscription and subscription.get("expires_at")
        else (datetime.utcnow() + timedelta(days=int(package.get("subscription_days") or 30))).isoformat(
            timespec="seconds"
        )
    )
    await mark_recurring_charge_success(
        int(row["id"]),
        order_id=order_id,
        next_charge_at=next_charge_at,
    )

    if bot:
        try:
            await bot.send_message(
                telegram_id,
                "🔁 <b>Подписка продлена автоматически</b>\n\n"
                f"Пакет: <code>{package['name']}</code>\n"
                f"Сумма: <code>{amount_rub}</code> ₽",
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Failed to notify recurring renewal: telegram_id=%s", telegram_id)
    return True


async def renew_due_recurring_subscriptions(
    *,
    bot: Bot | None = None,
    limit: int | None = None,
) -> int:
    rows = await list_due_recurring_subscriptions(
        limit or config.RECURRING_PAYMENTS_BATCH_LIMIT
    )
    renewed = 0
    for row in rows:
        try:
            if await renew_recurring_subscription(row, bot=bot):
                renewed += 1
        except Exception as exc:
            logger.exception("Recurring renewal failed for id=%s: %s", row.get("id"), exc)
            await mark_recurring_charge_failed(
                int(row["id"]),
                error=str(exc),
                next_charge_at=next_retry_at(),
            )
    return renewed
