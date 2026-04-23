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
from bot.services.tbank_service import tbank_service

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
    except TelegramBadRequest as exc:
        if _is_ignored_telegram_error(exc):
            raise
        raise


def _format_bonus_text(referral_bonus: dict) -> str:
    if referral_bonus.get("mode") == "partner":
        return f"🎁 Партнёрский бонус: <code>{referral_bonus['value']}</code> ₽\n"
    if referral_bonus.get("mode") == "banana":
        return f"🎁 Реферальный бонус: <code>{referral_bonus['value']}</code> бананов\n"
    return ""


def _topup_menu_text() -> str:
    return (
        "🍌 <b>Пополнение баланса</b>\n\n"
        "Выберите способ оплаты и пакет бананов.\n"
        "<i>Чем больше пакет, тем выгоднее цена за банан.</i>\n\n"
        "🍌 <b>Как тратятся бананы</b>\n"
        "• стандартные генерации: от 1 🍌\n"
        "• продвинутые модели: дороже, в зависимости от режима"
    )


def _payment_created_text(package: dict, total_credits: int) -> str:
    bonus_text = ""
    if package.get("bonus_credits", 0) > 0:
        bonus_text = f"\n🎁 Бонус: <code>{package['bonus_credits']}</code> бананов"

    return (
        f"💳 <b>Оплата пакета «{package['name']}»</b>\n\n"
        f"🍌 Бананов: <code>{total_credits}</code>{bonus_text}\n"
        f"💰 Сумма: <code>{package['price_rub']}</code> ₽\n\n"
        "Нажмите кнопку ниже, чтобы перейти к оплате.\n"
        "После успешной оплаты бананы начислятся автоматически."
    )


def _payment_success_text(transaction, referral_bonus: dict | None = None) -> str:
    bonus_text = _format_bonus_text(referral_bonus or {})
    return (
        "🎉 <b>Оплата успешна!</b>\n\n"
        f"🍌 Начислено: <code>{transaction.credits}</code> бананов\n"
        f"💰 Сумма: <code>{transaction.amount_rub}</code> ₽\n"
        f"{bonus_text}\n"
        "Теперь можно продолжать генерацию."
    )


async def _render_topup_menu(message: types.Message, provider: str):
    packages = preset_manager.get_packages()
    await message.edit_text(
        _topup_menu_text(),
        reply_markup=get_payment_packages_keyboard(packages, provider=provider),
        parse_mode="HTML",
    )


async def _complete_transaction(order_id: str, bot: Bot | None = None) -> bool:
    transaction = await get_transaction_by_order(order_id)
    if not transaction or transaction.status == "completed":
        return bool(transaction and transaction.status == "completed")

    telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
    if not telegram_id:
        logger.error("Telegram user not found for transaction %s", order_id)
        return False

    await add_credits(telegram_id, transaction.credits)
    await update_transaction_status(order_id, "completed")
    referral_bonus = await credit_first_payment_referral_bonus(
        telegram_id, transaction.credits, transaction.amount_rub
    )

    if bot:
        try:
            await _notify_user(
                bot,
                telegram_id,
                _payment_success_text(transaction, referral_bonus),
                parse_mode="HTML",
            )
        except TelegramBadRequest as exc:
            if _is_ignored_telegram_error(exc):
                logger.warning(
                    "Skipping payment notification for %s: %s", telegram_id, exc
                )
            else:
                logger.exception("Failed to notify user about payment")

    return True


@router.callback_query(F.data == "menu_topup")
async def show_topup_menu(callback: types.CallbackQuery):
    await _render_topup_menu(callback.message, config.payment_provider)


@router.callback_query(F.data == "menu_buy_credits")
async def show_packages(callback: types.CallbackQuery):
    await _render_topup_menu(callback.message, config.payment_provider)


@router.callback_query(F.data.startswith("topup_provider_"))
async def select_topup_provider(callback: types.CallbackQuery):
    provider = callback.data.replace("topup_provider_", "")
    if provider not in {"tbank", "cryptobot"}:
        provider = config.payment_provider

    await _render_topup_menu(callback.message, provider)
    provider_text = "Выбран Crypto Bot" if provider == "cryptobot" else "Выбран Т-Банк"
    await callback.answer(provider_text)


