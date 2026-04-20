import logging
import uuid

import aiosqlite
from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.database import (
    DATABASE_PATH,
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
        from bot.services.yookassa_service import yookassa_service

        transaction = await get_transaction_by_order(order_id)

        if transaction:
            if transaction.status == "completed":
                # Кредиты уже были начислены
                await message.answer(
                    f"✅ <b>Оплата уже обработана!</b>\n\n"
                    f"💎 Ваш баланс: <code>{user.credits}</code> GOEов",
                    reply_markup=get_main_menu_keyboard(user.credits),
                    parse_mode="HTML",
                )
                return
            elif transaction.status == "pending":
                try:
                    yk = await yookassa_service.get_payment(transaction.payment_id)
                    paid = bool(
                        yk
                        and (
                            yk.get("paid")
                            or (yk.get("status") or "").lower()
                            in ("succeeded", "paid", "captured")
                        )
                    )
                except Exception:
                    paid = False

                if paid:
                    # Начисляем кредиты
                    await add_credits(message.from_user.id, transaction.credits)
                    await update_transaction_status(order_id, "completed")

                    # Получаем обновлённый баланс
                    user = await get_or_create_user(message.from_user.id)

                    await message.answer(
                        f"🎉 <b>Оплата успешно обработана!</b>\n\n"
                        f"💎 Начислено: <code>{transaction.credits}</code> GOEов\n"
                        f"💰 Сумма: <code>{transaction.amount_rub}</code> ₽\n\n"
                        f"💎 Ваш баланс: <code>{user.credits}</code> GOEов",
                        reply_markup=get_main_menu_keyboard(user.credits),
                        parse_mode="HTML",
                    )
                    return
                else:
                    # Ожидаем подтверждения от банка/провайдера
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
💎 2Loop × AI — Создавай магию льда!
Твои идеи + наш ИИ = уникальный контент для фигурного катания

🎨 Генерация артов
Опиши образ — получи уникальный арт в стиле фигурного катания. Концепты костюмов, постеры, визуалы для соцсетей.

📸 Фото-магия
Стилизация снимков: добавь эффекты льда, зимнюю атмосферу, смени фон на каток. Замена объектов в один клик.

🎬 Видео-продакшн
Ролики из текста и фото — идеально для отчётов о соревнованиях, промо тренировок, благодарностей тренерам.

✨ FX-эффекты
Блёстки, следы на льду, динамичные переходы. Твои видео будут сиять как победные выступления.

💎 Баланс: <code>{user.credits}</code> GOE

📢 Канал: <a href="https://t.me/FS_2Loop">@FS_2Loop</a>

Попробуй прямо сейчас! 👇
⚠️ ВАЖНО:
Запрещён контент 18+, оскорбления, нарушение прав третьих лиц. Администрация оставляет за собой право блокировать нарушителей без возврата GOE. Ответственность за сгенерированный контент несёт пользователь.
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
• <b>Nano Banana Flash</b> — быстрая генерация (1💎)
• <b>Nano Banana Pro</b> — профессиональное качество, 4K (3💎)

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

<b>💎 Стоимость операций:</b>
• FLUX.2 Pro / Nano Banana / Seedream: 3💎
• Редактирование по референсам: 3💎 (до 14 референсов, 4K)
• Kling Standard: 6💎 | Kling Pro: 8-10💎

<b>❓ Нужна помощь?</b>
Обратитесь в поддержку: <a href="https://t.me/S_k7222">@design_2Loop7222</a>
"""

    await message.answer(help_text, reply_markup=get_back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "menu_help")
async def show_help(callback: types.CallbackQuery):
    """Показывает справку через inline-кнопку"""
    help_text = """
📖 <b>Помощь бота</b>

<b>💡 Что ты можешь спросить у ИИ-ассистента:</b>

Я — ИИ-ассистент в этом боте. Ты можешь написать мне ЛЮБОЙ вопрос, и я помогу!

🖼 <b>Генерация изображений:</b>
• Какую модель выбрать для фотореализма?
• Как написать хороший промпт для аниме?
• Чем отличается FLUX от Nano Banana?

🎬 <b>Генерация видео:</b>
• Какая модель лучше для коротких роликов?
• Как сделать видео из фото?
• Что такое Motion Control?

✏️ <b>Редактирование:</b>
• Как изменить стиль фото?
• Как добавить объект на изображение?
• Как использовать референсы?

💰 <b>Оплата и баланс:</b>
• Как пополнить баланс?
• Сколько стоит генерация?
• Какие есть скидки?

📝 <b>Просто напиши свой вопрос!</b>
Например: "как сделать крутой логотип?" или "помоги с промпт для космоса"

<b>❓ Или выбери "Тех. поддержка" для связи с нами</b>
"""

    try:
        await callback.message.edit_text(
            help_text, reply_markup=get_back_keyboard(), parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"Cannot edit message in show_help: {e}")
        await callback.message.answer(
            help_text, reply_markup=get_back_keyboard(), parse_mode="HTML"
        )
    await callback.answer()


@router.callback_query(F.data == "back_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
    await state.clear()

    user = await get_or_create_user(callback.from_user.id)

    # Запоминаем, что пользователь в главном меню
    _set_user_menu(callback.from_user.id, "main_menu")

    welcome_text = f"""
💎 2Loop & AI 
Создавай магию льда!
Твои идеи + наш ИИ = уникальный контент для фигурного катания

🎨 Генерация артов
Опиши образ — получи уникальный арт в стиле фигурного катания. Концепты костюмов, постеры, визуалы для соцсетей.

📸 Фото-магия
Стилизация снимков: добавь эффекты льда, зимнюю атмосферу, смени фон на каток. Замена объектов в один клик.
🎬 Видео-продакшн
Ролики из текста и фото — идеально для отчётов о соревнованиях, промо тренировок, благодарностей тренерам.

✨ FX-эффекты
Блёстки, следы на льду, динамичные переходы. Твои видео будут сиять как победные выступления.

💎 Баланс: <code>{user.credits}</code> GOE

📢 Канал: <a href="https://t.me/FS_2Loop">@FS_2Loop</a>
Попробуй прямо сейчас! 👇

⚠️ ВАЖНО:
Запрещён контент 18+, оскорбления, нарушение прав третьих лиц. Администрация оставляет за собой право блокировать нарушителей без возврата GOE. Ответственность за сгенерированный контент несёт пользователь.
"""

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

💎 Доступно GOEов: <code>{stats['credits']}</code>
📊 Всего генераций: <code>{stats['generations']}</code>
💸 Потрачено GOEов: <code>{stats['total_spent']}</code>
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
• Все модели: 3💎

🎬 Текст→Видео:
• Kling 2.6 (8💎) / Std (6💎) / Pro (8💎) / Omni / V2V

🖼→🎬 Фото→Видео:
• Std (6💎) / Pro (8💎) / Omni
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
    from bot.database import get_user_credits
    from bot.keyboards import get_motion_control_keyboard

    user_credits = await get_user_credits(callback.from_user.id)

    motion_text = f"""
🎬 <b>Motion Control</b>

Перенос движения с референсного видео на твоё фото!

📝 <b>Как это работает:</b>
1. Загрузи фото персонажа
2. Загрузи видео с движением
3. Получи анимированное фото!

💎 Баланс: {user_credits} GOE

Выбери качество:
"""

    await callback.message.edit_text(
        motion_text,
        reply_markup=get_motion_control_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "menu_support")
async def show_support(callback: types.CallbackQuery):
    """Показывает меню тех. поддержки"""
    from bot.keyboards import get_support_keyboard

    support_text = """
🆘 <b>Техническая поддержка</b>

💬 <b>Напиши свой вопрос ИИ-ассистенту</b>
Он поможет с:
• Генерацией изображений и видео
• Настройками и моделями
• Оплатой и балансом
• Любыми другими вопросами

📱 <b>Или свяжись с нами:</b>
@design_2Loop7222

Мы ответим вам в ближайшее время!
"""

    await callback.message.edit_text(
        support_text,
        reply_markup=get_support_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "menu_faq")
async def show_faq(callback: types.CallbackQuery):
    """Показывает FAQ с доставкой и офертой"""
    from bot.keyboards import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.button(text="📦 Доставка и возврат", callback_data="faq_dostavka")
    builder.button(text="📋 Публичная оферта", callback_data="faq_ofert")
    builder.button(text="🔙 Главное меню", callback_data="back_main")
    builder.adjust(1)

    await callback.message.edit_text(
        "📚 <b>FAQ</b>\n\n" "Политика доставки и возврат\n" "Публичная оферта",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


async def send_file_content_as_text(
    callback: types.CallbackQuery, filename: str, title: str
):
    """Отправляет содержимое файла как текст в чат, разбивая длинный текст на части"""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()
        chat_id = callback.message.chat.id
        from bot.keyboards import InlineKeyboardBuilder

        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 FAQ", callback_data="menu_faq")
        markup = kb.as_markup()
        max_len = 4096
        if len(content) <= max_len:
            await callback.bot.send_message(
                chat_id, f"{title}\n\n{content}", reply_markup=markup
            )
        else:
            pos = 0
            while pos < len(content):
                end = min(pos + max_len - 100, len(content))
                last_nl = content.rfind("\n\n", pos, end)
                if last_nl == -1:
                    last_nl = content.rfind("\n", pos, end)
                if last_nl > pos:
                    end = last_nl + 1
                part = content[pos:end]
                part_markup = markup if end >= len(content) else None
                await callback.bot.send_message(chat_id, part, reply_markup=part_markup)
                pos = end
        await callback.answer()
    except FileNotFoundError:
        await callback.message.answer("❌ Файл не найден.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка отправки {filename}: {e}")
        await callback.message.answer("❌ Ошибка отправки документа.")
        await callback.answer()


@router.callback_query(F.data == "faq_dostavka")
async def show_dostavka(callback: types.CallbackQuery):
    await send_file_content_as_text(
        callback, "static/uploads/dostavka.md", "📦 ПОЛИТИКА ДОСТАВКИ И ВОЗВРАТА"
    )


@router.callback_query(F.data == "faq_ofert")
async def show_ofert(callback: types.CallbackQuery):
    await send_file_content_as_text(
        callback, "static/uploads/ofert.md", "📋 ПУБЛИЧНАЯ ОФЕРТА"
    )


@router.callback_query(F.data == "menu_history")
async def show_history(callback: types.CallbackQuery):
    """Показывает историю генераций пользователя"""
    from bot.database import get_user_stats
    from bot.keyboards import get_main_menu_keyboard

    user = await get_or_create_user(callback.from_user.id)
    stats = await get_user_stats(callback.from_user.id)

    history_text = f"""
📋 <b>История</b>

📊 Всего генераций: <code>{stats['generations']}</code>
💸 Потрачено GOEов: <code>{stats['total_spent']}</code>
💎 Текущий баланс: <code>{user.credits}</code>💎
📅 Дата регистрации: <code>{stats['member_since']}</code>

<i>Детальная история скоро будет доступна!</i>
"""

    try:
        await callback.message.edit_text(
            history_text,
            reply_markup=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )
    except Exception as e:
        # Если сообщение нельзя отредактировать
        logger.warning(f"Cannot edit message: {e}")
        await callback.message.answer(
            history_text,
            reply_markup=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "motion_control_std")
async def start_motion_control_std(callback: types.CallbackQuery, state: FSMContext):
    """Запускает Motion Control Standard"""
    from bot.database import get_user_credits
    from bot.services.preset_manager import preset_manager
    from bot.states import GenerationStates

    user_credits = await get_user_credits(callback.from_user.id)
    cost = preset_manager.get_video_cost("v26_motion_std", 5)

    if user_credits < cost:
        await callback.answer("❌ Недостаточно GOEов! Пополни баланс.", show_alert=True)
        return

    # Сохраняем тип генерации
    await state.set_state(GenerationStates.waiting_for_motion_character_image)
    await state.update_data(
        generation_type="motion_control",
        video_model="v26_motion_std",
        cost=cost,
        mode="std",
    )

    await callback.message.edit_text(
        f"🎬 <b>Motion Control Standard</b>\n\n"
        f"Стоимость: {cost}💎\n\n"
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
    from bot.database import get_user_credits
    from bot.services.preset_manager import preset_manager
    from bot.states import GenerationStates

    user_credits = await get_user_credits(callback.from_user.id)
    cost = preset_manager.get_video_cost("v26_motion_pro", 5)

    if user_credits < cost:
        await callback.answer("❌ Недостаточно GOEов! Пополни баланс.", show_alert=True)
        return

    # Сохраняем тип генерации
    await state.set_state(GenerationStates.waiting_for_motion_character_image)
    await state.update_data(
        generation_type="motion_control",
        video_model="v26_motion_pro",
        cost=cost,
        mode="pro",
    )

    await callback.message.edit_text(
        f"💎 <b>Motion Control Pro</b>\n\n"
        f"Стоимость: {cost}💎\n\n"
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
        "nanobanana": "💎 Nano Banana",
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
        f"💎 Ваш баланс: <code>{user_credits}</code> GOEов\n\n"
        f"Выберите пресет:",
        reply_markup=get_category_keyboard(category, presets, user_credits),
        parse_mode="HTML",
    )


# =============================================================================
# ИИ-ассистент: обработка сообщений без FSM
# Позволяет отправлять вопросы ИИ напрямую из главного меню или настройках
# =============================================================================


@router.message(StateFilter(None), F.text)
async def handle_message_in_menu(message: types.Message, state: FSMContext):
    """Обработка текстовых сообщений в главном меню - перенаправление к ИИ с историей"""
    from bot.keyboards import get_ai_assistant_keyboard
    from bot.services.ai_assistant_service import ai_assistant_service

    user_id = message.from_user.id
    last_menu = _get_user_menu(user_id)

    if last_menu not in ("main_menu", "settings"):
        return

    await state.set_state(AIAssistantStates.waiting_for_message)
    await state.update_data(ai_mode=last_menu, history=[])

    user = await get_or_create_user(message.from_user.id)
    db_settings = await get_user_settings(message.from_user.id)

    context = {
        "user_credits": user.credits,
        "preferred_model": db_settings["preferred_model"],
        "preferred_video_model": db_settings["preferred_video_model"],
        "image_service": db_settings.get("image_service", "nanobanana"),
        "menu_location": "главное меню" if last_menu == "main_menu" else "настройки",
    }

    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        response = await ai_assistant_service.get_assistant_response(
            user_message=message.text, context=context, history=[]
        )

        history = [{"role": "user", "content": message.text}]
        if response:
            history.append({"role": "assistant", "content": response})
            await message.answer(
                f"🤖 2Loop AI:\n\n{response}",
                reply_markup=get_ai_assistant_keyboard(),
                parse_mode="HTML",
            )
        else:
            await message.answer(
                "😕 Временно недоступен. Попробуй позже или @design_2Loop7222",
                reply_markup=get_ai_assistant_keyboard(),
                parse_mode="HTML",
            )

        await state.update_data(history=history)

    except Exception as e:
        logger.exception(f"AI Assistant error: {e}")
        await message.answer(
            "😕 Ошибка. Попробуй снова или обратись в поддержку.",
            reply_markup=get_ai_assistant_keyboard(),
            parse_mode="HTML",
        )


# =============================================================================
# ВАЖНО: НЕ ДОБАВЛЯЙТЕ СЮДА ОБРАБОТЧИКИ СООБЩЕНИЙ БЕЗ FSM STATE FILTER!
# Это перехватит сообщения до FSM-хэндлеров в generation_router
# =============================================================================

# Для диагностики оставляем только callback_query обработчики
# Все message хэндлеры должны быть в generation_router с явными StateFilter


@router.callback_query(F.data == "check_subscription")
async def check_subscription(callback: types.CallbackQuery):
    """Обработчик кнопки проверки подписки"""
    await callback.answer(
        "✅ Подписка проверена! Теперь вы можете использовать бота.", show_alert=True
    )


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
        "available_models": "Flash (1💎), Pro (2💎), видео Std/Pro/Omni",
    }

    # Приветственное сообщение от ИИ
    welcome_ai = """💎 Привет! Я 2loop AI - твой ИИ-ассистент!

Я здесь, чтобы помочь тебе с ЛЮБЫМ вопросом! Ты можешь спросить меня абсолютно обо всём:

💡 <b>Примеры вопросов:</b>
• "как сделать аниме арт?"
• "какая модель лучше для фотореализма?"
• "сколько стоит генерация?"
• "как пополнить баланс?"
• "что такое Motion Control?"
• "помоги написать промпт для космоса"
• "как отредактировать фото в стиле киберпанк?"

📝 <b>Просто напиши свой вопрос!</b>
Я отвечу на любой вопрос связанный с ботом.

🔙 Нажми "В главное меню" чтобы вернуться."""

    await callback.message.edit_text(
        welcome_ai, reply_markup=get_ai_assistant_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "menu_ai_settings")
async def open_ai_assistant_settings(callback: types.CallbackQuery, state: FSMContext):
    """Открытие ИИ-ассистента из меню настройки"""
    await state.set_state(AIAssistantStates.waiting_for_message)
    await state.update_data(ai_mode="settings")

    # Загружаем настройки пользователя
    db_settings = await get_user_settings(callback.from_user.id)

    # Формируем контекст для ИИ
    context = {
        "menu_location": "меню настройки",
        "preferred_model": db_settings["preferred_model"],
        "preferred_video_model": db_settings["preferred_video_model"],
        "image_service": db_settings.get("image_service", "nanobanana"),
        "available_models": "Nano Banana (Flash/Pro), FLUX.2 Pro (Novita), Seedream (Novita), Kling 3 (Std/Pro/Omni)",
    }

    welcome_ai = """💎 Я здесь, чтобы помочь с настройками!

Ты находишься в меню настройки моделей.
Я могу объяснить:

💎 Какая модель изображений лучше:
   - Flash (1💎) - быстро и дёшево
   - Pro (2💎) - высокое качество, 4K

🎬 Какая модель видео подойдёт:
   - Std (4💎) - стандарт
   - Pro (5💎) - лучше качество
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


@router.message(GenerationStates.waiting_for_motion_character_image, F.photo)
async def handle_motion_character_upload(message: types.Message, state: FSMContext):
    """Загрузка фото персонажа для motion control"""
    import os
    import uuid

    from bot.config import config

    data = await state.get_data()
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)
    image_data = image_bytes.read()

    os.makedirs("static/uploads", exist_ok=True)
    host = config.WEBHOOK_HOST.rstrip("/")
    fname = f"{uuid.uuid4().hex}.jpg"
    fpath = f"static/uploads/{fname}"
    with open(fpath, "wb") as f:
        f.write(image_data)
    v_image_url = f"{host}/uploads/{fname}"

    await state.update_data(v_image_url=v_image_url)
    await message.answer(
        "✅ <b>Фото персонажа загружено!</b>\n\n"
        "📹 <b>Шаг 2:</b> Загрузите видео с движением\n"
        "(3-10 секунд, четкое движение)",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_motion_video)


