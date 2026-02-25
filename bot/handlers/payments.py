import logging
import time

from aiogram import Bot, F, Router, types
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.database import (
    add_credits,
    create_transaction,
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

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "menu_buy_credits")
async def show_packages(callback: types.CallbackQuery):
    """Показывает пакеты для покупки"""
    packages = preset_manager.get_packages()

    text = """
🍌 <b>Пополнение баланса</b>

Выберите пакет бананов:
<i>Чем больше пакет — тем выгоднее цена за банан</i>

🍌 <b>Бананы расходуются на генерации:</b>
• 1 банан = 1 стандартная генерация
• Премиум генерации стоят 2-6 бананов
"""

    await callback.message.edit_text(
        text, reply_markup=get_payment_packages_keyboard(packages), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("buy_"))
async def initiate_payment(callback: types.CallbackQuery):
    """Создаёт платёж в Т-Банке"""
    package_id = callback.data.replace("buy_", "")
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

    # Создаём платёж
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
            credits=total_credits,
            amount_rub=package["price_rub"],
            status="pending",
        )

        bonus_text = ""
        if package.get("bonus_credits", 0) > 0:
            bonus_text = f"\n🎁 Бонус: <code>{package['bonus_credits']}</code> бананов"

        await callback.message.edit_text(
            f"💳 <b>Оплата пакета «{package['name']}»</b>\n\n"
            f"🍌 Бананов: <code>{total_credits}</code>{bonus_text}\n"
            f"💰 Сумма: <code>{package['price_rub']}</code> ₽\n\n"
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
            f"❌ <b>Ошибка создания платежа</b>\n\n"
            f"{error_msg}\n\n"
            f"Попробуйте позже или обратитесь в поддержку.",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
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
            f"🍌 Начислено <code>{transaction.credits}</code> бананов\n"
            f"💰 Сумма: <code>{transaction.amount_rub}</code> ₽\n\n"
            f"Теперь вы можете создавать контент!",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
    elif transaction.status == "pending":
        # Проверяем статус в Т-Банке
        result = await tbank_service.get_state(transaction.payment_id)

        if result and result.get("Status") == "CONFIRMED":
            # Начисляем бананы
            user = await get_or_create_user(transaction.user_id)
            await add_credits(user.telegram_id, transaction.credits)
            await update_transaction_status(order_id, "completed")

            await callback.message.edit_text(
                f"✅ <b>Оплата подтверждена!</b>\n\n"
                f"🍌 Начислено <code>{transaction.credits}</code> бананов\n"
                f"💰 Сумма: <code>{transaction.amount_rub}</code> ₽\n\n"
                f"Теперь вы можете создавать контент!",
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML",
            )
        else:
            await callback.answer(
                "⏳ Ожидаем подтверждения от банка...", show_alert=True
            )
    else:
        await callback.message.edit_text(
            "❌ Платёж не был завершён.\n\n" "Попробуйте снова.",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )


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

                    logger.info(
                        f"Credits added: {transaction.credits} to user {telegram_id}"
                    )

                    # Уведомляем пользователя
                    try:
                        bot = Bot(token=config.BOT_TOKEN)
                        await bot.send_message(
                            telegram_id,
                            f"🎉 <b>Оплата успешна!</b>\n\n"
                            f"🍌 Начислено: <code>{transaction.credits}</code> бананов\n"
                            f"💰 Сумма: <code>{transaction.amount_rub}</code> ₽\n\n"
                            f"Теперь вы можете создавать контент!",
                            parse_mode="HTML",
                        )
                        await bot.session.close()
                    except Exception as e:
                        logger.error(f"Failed to notify user: {e}")
                else:
                    logger.error(
                        f"Cannot find telegram_id for user_id {transaction.user_id}"
                    )

        return web.Response(text="OK", status=200)

    except Exception as e:
        logger.exception(f"Error processing T-Bank webhook: {e}")
        return web.Response(status=500)
