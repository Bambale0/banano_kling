import logging

from aiogram import Bot, F, Router, types
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from bot.database import get_or_create_user, get_user_stats
from bot.keyboards import get_back_keyboard, get_main_menu_keyboard
from bot.services.preset_manager import preset_manager
from bot.states import GenerationStates, PaymentStates, AdminStates

logger = logging.getLogger(__name__)
router = Router()


# ⭐ ВАЖНО: Все обработчики сообщений в common.py должны иметь StateFilter(None)
# чтобы работать только когда пользователь НЕ в FSM-состоянии
# Иначе они перехватят сообщения ДО FSM-хэндлеров в generation_router


@router.message(CommandStart(), StateFilter(None))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    # Создаём или получаем пользователя
    user = await get_or_create_user(message.from_user.id)

    # Проверяем deep linking для возврата после оплаты
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []

    if args and args[0].startswith("success_"):
        # Извлекаем order_id из аргумента
        order_id = args[0].replace("success_", "")
        
        # Проверяем транзакцию в базе данных
        from bot.database import get_transaction_by_order, add_credits, update_transaction_status
        from bot.services.tbank_service import tbank_service
        
        transaction = await get_transaction_by_order(order_id)
        
        if transaction:
            if transaction.status == "completed":
                # Кредиты уже были начислены
                await message.answer(
                    f"✅ <b>Оплата уже обработана!</b>\n\n"
                    f"🍌 Ваш баланс: <code>{user.credits}</code> бананов",
                    reply_markup=get_main_menu_keyboard(user.credits),
                    parse_mode="HTML",
                )
                return
            elif transaction.status == "pending":
                # Проверяем статус в Т-Банке
                result = await tbank_service.get_state(transaction.payment_id)
                if result and result.get("Status") == "CONFIRMED":
                    # Начисляем кредиты
                    await add_credits(message.from_user.id, transaction.credits)
                    await update_transaction_status(order_id, "completed")
                    
                    # Получаем обновлённый баланс
                    user = await get_or_create_user(message.from_user.id)
                    
                    await message.answer(
                        f"🎉 <b>Оплата успешно обработана!</b>\n\n"
                        f"🍌 Начислено: <code>{transaction.credits}</code> бананов\n"
                        f"💰 Сумма: <code>{transaction.amount_rub}</code> ₽\n\n"
                        f"💎 Ваш баланс: <code>{user.credits}</code> бананов",
                        reply_markup=get_main_menu_keyboard(user.credits),
                        parse_mode="HTML",
                    )
                    return
                else:
                    # Ожидаем подтверждения от банка
                    await message.answer(
                        "⏳ <b>Оплата в обработке...</b>\n\n"
                        "Пожалуйста, подождите. Кредиты будут начислены в течение нескольких минут.",
                        reply_markup=get_main_menu_keyboard(user.credits),
                        parse_mode="HTML",
                    )
                    return
        else:
            await message.answer(
                "❌ <b>Транзакция не найдена</b>\n\n"
                "Пожалуйста, свяжитесь с поддержкой.",
                reply_markup=get_main_menu_keyboard(user.credits),
                parse_mode="HTML",
            )
            return
            
    elif args and args[0].startswith("fail_"):
        await message.answer(
            "❌ <b>Оплата не была завершена</b>\n\n"
            "Вы можете попробовать снова в любое время.",
            reply_markup=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )
        return

    # Приветственное сообщение
    welcome_text = f"""
👋 <b>Добро пожаловать!</b>

Это бот для генерации изображений и видео с помощью AI.

🎨 <b>Возможности:</b>
• Генерация изображений по описанию
• Редактирование фото (стилизация, добавление объектов)
• Создание видео из текста и изображений
• Применение эффектов к видео

🍌 <b>Ваш баланс:</b> <code>{user.credits}</code> бананов

<i>Выберите действие в меню ниже:</i>
"""

    await message.answer(
        welcome_text, reply_markup=get_main_menu_keyboard(user.credits), parse_mode="HTML"
    )


@router.message(Command("help"), StateFilter(None))
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    help_text = """
📖 <b>Справка по использованию бота</b>

<b>🖼 Генерация изображений</b>
Выберите категорию "Генерация фото", затем пресет.
Введите описание того, что хотите создать.

<b>✏️ Редактирование фото</b>
Загрузите изображение, выберите эффект или стиль.
Бот обработает ваше фото и вернёт результат.

<b>🎬 Генерация видео</b>
Опишите сцену для видео или загрузите изображение.
Видео будет готово через 1-3 минуты.

<b>🍌 Система бананов</b>
• 1 банан = 1 стандартная генерация
• Премиум генерации стоят больше
• Бонусы при покупке больших пакетов

<b>🍌 Стоимость операций:</b>
• Gemini Flash: 1🍌
• Gemini Pro: 2🍌
• Kling Standard: 4🍌
• Kling Pro: 5-6🍌

<b>❓ Нужна помощь?</b>
Обратитесь в поддержку: @support_username
"""

    await message.answer(help_text, reply_markup=get_back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "menu_help")
