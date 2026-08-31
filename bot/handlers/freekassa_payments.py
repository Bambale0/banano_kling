from __future__ import annotations

import asyncio
import contextlib
import html
import logging
from decimal import Decimal
from typing import Any

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

from bot.config import config
from bot.database import (
    create_miniapp_notification,
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
    package_bonus_credits,
    package_stars_amount,
    total_package_credits,
)
from bot.services.cryptobot_service import cryptobot_service
from bot.services.freekassa_service import (
    freekassa_service,
    normalize_amount,
)
from bot.services.lava_service import lava_service
from bot.services.preset_manager import preset_manager

logger = logging.getLogger(__name__)
router = Router()

FREEKASSA_RECONCILE_INTERVAL_SECONDS = 5 * 60
FREEKASSA_RECONCILE_BATCH_SIZE = 100
FREEKASSA_BOT_RETURN_URL = "https://t.me/Neuromixx_bot"
FREEKASSA_CHECKOUT_PATH = "/freekassa/checkout"


class _CallbackDataProxy:
    """Delegate a callback while replacing only its routing payload."""

    def __init__(self, callback: types.CallbackQuery, data: str) -> None:
        self._callback = callback
        self.data = data

    def __getattr__(self, name: str) -> Any:
        return getattr(self._callback, name)


async def handle_freekassa_checkout(request: web.Request) -> web.Response:
    logger.info("Blocked disabled FreeKassa checkout request path=%s", request.path)
    return web.Response(
        text="""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Оплата отключена</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#101116;color:#fff;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{width:min(88vw,420px);padding:28px;border:1px solid #343641;border-radius:18px;background:#1b1d24}p{color:#b8bbc6;line-height:1.45}</style></head>
<body><main><h1>Оплата отключена</h1><p>Этот способ оплаты больше не используется. Вернитесь в бота и выберите оплату через Lava.</p></main></body></html>""",
        content_type="text/html",
        status=410,
    )


