from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

from bot.config import config
from bot.database import (
    create_miniapp_notification,
    create_transaction,
    get_or_create_user,
    get_telegram_id_by_user_id,
    get_transaction_by_order,
    update_transaction_payment_id,
    update_transaction_status,
)
from bot.handlers.payments import (
    _build_bonus_text,
    _build_promo_bonus_text,
    _complete_transaction,
    _get_selected_promo,
    _is_ignored_telegram_error,
    _notify_user,
    _package_lava_offer_config,
    _promo_bonus_for_package,
    _transaction_promo_text,
)
from bot.keyboards import get_back_keyboard, get_main_menu_keyboard
from bot.payment_utils import (
    TELEGRAM_STARS_PROVIDER,
    package_bonus_credits,
    package_stars_amount,
    total_package_credits,
)
from bot.services.cryptobot_service import cryptobot_service
from bot.services.freekassa_service import freekassa_service, normalize_amount
from bot.services.lava_service import lava_service
from bot.services.preset_manager import preset_manager

logger = logging.getLogger(__name__)
router = Router()

FREEKASSA_RECONCILE_INTERVAL_SECONDS = 5 * 60
FREEKASSA_RECONCILE_BATCH_SIZE = 100


def _payment_method_keyboard(
    package_id: str,
    *,
    has_stars: bool,
    has_freekassa: bool,
    has_crypto: bool,
    has_lava: bool,
) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_freekassa:
        builder.button(
            text="💳 Карта / СБП (FreeKassa)",
            callback_data=f"buy_freekassa_{package_id}",
        )
    if has_stars:
        builder.button(
            text="⭐ Telegram Stars",
            callback_data=f"buy_stars_{package_id}",
        )
    if has_crypto:
        builder.button(
            text="₿ Криптовалюта (CryptoBot)",
            callback_data=f"buy_crypto_{package_id}",
        )
    if has_lava:
        builder.button(
            text="🌐 Оплата через Lava",
            callback_data=f"buy_lava_{package_id}",
        )
    builder.button(text="◀️ Назад", callback_data="menu_topup")
    builder.adjust(1)
    return builder.as_markup()


def _freekassa_confirmation_keyboard(
    payment_url: str,
    order_id: str,
) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Перейти к оплате", url=payment_url)
    builder.button(
        text="✅ Проверить оплату",
        callback_data=f"check_freekassa_{order_id}",
    )
    builder.button(text="❌ Отмена", callback_data="cancel_payment")
    builder.adjust(1)
    return builder.as_markup()


def _request_ip(request: web.Request) -> str:
    real_ip = str(request.headers.get("X-Real-IP") or "").strip()
    if real_ip:
        return real_ip
    forwarded = str(request.headers.get("X-Forwarded-For") or "").strip()
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return str(request.remote or "").strip()


def _amount_matches(actual: Any, expected: Any) -> bool:
    try:
        return Decimal(normalize_amount(actual)) == Decimal(normalize_amount(expected))
    except (ValueError, InvalidOperation):
        return False


