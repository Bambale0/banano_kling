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
    accept_partner_agreement,
    create_partner_withdrawal,
    get_or_create_user,
    get_partner_overview,
    get_referral_stats,
    get_user_settings,
    get_user_stats,
    process_referral,
    save_user_settings,
)
from bot.keyboards import (
    get_ai_assistant_keyboard,
    get_back_keyboard,
    get_main_menu_keyboard,
    get_partner_consent_keyboard,
    get_partner_program_keyboard,
    get_referral_keyboard,
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


def _build_main_menu_text(user_credits: int, referral_bonus_text: str = "") -> str:
    bonus_block = f"\n{referral_bonus_text.strip()}\n" if referral_bonus_text else "\n"
    return (
        "🏠 <b>Главное меню</b>\n"
        "Создавайте изображения, видео и эффекты в одном аккуратном потоке.\n\n"
        "<b>Что можно сделать</b>\n"
        "• Арты и иллюстрации по промпту\n"
        "• Редактирование и стилизация фото\n"
        "• Видео из текста, фото и референсов\n"
        "• Motion Control и апгрейды результата\n\n"
        f"🍌 <b>Баланс:</b> <code>{user_credits}</code> бананов"
        f"{bonus_block}"
        "<i>Выберите, с чего начнём.</i>"
    )


def _build_balance_text(stats: dict) -> str:
    return (
        "💎 <b>Баланс и статистика</b>\n\n"
        f"• Бананов доступно: <code>{stats['credits']}</code>\n"
        f"• Всего генераций: <code>{stats['generations']}</code>\n"
        f"• Потрачено бананов: <code>{stats['total_spent']}</code>\n"
        f"• Дата регистрации: <code>{stats['member_since']}</code>\n"
        f"• Приглашено друзей: <code>{stats.get('referrals_count', 0)}</code>\n"
        f"• Заработано по рефералке: <code>{stats.get('referral_earned', 0)}</code>"
    )


def _build_settings_text() -> str:
    return (
        "⚙️ <b>Настройки</b>\n"
        "Здесь можно выбрать модели по умолчанию для разных сценариев.\n\n"
        "<b>Разделы</b>\n"
        "• Изображения\n"
        "• Текст -> Видео\n"
        "• Фото -> Видео\n"
        "• Сервис для изображений\n\n"
        "<i>Текущий выбор всегда отмечен в клавиатуре ниже.</i>"
    )


def _build_motion_control_menu_text(user_credits: int) -> str:
    return (
        "🎬 <b>Motion Control</b>\n"
        "Перенесите движение из референсного видео на персонажа или объект на фото.\n\n"
        "<b>Как это работает</b>\n"
        "1. Загрузите фото\n"
        "2. Добавьте видео с движением\n"
        "3. Получите анимированный результат\n\n"
        f"🍌 <b>Баланс:</b> <code>{user_credits}</code> бананов\n\n"
        "<i>Выберите качество ниже.</i>"
    )


def _build_motion_control_step_text(title: str, cost: int) -> str:
    return (
        f"{title}\n"
        f"🍌 <b>Стоимость:</b> <code>{cost}</code>\n\n"
        "<b>Шаг 1. Фото персонажа</b>\n"
        "Загрузите изображение, которое нужно анимировать.\n\n"
        "Подойдёт:\n"
        "• фото человека\n"
        "• персонаж или иллюстрация\n"
        "• любой объект, которому нужно передать движение"
    )


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
                    f"✅ <b>Оплата уже обработана!</b>"
                    f"🍌 Ваш баланс: <code>{user.credits}</code> бананов",
                    reply_markup=get_main_menu_keyboard(user.credits),
                    parse_mode="HTML",
                )
                return
            elif transaction.status == "pending":
                # Проверяем статус у провайдера — поддерживаем Т-Банк и YooKassa
                try:
                    # T-Bank проверка
                    result = await tbank_service.get_state(transaction.payment_id)
                except Exception:
                    result = None

                paid = False
                # T-Bank: Status == CONFIRMED
                if result and result.get("Status") == "CONFIRMED":
                    paid = True

                # Если не T-Bank или не подтверждён — попробуем YooKassa
                if not paid:
                    try:
                        from bot.services.yookassa_service import yookassa_service

                        yk = await yookassa_service.get_payment(transaction.payment_id)
                        if yk and (
                            yk.get("paid")
                            or (yk.get("status") or "").lower()
                            in ("succeeded", "paid", "captured")
                        ):
                            paid = True
                    except Exception:
                        # Не фатально — будем ожидать webhook
                        pass

                if paid:
                    # Начисляем кредиты
                    await add_credits(message.from_user.id, transaction.credits)
                    await update_transaction_status(order_id, "completed")

                    # Получаем обновлённый баланс
                    user = await get_or_create_user(message.from_user.id)

                    await message.answer(
                        f"🎉 <b>Оплата успешно обработана!</b>"
                        f"🍌 Начислено: <code>{transaction.credits}</code> бананов\n"
                        f"💰 Сумма: <code>{transaction.amount_rub}</code> ₽"
                        f"💎 Ваш баланс: <code>{user.credits}</code> бананов",
                        reply_markup=get_main_menu_keyboard(user.credits),
                        parse_mode="HTML",
                    )
                    return
                else:
                    # Ожидаем подтверждения от банка/провайдера
                    await message.answer(
                        "⏳ <b>Оплата в обработке...</b>"
                        "Пожалуйста, подождите. Кредиты будут начислены в течение нескольких минут.",
                        reply_markup=get_main_menu_keyboard(user.credits),
                        parse_mode="HTML",
                    )
                    return
        else:
            await message.answer(
                "❌ <b>Транзакция не найдена</b>" "Пожалуйста, свяжитесь с поддержкой.",
                reply_markup=get_main_menu_keyboard(user.credits),
                parse_mode="HTML",
            )
            return

    elif args and args[0].startswith("fail_"):
        await message.answer(
            "❌ <b>Оплата не была завершена</b>"
            "Вы можете попробовать снова в любое время.",
            reply_markup=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )
        return

    referral_bonus_text = ""
    if args and args[0].startswith("ref_"):
        referral_code = args[0].replace("ref_", "", 1)
        processed = await process_referral(message.from_user.id, referral_code)
        if processed:
            referral_bonus_text = (
                "\n🎁 <b>Реферальный бонус активирован!</b>\n"
                "Вы получили бонус за регистрацию по приглашению."
            )

    welcome_text = _build_main_menu_text(user.credits, referral_bonus_text)

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
    help_text = (
        "📖 <b>Помощь</b>\n"
        "Коротко о том, что сейчас умеет бот.\n\n"
        "<b>Фото</b>\n"
        "• Генерация и редактирование в одном меню\n"
        "• Модели: Banana Pro, Banana 2, Seedream 4.5, Grok Imagine i2i\n"
        "• Можно добавлять референсы и менять формат кадра\n\n"
        "<b>Видео</b>\n"
        "• Генерация из текста, фото и видео-референсов\n"
        "• Модели: Kling 3, Grok Imagine, Veo 3.1\n"
        "• Для части моделей доступны расширенные настройки прямо в клавиатуре\n\n"
        "<b>Дополнительно</b>\n"
        "• Motion Control для переноса движения с видео на фото\n"
        "• Анализ фото -> промпт\n"
        "• Пополнение баланса внутри бота\n\n"
        "<b>Как получить лучший результат</b>\n"
        "• пишите промпт полными фразами\n"
        "• добавляйте стиль, свет, ракурс и настроение\n"
        "• используйте референсы, если важны персонажи, стиль или композиция\n\n"
        "<b>Поддержка</b>\n"
        "@chillcreative"
    )

    await message.answer(help_text, reply_markup=get_back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "menu_help")
