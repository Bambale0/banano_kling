import logging

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext

from bot.database import (
    get_or_create_user,
    get_user_settings,
    get_user_stats,
    save_user_settings,
)
from bot.keyboards import get_back_keyboard, get_main_menu_keyboard
from bot.services.preset_manager import preset_manager
from bot.states import AdminStates, GenerationStates, PaymentStates

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
        from bot.database import (
            add_credits,
            get_transaction_by_order,
            update_transaction_status,
        )
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
Хватит просто смотреть — создавай с AI! 🔥

✅ <b>Генерация артов:</b> Пиши промпт — получай шедевр.
✅ <b>Фото-магия:</b> Стилизация и замена объектов в пару кликов.
✅ <b>Видео-продакшн:</b> Делаю ролики из слов и фото.
✅ <b>FX-эффекты:</b> Твои видео станут выглядеть на миллион.

🍌 <b>Ваш баланс:</b> <code>{user.credits}</code> бананов

<i>Попробуй прямо сейчас! 👇</i>
"""

    try:
        await message.answer(
            welcome_text,
            reply_markup=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )
    except TelegramBadRequest as e:
        if "chat not found" in str(e).lower():
            logger.warning(
                f"Chat not found for user {message.from_user.id}, user may have deleted chat or blocked bot"
            )
        else:
            raise


@router.message(Command("help"), StateFilter(None))
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    help_text = """
📖 <b>Справка по использованию бота</b>

<b>⚡ Пакетное редактирование</b>
1. Нажмите "⚡ ПАКЕТНОЕ РЕДАКТИРОВАНИЕ"
2. Загрузите одно или несколько фото
3. Нажмите «Готово» и введите промпт
4. Выберите формат (1:1, 16:9, 9:16 и т.д.)
5. Получите результат в 4K качестве!

<b>💎 Nano Banana (Генерация изображений)</b>
Бот использует передовые модели Google Gemini:
• <b>Nano Banana Flash</b> — быстрая генерация (1🍌)
• <b>Nano Banana Pro</b> — профессиональное качество, 4K (3🍌)

<b>📝 Как составлять промпты:</b>
• Опишите сцену подробно, а не просто ключевые слова
• Укажите стиль: "фотореализм", "аниме", "масляная живопись"
• Добавьте детали освещения: "золотой час", "неоновое освещение"
• Укажите ракурс: "вид сверху", "портрет крупным планом"

<b>✏️ Редактирование фото</b>
Загрузите изображение, выберите эффект или стиль.
Бот обработает ваше фото и вернёт результат.

<b>🎬 Генерация видео</b>
Опишите сцену для видео или загрузите изображение.
Видео будет готово через 1-3 минуты.

<b>🍌 Стоимость операций:</b>
• Gemini Flash: 1🍌 | Gemini Pro: 2🍌
• Пакетное редактирование: 3🍌/фото (4K)
• Kling Standard: 4🍌 | Kling Pro: 5-6🍌

<b>❓ Нужна помощь?</b>
Обратитесь в поддержку: @support_username
"""

    await message.answer(help_text, reply_markup=get_back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "menu_help")
async def show_help(callback: types.CallbackQuery):
    """Показывает справку через inline-кнопку"""
    help_text = """
📖 <b>Справка по использованию бота</b>

<b>⚡ Пакетное редактирование</b>
1. Нажмите "⚡ ПАКЕТНОЕ РЕДАКТИРОВАНИЕ"
2. Загрузите одно или несколько фото
3. Нажмите «Готово» и введите промпт
4. Выберите формат (1:1, 16:9, 9:16 и т.д.)
5. Получите результат в 4K качестве!

<b>💎 Nano Banana (Генерация изображений)</b>
Бот использует передовые модели Google Gemini:
• <b>Nano Banana Flash</b> — быстрая генерация (1🍌)
• <b>Nano Banana Pro</b> — профессиональное качество, 4K (3🍌)

<b>📝 Как составлять промпты:</b>
• Опишите сцену подробно, а не просто ключевые слова
• Укажите стиль: "фотореализм", "аниме", "масляная живопись"
• Добавьте детали освещения: "золотой час", "неоновое освещение"
• Укажите ракурс: "вид сверху", "портрет крупным планом"

<b>✏️ Редактирование фото</b>
Загрузите изображение, выберите эффект или стиль.
Бот обработает ваше фото и вернёт результат.

<b>🎬 Генерация видео</b>
Опишите сцену для видео или загрузите изображение.
Видео будет готово через 1-3 минуты.

<b>🍌 Стоимость операций:</b>
• Gemini Flash: 1🍌 | Gemini Pro: 2🍌
• Пакетное редактирование: 3🍌/фото (4K)
• Kling Standard: 4🍌 | Kling Pro: 5-6🍌

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
        balance_text,
        reply_markup=get_main_menu_keyboard(user.credits),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_settings")