def _payment_return_page(*, title: str, message: str) -> str:
    bot_url = html.escape(FREEKASSA_BOT_RETURN_URL, quote=True)
    miniapp_url = html.escape(config.mini_app_url, quote=True)
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #fff7df;
      color: #21180a;
    }}
    main {{
      width: min(92vw, 460px);
      padding: 32px;
      border-radius: 24px;
      background: #fff;
      box-shadow: 0 18px 60px rgba(52, 35, 8, .16);
      text-align: center;
    }}
    h1 {{ margin: 0 0 12px; font-size: 28px; }}
    p {{ margin: 0 0 24px; line-height: 1.5; color: #5f513d; }}
    a {{
      display: block;
      padding: 14px 18px;
      margin-top: 10px;
      border-radius: 14px;
      text-decoration: none;
      font-weight: 700;
      background: #ffc83d;
      color: #21180a;
    }}
    a.secondary {{ background: #f2ead8; }}
  </style>
</head>
<body>
  <main>
    <h1>{html.escape(title)}</h1>
    <p>{html.escape(message)}</p>
    <a href="{bot_url}">Открыть бота</a>
    <a class="secondary" href="{miniapp_url}">Открыть Mini App</a>
  </main>
</body>
</html>"""


async def handle_freekassa_success_return(request: web.Request) -> web.Response:
    _ = request
    return web.Response(
        text=_payment_return_page(
            title="Оплата принята",
            message="Вернитесь в бота. Бананы начислятся автоматически после подтверждения KASSA.",
        ),
        content_type="text/html",
    )


async def handle_freekassa_fail_return(request: web.Request) -> web.Response:
    _ = request
    return web.Response(
        text=_payment_return_page(
            title="Оплата не завершена",
            message="Платеж отменен или не прошел. Можно вернуться в бота и попробовать еще раз.",
        ),
        content_type="text/html",
    )


def _provider_keyboard(
    package_id: str,
    *,
    stars: bool,
    freekassa: bool,
    crypto: bool,
    lava: bool,
) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if freekassa:
        builder.button(
            text="🇷🇺 РФ — KASSA (резерв)",
            callback_data=f"buy_freekassa_{package_id}",
        )
    if stars:
        builder.button(
            text="⭐ Telegram Stars", callback_data=f"buy_stars_{package_id}"
        )
    if crypto:
        builder.button(
            text="₿ Криптовалюта (CryptoBot)",
            callback_data=f"buy_crypto_{package_id}",
        )
    if lava:
        builder.button(
            text="🌐 Оплата через Lava", callback_data=f"buy_lava_{package_id}"
        )
    builder.button(text="◀️ Назад", callback_data="menu_topup")
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
    except (ValueError, TypeError):
        return False


async def _render_completed_payment(message, transaction, bonus_text: str = "") -> None:
    await message.edit_text(
        "✅ <b>Оплата подтверждена</b>\n"
        f"• Начислено: <code>{transaction.credits}</code> бананов\n"
        f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("choose_pay_"))
async def choose_payment_method_freekassa(
    callback: types.CallbackQuery, state: FSMContext
):
    """Show all enabled providers with FreeKassa replacing YooKassa."""

    package_id = callback.data.replace("choose_pay_", "", 1)
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    lava_offer_id, _ = _package_lava_offer_config(package)
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
    bonus_lines: list[str] = []
    if package_bonus > 0:
        bonus_lines.append(f"Бонус пакета: <code>{package_bonus}</code>🍌")
    if promo_bonus > 0 and promo:
        bonus_lines.append(
            f"Промокод <code>{html.escape(promo.code)}</code>: "
            f"+<code>{promo_bonus}</code>🍌"
        )
    bonus_text = ("\n" + "\n".join(bonus_lines)) if bonus_lines else ""

    await callback.message.edit_text(
        "💳 <b>Выберите способ оплаты</b>\n\n"
        f"Пакет: <b>{html.escape(str(package['name']))}</b>\n"
        f"Бананы: <code>{total_credits}</code>🍌\n"
        f"Сумма: <code>{package['price_rub']}</code>₽ / "
        f"<code>{package_stars_amount(package)}</code>⭐{bonus_text}",
        reply_markup=_provider_keyboard(
            package_id,
            stars=has_stars,
            freekassa=has_freekassa,
            crypto=has_crypto,
            lava=has_lava,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_freekassa_"))
async def choose_freekassa_method(callback: types.CallbackQuery):
    package_id = callback.data.replace("buy_freekassa_", "", 1)
    if not preset_manager.get_package(package_id):
        await callback.answer("Пакет не найден", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Картой", callback_data=f"buy_lava_card_{package_id}")
    builder.button(text="⚡ СБП", callback_data=f"buy_lava_sbp_{package_id}")
    builder.button(text="◀️ Назад", callback_data=f"choose_pay_{package_id}")
    builder.adjust(1)
    await callback.message.edit_text(
        "💳 <b>Выберите способ оплаты Lava</b>\n\n"
        "Карта и СБП оформляются через Lava.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("freekassa_card_"))
@router.callback_query(F.data.startswith("freekassa_sbp_"))
@router.callback_query(F.data.startswith("buy_yookassa_"))
async def initiate_freekassa_payment(
    callback: types.CallbackQuery, state: FSMContext
):
    """Keep old FreeKassa/YooKassa buttons working by routing them to Lava."""

    target_mode = "card"
    if callback.data.startswith("freekassa_sbp_"):
        prefix = "freekassa_sbp_"
        target_mode = "sbp"
    elif callback.data.startswith("freekassa_card_"):
        prefix = "freekassa_card_"
    else:
        prefix = "buy_yookassa_"
    package_id = callback.data.replace(prefix, "", 1)

    from bot.handlers.lava_checkout import handle_lava_checkout_entry

    proxy = _CallbackDataProxy(callback, f"buy_lava_{target_mode}_{package_id}")
    await handle_lava_checkout_entry(proxy, state)


@router.callback_query(F.data.startswith("check_freekassa_"))
async def check_freekassa_payment(callback: types.CallbackQuery):
    order_id = callback.data.replace("check_freekassa_", "", 1)
    transaction = await get_transaction_by_order(order_id)
    if not transaction or transaction.provider not in {"freekassa", "yookassa"}:
        await callback.answer("Транзакция не найдена", show_alert=True)
        return

    telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
    if telegram_id != callback.from_user.id:
        await callback.answer(
            "Этот платёж создан для другого пользователя", show_alert=True
        )
        return

    if transaction.status == "completed":
        await _render_completed_payment(
            callback.message,
            transaction,
            _transaction_promo_text(transaction),
        )
        await callback.answer()
        return

    payment = await freekassa_service.get_payment(merchant_order_id=order_id)
    if not payment or payment.get("status") == "webhook_only":
        await callback.answer(
            "Платёж ещё не подтверждён. KASSA уведомит бот автоматически.",
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
            "FreeKassa manual amount mismatch: order=%s actual=%s expected=%s",
            order_id,
            payment.get("amount"),
            transaction.amount_rub,
        )
        await callback.answer(
            "Сумма платежа не совпала. Напишите в поддержку.", show_alert=True
        )
        return
    currency = str(payment.get("currency") or freekassa_service.currency).upper()
    if currency != freekassa_service.currency:
        await callback.answer(
            "Валюта платежа не совпала. Напишите в поддержку.", show_alert=True
        )
        return

    provider_payment_id = str(payment.get("id") or "").strip()
    if provider_payment_id:
        await update_transaction_payment_id(order_id, provider_payment_id)

    completion = await _complete_transaction(order_id, bot=callback.bot)
    if not completion.get("ok"):
        await callback.answer("Не удалось завершить оплату", show_alert=True)
        return
    if completion.get("already_completed"):
        await callback.answer("Оплата уже была зачислена ранее", show_alert=True)
        return

    bonus_text = (
        _build_promo_bonus_text(completion.get("promo_bonus") or {})
        + _build_bonus_text(completion.get("referral_bonus") or {})
    )
    await _render_completed_payment(
        callback.message,
        completion["transaction"],
        bonus_text,
    )
    await callback.answer()


async def handle_freekassa_webhook(request: web.Request) -> web.Response:
    """Validate FreeKassa Result URL data and complete the order atomically."""

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
            "Rejected FreeKassa amount mismatch: order=%s actual=%s expected=%s",
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
            "FreeKassa completion failed: order=%s reason=%s",
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
                "✅ <b>Оплата KASSA успешно обработана</b>\n"
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
            f"✅ Оплата KASSA обработана — {transaction.credits} бананов "
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


async def _reconcile_loop(app: web.Application) -> None:
    await asyncio.sleep(FREEKASSA_RECONCILE_INTERVAL_SECONDS)
    while True:
        try:
            results = await freekassa_service.poll_pending_transactions(
                limit=FREEKASSA_RECONCILE_BATCH_SIZE,
                providers=("freekassa",),
                complete_order=lambda order_id: _complete_transaction(
                    order_id, bot=app.get("bot")
                ),
            )
            if results:
                logger.info(
                    "FreeKassa reconcile: checked=%s completed=%s failed=%s pending=%s",
                    len(results),
                    sum(
                        item.get("action") in {"completed", "already_completed"}
                        for item in results
                    ),
                    sum(item.get("action") == "failed" for item in results),
                    sum(item.get("action") == "still_pending" for item in results),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("FreeKassa reconcile loop failed")
        await asyncio.sleep(FREEKASSA_RECONCILE_INTERVAL_SECONDS)


async def _cleanup_context(app: web.Application):
    task = None
    if freekassa_service.api_enabled:
        task = asyncio.create_task(_reconcile_loop(app), name="freekassa-reconcile")
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
    app.router.add_get("/payment/success", handle_freekassa_success_return)
    app.router.add_get("/payment/fail", handle_freekassa_fail_return)
    app.router.add_get(FREEKASSA_CHECKOUT_PATH, handle_freekassa_checkout)
    app.router.add_post(FREEKASSA_CHECKOUT_PATH, handle_freekassa_checkout)
    app.cleanup_ctx.append(_cleanup_context)
    logger.info(
        "FreeKassa routes registered: paths=%s enabled=%s api_enabled=%s verify_ip=%s",
        sorted(paths),
        freekassa_service.enabled,
        freekassa_service.api_enabled,
        freekassa_service.verify_webhook_ip,
    )
