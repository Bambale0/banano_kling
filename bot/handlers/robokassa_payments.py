from __future__ import annotations

import html
import logging
from functools import wraps
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
from bot.services.freekassa_service import freekassa_service
from bot.services.lava_service import lava_service
from bot.services.preset_manager import preset_manager
from bot.services.robokassa_service import (
    amounts_equal,
    new_invoice_id,
    robokassa_service,
)

logger = logging.getLogger(__name__)
router = Router()

_ROBOKASSA_ROUTES_REGISTERED = web.AppKey("robokassa_routes_registered", bool)


def _provider_keyboard(
    package_id: str,
    *,
    robokassa: bool,
    freekassa: bool,
    stars: bool,
    crypto: bool,
    lava: bool,
) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if lava:
        builder.button(text="💳 Lava", callback_data=f"buy_lava_{package_id}")
    if freekassa:
        builder.button(
            text="↩️ Резерв · KASSA",
            callback_data=f"buy_freekassa_{package_id}",
        )
    if robokassa:
        builder.button(
            text="↩️ Резерв · Robokassa",
            callback_data=f"buy_robokassa_{package_id}",
        )
    if crypto:
        builder.button(
            text="₿ Криптовалюта (CryptoBot)",
            callback_data=f"buy_crypto_{package_id}",
        )
    if stars:
        builder.button(text="⭐ Telegram Stars", callback_data=f"buy_stars_{package_id}")
    builder.button(text="◀️ Назад", callback_data="menu_topup")
    builder.adjust(1)
    return builder.as_markup()


def _confirmation_keyboard(payment_url: str, order_id: str) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Перейти к оплате", url=payment_url)
    builder.button(
        text="✅ Проверить оплату",
        callback_data=f"check_robokassa_{order_id}",
    )
    builder.button(text="❌ Отмена", callback_data="cancel_payment")
    builder.adjust(1)
    return builder.as_markup()


async def _render_completed_payment(message, transaction, bonus_text: str = "") -> None:
    await message.edit_text(
        "✅ <b>Оплата подтверждена</b>\n"
        f"• Начислено: <code>{transaction.credits}</code> бананов\n"
        f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("choose_pay_"))
