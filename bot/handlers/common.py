import logging

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.database import (
    get_or_create_user,
    get_user_settings,
    get_user_stats,
    save_user_settings,
)
from bot.keyboards import (
    get_ai_assistant_keyboard,
    get_back_keyboard,
    get_main_menu_keyboard,
)
from bot.services.preset_manager import preset_manager
from bot.states import AdminStates, GenerationStates, PaymentStates

logger = logging.getLogger(__name__)
router = Router()


# Состояния для ИИ-ассистента
class AIAssistantStates(StatesGroup):
    """Состояния для ИИ-ассистента"""

    main_menu = State()  # Пользователь в главном меню
    settings = State()  # Пользователь в настройках
    waiting_for_message = State()  # Ожидание сообщения от пользователя


# ⭐ ВАЖНО: Все обработчики сообщений в common.py должны иметь StateFilter(None)
# чтобы работать только когда пользователь НЕ в FSM-состоянии
# Иначе они перехватят сообщения ДО FSM-хэндлеров в generation_router


# Хранилище для быстрого доступа к последнему меню пользователя
# user_id -> "main_menu" | "settings" | None
_user_last_menu = {}


def _set_user_menu(user_id: int, menu: str):
    """Устанавливает последнее посещённое меню пользователя"""
    _user_last_menu[user_id] = menu


def _get_user_menu(user_id: int) -> str:
    """Получает последнее посещённое меню пользователя"""
    return _user_last_menu.get(user_id)


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

📢 <b>Наш канал:</b> <a href="https://t.me/ai_neir_set">@ai_neir_set</a>

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

    # Запоминаем, что пользователь в главном меню
    _set_user_menu(message.from_user.id, "main_menu")


@router.message(Command("help"), StateFilter(None))
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    help_text = """
📖 <b>Справка по использованию бота</b>

<b>⚡ Редактирование по референсам</b>
1. Нажмите "⚡ ПАКЕТНОЕ РЕДАКТИРОВАНИЕ"
2. Загрузите <b>главное фото</b> для редактирования
3. Добавьте до <b>14 референсных изображений</b> (стиль, объекты, персонажи)
4. Введите промпт
5. Получите результат с учётом всех референсов в 4K!

<b>Возможности:</b>
• До 10 объектов с высокой точностью
• До 4 персонажей для консистентности
• Перенос стиля, композиции, цветов

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
• FLUX.2 Pro / Nano Banana / Seedream: 3🍌
• Редактирование по референсам: 3🍌 (до 14 референсов, 4K)
• Kling Standard: 6🍌 | Kling Pro: 8-10🍌

<b>❓ Нужна помощь?</b>
Обратитесь в поддержку: <a href="https://t.me/S_k7222">@S_k7222</a>
"""

    await message.answer(help_text, reply_markup=get_back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "menu_help")
async def show_help(callback: types.CallbackQuery):
    """Показывает справку через inline-кнопку"""
    help_text = """
📖 <b>Справка по использованию бота</b>

<b>⚡ Редактирование по референсам</b>
1. Нажмите "⚡ ПАКЕТНОЕ РЕДАКТИРОВАНИЕ"
2. Загрузите <b>главное фото</b> для редактирования
3. Добавьте до <b>14 референсных изображений</b> (стиль, объекты, персонажи)
4. Введите промпт
5. Получите результат с учётом всех референсов в 4K!

<b>Возможности:</b>
• До 10 объектов с высокой точностью
• До 4 персонажей для консистентности
• Перенос стиля, композиции, цветов

<b>💎 Генерация изображений</b>
Бот использует передовые модели:
• <b>FLUX.2 Pro</b> — высокое качество, до 1536px (3🍌)
• <b>Nano Banana</b> — быстрая генерация, до 4K (3🍌)
• <b>Seedream</b> — стилизованные арты через Novita (3🍌)

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
• FLUX.2 Pro / Nano Banana / Seedream: 3🍌
• Редактирование по референсам: 3🍌 (до 14 референсов, 4K)
• Kling Standard: 6🍌 | Kling Pro: 8-10🍌

<b>❓ Нужна помощь?</b>
Обратитесь в поддержку: <a href="https://t.me/S_k7222">@S_k7222</a>
"""

    await callback.message.edit_text(
        help_text, reply_markup=get_back_keyboard(), parse_mode="HTML"
    )


