import json
import logging
import time

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiohttp import web

from bot.config import config
from bot.database import (
    add_credits,
    create_transaction,
    credit_first_payment_referral_bonus,
    get_or_create_user,
    get_telegram_id_by_user_id,
    get_transaction_by_order,
    update_transaction_status,
)
from bot.keyboards import (
    get_back_keyboard,
    get_main_menu_keyboard,
    get_payment_confirmation_keyboard,
    get_payment_packages_keyboard,
)
from bot.services.cryptobot_service import cryptobot_service
from bot.services.preset_manager import preset_manager

logger = logging.getLogger(__name__)
router = Router()


def _is_ignored_telegram_error(error: Exception) -> bool:
    error_msg = str(error).lower()
    return (
        "chat not found" in error_msg
        or "bot was blocked" in error_msg
        or "user is deactivated" in error_msg
        or "bot can't initiate conversation" in error_msg
        or "forbidden" in error_msg
        or "chat is deactivated" in error_msg
    )


async def _notify_user(bot: Bot, telegram_id: int, text: str, *, parse_mode=None):
    try:
        await bot.send_message(telegram_id, text, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        if _is_ignored_telegram_error(e):
            raise
        raise


async def _render_topup_menu(message: types.Message):
    packages = preset_manager.get_packages()
    text = (
        "🍌 <b>Пополнение баланса</b>\n\n"
        "Оплата выполняется через CryptoBot.\n"
        "Выберите пакет бананов ниже.\n\n"
        "<i>Чем больше пакет, тем выгоднее цена за банан.</i>"
    )

    await message.edit_text(
        text,
        reply_markup=get_payment_packages_keyboard(packages),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_topup")
async def show_topup_menu(callback: types.CallbackQuery):
    await _render_topup_menu(callback.message)


@router.callback_query(F.data == "menu_buy_credits")
async def show_packages(callback: types.CallbackQuery):
    await _render_topup_menu(callback.message)


@router.callback_query(F.data.startswith("buy_"))
async def initiate_payment(callback: types.CallbackQuery):
    """Создаёт инвойс в CryptoBot."""
    if not cryptobot_service.enabled:
        await callback.message.edit_text(
            "Не удалось создать оплату: CryptoBot не настроен.\n"
            "Проверьте переменную окружения <code>CRYPTOBOT_API_TOKEN</code>.",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
        return

    payload = callback.data.replace("buy_", "", 1)
    package_id = payload
    if payload.startswith("crypto_"):
        package_id = payload.replace("crypto_", "", 1)
    elif "_" in payload:
        # Совместимость со старыми callback вида buy_tbank_xxx / buy_yookassa_xxx
        package_id = payload.split("_", 1)[1]
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    order_id = f"{callback.from_user.id}_{int(time.time())}_{package_id}"

    bot_info = await callback.bot.get_me()
    success_url = f"https://t.me/{bot_info.username}?start=success_{order_id}"

    total_credits = package["credits"] + package.get("bonus_credits", 0)
    description = f"Покупка {total_credits} бананов ({package['name']})"

    result = await cryptobot_service.create_invoice(
        amount_rub=float(package["price_rub"]),
        description=description,
        order_id=order_id,
        paid_btn_url=success_url,
    )

    if not result or not result.get("ok"):
        error_msg = (
            (result or {}).get("error")
            or (result or {}).get("message")
            or "Не удалось создать инвойс"
        )
        await callback.message.edit_text(
            "Не удалось создать платёж.\n" f"Причина: <code>{error_msg}</code>",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        return

    invoice = result.get("result") or {}
    invoice_id = str(invoice.get("invoice_id"))
    payment_url = (
        invoice.get("bot_invoice_url")
        or invoice.get("mini_app_invoice_url")
        or invoice.get("web_app_invoice_url")
    )

    if not invoice_id or not payment_url:
        await callback.message.edit_text(
            "Не удалось получить ссылку на оплату от CryptoBot.",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        return

    user = await get_or_create_user(callback.from_user.id)
    await create_transaction(
        order_id=order_id,
        user_id=user.id,
        payment_id=invoice_id,
        provider="cryptobot",
        credits=total_credits,
        amount_rub=float(package["price_rub"]),
        status="pending",
    )

    bonus_text = ""
    if package.get("bonus_credits", 0) > 0:
        bonus_text = f"\n• Бонус: <code>{package['bonus_credits']}</code> бананов"

    await callback.message.edit_text(
        "💳 <b>Оплата через CryptoBot</b>\n"
        f"• Пакет: <code>{package['name']}</code>\n"
        f"• Бананов: <code>{total_credits}</code>{bonus_text}\n"
        f"• Сумма: <code>{package['price_rub']}</code> ₽\n\n"
        "Нажмите кнопку ниже и завершите оплату в CryptoBot.",
        reply_markup=get_payment_confirmation_keyboard(payment_url, order_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment_status(callback: types.CallbackQuery):
    """Ручная проверка статуса платежа в CryptoBot."""
    order_id = callback.data.replace("check_payment_", "")
    transaction = await get_transaction_by_order(order_id)

    if not transaction:
        await callback.answer("Транзакция не найдена", show_alert=True)
        return

    if transaction.status == "completed":
        await callback.message.edit_text(
            "✅ <b>Оплата подтверждена</b>\n"
            f"• Начислено: <code>{transaction.credits}</code> бананов\n"
            f"• Сумма: <code>{transaction.amount_rub}</code> ₽",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    if not cryptobot_service.enabled:
        await callback.answer("Платёжный сервис временно недоступен", show_alert=True)
        return

    invoice = await cryptobot_service.get_invoice(transaction.payment_id)
    status = (invoice or {}).get("status", "")
    paid = status == "paid"

    if not paid:
        await callback.answer("Платёж ещё в обработке", show_alert=True)
        return

    user = await get_or_create_user(transaction.user_id)
    await add_credits(user.telegram_id, transaction.credits)
    await update_transaction_status(order_id, "completed")
    referral_bonus = await credit_first_payment_referral_bonus(
        user.telegram_id, transaction.credits, transaction.amount_rub
    )

    bonus_text = ""
    if referral_bonus.get("mode") == "partner":
        bonus_text = f"\n🎁 Партнёрский бонус: <code>{referral_bonus['value']}</code> ₽"
    elif referral_bonus.get("mode") == "banana":
        bonus_text = (
            f"\n🎁 Реферальный бонус: <code>{referral_bonus['value']}</code> бананов"
        )

    await callback.message.edit_text(
        "✅ <b>Оплата подтверждена</b>\n"
        f"• Начислено: <code>{transaction.credits}</code> бананов\n"
        f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "Платёж отменён. Вы можете попробовать снова в любое время.",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )


async def handle_cryptobot_webhook(request: web.Request):
    """Webhook updates from Crypto Pay API."""
    try:
        raw_body = await request.read()
        if not raw_body:
            return web.Response(status=200)

        signature = request.headers.get("crypto-pay-api-signature", "")
        if signature and not cryptobot_service.verify_webhook_signature(
            raw_body, signature
        ):
            logger.warning("Invalid CryptoBot webhook signature")
            return web.Response(status=403)

        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception:
            return web.Response(status=200)

        if data.get("update_type") != "invoice_paid":
            return web.Response(status=200)

        invoice = data.get("payload") or {}
        if (invoice.get("status") or "") != "paid":
            return web.Response(status=200)

        order_id = invoice.get("payload")
        if not order_id:
            logger.warning("CryptoBot webhook has no invoice payload order_id")
            return web.Response(status=200)

        transaction = await get_transaction_by_order(order_id)
        if not transaction or transaction.status == "completed":
            return web.Response(status=200)

        telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
        if not telegram_id:
            logger.warning(
                "Cannot resolve telegram_id for user_id=%s", transaction.user_id
            )
            return web.Response(status=200)

        await add_credits(telegram_id, transaction.credits)
        await update_transaction_status(order_id, "completed")
        referral_bonus = await credit_first_payment_referral_bonus(
            telegram_id, transaction.credits, transaction.amount_rub
        )

        bonus_text = ""
        if referral_bonus.get("mode") == "partner":
            bonus_text = (
                f"\n🎁 Партнёрский бонус: <code>{referral_bonus['value']}</code> ₽"
            )
        elif referral_bonus.get("mode") == "banana":
            bonus_text = f"\n🎁 Реферальный бонус: <code>{referral_bonus['value']}</code> бананов"

        try:
            await _notify_user(
                request.app["bot"],
                telegram_id,
                "✅ <b>Оплата успешно обработана</b>\n"
                f"• Начислено: <code>{transaction.credits}</code> бананов\n"
                f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}",
                parse_mode="HTML",
            )
        except TelegramBadRequest as e:
            if _is_ignored_telegram_error(e):
                logger.warning(
                    "Skipping CryptoBot notification for user %s: %s", telegram_id, e
                )
            else:
                logger.error("Failed to notify user %s: %s", telegram_id, e)

        return web.Response(status=200)

    except Exception as e:
        logger.exception("Error processing CryptoBot webhook: %s", e)
        return web.Response(status=200)