@router.callback_query(F.data.startswith("buy_"))
async def initiate_payment(callback: types.CallbackQuery):
    payload = callback.data.replace("buy_", "")
    provider = config.payment_provider

    if payload.startswith("cryptobot_"):
        provider = "cryptobot"
        package_id = payload.replace("cryptobot_", "", 1)
    elif payload.startswith("tbank_"):
        provider = "tbank"
        package_id = payload.replace("tbank_", "", 1)
    else:
        package_id = payload

    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    order_id = f"{callback.from_user.id}_{int(time.time())}_{package_id}"
    amount_kop = package["price_rub"] * 100

    bot_info = await callback.bot.get_me()
    success_url = f"https://t.me/{bot_info.username}?start=success_{order_id}"
    fail_url = f"https://t.me/{bot_info.username}?start=fail_{order_id}"

    if provider == "cryptobot" and cryptobot_service.enabled:
        result = await cryptobot_service.create_invoice(
            amount_rub=package["price_rub"],
            order_id=order_id,
            description=f"Покупка {package['credits']} бананов ({package['name']})",
            paid_btn_url=success_url,
        )
    else:
        provider = "tbank"
        result = await tbank_service.init_payment(
            amount=amount_kop,
            order_id=order_id,
            description=f"Покупка {package['credits']} бананов ({package['name']})",
            customer_key=str(callback.from_user.id),
            success_url=success_url,
            fail_url=fail_url,
            notification_url=config.tbank_notification_url,
        )

    if not result or not result.get("Success"):
        error_msg = (
            result.get("Message", "Неизвестная ошибка")
            if result
            else "Нет соединения с платёжным сервисом"
        )
        await callback.message.edit_text(
            "❌ <b>Не удалось создать платёж</b>\n\n"
            f"{error_msg}\n"
            "Попробуйте позже или выберите другой способ оплаты.",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        return

    payment_id = result["PaymentId"]
    payment_url = result["PaymentURL"]

    user = await get_or_create_user(callback.from_user.id)
    total_credits = package["credits"] + package.get("bonus_credits", 0)
    await create_transaction(
        order_id=order_id,
        user_id=user.id,
        payment_id=str(payment_id),
        provider=provider,
        credits=total_credits,
        amount_rub=package["price_rub"],
        status="pending",
    )

    await callback.message.edit_text(
        _payment_created_text(package, total_credits),
        reply_markup=get_payment_confirmation_keyboard(payment_url, order_id),
        parse_mode="HTML",
    )


@router.message(F.text.startswith("/cryptobot"))
async def cryptobot_status_hint(message: types.Message):
    if config.has_cryptobot:
        await message.answer("✅ Crypto Bot настроен и готов к приёму платежей.")
    else:
        await message.answer(
            "⚠️ Crypto Bot не настроен. Проверьте переменную CRYPTOBOT_API_TOKEN."
        )


@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment_status(callback: types.CallbackQuery):
    order_id = callback.data.replace("check_payment_", "")
    transaction = await get_transaction_by_order(order_id)

    if not transaction:
        await callback.answer("Транзакция не найдена", show_alert=True)
        return

    if transaction.status == "completed":
        await callback.message.edit_text(
            _payment_success_text(transaction),
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    paid = False
    if transaction.provider == "cryptobot":
        invoice = await cryptobot_service.get_invoice(transaction.payment_id)
        paid = bool(invoice and invoice.get("status") == "paid")
    else:
        result = await tbank_service.get_state(transaction.payment_id)
        paid = bool(result and result.get("Status") == "CONFIRMED")

    if not paid:
        await callback.answer("⏳ Платёж ещё не подтверждён.", show_alert=True)
        return

    await _complete_transaction(order_id)
    transaction = await get_transaction_by_order(order_id)
    await callback.message.edit_text(
        _payment_success_text(transaction),
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "❌ <b>Платёж отменён</b>\n\n" "Вы можете попробовать снова в любое время.",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )


async def handle_tbank_webhook(request):
    try:
        data = await request.json()
        logger.info("T-Bank webhook received: %s", data.get("OrderId"))

        if not tbank_service.verify_notification(data.copy()):
            logger.warning("Invalid signature in T-Bank webhook")
            return web.Response(status=403)

        if data.get("Status") == "CONFIRMED":
            await _complete_transaction(data.get("OrderId"), request.app["bot"])

        return web.Response(text="OK", status=200)
    except Exception as exc:
        logger.exception("Error processing T-Bank webhook: %s", exc)
        return web.Response(status=500)


async def handle_cryptobot_webhook(request):
    try:
        raw_body = await request.read()
        signature = request.headers.get("crypto-pay-api-signature", "")

        if not cryptobot_service.verify_webhook_signature(raw_body, signature):
            logger.warning("Invalid Crypto Bot webhook signature")
            return web.Response(status=403)

        data = await request.json()
        if data.get("update_type") != "invoice_paid":
            return web.Response(status=200)

        invoice = data.get("payload", {})
        order_id = invoice.get("payload")
        if not order_id:
            logger.warning("Crypto Bot webhook missing order_id")
            return web.Response(status=200)

        await _complete_transaction(order_id, request.app["bot"])
        return web.Response(status=200)
    except Exception as exc:
        logger.exception("Error processing Crypto Bot webhook: %s", exc)
        return web.Response(status=500)