async def show_help(callback: types.CallbackQuery):
    """Показывает справку через inline-кнопку"""
    help_text = (
        "📖 <b>Помощь</b>\n\n"
        "<b>Что можно сделать в боте</b>\n"
        "• создать фото по промпту\n"
        "• отредактировать фото с референсами\n"
        "• сгенерировать видео из текста, фото или видео\n"
        "• запустить Motion Control\n"
        "• разобрать фото в готовый промпт\n\n"
        "<b>Актуальные модели</b>\n"
        "• Фото: Banana Pro, Banana 2, Seedream 4.5, Grok Imagine i2i\n"
        "• Видео: Kling 3, Grok Imagine, Veo 3.1\n\n"
        "<b>О чём можно спросить AI-ассистента</b>\n"
        "• какую модель выбрать под задачу\n"
        "• как написать сильный промпт\n"
        "• какой формат лучше для Reels, TikTok, YouTube\n"
        "• как использовать референсы\n"
        "• как работает Motion Control\n"
        "• сколько стоит нужный сценарий\n\n"
        "<b>Поддержка</b>\n"
        "@chillcreative"
    )

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

    welcome_text = _build_main_menu_text(user.credits)

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

    balance_text = _build_balance_text(stats)

    await callback.message.edit_text(
        balance_text,
        reply_markup=get_main_menu_keyboard(user.credits),
        parse_mode="HTML",
    )