async def show_settings(callback: types.CallbackQuery, state: FSMContext):
    """Показывает настройки с выбором модели"""
    from bot.keyboards import get_settings_keyboard

    # Загружаем настройки из БД
    db_settings = await get_user_settings(callback.from_user.id)

    # Сохраняем в состояние
    await state.update_data(
        preferred_model=db_settings["preferred_model"],
        preferred_video_model=db_settings["preferred_video_model"],
        preferred_i2v_model=db_settings["preferred_i2v_model"],
    )

    settings_text = """
⚙️ <b>Настройки</b>

🖼 Изображения:
• Flash (1🍌) / Pro (2🍌)

🎬 Текст→Видео:
• Std/Pro, Omni, V2V

🖼→🎬 Фото→Видео:
• Std (4🍌) / Pro (5🍌) / Omni
"""

    await callback.message.edit_text(
        settings_text,
        reply_markup=get_settings_keyboard(
            db_settings["preferred_model"],
            db_settings["preferred_video_model"],
            db_settings["preferred_i2v_model"],
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("settings_model_"))
async def handle_settings_model(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора модели изображений в настройках"""
    model_type = callback.data.replace("settings_model_", "")

    # Сохраняем выбор модели в БД
    await save_user_settings(callback.from_user.id, preferred_model=model_type)

    # Сохраняем в состояние
    await state.update_data(preferred_model=model_type)

    # Показываем подтверждение (короткое)
    model_name = "Flash" if model_type == "flash" else "Pro"

    from bot.keyboards import get_settings_keyboard

    # Также получаем текущую модель видео
    data = await state.get_data()
    current_video_model = data.get("preferred_video_model", "v3_std")
    current_i2v_model = data.get("preferred_i2v_model", "v3_std")

    await callback.message.edit_text(
        f"✅ Изображение: {model_name}",
        reply_markup=get_settings_keyboard(
            model_type, current_video_model, current_i2v_model
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("settings_video_"))
async def handle_settings_video_model(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора модели видео в настройках"""
    video_model = callback.data.replace("settings_video_", "")

    # Сохраняем выбор модели видео в БД
    await save_user_settings(callback.from_user.id, preferred_video_model=video_model)

    # Сохраняем в состояние
    await state.update_data(preferred_video_model=video_model)

    # Короткие названия
    video_names = {
        "v3_std": "Std",
        "v3_pro": "Pro",
        "v3_omni_std": "Omni",
        "v3_omni_pro": "Omni Pro",
        "v3_omni_std_r2v": "V2V",
        "v3_omni_pro_r2v": "V2V Pro",
    }

    model_name = video_names.get(video_model, video_model)

    from bot.keyboards import get_settings_keyboard

    # Также получаем текущую модель изображений
    data = await state.get_data()
    current_model = data.get("preferred_model", "flash")
    current_i2v_model = data.get("preferred_i2v_model", "v3_std")

    await callback.message.edit_text(
        f"✅ Видео: {model_name}",
        reply_markup=get_settings_keyboard(
            current_model, video_model, current_i2v_model
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("settings_i2v_"))
async def handle_settings_i2v_model(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора модели для фото-в-видео в настройках"""
    i2v_model = callback.data.replace("settings_i2v_", "")

    # Сохраняем выбор модели i2v в БД
    await save_user_settings(callback.from_user.id, preferred_i2v_model=i2v_model)

    # Сохраняем в состояние
    await state.update_data(preferred_i2v_model=i2v_model)

    # Короткие названия
    i2v_names = {
        "v3_std": "Std",
        "v3_pro": "Pro",
        "v3_omni_std": "Omni Std",
        "v3_omni_pro": "Omni Pro",
    }

    model_name = i2v_names.get(i2v_model, i2v_model)

    from bot.keyboards import get_settings_keyboard

    # Получаем текущие модели
    data = await state.get_data()
    current_model = data.get("preferred_model", "flash")
    current_video_model = data.get("preferred_video_model", "v3_std")

    await callback.message.edit_text(
        f"✅ Фото→Видео: {model_name}",
        reply_markup=get_settings_keyboard(
            current_model, current_video_model, i2v_model
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("back_cat_"))
async def back_to_category(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к категории пресетов"""
    from bot.handlers.generation import show_category

    category = callback.data.replace("back_cat_", "")

    # Вызываем show_category напрямую с callback
    # show_category уже ожидает callback и bot
    await callback.message.edit_text(
        f"Загрузка категории {category}...", reply_markup=None
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


@router.callback_query(F.data.startswith("ignore_"))
async def handle_ignore_callback(callback: types.CallbackQuery):
    """Обработчик для неинтерактивных кнопок-заголовков и разделителей"""
    await callback.answer()  # Просто закрываем уведомление о нажатии
