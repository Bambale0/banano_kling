import logging
import time

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
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
from bot.services.robokassa_service import robokassa_service
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


async def _render_topup_menu(message: types.Message, provider: str = None):
    packages = preset_manager.get_packages()
    text = """
💎 <b>Пополнение баланса</b>

Выберите способ оплаты и пакет GOEов:
<i>Чем больше пакет — тем выгоднее цена за GOE</i>

"""

    kb = InlineKeyboardBuilder()

    providers = []
    if config.has_yookassa:
        providers.append("yookassa")
    if config.has_robokassa:
        providers.append("robokassa")

    effective_provider = (
        provider
        or config.payment_provider
        or (providers[0] if providers else "yookassa")
    )

    if len(providers) > 1:
        # Show provider buttons
        for p in providers:
            check = "✅ " if p == effective_provider else ""
            kb.button(text=f"{check}{p.title()}", callback_data=f"topup_provider_{p}")

    # Package buttons
    for pkg in packages:
        popular = " 🔥" if pkg.get("popular") else ""
        kb.button(
            text=f"{pkg['name']}: {pkg['credits']}💎 за {pkg['price_rub']}₽{popular}",
            callback_data=f"buy_{effective_provider}_{pkg['id']}",
        )

    kb.button(text="🔙 Главное меню", callback_data="back_main")
    kb.adjust(1)

    await message.edit_text(
        text,
        reply_markup=kb.as_markup(),
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
    new_provider = callback.data.replace("topup_provider_", "")
    if new_provider in ["yookassa", "robokassa"] and (
        new_provider == "yookassa"
        and config.has_yookassa
        or new_provider == "robokassa"
        and config.has_robokassa
    ):
        await _render_topup_menu(callback.message, new_provider)
    else:
        await callback.answer("Провайдер недоступен")


@router.callback_query(F.data.startswith("buy_"))
async def initiate_payment(callback: types.CallbackQuery):
    """Создаёт платёж через выбранного провайдера"""
    payload = callback.data.replace("buy_", "")
    if payload.startswith("yookassa_"):
        provider = "yookassa"
        package_id = payload[9:]
    elif payload.startswith("robokassa_"):
        provider = "robokassa"
        package_id = payload[10:]
    else:
        provider = config.payment_provider
        package_id = payload

    if provider not in ["yookassa", "robokassa"]:
        await callback.answer("Неверный провайдер")
        return

    package = preset_manager.get_package(package_id)

    if not package:
        await callback.answer("Пакет не найден")
        return

    # Генерируем уникальный NUMERIC order_id для Robokassa (1..2^63-1)
    import random

    order_id = f"{callback.from_user.id}{int(time.time())}{random.randint(1000,9999)}"
    order_id = str(int(order_id) % 9223372036854775807)  # ensure < 2^63-1
    amount_kop = package["price_rub"] * 100  # в копейках

    bot_info = await callback.bot.get_me()
    bot_username = config.BOT_USERNAME or bot_info.username
    success_deep_link = f"https://t.me/{bot_username}?start=success_{order_id}"

    if provider == "yookassa":
        if not config.has_yookassa:
            await callback.answer("YooKassa не настроена")
            return
        result = await yookassa_service.create_payment(
            amount_rub=package["price_rub"],
            order_id=order_id,
            description=f"Покупка {package['credits']} GOEов ({package['name']})",
            return_url=success_deep_link,
            notification_url=config.yookassa_notification_url,
        )
    elif provider == "robokassa":
        if not config.has_robokassa:
            await callback.answer("Robokassa не настроена")
            return
        result = await robokassa_service.create_payment(
            amount_rub=package["price_rub"],
            order_id=order_id,
            description=f"Покупка {package['credits']} GOEов ({package['name']})",
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
            payment_id=payment_id,
            provider=provider,
            credits=total_credits,
            amount_rub=package["price_rub"],
            status="pending",
        )

        bonus_text = ""
        if package.get("bonus_credits", 0) > 0:
            bonus_text = f"\n🎁 Бонус: <code>{package['bonus_credits']}</code> GOEов"

        await callback.message.edit_text(
            f"💳 <b>Оплата пакета «{package['name']}» ({provider.title()})</b>\n\n"
            f"💎 GOEов: <code>{total_credits}</code>{bonus_text}\n"
            f"💰 Сумма: <code>{package['price_rub']}</code> ₽\n\n"
            f"Нажмите кнопку ниже для перехода к оплате.\n"
            f"После оплаты GOE начислятся автоматически.",
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
            f"❌ <b>Ошибка создания платежа</b>\n\n"
            f"{error_msg}\n\n"
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
            f"✅ <b>Оплата подтверждена!</b>\n\n"
            f"💎 Начислено <code>{transaction.credits}</code> GOEов\n"
            f"💰 Сумма: <code>{transaction.amount_rub}</code> ₽\n\n"
            f"Теперь вы можете создавать контент!",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    if transaction.status != "pending":
        await callback.message.edit_text(
            "❌ Платёж не был завершён.\n\n" "Попробуйте снова.",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    # Для robokassa нет API проверки, только DB статус
    if transaction.provider == "robokassa":
        await callback.answer("⏳ Ожидаем уведомления от Robokassa...", show_alert=True)
        return

    # YooKassa check
    result = await yookassa_service.get_payment(transaction.payment_id)
    paid = bool(result and (result.get("paid") or result.get("status") == "succeeded"))

    if paid:
        # Начисляем GOE
        telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
        await add_credits(telegram_id, transaction.credits)
        await update_transaction_status(order_id, "completed")
        referral_bonus = await credit_first_payment_referral_bonus(
            telegram_id, transaction.credits, transaction.amount_rub
        )

        bonus_text = ""
        if referral_bonus.get("mode") == "partner":
            bonus_text = (
                f"🎁 Партнёрский бонус: <code>{referral_bonus['value']}</code> ₽\n"
            )
        elif referral_bonus.get("mode") == "banana":
            bonus_text = (
                f"🎁 Реферальный бонус: <code>{referral_bonus['value']}</code> GOEов\n"
            )
        message_text = (
            f"✅ <b>Оплата подтверждена!</b>\n\n"
            f"💎 Начислено <code>{transaction.credits}</code> GOEов\n"
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
        await callback.answer("⏳ Ожидаем подтверждения от банка...", show_alert=True)


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery):
    """Отмена платежа"""
    await callback.message.edit_text(
        "❌ <b>Платёж отменён</b>\n\n" "Вы можете попробовать снова в любое время.",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_buy_credits")
async def back_to_packages(callback: types.CallbackQuery):
    """Возврат к выбору пакетов из подтверждения оплаты"""
    await show_packages(callback)


async def handle_robokassa_result(request):
    """Обработчик ResultURL от Robokassa (server-to-server)"""
    try:
        logger.info(
            f"Robokassa ResultURL: method={request.method}, query={request.query_string}"
        )

        if request.method.upper() == "POST":
            post_data = await request.post()
            params = {k: post_data.get(k, "") for k in post_data.keys()}
        else:
            params = robokassa_service.parse_response(request.query_string)

        logger.info(f"Robokassa ResultURL params: {params}")

        verification = robokassa_service.verify_result(params)
        if verification["valid"]:
            order_id = verification["order_id"]
            transaction = await get_transaction_by_order(order_id)
            if transaction and transaction.status == "pending":
                telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
                await add_credits(telegram_id, transaction.credits)
                await update_transaction_status(order_id, "completed")
                referral_bonus = await credit_first_payment_referral_bonus(
                    telegram_id, transaction.credits, transaction.amount_rub
                )
                logger.info(f"Robokassa payment completed for order {order_id}")

                # Notify user
                bonus_text = ""
                if referral_bonus.get("mode") == "partner":
                    bonus_text = f"🎁 Партнёрский бонус: {referral_bonus['value']} ₽"
                elif referral_bonus.get("mode") == "banana":
                    bonus_text = (
                        f"🎁 Реферальный бонус: {referral_bonus['value']} GOEов"
                    )

                try:
                    await _notify_user(
                        request.app["bot"],
                        telegram_id,
                        f"🎉 <b>Оплата успешна!</b>\n\n"
                        f"💎 Начислено: <code>{transaction.credits}</code> GOEов\n"
                        f"💰 Сумма: <code>{transaction.amount_rub}</code> ₽\n"
                        f"{bonus_text}\n"
                        f"Теперь вы можете создавать контент!",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.error(f"Failed to notify Robokassa user {telegram_id}: {e}")

            return web.Response(text=f"OK{order_id}")
        else:
            logger.warning(
                f"Robokassa ResultURL invalid: {verification.get('message')}"
            )
            return web.Response(text="bad sign")
    except Exception as e:
        logger.exception("Robokassa ResultURL error")
        return web.Response(text="bad sign")


async def handle_robokassa_success(request):
    """Обработчик SuccessURL от Robokassa (user redirect)"""
    try:
        query_str = request.query_string
        logger.info(f"Robokassa SuccessURL: {query_str}")

        params = robokassa_service.parse_response(query_str)
        verification = robokassa_service.verify_result(params)
        if verification["valid"]:
            order_id = verification["order_id"]
            # HTML with deeplink or success message
            bot_username = config.BOT_USERNAME or "your_bot_username"
            deeplink = f"https://t.me/{bot_username}?start=success_{order_id}"
            html = f"""
            <html>
            <head><title>Оплата успешна</title></head>
            <body>
                <h1>Спасибо за оплату!</h1>
                <p>GOE начислены автоматически.</p>
                <p><a href="{deeplink}">← Вернуться в бот</a></p>
                <script>window.location.href = "{deeplink}";</script>
            </body>
            </html>
            """
            return web.Response(text=html, content_type="text/html")
        else:
            logger.warning(
                f"Robokassa SuccessURL invalid: {verification.get('message')}"
            )
            return web.Response(text="bad sign")
    except Exception as e:
        logger.exception("Robokassa SuccessURL error")
        return web.Response(text="Ошибка", status=500)


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
                telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
                logger.info(
                    "Crediting %s credits to user %s for order %s (payment %s)",
                    transaction.credits,
                    telegram_id,
                    order_id,
                    payment.get("id"),
                )

                await add_credits(telegram_id, transaction.credits)
                await update_transaction_status(order_id, "completed")
                referral_bonus = await credit_first_payment_referral_bonus(
                    telegram_id, transaction.credits, transaction.amount_rub
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
                bonus_text = f"🎁 Реферальный бонус: <code>{referral_bonus['value']}</code> GOEов\n"

            try:
                await _notify_user(
                    request.app["bot"],
                    telegram_id,
                    f"🎉 <b>Оплата успешна!</b>\n\n"
                    f"💎 Начислено: <code>{transaction.credits}</code> GOEов\n"
                    f"💰 Сумма: <code>{transaction.amount_rub}</code> ₽\n"
                    f"{bonus_text}\n"
                    f"Теперь вы можете создавать контент!",
                    parse_mode="HTML",
                )
            except TelegramBadRequest as e:
                if _is_ignored_telegram_error(e):
                    logger.warning(
                        "Failed to notify YooKassa user %s (safe to ignore): %s",
                        telegram_id,
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