@router.message(GenerationStates.waiting_for_motion_video, F.video)
async def handle_motion_video_upload(message: types.Message, state: FSMContext):
    """Загрузка видео движения для motion control"""
    import os
    import uuid

    from bot.config import config
    from bot.database import (
        add_credits,
        add_generation_task,
        deduct_credits,
        get_or_create_user,
    )
    from bot.services.kling_service import kling_service

    data = await state.get_data()
    v_image_url = data.get("v_image_url")
    if not v_image_url:
        await message.answer("❌ Сначала загрузите фото персонажа!", parse_mode="HTML")
        return

    video = message.video
    file = await message.bot.get_file(video.file_id)
    video_bytes = await message.bot.download_file(file.file_path)
    video_data = video_bytes.read()

    os.makedirs("static/uploads", exist_ok=True)
    host = config.WEBHOOK_HOST.rstrip("/")
    fname = f"{uuid.uuid4().hex}.mp4"
    fpath = f"static/uploads/{fname}"
    with open(fpath, "wb") as f:
        f.write(video_data)
    v_video_url = f"{host}/uploads/{fname}"

    telegram_id = message.from_user.id
    user = await get_or_create_user(telegram_id)
    cost = data.get("cost")
    video_model = data.get("video_model")
    mode = data.get("mode", "std")

    await deduct_credits(telegram_id, cost)

    local_task_id = f"motion_{uuid.uuid4().hex[:12]}"
    await add_generation_task(
        user_id=user.id,
        telegram_id=telegram_id,
        task_id=local_task_id,
        type="motion_control",
        preset_id="motion_control",
        model=video_model,
        prompt="motion control",
        cost=cost,
    )

    task_result = await kling_service.generate_motion_control(
        image_url=v_image_url,
        video_urls=[v_video_url],
        mode=mode,
        webhook_url=config.kie_notification_url,
    )

    if task_result and "task_id" in task_result:
        api_task_id = task_result["task_id"]
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "UPDATE generation_tasks SET task_id = ? WHERE task_id = ? AND user_id = ?",
                (api_task_id, local_task_id, user.id),
            )
            await db.commit()
        await message.answer(
            f"🚀 <b>Motion Control запущен!</b>\n\n"
            f"💰 <code>{cost}</code>💎\n"
            f"🤖 <code>{mode.upper()}</code>\n"
            f"🆔 <code>{api_task_id}</code>\n\n"
            f"Ожидайте результат (1-5 мин)...",
            parse_mode="HTML",
        )
        await state.clear()
    else:
        await add_credits(telegram_id, cost)
        await message.answer("❌ Ошибка запуска. GOE возвращены.", parse_mode="HTML")