async def show_help(callback: types.CallbackQuery):
    """Показывает справку через inline-кнопку"""
    help_text = """
📖 <b>Справка по использованию бота</b>

<b>🖼 Генерация изображений</b>
Выберите категорию "Генерация фото", затем пресет.
Введите описание того, что хотите создать.

<b>✏️ Редактирование фото</b>
Загрузите изображение, выберите эффект или стиль.
Бот обработает ваше фото и вернёт результат.

<b>🎬 Генерация видео</b>
Опишите сцену для видео или загрузите изображение.
Видео будет готово через 1-3 минуты.

<b>🍌 Система бананов</b>
• 1 банан = 1 стандартная генерация
• Премиум генерации стоят больше
• Бонусы при покупке больших пакетов

<b>🍌 Стоимость операций:</b>
• Gemini Flash: 1🍌
• Gemini Pro: 2🍌
• Kling Standard: 4🍌
• Kling Pro: 5-6🍌

<b>❓ Нужна помощь?</b>
Обратитесь в поддержку: @support_username
"""

    await callback.message.edit_text(
        help_text, reply_markup=get_back_keyboard(), parse_mode="HTML"
    )


@router.callback_query(F.data == "back_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
    await state.clear()

    user = await get_or_create_user(callback.from_user.id)

    try:
        await callback.message.edit_text(
            f"🏠 <b>Главное меню</b>\n\n"
            f"🍌 Ваш баланс: <code>{user.credits}</code> бананов\n\n"
            f"Выберите действие:",
            reply_markup=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )
    except Exception as e:
        # Если сообщение нельзя отредактировать (например, нет текста или сообщение удалено)
        logger.warning(f"Cannot edit message: {e}")
        # Отправляем новое сообщение
        await callback.message.answer(
            f"🏠 <b>Главное меню</b>\n\n"
            f"🍌 Ваш баланс: <code>{user.credits}</code> бананов\n\n"
            f"Выберите действие:",
            reply_markup=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "menu_balance")
async def show_balance(callback: types.CallbackQuery):
    """Показывает баланс и статистику пользователя"""
    user = await get_or_create_user(callback.from_user.id)
    stats = await get_user_stats(callback.from_user.id)

    balance_text = f"""
💎 <b>Ваш баланс</b>

🍌 Доступно бананов: <code>{stats['credits']}</code>
📊 Всего генераций: <code>{stats['generations']}</code>
💸 Потрачено бананов: <code>{stats['total_spent']}</code>
📅 Дата регистрации: <code>{stats['member_since']}</code>

<i>1 банан = 1 генерация стандартного качества</i>
<i>Премиум генерации стоят больше бананов</i>
"""

    await callback.message.edit_text(
        balance_text, reply_markup=get_main_menu_keyboard(user.credits), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("back_cat_"))
async def back_to_category(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к категории пресетов"""
    from bot.handlers.generation import show_category

    category = callback.data.replace("back_cat_", "")
    
    # Вызываем show_category напрямую с callback
    # show_category уже ожидает callback и bot
    await callback.message.edit_text(
        f"Загрузка категории {category}...",
        reply_markup=None
    )
    
    # Просто редактируем сообщение категории
    from bot.services.preset_manager import preset_manager
    presets = preset_manager.get_category_presets(category)
    categories = preset_manager.get_categories()
    
    if not presets:
        await callback.answer("Категория пуста")
        return
        
    user_credits = 0  # Default value
    from bot.database import get_user_credits
    try:
        user_credits = await get_user_credits(callback.from_user.id)
    except:
        pass
        
    from bot.keyboards import get_category_keyboard
    await callback.message.edit_text(
        f"📂 <b>{categories[category]['name']}</b>\n"
        f"📝 {categories[category].get('description', '')}\n\n"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n\n"
        f"Выберите пресет:",
        reply_markup=get_category_keyboard(category, presets, user_credits),
        parse_mode="HTML",
    )


# =============================================================================
# ВАЖНО: НЕ ДОБАВЛЯЙТЕ СЮДА ОБРАБОТЧИКИ СООБЩЕНИЙ БЕЗ FSM STATE FILTER!
# Это перехватит сообщения до FSM-хэндлеров в generation_router
# =============================================================================

# Для диагностики оставляем только callback_query обработчики
# Все message хэндлеры должны быть в generation_router с явными StateFilter