@router.callback_query(F.data.startswith("choose_pay_"))
async def choose_payment_method_freekassa(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    """Render the provider list with FreeKassa replacing YooKassa."""

    package_id = callback.data.replace("choose_pay_", "", 1)
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    lava_offer_id, _lava_currency = _package_lava_offer_config(package)
    has_stars = bool(config.TELEGRAM_STARS_ENABLED)
    has_freekassa = freekassa_service.enabled
    has_crypto = cryptobot_service.enabled
    has_lava = lava_service.enabled and bool(lava_offer_id)

    if not any((has_stars, has_freekassa, has_crypto, has_lava)):
        await callback.message.edit_text(
            "❌ Платёжные системы временно недоступны.\nОбратитесь в поддержку.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        await callback.answer()
        return

    promo = await _get_selected_promo(state)
    package_bonus = package_bonus_credits(package)
    promo_bonus = _promo_bonus_for_package(promo, package)
    total_credits = total_package_credits(package, promo_bonus)
    stars_amount = package_stars_amount(package)

    bonus_lines: list[str] = []
    if package_bonus > 0:
        bonus_lines.append(f"Бонус пакета: <code>{package_bonus}</code>🍌")
    if promo_bonus > 0 and promo:
        bonus_lines.append(
            f"Промокод <code>{html.escape(promo.code)}</code>: "
            f"+<code>{promo_bonus}</code>🍌"
        )
    bonus_text = f"\n{'\n'.join(bonus_lines)}" if bonus_lines else ""

    await callback.message.edit_text(
        "💳 <b>Выберите способ оплаты</b>\n\n"
        f"Пакет: <b>{html.escape(str(package['name']))}</b>\n"
        f"Бананы: <code>{total_credits}</code>🍌\n"
        f"Сумма: <code>{package['price_rub']}</code>₽ / "
        f"<code>{stars_amount}</code>⭐{bonus_text}",
        reply_markup=_payment_method_keyboard(
            package_id,
            has_stars=has_stars,
            has_freekassa=has_freekassa,
            has_crypto=has_crypto,
            has_lava=has_lava,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_freekassa_"))
@router.callback_query(F.data.startswith("buy_yookassa_"))
async def initiate_freekassa_payment(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    """Create a signed FreeKassa SCI checkout for a package."""

    if not freekassa_service.enabled:
        await callback.message.edit_text(
            "FreeKassa временно недоступна. Попробуйте другой способ оплаты.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        await callback.answer()
        return

    prefix = (
        "buy_freekassa_"
        if callback.data.startswith("buy_freekassa_")
        else "buy_yookassa_"
    )
    package_id = callback.data.replace(prefix, "", 1)
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    promo = await _get_selected_promo(state)
    package_bonus = package_bonus_credits(package)
    promo_bonus = _promo_bonus_for_package(promo, package)
    total_credits = total_package_credits(package, promo_bonus)
    order_id = f"{callback.from_user.id}_{int(time.time() * 1000)}_{package_id}"
    description = f"Покупка {total_credits} бананов ({package['name']})"

    result = await freekassa_service.create_payment(
        amount_rub=float(package["price_rub"]),
        order_id=order_id,
        description=description,
    )
    if not result.get("ok"):
        await callback.message.edit_text(
            "Не удалось создать платёж.\n"
            f"Причина: <code>{html.escape(str(result.get('error') or 'unknown'))}</code>",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    user = await get_or_create_user(callback.from_user.id)
    created = await create_transaction(
        order_id=order_id,
        user_id=user.id,
        payment_id=str(result["payment_id"]),
        provider="freekassa",
        credits=total_credits,
        amount_rub=float(package["price_rub"]),
        status="pending",
        promo_code_id=promo.id if promo and promo_bonus > 0 else None,
        promo_code=promo.code if promo and promo_bonus > 0 else None,
        promo_bonus_credits=promo_bonus,
    )
    if not created:
        await callback.message.edit_text(
            "Не удалось сохранить платёж. Выберите пакет и попробуйте ещё раз.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        await callback.answer()
        return

    bonus_text = ""
    if package_bonus > 0:
        bonus_text += f"\n• Бонус пакета: <code>{package_bonus}</code> бананов"
    if promo and promo_bonus > 0:
        bonus_text += (
            f"\n• Промокод <code>{html.escape(promo.code)}</code>: "
            f"+<code>{promo_bonus}</code> бананов"
        )

    await callback.message.edit_text(
        "💳 <b>Оплата через FreeKassa</b>\n"
        f"• Пакет: <code>{html.escape(str(package['name']))}</code>\n"
        f"• Бананов: <code>{total_credits}</code>{bonus_text}\n"
        f"• Сумма: <code>{package['price_rub']}</code> ₽\n\n"
        "Нажмите кнопку ниже. После оплаты бананы начислятся автоматически.",
        reply_markup=_freekassa_confirmation_keyboard(
            str(result["payment_url"]),
            order_id,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("check_freekassa_"))
async def check_freekassa_payment(
    callback: types.CallbackQuery,
):
    order_id = callback.data.replace("check_freekassa_", "", 1)
    transaction = await get_transaction_by_order(order_id)
    if not transaction or transaction.provider not in {"freekassa", "yookassa"}:
        await callback.answer("Транзакция не найдена", show_alert=True)
        return

    telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
    if telegram_id != callback.from_user.id:
        await callback.answer("Этот платёж создан для другого пользователя", show_alert=True)
        return

    if transaction.status == "completed":
        await callback.message.edit_text(
            "✅ <b>Оплата подтверждена</b>\n"
            f"• Начислено: <code>{transaction.credits}</code> бананов\n"
            f"• Сумма: <code>{transaction.amount_rub}</code> ₽"
            f"{_transaction_promo_text(transaction)}",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    payment = await freekassa_service.get_payment(merchant_order_id=order_id)
    if not payment or payment.get("status") == "webhook_only":
        await callback.answer(
            "Платёж ещё не подтверждён. После оплаты FreeKassa пришлёт уведомление автоматически.",
            show_alert=True,
        )
        return

    if payment.get("failed"):
        await update_transaction_status(order_id, "failed")
        await callback.answer("Платёж отменён или не прошёл", show_alert=True)
        return
    if not payment.get("paid"):
        await callback.answer("Платёж ещё в обработке", show_alert=True)
        return

    if not _amount_matches(payment.get("amount"), transaction.amount_rub):
        logger.error(
            "FreeKassa manual check amount mismatch order=%s actual=%s expected=%s",
            order_id,
            payment.get("amount"),
            transaction.amount_rub,
        )
        await callback.answer("Сумма платежа не совпала. Напишите в поддержку.", show_alert=True)
        return
    currency = str(payment.get("currency") or freekassa_service.currency).upper()
    if currency != freekassa_service.currency:
        await callback.answer("Валюта платежа не совпала. Напишите в поддержку.", show_alert=True)
        return

    provider_payment_id = str(payment.get("id") or "").strip()
    if provider_payment_id:
        await update_transaction_payment_id(order_id, provider_payment_id)

    result = await _complete_transaction(order_id, bot=callback.bot)
    if not result.get("ok"):
        await callback.answer("Не удалось завершить оплату", show_alert=True)
        return
    if result.get("already_completed"):
        await callback.answer("Оплата уже была зачислена ранее", show_alert=True)
        return

    transaction = result["transaction"]
    bonus_text = (
        _build_promo_bonus_text(result.get("promo_bonus") or {})
        + _build_bonus_text(result.get("referral_bonus") or {})
    )
    await callback.message.edit_text(
        "✅ <b>Оплата FreeKassa подтверждена</b>\n"
        f"• Начислено: <code>{transaction.credits}</code> бананов\n"
        f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


async def handle_freekassa_webhook(request: web.Request) -> web.Response:
    """Validate and atomically process a FreeKassa Result URL callback."""

    if not freekassa_service.enabled:
        return web.Response(text="FreeKassa disabled", status=503)

    remote_ip = _request_ip(request)
    if not freekassa_service.is_allowed_webhook_ip(remote_ip):
        logger.warning("Rejected FreeKassa webhook from IP %s", remote_ip)
        return web.Response(text="Forbidden", status=403)

    try:
        form = await request.post()
        payload = {str(key): str(value) for key, value in form.items()}
    except Exception:
        logger.exception("FreeKassa webhook form parsing failed")
        return web.Response(text="Invalid form", status=400)

    verified, reason = freekassa_service.verify_notification(payload)
    if not verified:
        logger.warning(
            "Rejected FreeKassa webhook: reason=%s merchant=%s order=%s ip=%s",
            reason,
            payload.get("MERCHANT_ID"),
            payload.get("MERCHANT_ORDER_ID"),
            remote_ip,
        )
        return web.Response(text="Invalid signature", status=403)

    order_id = str(payload.get("MERCHANT_ORDER_ID") or "").strip()
    transaction = await get_transaction_by_order(order_id)
    if not transaction or transaction.provider not in {"freekassa", "yookassa"}:
        logger.warning("FreeKassa transaction not found: order=%s", order_id)
        return web.Response(text="Order not found", status=404)

    if not _amount_matches(payload.get("AMOUNT"), transaction.amount_rub):
        logger.error(
            "Rejected FreeKassa webhook amount mismatch: order=%s actual=%s expected=%s",
            order_id,
            payload.get("AMOUNT"),
            transaction.amount_rub,
        )
        return web.Response(text="Amount mismatch", status=400)

    provider_payment_id = str(payload.get("intid") or "").strip()
    if provider_payment_id:
        await update_transaction_payment_id(order_id, provider_payment_id)

    completion = await _complete_transaction(order_id, bot=request.app.get("bot"))
    if completion.get("already_completed"):
        logger.info("FreeKassa webhook already processed: order=%s", order_id)
        return web.Response(text="YES")
    if not completion.get("ok"):
        logger.error(
            "FreeKassa webhook completion failed: order=%s reason=%s",
            order_id,
            completion.get("reason"),
        )
        return web.Response(text="Temporary error", status=500)

    transaction = completion["transaction"]
    telegram_id = completion.get("telegram_id")
    bonus_text = (
        _build_promo_bonus_text(completion.get("promo_bonus") or {})
        + _build_bonus_text(completion.get("referral_bonus") or {})
    )
    bot = request.app.get("bot")

    if bot and telegram_id:
        try:
            await _notify_user(
                bot,
                telegram_id,
                "✅ <b>Оплата FreeKassa успешно обработана</b>\n"
                f"• Начислено: <code>{transaction.credits}</code> бананов\n"
                f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}",
                parse_mode="HTML",
            )
        except TelegramBadRequest as exc:
            if _is_ignored_telegram_error(exc):
                logger.warning(
                    "Skipping FreeKassa notification for user %s: %s",
                    telegram_id,
                    exc,
                )
            else:
                logger.exception("FreeKassa Telegram notification failed")
        except Exception:
            logger.exception("FreeKassa Telegram notification failed")

    try:
        await create_miniapp_notification(
            transaction.user_id,
            f"✅ Оплата FreeKassa обработана — {transaction.credits} бананов "
            f"за {transaction.amount_rub} ₽",
        )
    except Exception:
        logger.exception("FreeKassa Mini App notification failed: order=%s", order_id)

    logger.info(
        "FreeKassa payment completed: order=%s intid=%s amount=%s",
        order_id,
        provider_payment_id,
        payload.get("AMOUNT"),
    )
    return web.Response(text="YES")


async def _freekassa_reconcile_loop(app: web.Application) -> None:
    await asyncio.sleep(FREEKASSA_RECONCILE_INTERVAL_SECONDS)
    while True:
        try:
            results = await freekassa_service.poll_pending_transactions(
                limit=FREEKASSA_RECONCILE_BATCH_SIZE,
                providers=("freekassa",),
                complete_order=lambda order_id: _complete_transaction(
                    order_id,
                    bot=app.get("bot"),
                ),
            )
            if results:
                logger.info(
                    "FreeKassa reconcile tick: checked=%s completed=%s failed=%s pending=%s",
                    len(results),
                    sum(
                        1
                        for item in results
                        if item.get("action") in {"completed", "already_completed"}
                    ),
                    sum(1 for item in results if item.get("action") == "failed"),
                    sum(1 for item in results if item.get("action") == "still_pending"),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("FreeKassa reconcile loop failed")
        await asyncio.sleep(FREEKASSA_RECONCILE_INTERVAL_SECONDS)


async def _freekassa_cleanup_context(app: web.Application):
    task = None
    if freekassa_service.api_enabled:
        task = asyncio.create_task(
            _freekassa_reconcile_loop(app),
            name="freekassa-reconcile",
        )
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await freekassa_service.close()


def setup_freekassa_routes(app: web.Application) -> None:
    paths = {freekassa_service.webhook_path, "/webhook/freekassa"}
    for path in paths:
        app.router.add_post(path, handle_freekassa_webhook)
    app.cleanup_ctx.append(_freekassa_cleanup_context)
    logger.info(
        "FreeKassa routes registered: paths=%s enabled=%s api_enabled=%s verify_ip=%s",
        sorted(paths),
        freekassa_service.enabled,
        freekassa_service.api_enabled,
        freekassa_service.verify_webhook_ip,
    )