async def choose_payment_method_robokassa(
    callback: types.CallbackQuery, state: FSMContext
):
    """Show Robokassa first while retaining established reserve methods."""

    package_id = callback.data.replace("choose_pay_", "", 1)
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    lava_offer_id, _ = _package_lava_offer_config(package)
    has_robokassa = robokassa_service.enabled
    has_freekassa = freekassa_service.api_enabled
    has_stars = bool(config.TELEGRAM_STARS_ENABLED)
    has_crypto = cryptobot_service.enabled
    has_lava = lava_service.enabled and bool(lava_offer_id)

    if not any((has_robokassa, has_freekassa, has_stars, has_crypto, has_lava)):
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
        f"Пакет: <b>{html.escape(str(package.get("name", "")))}</b>\n"
        f"Бананы: <code>{total_credits}</code>🍌\n"
        f"Сумма: <code>{package.get("price_rub")}</code>₽ / "
        f"<code>{package_stars_amount(package)}</code>⭐{bonus_text}",
        reply_markup=_provider_keyboard(
            package_id,
            robokassa=has_robokassa,
            freekassa=has_freekassa,
            stars=has_stars,
            crypto=has_crypto,
            lava=has_lava,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_robokassa_"))
async def initiate_robokassa_payment(
    callback: types.CallbackQuery, state: FSMContext
):
    if not robokassa_service.enabled:
        await callback.message.edit_text(
            "Robokassa временно недоступна. Попробуйте резервный способ оплаты.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        await callback.answer()
        return

    package_id = callback.data.replace("buy_robokassa_", "", 1)
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    promo = await _get_selected_promo(state)
    package_bonus = package_bonus_credits(package)
    promo_bonus = _promo_bonus_for_package(promo, package)
    total_credits = total_package_credits(package, promo_bonus)
    user = await get_or_create_user(callback.from_user.id)

    order_id = ""
    for _ in range(3):
        candidate = new_invoice_id()
        created = await create_transaction(
            order_id=candidate,
            user_id=user.id,
            payment_id=candidate,
            provider="robokassa",
            credits=total_credits,
            amount_rub=float(package["price_rub"]),
            status="pending",
            promo_code_id=promo.id if promo and promo_bonus > 0 else None,
            promo_code=promo.code if promo and promo_bonus > 0 else None,
            promo_bonus_credits=promo_bonus,
        )
        if created:
            order_id = candidate
            break
    if not order_id:
        await callback.message.edit_text(
            "Не удалось сохранить платёж. Попробуйте ещё раз.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        await callback.answer()
        return

    payment_url = robokassa_service.create_payment_url(
        amount_rub=package["price_rub"],
        inv_id=order_id,
        description=f"Покупка {total_credits} бананов ({package.get("name", "")})",
    )

    bonus_text = ""
    if package_bonus > 0:
        bonus_text += f"\n• Бонус пакета: <code>{package_bonus}</code> бананов"
    if promo and promo_bonus > 0:
        bonus_text += (
            f"\n• Промокод <code>{html.escape(promo.code)}</code>: "
            f"+<code>{promo_bonus}</code> бананов"
        )

    await callback.message.edit_text(
        "💳 <b>КАРТА | СБП</b>\n"
        f"• Пакет: <code>{html.escape(str(package.get("name", "")))}</code>\n"
        f"• Бананов: <code>{total_credits}</code>{bonus_text}\n"
        f"• Сумма: <code>{package.get("price_rub")}</code> ₽\n\n"
        "На странице Robokassa выберите удобный способ оплаты. "
        "После подтверждения бананы начислятся автоматически.",
        reply_markup=_confirmation_keyboard(payment_url, order_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("check_robokassa_"))
async def check_robokassa_payment(callback: types.CallbackQuery):
    order_id = callback.data.replace("check_robokassa_", "", 1)
    transaction = await get_transaction_by_order(order_id)
    if not transaction or transaction.provider != "robokassa":
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

    await callback.answer(
        "Платёж ещё не подтверждён. После оплаты баланс обновится автоматически.",
        show_alert=True,
    )


async def handle_robokassa_result(request: web.Request) -> web.Response:
    """Verify ResultURL signature and atomically complete the matching order."""

    if not robokassa_service.enabled:
        return web.Response(text="Robokassa disabled", status=503)

    try:
        values = request.query if request.method == "GET" else await request.post()
        payload = {str(key): str(value) for key, value in values.items()}
    except Exception:
        logger.exception("Robokassa ResultURL parsing failed")
        return web.Response(text="Invalid request", status=400)

    verified, reason = robokassa_service.verify_result(payload)
    if not verified:
        logger.warning(
            "Rejected Robokassa ResultURL: reason=%s inv_id=%s",
            reason,
            payload.get("InvId"),
        )
        return web.Response(text="Invalid signature", status=403)

    order_id = str(payload.get("InvId") or "").strip()
    transaction = await get_transaction_by_order(order_id)
    if not transaction or transaction.provider != "robokassa":
        logger.warning("Robokassa transaction not found: inv_id=%s", order_id)
        return web.Response(text="Order not found", status=404)

    if not amounts_equal(payload.get("OutSum"), transaction.amount_rub):
        logger.error(
            "Rejected Robokassa amount mismatch: inv_id=%s actual=%s expected=%s",
            order_id,
            payload.get("OutSum"),
            transaction.amount_rub,
        )
        return web.Response(text="Amount mismatch", status=400)

    completion = await _complete_transaction(order_id, bot=request.app.get("bot"))
    if completion.get("already_completed"):
        logger.info("Robokassa ResultURL already processed: inv_id=%s", order_id)
        return web.Response(text=f"OK{order_id}")
    if not completion.get("ok"):
        logger.error(
            "Robokassa completion failed: inv_id=%s reason=%s",
            order_id,
            completion.get("reason"),
        )
        return web.Response(text="Temporary error", status=500)

    completed_transaction = completion["transaction"]
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
                "✅ <b>Оплата Robokassa успешно обработана</b>\n"
                f"• Начислено: <code>{completed_transaction.credits}</code> бананов\n"
                f"• Сумма: <code>{completed_transaction.amount_rub}</code> ₽{bonus_text}",
                parse_mode="HTML",
            )
        except TelegramBadRequest as exc:
            if _is_ignored_telegram_error(exc):
                logger.warning(
                    "Skipping Robokassa notification for user %s: %s",
                    telegram_id,
                    exc,
                )
            else:
                logger.exception("Robokassa Telegram notification failed")
        except Exception:
            logger.exception("Robokassa Telegram notification failed")

    try:
        await create_miniapp_notification(
            completed_transaction.user_id,
            f"✅ Оплата Robokassa обработана — {completed_transaction.credits} бананов "
            f"за {completed_transaction.amount_rub} ₽",
        )
    except Exception:
        logger.exception("Robokassa Mini App notification failed: inv_id=%s", order_id)

    logger.info(
        "Robokassa payment completed: inv_id=%s amount=%s method=%s",
        order_id,
        payload.get("OutSum"),
        payload.get("PaymentMethod"),
    )
    return web.Response(text=f"OK{order_id}")


def _install_robokassa_package_flag(miniapp_module: Any) -> None:
    current_payload = miniapp_module._payment_package_payload
    if getattr(current_payload, "_robokassa_primary_compat", False):
        return

    @wraps(current_payload)
    def payment_package_with_robokassa(package: dict[str, Any]) -> dict[str, Any]:
        payload = current_payload(package)
        payload["robokassa_enabled"] = bool(robokassa_service.enabled)
        return payload

    payment_package_with_robokassa._robokassa_primary_compat = True
    miniapp_module._payment_package_payload = payment_package_with_robokassa


async def _create_robokassa_miniapp_checkout(
    request: web.Request,
    body: dict[str, Any],
    miniapp_module: Any,
) -> web.Response:
    if not robokassa_service.enabled:
        return web.json_response(
            {"ok": False, "error": "Robokassa временно недоступна"}, status=503
        )

    package_id = body.get("package_id")
    if not package_id:
        return web.json_response(
            {"ok": False, "error": "package_id is required"}, status=400
        )

    _telegram_id, ctx = await miniapp_module._get_user_context(
        request.app,
        body.get("init_data", ""),
        body.get("start_param_fallback"),
    )
    user = ctx["user"]
    package = miniapp_module.preset_manager.get_package(package_id)
    if not package:
        return web.json_response(
            {"ok": False, "error": "Package not found"}, status=404
        )

    promo_code = body.get("promo_code")
    promo = (
        await miniapp_module.get_promo_code_by_code(promo_code, active_only=True)
        if promo_code
        else None
    )
    promo_bonus = (
        miniapp_module.get_promo_bonus_for_credits(package["credits"]) if promo else 0
    )
    total_credits = miniapp_module.total_package_credits(package, promo_bonus)

    order_id = ""
    for _ in range(3):
        candidate = new_invoice_id()
        created = await miniapp_module.create_transaction(
            order_id=candidate,
            user_id=user.id,
            payment_id=candidate,
            provider="robokassa",
            credits=total_credits,
            amount_rub=float(package["price_rub"]),
            status="pending",
            promo_code_id=promo.id if promo and promo_bonus > 0 else None,
            promo_code=promo.code if promo and promo_bonus > 0 else None,
            promo_bonus_credits=promo_bonus,
        )
        if created:
            order_id = candidate
            break
    if not order_id:
        return web.json_response(
            {"ok": False, "error": "Не удалось сохранить платёж. Попробуйте ещё раз."},
            status=500,
        )

    payment_url = robokassa_service.create_payment_url(
        amount_rub=package["price_rub"],
        inv_id=order_id,
        description=f"Покупка {total_credits} бананов ({package.get("name", "")})",
    )
    return web.json_response(
        {
            "ok": True,
            "provider": "robokassa",
            "order_id": order_id,
            "payment_id": order_id,
            "payment_url": payment_url,
            "credits": total_credits,
            "promo_bonus_credits": promo_bonus,
            "promo_code": promo.code if promo and promo_bonus > 0 else "",
        }
    )


def install_robokassa_payment_surfaces() -> None:
    """Expose Robokassa availability and Mini App checkout without replacing reserves."""

    import bot.miniapp as miniapp_module

    _install_robokassa_package_flag(miniapp_module)
    current_create_payment = miniapp_module.miniapp_create_payment
    if getattr(current_create_payment, "_robokassa_primary_compat", False):
        return

    @wraps(current_create_payment)
    async def create_payment_with_robokassa(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            raw_provider = str(body.get("provider") or "").strip().lower()
            if raw_provider != "robokassa":
                return await current_create_payment(request)
            return await _create_robokassa_miniapp_checkout(request, body, miniapp_module)
        except Exception as exc:  # noqa: BLE001
            return miniapp_module._miniapp_error_response(
                exc,
                log_message="Mini App Robokassa payment creation failed",
            )

    create_payment_with_robokassa._robokassa_primary_compat = True
    miniapp_module.miniapp_create_payment = create_payment_with_robokassa


def setup_robokassa_routes(app: web.Application) -> None:
    if app.get(_ROBOKASSA_ROUTES_REGISTERED, False):
        return

    paths = {robokassa_service.webhook_path, "/webhook/robokassa"}
    for path in paths:
        app.router.add_post(path, handle_robokassa_result)
        app.router.add_get(path, handle_robokassa_result)
    app[_ROBOKASSA_ROUTES_REGISTERED] = True
    logger.info(
        "Robokassa routes registered: paths=%s enabled=%s test_mode=%s hash=%s",
        sorted(paths),
        robokassa_service.enabled,
        robokassa_service.test_mode,
        robokassa_service.hash_algorithm,
    )