@router.message(Command("ref"), StateFilter(None))
@router.message(Command("earn"), StateFilter(None))
async def cmd_partner(message: types.Message):
    """Показывает партнёрскую программу."""
    await render_partner_program(message, user_id=message.from_user.id)


@router.callback_query(F.data.in_({"menu_referrals", "menu_partner"}))
async def show_partner(callback: types.CallbackQuery):
    """Показывает партнёрскую программу."""
    await render_partner_program(callback.message, user_id=callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "partner_offer")
async def show_partner_offer(callback: types.CallbackQuery):
    """Показывает текст публичной оферты из static/ofert.md (локально)."""
    import os

    try:
        ofert_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "static", "ofert.md")
        )

        # Попробуем сначала отправить файл как документ — это самый надёжный способ
        try:
            # Try to send the local file path directly. Avoid using InputFile
            # class instantiation which may not be compatible with this aiogram
            # version (causes "Can't instantiate abstract class InputFile").
            await callback.message.answer_document(
                document=ofert_path,
                caption="📜 Публичная оферта",
                reply_markup=get_partner_consent_keyboard(),
            )
            await callback.answer()
            return
        except Exception as e_doc:
            logger.info(
                "Sending offer as document failed, falling back to text: %s", e_doc
            )

        # Если отправка документа не удалась, попытаемся отправить текст по частям
        with open(ofert_path, "r", encoding="utf-8") as f:
            ofert_text = f.read()

        # Telegram имеет ограничение на длину сообщения (~4096 символов). Разделим на части.
        max_len = 4000
        parts = [
            ofert_text[i : i + max_len] for i in range(0, len(ofert_text), max_len)
        ]

        # Отправляем части: для первой части пробуем отредактировать сообщение,
        # для промежуточных частей отправляем просто текст (без клавиатуры),
        # а клавиатуру с возможностью "Назад" и акцепта показываем только в последней части.
        for idx, part in enumerate(parts):
            try:
                is_last = idx == len(parts) - 1
                if idx == 0:
                    try:
                        # Пытаемся отредактировать существующее сообщение и сразу добавить клавиатуру
                        await callback.message.edit_text(
                            part,
                            reply_markup=(
                                get_partner_consent_keyboard() if is_last else None
                            ),
                            parse_mode="HTML",
                        )
                        # Если отредактировали и это не последняя часть, продолжим к следующей
                        if not is_last:
                            continue
                        else:
                            # Если это была единственная/последняя часть — всё готово
                            break
                    except Exception:
                        # Не удалось отредактировать — отправим новое сообщение ниже
                        pass

                # Для всех отправляемых сообщений: добавляем клавиатуру ТОЛЬКО для последней части
                if is_last:
                    await callback.message.answer(
                        part,
                        reply_markup=get_partner_consent_keyboard(),
                        parse_mode="HTML",
                    )
                else:
                    await callback.message.answer(part, parse_mode="HTML")
            except Exception as e_part:
                logger.exception("Failed to send part of offer: %s", e_part)

        await callback.answer()

    except Exception as e:
        logger.exception("Failed to load partner offer: %s", e)
        await callback.answer("Не удалось загрузить оферту.", show_alert=True)