@router.message(GenerationStates.waiting_for_motion_character_image)
async def invalid_motion_character_upload(message: types.Message, state: FSMContext):
    """Невалидный ввод при загрузке фото персонажа"""
    await message.answer(
        "⚠️ <b>Пожалуйста, отправьте фото персонажа</b>", parse_mode="HTML"
    )


@router.message(GenerationStates.waiting_for_motion_video)
async def invalid_motion_video_upload(message: types.Message, state: FSMContext):
    """Невалидный ввод при загрузке видео движения"""
    await message.answer(
        "⚠️ <b>Пожалуйста, отправьте видео (3-10 сек)</b>", parse_mode="HTML"
    )


@router.message(StateFilter(AIAssistantStates.waiting_for_message))
async def handle_ai_assistant_message(message: types.Message, state: FSMContext):
    """Обработка сообщений ИИ-ассистента с историей (до 7 сообщений)"""
    from bot.database import get_user_settings
    from bot.keyboards import get_ai_assistant_keyboard
    from bot.services.ai_assistant_service import ai_assistant_service

    data = await state.get_data()
    history = data.get("history", [])
    ai_mode = data.get("ai_mode", "main_menu")

    user = await get_or_create_user(message.from_user.id)
    db_settings = await get_user_settings(message.from_user.id)

    context = {
        "user_credits": user.credits,
        "preferred_model": db_settings["preferred_model"],
        "preferred_video_model": db_settings["preferred_video_model"],
        "image_service": db_settings.get("image_service", "nanobanana"),
        "menu_location": "главное меню" if ai_mode == "main_menu" else "настройки",
    }

    # Добавляем новое сообщение пользователя в историю
    history.append({"role": "user", "content": message.text})

    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        response = await ai_assistant_service.get_assistant_response(
            user_message=message.text, context=context, history=history
        )

        if response:
            history.append({"role": "assistant", "content": response})
            # Ограничиваем историю 7 сообщениями (последние)
            if len(history) > 7:
                history = history[-7:]
            await state.update_data(history=history)

            await message.answer(
                f"🤖 2Loop AI:\n\n{response}",
                reply_markup=get_ai_assistant_keyboard(),
                parse_mode="HTML",
            )
        else:
            await message.answer(
                "😕 Не удалось получить ответ. Попробуй перефразировать или @design_2Loop7222",
                reply_markup=get_ai_assistant_keyboard(),
                parse_mode="HTML",
            )

    except Exception as e:
        logger.exception(f"AI Assistant error: {e}")
        await message.answer(
            "😕 Ошибка связи с ИИ. Попробуй позже.",
            reply_markup=get_ai_assistant_keyboard(),
            parse_mode="HTML",
        )
