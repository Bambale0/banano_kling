import logging
import time

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiohttp import web

from bot.config import config
from bot.database import (
    add_credits,
    create_transaction,
    credit_first_payment_referral_bonus,
    get_or_create_user,
    get_telegram_id_by_user_id,
    get_transaction_by_order,
    get_user_credits,
    update_transaction_status,
)
from bot.keyboards import (
    get_back_keyboard,
    get_main_menu_keyboard,
    get_payment_confirmation_keyboard,
    get_payment_packages_keyboard,
)
from bot.services.preset_manager import preset_manager
from bot.services.tbank_service import tbank_service
from bot.services.yookassa_service import yookassa_service

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
    """Send a Telegram message using the shared bot instance."""
    try:
        await bot.send_message(telegram_id, text, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        if _is_ignored_telegram_error(e):
            raise
        raise


async def _render_topup_menu(message: types.Message, provider: str):
    packages = preset_manager.get_packages()
    text = """
🍌 <b>Пополнение баланса</b>

Выберите способ оплаты и пакет бананов:
<i>Чем больше пакет — тем выгоднее цена за банан</i>

🍌 <b>Бананы расходуются на генерации:</b>
• 1 банан = 1 стандартная генерация
• Премиум генерации стоят 2-6 бананов
"""

    await message.edit_text(
        text,
        reply_markup=get_payment_packages_keyboard(packages, provider=provider),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_topup")
async def show_topup_menu(callback: types.CallbackQuery):
    """Показывает меню пополнения баланса"""
    await _render_topup_menu(callback.message, config.payment_provider)


# Алиас для обратной совместимости
@router.callback_query(F.data == "menu_buy_credits")
async def show_packages(callback: types.CallbackQuery):
    """Показывает пакеты для покупки (алиас для menu_topup)"""
    await _render_topup_menu(callback.message, config.payment_provider)


@router.callback_query(F.data.startswith("topup_provider_"))
async def select_topup_provider(callback: types.CallbackQuery):
    """Меняет платёжного провайдера в меню пополнения"""
    provider = callback.data.replace("topup_provider_", "")
    if provider not in {"tbank", "yookassa"}:
        provider = config.payment_provider
    await _render_topup_menu(callback.message, provider)
    await callback.answer(
        "Выбран YooKassa" if provider == "yookassa" else "Выбран Т-Банк"
    )


@router.callback_query(F.data.startswith("buy_"))
async def initiate_payment(callback: types.CallbackQuery):
    """Создаёт платёж через выбранного провайдера"""
    payload = callback.data.replace("buy_", "")
    provider = config.payment_provider

    if payload.startswith("yookassa_"):
        provider = "yookassa"
        package_id = payload.replace("yookassa_", "", 1)
    elif payload.startswith("tbank_"):
        provider = "tbank"
        package_id = payload.replace("tbank_", "", 1)
    else:
        package_id = payload

    package = preset_manager.get_package(package_id)

    if not package:
        await callback.answer("Пакет не найден")
        return

    # Генерируем уникальный order_id
    order_id = f"{callback.from_user.id}_{int(time.time())}_{package_id}"
    amount_kop = package["price_rub"] * 100  # в копейках

    # URL для возврата в бот (через deep linking)
    bot_info = await callback.bot.get_me()
    success_url = f"https://t.me/{bot_info.username}?start=success_{order_id}"
    fail_url = f"https://t.me/{bot_info.username}?start=fail_{order_id}"

    use_yookassa = provider == "yookassa" and yookassa_service.enabled

    if use_yookassa:
        result = await yookassa_service.create_payment(
            amount_rub=package["price_rub"],
            order_id=order_id,
            description=f"Покупка {package['credits']} бананов ({package['name']})",
            return_url=success_url,
            notification_url=config.yookassa_notification_url,
        )
    else:
        # Создаём платёж в Т-Банке
        result = await tbank_service.init_payment(
            amount=amount_kop,
            order_id=order_id,
            description=f"Покупка {package['credits']} бананов ({package['name']})",
            customer_key=str(callback.from_user.id),
            success_url=success_url,
            fail_url=fail_url,
            notification_url=config.tbank_notification_url,
        )

    if result and result.get("Success"):
        payment_id = result["PaymentId"]
        payment_url = result["PaymentURL"]

        # Сохраняем транзакцию в БД
        user = await get_or_create_user(callback.from_user.id)
        total_credits = package["credits"] + package.get("bonus_credits", 0)
        await create_transaction(
            order_id=order_id,
            user_id=user.id,
            payment_id=str(payment_id),
            provider=provider if use_yookassa else "tbank",
            credits=total_credits,
            amount_rub=package["price_rub"],
            status="pending",
        )

        bonus_text = ""
        if package.get("bonus_credits", 0) > 0:
            bonus_text = f"\n🎁 Бонус: <code>{package['bonus_credits']}</code> бананов"

        await callback.message.edit_text(
            f"💳 <b>Оплата пакета «{package['name']}»</b>"
            f"🍌 Бананов: <code>{total_credits}</code>{bonus_text}\n"
            f"💰 Сумма: <code>{package['price_rub']}</code> ₽"
            f"Нажмите кнопку ниже для перехода к оплате.\n"
            f"После оплаты бананы начислятся автоматически.",
            reply_markup=get_payment_confirmation_keyboard(payment_url, order_id),
            parse_mode="HTML",
        )
    else:
        error_msg = (
            result.get("Message", "Неизвестная ошибка")
            if result
            else "Нет соединения с банком"
        )
        await callback.message.edit_text(
            f"❌ <b>Ошибка создания платежа</b>"
            f"{error_msg}"
            f"Попробуйте позже или обратитесь в поддержку.",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )


@router.message(F.text.startswith("/yookassa"))
async def yookassa_status_hint(message: types.Message):
    """Подсказка по доступности YooKassa"""
    if config.has_yookassa:
        await message.answer("✅ YooKassa настроена и готова к приёму платежей.")
    else:
        await message.answer(
            "⚠️ YooKassa не настроена. Проверьте YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY."
        )


@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment_status(callback: types.CallbackQuery):
    """Ручная проверка статуса платежа (если вебхук не сработал)"""
    order_id = callback.data.replace("check_payment_", "")
    transaction = await get_transaction_by_order(order_id)

    if not transaction:
        await callback.answer("Транзакция не найдена", show_alert=True)
        return

    if transaction.status == "completed":
        await callback.message.edit_text(
            f"✅ <b>Оплата подтверждена!</b>"
            f"🍌 Начислено <code>{transaction.credits}</code> бананов\n"
            f"💰 Сумма: <code>{transaction.amount_rub}</code> ₽"
            f"Теперь вы можете создавать контент!",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
    elif transaction.status == "pending":
        if transaction.provider == "yookassa":
            result = await yookassa_service.get_payment(transaction.payment_id)
            paid = bool(
                result and (result.get("paid") or result.get("status") == "succeeded")
            )
        else:
            # Проверяем статус в Т-Банке
            result = await tbank_service.get_state(transaction.payment_id)
            paid = bool(result and result.get("Status") == "CONFIRMED")

        if paid:
            # Начисляем бананы
            user = await get_or_create_user(transaction.user_id)
            await add_credits(user.telegram_id, transaction.credits)
            await update_transaction_status(order_id, "completed")
            referral_bonus = await credit_first_payment_referral_bonus(
                user.telegram_id, transaction.credits, transaction.amount_rub
            )

            bonus_text = ""
            if referral_bonus.get("mode") == "partner":
                bonus_text = (
                    f"🎁 Партнёрский бонус: <code>{referral_bonus['value']}</code> ₽\n"
                )
            elif referral_bonus.get("mode") == "banana":
                bonus_text = f"🎁 Реферальный бонус: <code>{referral_bonus['value']}</code> бананов\n"
            message_text = (
                f"✅ <b>Оплата подтверждена!</b>"
                f"🍌 Начислено <code>{transaction.credits}</code> бананов\n"
                f"💰 Сумма: <code>{transaction.amount_rub}</code> ₽\n"
                f"{bonus_text}\n"
                f"Теперь вы можете создавать контент!"
            )

            await callback.message.edit_text(
                message_text,
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML",
            )
        else:
            await callback.answer(
                "⏳ Ожидаем подтверждения от банка...", show_alert=True
            )
    else:
        await callback.message.edit_text(
            "❌ Платёж не был завершён." "Попробуйте снова.",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery):
    """Отмена платежа"""
    await callback.message.edit_text(
        "❌ <b>Платёж отменён</b>" "Вы можете попробовать снова в любое время.",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )


# Вебхук для Т-Банка (обрабатывается в aiohttp сервере)
async def handle_tbank_webhook(request):
    """Обработчик уведомлений от Т-Банка"""
    from aiohttp import web

    try:
        data = await request.json()
        logger.info(f"T-Bank webhook received: {data.get('OrderId')}")

        # Проверяем подпись
        if not tbank_service.verify_notification(data.copy()):
            logger.warning("Invalid signature in T-Bank webhook")
            return web.Response(status=403)

        order_id = data.get("OrderId")
        status = data.get("Status")
        payment_id = data.get("PaymentId")

        if status == "CONFIRMED":
            transaction = await get_transaction_by_order(order_id)

            if transaction and transaction.status == "pending":
                # Получаем telegram_id по internal user_id
                telegram_id = await get_telegram_id_by_user_id(transaction.user_id)

                if telegram_id:
                    # Начисляем кредиты
                    await add_credits(telegram_id, transaction.credits)
                    await update_transaction_status(order_id, "completed")
                    referral_bonus = await credit_first_payment_referral_bonus(
                        telegram_id, transaction.credits, transaction.amount_rub
                    )

                    bonus_text = ""
                    if referral_bonus.get("mode") == "partner":
                        bonus_text = f"🎁 Партнёрский бонус: <code>{referral_bonus['value']}</code> ₽\n"
                    elif referral_bonus.get("mode") == "banana":
                        bonus_text = f"🎁 Реферальный бонус: <code>{referral_bonus['value']}</code> бананов\n"

                    logger.info(
                        f"Credits added: {transaction.credits} to user {telegram_id}"
                    )

                    # Уведомляем пользователя
                    try:
                        await _notify_user(
                            request.app["bot"],
                            telegram_id,
                            f"🎉 <b>Оплата успешна!</b>"
                            f"🍌 Начислено: <code>{transaction.credits}</code> бананов\n"
                            f"💰 Сумма: <code>{transaction.amount_rub}</code> ₽\n"
                            f"{bonus_text}\n"
                            f"Теперь вы можете создавать контент!",
                            parse_mode="HTML",
                        )
                    except TelegramBadRequest as e:
                        if _is_ignored_telegram_error(e):
                            logger.warning(
                                "Skipping T-Bank notification for user %s: %s",
                                telegram_id,
                                e,
                            )
                        else:
                            logger.error("Failed to notify user: %s", e)
                    except Exception as e:
                        logger.error("Failed to notify user: %s", e)
                else:
                    logger.error(
                        f"Cannot find telegram_id for user_id {transaction.user_id}"
                    )

        return web.Response(text="OK", status=200)

    except Exception as e:
        logger.exception(f"Error processing T-Bank webhook: {e}")
        return web.Response(status=500)


async def handle_yookassa_webhook(request):
    """Обработчик уведомлений от YooKassa"""
    try:
        data = await request.json()
        # Log minimal identifying info and redact full payload to avoid leaking secrets
        logger.info(
            "YooKassa webhook received: event=%s, object_present=%s",
            data.get("event"),
            "object" in data,
        )

        if data.get("type") != "notification":
            return web.Response(status=200)

        event = data.get("event", "")
        payment = data.get("object", {})

        if not event.startswith("payment."):
            return web.Response(status=200)

        if event not in {"payment.succeeded", "payment.waiting_for_capture"}:
            return web.Response(status=200)

        # Try to extract order_id from the payment object using the service helper
        # (handles cases where metadata may be missing or in a slightly different shape)
        order_id = yookassa_service.extract_order_id(payment)
        payment_id = payment.get("id")
        status = payment.get("status")

        if not order_id:
            logger.warning(
                "YooKassa webhook missing order_id for payment %s", payment.get("id")
            )
            return web.Response(status=200)

        transaction = await get_transaction_by_order(order_id)
        if not transaction:
            logger.warning(
                "No transaction found for order %s (payment %s)",
                order_id,
                payment.get("id"),
            )
            return web.Response(status=200)

        # Already completed -> idempotent
        if transaction.status == "completed":
            logger.info(
                "Transaction %s already completed (order %s)",
                transaction.payment_id,
                order_id,
            )
            return web.Response(status=200)

        if (
            payment_id
            and transaction.payment_id
            and str(payment_id) != str(transaction.payment_id)
        ):
            logger.warning("YooKassa payment id mismatch for order %s", order_id)

        if status == "succeeded" or event == "payment.succeeded":
            try:
                user = await get_or_create_user(transaction.user_id)
                logger.info(
                    "Crediting %s credits to user %s for order %s (payment %s)",
                    transaction.credits,
                    user.telegram_id,
                    order_id,
                    payment.get("id"),
                )

                await add_credits(user.telegram_id, transaction.credits)
                await update_transaction_status(order_id, "completed")
                referral_bonus = await credit_first_payment_referral_bonus(
                    user.telegram_id, transaction.credits, transaction.amount_rub
                )
            except Exception as exc:
                logger.exception(
                    "Failed to credit user for YooKassa payment %s / order %s: %s",
                    payment.get("id"),
                    order_id,
                    exc,
                )
                # Return 200 to acknowledge webhook (YooKassa will retry if necessary)
                return web.Response(status=200)

            bonus_text = ""
            if referral_bonus.get("mode") == "partner":
                bonus_text = (
                    f"🎁 Партнёрский бонус: <code>{referral_bonus['value']}</code> ₽\n"
                )
            elif referral_bonus.get("mode") == "banana":
                bonus_text = f"🎁 Реферальный бонус: <code>{referral_bonus['value']}</code> бананов\n"

            try:
                await _notify_user(
                    request.app["bot"],
                    user.telegram_id,
                    f"🎉 <b>Оплата успешна!</b>"
                    f"🍌 Начислено: <code>{transaction.credits}</code> бананов\n"
                    f"💰 Сумма: <code>{transaction.amount_rub}</code> ₽\n"
                    f"{bonus_text}\n"
                    f"Теперь вы можете создавать контент!",
                    parse_mode="HTML",
                )
            except TelegramBadRequest as e:
                if _is_ignored_telegram_error(e):
                    logger.warning(
                        "Failed to notify YooKassa user %s (safe to ignore): %s",
                        user.telegram_id,
                        e,
                    )
                else:
                    logger.error("Failed to notify YooKassa user: %s", e)
            except Exception as e:
                logger.error("Failed to notify YooKassa user: %s", e)

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Error processing YooKassa webhook: {e}")
        return web.Response(status=500)