async def render_partner_program(target, user_id: int):
    """Рендерит экран партнёрской программы."""
    user = await get_or_create_user(user_id)
    stats = await get_partner_overview(user_id)

    bot = target.bot
    me = await bot.get_me()
    referral_code = user.referral_code or ""
    referral_link = (
        f"https://t.me/{me.username}?start=ref_{referral_code}" if referral_code else ""
    )

    tier = stats.get("tier", "basic")
    percent = stats.get("percent", 30)
    offer_url = "https://example.com/offer"
    rules_url = "https://example.com/rules"
    if hasattr(bot, "offer_url"):
        offer_url = bot.offer_url

    text = (
        "💼 <b>Партнёрам</b>"
        "Это практическое руководство по участию в партнёрской программе.\n"
        "Юридически значимые условия содержатся в Публичной оферте."
        f"🔗 Ваша личная ссылка: <code>{referral_link or 'Ссылка появится после активации'} </code>\n"
        f"👥 Всего рефералов: <code>{stats.get('referrals_count', 0)}</code>\n"
        f"💰 Заработано: <code>{stats.get('balance_rub', 0)}</code> ₽\n"
        f"💸 Выведено: <code>{stats.get('withdrawn_rub', 0)}</code> ₽\n"
        f"🧮 Текущий баланс: <code>{stats.get('balance_rub', 0)}</code> ₽\n"
        f"🏷 Уровень: <code>{tier}</code> • <code>{percent}%</code>"
        "<b>Уровни вознаграждения:</b>\n"
        "• 30% — базовый уровень\n"
        "• 35% — от 100 000 ₽ оборота рефералов\n"
        "• 50% — от 1 000 000 ₽ оборота рефералов"
        "<b>Как это работает:</b>\n"
        "• Пользователь переходит по вашей ссылке\n"
        "• Регистрируется и закрепляется за вами навсегда\n"
        "• После оплат рефералов начисляется денежное вознаграждение\n"
        "• Вывод доступен после достижения минимальной суммы\n"
    )

    markup = (
        get_partner_program_keyboard(
            referral_link, is_partner=stats.get("is_partner", False)
        )
        if referral_link
        else get_partner_consent_keyboard()
    )

    if isinstance(target, types.Message):
        await target.answer(text, reply_markup=markup, parse_mode="HTML")
    else:
        await target.edit_text(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data == "partner_accept")
async def accept_partner(callback: types.CallbackQuery):
    """Подтверждение участия в партнёрской программе."""
    from bot.database import generate_referral_code, update_user_referral_code

    await accept_partner_agreement(callback.from_user.id)

    # Ensure user has a referral code after activation — some older users may lack it
    user = await get_or_create_user(callback.from_user.id)
    try:
        if not user.referral_code:
            new_code = await generate_referral_code()
            await update_user_referral_code(callback.from_user.id, new_code)
            # refresh user object
            user = await get_or_create_user(callback.from_user.id)
    except Exception:
        # Non-fatal: if generation/update fails, continue without blocking the flow
        logger.exception("Failed to ensure referral code on partner accept")
    # Подготавливаем корректную реферальную ссылку — без лишнего 'ref_' если кода нет
    me = await callback.bot.get_me()
    referral_code = user.referral_code
    referral_link = (
        f"https://t.me/{me.username}?start=ref_{referral_code}" if referral_code else ""
    )

    await callback.message.edit_text(
        "✅ <b>Партнёрский статус активирован</b>"
        "Теперь вы получаете денежное вознаграждение за оплату рефералов.\n"
        "Ваш процент зависит от оборота рефералов и обновляется автоматически.",
        reply_markup=get_partner_program_keyboard(referral_link, is_partner=True),
        parse_mode="HTML",
    )
    await callback.answer("Партнёрская программа активирована")