@router.callback_query(F.data == "back_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
    await state.clear()

    user = await get_or_create_user(callback.from_user.id)

    # Запоминаем, что пользователь в главном меню
    _set_user_menu(callback.from_user.id, "main_menu")

    # Полный текст главного меню как в cmd_start
    welcome_text = (
        f"🏠 <b>Главное меню</b>\n\n"
        f"Хватит просто смотреть — создавай с AI! 🔥\n\n"
        f"✅ <b>Генерация артов:</b> Пиши промпт — получай шедевр.\n"
        f"✅ <b>Фото-магия:</b> Стилизация и замена объектов в пару кликов.\n"
        f"✅ <b>Видео-продакшн:</b> Делаю ролики из слов и фото.\n"
        f"✅ <b>FX-эффекты:</b> Твои видео станут выглядеть на миллион.\n\n"
        f"🍌 <b>Ваш баланс:</b> <code>{user.credits}</code> бананов\n\n"
        f'📢 <b>Наш канал:</b> <a href="https://t.me/ai_neir_set">@ai_neir_set</a>\n\n'
        f"<i>Попробуй прямо сейчас! 👇</i>"
    )

    try:
        await callback.message.edit_text(
            welcome_text,
            reply_markup=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )
    except Exception as e:
        # Если сообщение нельзя отредактировать (например, нет текста или сообщение удалено)
        logger.warning(f"Cannot edit message: {e}")
        # Отправляем новое сообщение
        await callback.message.answer(
            welcome_text,
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
"""

    await callback.message.edit_text(
        balance_text,
        reply_markup=get_main_menu_keyboard(user.credits),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_settings")
async def show_settings(callback: types.CallbackQuery, state: FSMContext):
    """Показывает настройки с выбором модели и кнопкой ИИ"""
    from bot.keyboards import get_settings_keyboard_with_ai

    # Запоминаем, что пользователь в настройках
    _set_user_menu(callback.from_user.id, "settings")

    # Загружаем настройки из БД
    db_settings = await get_user_settings(callback.from_user.id)

    # Сохраняем в состояние
    await state.update_data(
        preferred_model=db_settings["preferred_model"],
        preferred_video_model=db_settings["preferred_video_model"],
        preferred_i2v_model=db_settings["preferred_i2v_model"],
        image_service=db_settings.get("image_service", "nanobanana"),
    )

    settings_text = """
⚙️ <b>Настройки</b>

🖼 Изображения:
• FLUX.2 Pro / Nano Banana / Seedream
• Все модели: 3🍌

🎬 Текст→Видео:
• Kling 2.6 (8🍌) / Std (6🍌) / Pro (8🍌) / Omni / V2V

🖼→🎬 Фото→Видео:
• Std (6🍌) / Pro (8🍌) / Omni
"""

    await callback.message.edit_text(
        settings_text,
        reply_markup=get_settings_keyboard_with_ai(
            db_settings["preferred_model"],
            db_settings["preferred_video_model"],
            db_settings["preferred_i2v_model"],
            db_settings.get("image_service", "nanobanana"),
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_motion_control")
async def show_motion_control_menu(callback: types.CallbackQuery):
    """Показывает меню Motion Control"""
    from bot.keyboards import get_motion_control_keyboard
    from bot.database import get_user_credits

    user_credits = await get_user_credits(callback.from_user.id)

    motion_text = f"""
🎬 <b>Motion Control</b>

Перенос движения с референсного видео на твоё фото!

📝 <b>Как это работает:</b>
1. Загрузи фото персонажа
2. Загрузи видео с движением
3. Получи анимированное фото!

💰 Баланс: {user_credits}🍌

Выбери качество:
"""

    await callback.message.edit_text(
        motion_text,
        reply_markup=get_motion_control_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "motion_control_std")
async def start_motion_control_std(callback: types.CallbackQuery, state: FSMContext):
    """Запускает Motion Control Standard"""
    from bot.states import GenerationStates
    from bot.database import get_user_credits
    from bot.services.preset_manager import preset_manager
    
    user_credits = await get_user_credits(callback.from_user.id)
    cost = preset_manager.get_video_cost("v26_motion_std", 5)
    
    if user_credits < cost:
        await callback.answer("❌ Недостаточно бананов! Пополни баланс.", show_alert=True)
        return
    
    # Сохраняем тип генерации
    await state.set_state(GenerationStates.waiting_for_image)
    await state.update_data(
        generation_type="motion_control",
        video_model="v26_motion_std",
        cost=cost
    )
    
    await callback.message.edit_text(
        f"🎬 <b>Motion Control Standard</b>\n\n"
        f"Стоимость: {cost}🍌\n\n"
        f"📸 <b>Шаг 1:</b> Загрузи фото персонажа,\n"
        f"которое нужно анимировать\n\n"
        f"Это может быть:\n"
        f"• Фото человека\n"
        f"• Фото персонажа\n"
        f"• Любое изображение для анимации",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "motion_control_pro")
async def start_motion_control_pro(callback: types.CallbackQuery, state: FSMContext):
    """Запускает Motion Control Pro"""
    from bot.states import GenerationStates
    from bot.database import get_user_credits
    from bot.services.preset_manager import preset_manager
    
    user_credits = await get_user_credits(callback.from_user.id)
    cost = preset_manager.get_video_cost("v26_motion_pro", 5)
    
    if user_credits < cost:
        await callback.answer("❌ Недостаточно бананов! Пополни баланс.", show_alert=True)
        return
    
    # Сохраняем тип генерации
    await state.set_state(GenerationStates.waiting_for_image)
    await state.update_data(
        generation_type="motion_control",
        video_model="v26_motion_pro",
        cost=cost
    )
    
    await callback.message.edit_text(
        f"💎 <b>Motion Control Pro</b>\n\n"
        f"Стоимость: {cost}🍌\n\n"
        f"📸 <b>Шаг 1:</b> Загрузи фото персонажа,\n"
        f"которое нужно анимировать\n\n"
        f"Это может быть:\n"
        f"• Фото человека\n"
        f"• Фото персонажа\n"
        f"• Любое изображение для анимации",
        parse_mode="HTML",
    )
    await callback.answer()


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

    from bot.keyboards import get_settings_keyboard_with_ai

    # Также получаем текущую модель видео
    data = await state.get_data()
    current_video_model = data.get("preferred_video_model", "v3_std")
    current_i2v_model = data.get("preferred_i2v_model", "v3_std")
    current_image_service = data.get("image_service", "nanobanana")

    await callback.message.edit_text(
        f"✅ Изображение: {model_name}",
        reply_markup=get_settings_keyboard_with_ai(
            model_type,
            current_video_model,
            current_i2v_model,
            image_service=current_image_service,
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
        "v26_pro": "Kling 2.6",
        "v26_motion_pro": "Motion Pro",
        "v26_motion_std": "Motion",
    }

    model_name = video_names.get(video_model, video_model)

    from bot.keyboards import get_settings_keyboard_with_ai

    # Также получаем текущую модель изображений
    data = await state.get_data()
    current_model = data.get("preferred_model", "flash")
    current_i2v_model = data.get("preferred_i2v_model", "v3_std")
    current_image_service = data.get("image_service", "nanobanana")

    await callback.message.edit_text(
        f"✅ Видео: {model_name}",
        reply_markup=get_settings_keyboard_with_ai(
            current_model,
            video_model,
            current_i2v_model,
            image_service=current_image_service,
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

    from bot.keyboards import get_settings_keyboard_with_ai

    # Получаем текущие модели
    data = await state.get_data()
    current_model = data.get("preferred_model", "flash")
    current_video_model = data.get("preferred_video_model", "v3_std")
    current_image_service = data.get("image_service", "nanobanana")

    await callback.message.edit_text(
        f"✅ Фото→Видео: {model_name}",
        reply_markup=get_settings_keyboard_with_ai(
            current_model,
            current_video_model,
            i2v_model,
            image_service=current_image_service,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("settings_service_"))
async def handle_settings_service(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора сервиса для генерации изображений (nanobanana, novita или seedream)"""
    service = callback.data.replace("settings_service_", "")

    # Сохраняем выбор сервиса в БД
    await save_user_settings(callback.from_user.id, image_service=service)

    # Сохраняем в состояние
    await state.update_data(image_service=service)

    # Названия сервисов
    service_names = {
        "nanobanana": "🍌 Nano Banana",
        "novita": "✨ FLUX.2 Pro (Novita)",
        "banana_pro": "💎 Banana Pro",
        "seedream": "🎨 Seedream (Novita)",
        "z_image_turbo": "🚀 Z-Image Turbo LoRA",
    }

    service_name = service_names.get(service, service)

    from bot.keyboards import get_settings_keyboard_with_ai

    # Получаем текущие модели
    data = await state.get_data()
    current_model = data.get("preferred_model", "flash")
    current_video_model = data.get("preferred_video_model", "v3_std")
    current_i2v_model = data.get("preferred_i2v_model", "v3_std")

    await callback.message.edit_text(
        f"✅ Сервис: {service_name}",
        reply_markup=get_settings_keyboard_with_ai(
            current_model, current_video_model, current_i2v_model, image_service=service
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
# ИИ-ассистент: обработка сообщений без FSM
# Позволяет отправлять вопросы ИИ напрямую из главного меню или настроек
# =============================================================================


@router.message(StateFilter(None), F.text)
async def handle_message_in_menu(message: types.Message, state: FSMContext):
    """Обработка текстовых сообщений в главном меню или настройках - перенаправление к ИИ"""
    from bot.keyboards import get_ai_assistant_keyboard, get_back_keyboard
    from bot.services.ai_assistant_service import ai_assistant_service

    user_id = message.from_user.id
    last_menu = _get_user_menu(user_id)

    # Проверяем, находится ли пользователь в главном меню или настройках
    if last_menu not in ("main_menu", "settings"):
        # Если пользователь не в главном меню или настройках, не обрабатываем
        return

    # Устанавливаем состояние ожидания сообщения
    await state.set_state(AIAssistantStates.waiting_for_message)
    await state.update_data(ai_mode=last_menu)

    # Загружаем контекст пользователя
    user = await get_or_create_user(message.from_user.id)
    db_settings = await get_user_settings(message.from_user.id)

    context = {
        "user_credits": user.credits,
        "preferred_model": db_settings["preferred_model"],
        "preferred_video_model": db_settings["preferred_video_model"],
        "image_service": db_settings.get("image_service", "nanobanana"),
        "menu_location": "главное меню" if last_menu == "main_menu" else "настройки",
    }

    # Отправляем "печатает" статус
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        # Получаем ответ от ИИ
        response = await ai_assistant_service.get_assistant_response(
            user_message=message.text, context=context
        )

        if response:
            # Отправляем ответ пользователю с клавиатурой ИИ
            await message.answer(
                f"🍌 <b>Banana Boom AI:</b>\n\n{response}",
                reply_markup=get_ai_assistant_keyboard(),
                parse_mode="HTML",
            )
        else:
            # Fallback если ИИ не ответил
            await message.answer(
                "😕 Извини, я временно недоступен. Попробуй ещё раз позже или напиши в поддержку @S_k7222",
                reply_markup=get_ai_assistant_keyboard(),
                parse_mode="HTML",
            )

    except Exception as e:
        logger.exception(f"AI Assistant error: {e}")
        await message.answer(
            "😕 Что-то пошло не так. Попробуй ещё раз или обратись в поддержку @S_k7222",
            reply_markup=get_ai_assistant_keyboard(),
            parse_mode="HTML",
        )


# =============================================================================
# ВАЖНО: НЕ ДОБАВЛЯЙТЕ СЮДА ОБРАБОТЧИКИ СООБЩЕНИЙ БЕЗ FSM STATE FILTER!
# Это перехватит сообщения до FSM-хэндлеров в generation_router
# =============================================================================

# Для диагностики оставляем только callback_query обработчики
# Все message хэндлеры должны быть в generation_router с явными StateFilter


@router.callback_query(F.data.startswith("ignore_"))
@router.callback_query(F.data == "ignore")
async def handle_ignore_callback(callback: types.CallbackQuery):
    """Обработчик для неинтерактивных кнопок-заголовков и разделителей"""
    await callback.answer()  # Просто закрываем уведомление о нажатии


# =============================================================================
# ИИ-ассистент (Дипсик)
# =============================================================================


@router.callback_query(F.data == "menu_ai_assistant")
async def open_ai_assistant_main(callback: types.CallbackQuery, state: FSMContext):
    """Открытие ИИ-ассистента из главного меню"""
    await state.set_state(AIAssistantStates.waiting_for_message)
    await state.update_data(ai_mode="main_menu")

    user = await get_or_create_user(callback.from_user.id)

    # Формируем контекст для ИИ
    context = {
        "user_credits": user.credits,
        "menu_location": "главное меню",
        "available_models": "Flash (1🍌), Pro (2🍌), видео Std/Pro/Omni",
    }

    # Приветственное сообщение от ИИ
    welcome_ai = """🍌 Привет! Я Banana Boom AI - твой ИИ-ассистент!

Я могу помочь тебе с:
🖼 Выбором модели для генерации изображений
✏️ Понять как редактировать фото
🎬 Подобрать настройки для видео
📝 Написать хороший промпт
⚙️ Разобраться в настройках

Просто напиши мне свой вопрос! Например:
• "как сделать аниме арт?"
• "какая модель лучше для фотореализма?"
• "как отредактировать фото в стиле киберпанк?"

Или нажми "В главное меню" чтобы вернуться."""

    await callback.message.edit_text(
        welcome_ai, reply_markup=get_ai_assistant_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "menu_ai_settings")
async def open_ai_assistant_settings(callback: types.CallbackQuery, state: FSMContext):
    """Открытие ИИ-ассистента из меню настроек"""
    await state.set_state(AIAssistantStates.waiting_for_message)
    await state.update_data(ai_mode="settings")

    # Загружаем настройки пользователя
    db_settings = await get_user_settings(callback.from_user.id)

    # Формируем контекст для ИИ
    context = {
        "menu_location": "меню настроек",
        "preferred_model": db_settings["preferred_model"],
        "preferred_video_model": db_settings["preferred_video_model"],
        "image_service": db_settings.get("image_service", "nanobanana"),
        "available_models": "Nano Banana (Flash/Pro), FLUX.2 Pro (Novita), Seedream (Novita), Kling 3 (Std/Pro/Omni)",
    }

    welcome_ai = """🍌 Я здесь, чтобы помочь с настройками!

Ты находишься в меню настройки моделей.
Я могу объяснить:

🍌 Какая модель изображений лучше:
   - Flash (1🍌) - быстро и дёшево
   - Pro (2🍌) - высокое качество, 4K

🎬 Какая модель видео подойдёт:
   - Std (4🍌) - стандарт
   - Pro (5🍌) - лучше качество
   - Omni - продвинутая

🖼 Чем отличаются сервисы:
   - Nano Banana - Gemini
   - Novita - FLUX.2 Pro и Seedream

Просто спроси меня! Например:
• "что лучше для портрета?"
• "какой формат выбрать для тиктока?"
• "зачем нужен Omni?"

Или нажми "Назад" чтобы вернуться к настройкам."""

    await callback.message.edit_text(
        welcome_ai, reply_markup=get_back_keyboard("menu_settings"), parse_mode="HTML"
    )
    await callback.answer()


@router.message(StateFilter(AIAssistantStates.waiting_for_message))
async def handle_ai_assistant_message(message: types.Message, state: FSMContext):
    """Обработка сообщения пользователя ИИ-ассистентом"""
    from bot.database import get_user_credits, get_user_settings
    from bot.keyboards import get_ai_assistant_keyboard
    from bot.services.ai_assistant_service import ai_assistant_service

    # Получаем текущий режим
    data = await state.get_data()
    ai_mode = data.get("ai_mode", "main_menu")

    # Загружаем контекст пользователя
    user = await get_or_create_user(message.from_user.id)
    db_settings = await get_user_settings(message.from_user.id)

    context = {
        "user_credits": user.credits,
        "preferred_model": db_settings["preferred_model"],
        "preferred_video_model": db_settings["preferred_video_model"],
        "image_service": db_settings.get("image_service", "nanobanana"),
        "menu_location": "главное меню" if ai_mode == "main_menu" else "настройки",
    }

    # Отправляем "печатает" статус
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        # Получаем ответ от ИИ
        response = await ai_assistant_service.get_assistant_response(
            user_message=message.text, context=context
        )

        if response:
            # Отправляем ответ пользователю
            await message.answer(
                f"🍌 <b>Banana Boom AI:</b>\n\n{response}",
                reply_markup=get_ai_assistant_keyboard(),
                parse_mode="HTML",
            )
        else:
            # Fallback если ИИ не ответил
            await message.answer(
                "😕 Извини, я временно недоступен. Попробуй ещё раз позже или напиши в поддержку @S_k7222",
                reply_markup=get_ai_assistant_keyboard(),
                parse_mode="HTML",
            )

    except Exception as e:
        logger.exception(f"AI Assistant error: {e}")
        await message.answer(
            "😕 Что-то пошло не так. Попробуй ещё раз или обратись в поддержку @S_k7222",
            reply_markup=get_ai_assistant_keyboard(),
            parse_mode="HTML",
        )