@router.callback_query(F.data == "partner_stats")
async def partner_stats(callback: types.CallbackQuery):
    """Показывает детальную статистику партнёра."""
    stats = await get_partner_overview(callback.from_user.id)
    text = (
        "📈 <b>Детальная статистика</b>"
        f"• Всего рефералов: <code>{stats.get('referrals_count', 0)}</code>\n"
        f"• Активных за 7 дней: <code>{stats.get('active_7d', 0)}</code>\n"
        f"• Всего покупок: <code>{stats.get('total_payments', 0)}</code>\n"
        f"• Доход за месяц: <code>{stats.get('monthly_revenue', 0)}</code> ₽\n"
        f"• Новые за сегодня: <code>{stats.get('today_payments', 0)}</code>\n"
        f"• Доход за сегодня: <code>{stats.get('today_revenue', 0)}</code> ₽\n"
    )
    # Подготавливаем корректную реферальную ссылку — без лишнего 'ref_' если кода нет
    user = await get_or_create_user(callback.from_user.id)
    me = await callback.bot.get_me()
    referral_code = user.referral_code
    referral_link = (
        f"https://t.me/{me.username}?start=ref_{referral_code}" if referral_code else ""
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_partner_program_keyboard(
            referral_link, is_partner=stats.get("is_partner", False)
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "partner_withdraw")
async def partner_withdraw(callback: types.CallbackQuery):
    """Показывает меню вывода."""
    stats = await get_partner_overview(callback.from_user.id)
    min_withdraw = 2000
    # Подготавливаем корректную реферальную ссылку — без лишнего 'ref_' если кода нет
    user = await get_or_create_user(callback.from_user.id)
    me = await callback.bot.get_me()
    referral_code = user.referral_code
    referral_link = (
        f"https://t.me/{me.username}?start=ref_{referral_code}" if referral_code else ""
    )

    await callback.message.edit_text(
        "🎟️ <b>Вывод заработка</b>"
        f"Доступно: <code>{stats.get('balance_rub', 0)}</code> ₽\n"
        f"Минимальная сумма вывода: <code>{min_withdraw}</code> ₽"
        "Для оформления вывода напишите реквизиты и сумму в поддержку или добавим форму следующим шагом.",
        reply_markup=get_partner_program_keyboard(
            referral_link, is_partner=stats.get("is_partner", False)
        ),
        parse_mode="HTML",
    )
    await callback.answer()


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

    settings_text = _build_settings_text()

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

    motion_text = _build_motion_control_menu_text(user_credits)

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

    support_text = (
        "🆘 <b>Поддержка</b>\n\n"
        "Можно написать прямо сюда — AI-ассистент поможет с:\n"
        "• генерацией изображений и видео\n"
        "• выбором модели и настроек\n"
        "• оплатой и балансом\n"
        "• любыми непонятными шагами в боте\n\n"
        "<b>Если нужен человек:</b>\n"
        "@chillcreative"
    )

    await callback.message.edit_text(
        support_text,
        reply_markup=get_support_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "menu_history")
async def show_history(callback: types.CallbackQuery):
    """Показывает историю генераций пользователя"""
    from bot.database import get_user_stats
    from bot.keyboards import get_main_menu_keyboard

    user = await get_or_create_user(callback.from_user.id)
    stats = await get_user_stats(callback.from_user.id)

    history_text = (
        "📋 <b>История</b>\n\n"
        f"• Всего генераций: <code>{stats['generations']}</code>\n"
        f"• Потрачено бананов: <code>{stats['total_spent']}</code>\n"
        f"• Текущий баланс: <code>{user.credits}</code>🍌\n"
        f"• Дата регистрации: <code>{stats['member_since']}</code>\n\n"
        "<i>Подробная история запусков появится здесь чуть позже.</i>"
    )

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
        await callback.answer(
            "❌ Недостаточно бананов! Пополни баланс.", show_alert=True
        )
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
        _build_motion_control_step_text("🎬 <b>Motion Control Standard</b>", cost),
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
        await callback.answer(
            "❌ Недостаточно бананов! Пополни баланс.", show_alert=True
        )
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
        _build_motion_control_step_text("💎 <b>Motion Control Pro</b>", cost),
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

    from bot.keyboards import get_settings_keyboard_with_ai

    data = await state.get_data()
    current_video_model = data.get("preferred_video_model", "v3_std")
    current_i2v_model = data.get("preferred_i2v_model", "v3_std")
    current_image_service = data.get("image_service", "nanobanana")

    await callback.message.edit_text(
        _build_settings_text(),
        reply_markup=get_settings_keyboard_with_ai(
            model_type,
            current_video_model,
            current_i2v_model,
            image_service=current_image_service,
        ),
        parse_mode="HTML",
    )
    await callback.answer("Настройки изображений обновлены")


@router.callback_query(F.data.startswith("settings_video_"))
async def handle_settings_video_model(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора модели видео в настройках"""
    video_model = callback.data.replace("settings_video_", "")

    # Сохраняем выбор модели видео в БД
    await save_user_settings(callback.from_user.id, preferred_video_model=video_model)

    # Сохраняем в состояние
    await state.update_data(preferred_video_model=video_model)

    from bot.keyboards import get_settings_keyboard_with_ai

    data = await state.get_data()
    current_model = data.get("preferred_model", "flash")
    current_i2v_model = data.get("preferred_i2v_model", "v3_std")
    current_image_service = data.get("image_service", "nanobanana")

    await callback.message.edit_text(
        _build_settings_text(),
        reply_markup=get_settings_keyboard_with_ai(
            current_model,
            video_model,
            current_i2v_model,
            image_service=current_image_service,
        ),
        parse_mode="HTML",
    )
    await callback.answer("Настройки видео обновлены")


@router.callback_query(F.data.startswith("settings_i2v_"))
async def handle_settings_i2v_model(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора модели для фото-в-видео в настройках"""
    i2v_model = callback.data.replace("settings_i2v_", "")

    # Сохраняем выбор модели i2v в БД
    await save_user_settings(callback.from_user.id, preferred_i2v_model=i2v_model)

    # Сохраняем в состояние
    await state.update_data(preferred_i2v_model=i2v_model)

    from bot.keyboards import get_settings_keyboard_with_ai

    data = await state.get_data()
    current_model = data.get("preferred_model", "flash")
    current_video_model = data.get("preferred_video_model", "v3_std")
    current_image_service = data.get("image_service", "nanobanana")

    await callback.message.edit_text(
        _build_settings_text(),
        reply_markup=get_settings_keyboard_with_ai(
            current_model,
            current_video_model,
            i2v_model,
            image_service=current_image_service,
        ),
        parse_mode="HTML",
    )
    await callback.answer("Настройки фото -> видео обновлены")


@router.callback_query(F.data.startswith("settings_service_"))
async def handle_settings_service(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора сервиса/модели для генерации изображений."""
    service = callback.data.replace("settings_service_", "")

    # Сохраняем выбор сервиса в БД
    await save_user_settings(callback.from_user.id, image_service=service)

    # Сохраняем в состояние
    await state.update_data(image_service=service)

    from bot.keyboards import get_settings_keyboard_with_ai

    data = await state.get_data()
    current_model = data.get("preferred_model", "flash")
    current_video_model = data.get("preferred_video_model", "v3_std")
    current_i2v_model = data.get("preferred_i2v_model", "v3_std")

    await callback.message.edit_text(
        _build_settings_text(),
        reply_markup=get_settings_keyboard_with_ai(
            current_model, current_video_model, current_i2v_model, image_service=service
        ),
        parse_mode="HTML",
    )
    await callback.answer("Сервис изображений обновлён")


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
        f"📝 {categories[category].get('description', '')}"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов"
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
                f"🤖 <b>BotAI:</b>{response}",
                reply_markup=get_ai_assistant_keyboard(),
                parse_mode="HTML",
            )
        else:
            # Fallback если ИИ не ответил
            await message.answer(
                "😕 Извини, я временно недоступен. Попробуй ещё раз позже или напиши в поддержку @chillcreative",
                reply_markup=get_ai_assistant_keyboard(),
                parse_mode="HTML",
            )

    except Exception as e:
        logger.exception(f"AI Assistant error: {e}")
        await message.answer(
            "😕 Что-то пошло не так. Попробуй ещё раз или обратись в поддержку @chillcreative",
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
        "available_models": "Banana Pro, Banana 2, Seedream 4.5, Grok Imagine i2i, Kling 3, Grok Imagine, Veo 3.1, Motion Control",
    }

    # Приветственное сообщение от ИИ
    welcome_ai = """🍌 <b>AI-ассистент</b>

Я помогу с моделями, промптами, настройками и сценариями генерации.

<b>Например, можно спросить:</b>
• какая модель лучше для фотореализма
• что выбрать для видео из фото
• как использовать референсы
• как собрать промпт под fashion / anime / product
• чем отличается Veo от Kling
• как работает Motion Control

<i>Просто напишите вопрос — отвечу по делу и подскажу следующий шаг в боте.</i>"""

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
        "available_models": "Banana Pro, Banana 2, Seedream 4.5, Grok Imagine i2i, Kling 3, Grok Imagine, Veo 3.1",
    }

    welcome_ai = """🍌 <b>AI-ассистент по настройкам</b>

Сейчас я могу помочь выбрать подходящую модель и объяснить опции в меню.

<b>Чем могу помочь:</b>
• подобрать модель под портрет, product, anime или edit
• подсказать формат под TikTok, Reels, Shorts или YouTube
• объяснить разницу между Kling, Grok Imagine и Veo
• рассказать, когда использовать референсы и Motion Control

<i>Напишите вопрос в свободной форме — например: «что лучше для рекламного ролика?»</i>"""

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
        "✅ <b>Фото персонажа загружено!</b>"
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
            f"🚀 <b>Motion Control запущен!</b>"
            f"💰 <code>{cost}</code>🍌\n"
            f"🤖 <code>{mode.upper()}</code>\n"
            f"🆔 <code>{api_task_id}</code>"
            f"Ожидайте результат (1-5 мин)...",
            parse_mode="HTML",
        )
        await state.clear()
    else:
        await add_credits(telegram_id, cost)
        await message.answer("❌ Ошибка запуска. Бананы возвращены.", parse_mode="HTML")


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
                f"🤖 <b>BotAI:</b>{response}",
                reply_markup=get_ai_assistant_keyboard(),
                parse_mode="HTML",
            )
        else:
            # Fallback если ИИ не ответил
            await message.answer(
                "😕 Извини, я временно недоступен. Попробуй ещё раз позже или напиши в поддержку @chillcreative",
                reply_markup=get_ai_assistant_keyboard(),
                parse_mode="HTML",
            )

    except Exception as e:
        logger.exception(f"AI Assistant error: {e}")
        await message.answer(
            "😕 Что-то пошло не так. Попробуй ещё раз или обратись в поддержку @chillcreative",
            reply_markup=get_ai_assistant_keyboard(),
            parse_mode="HTML",
        )
