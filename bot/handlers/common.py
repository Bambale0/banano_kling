import logging
import re
import uuid

import aiosqlite
from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.config import config
from bot.database import (
    DATABASE_PATH,
    accept_partner_agreement,
    create_partner_withdrawal,
    get_or_create_user,
    get_partner_overview,
    get_recent_partner_withdrawals,
    get_referral_stats,
    get_user_settings,
    get_user_stats,
    process_referral,
    save_user_settings,
    update_partner_withdrawal_status,
)
from bot.image_models import get_image_model_config, resolve_image_model
from bot.keyboards import (
    get_ai_assistant_keyboard,
    get_back_keyboard,
    get_main_menu_keyboard,
    get_partner_consent_keyboard,
    get_partner_program_keyboard,
    get_referral_keyboard,
)
from bot.services.jump_finance_service import JumpFinanceError, jump_finance_service
from bot.services.preset_manager import preset_manager
from bot.states import (
    AdminStates,
    GenerationStates,
    PartnerWithdrawalStates,
    PaymentStates,
)

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


def _build_welcome_text(credits: int, referral_bonus_text: str = "") -> str:
    bonus_block = f"{referral_bonus_text}\n\n" if referral_bonus_text else ""
    return (
        "🏠 <b>Главное меню</b>\n\n"
        "Хватит просто смотреть, пора создавать с AI.\n\n"
        "<b>Что можно сделать:</b>\n"
        "• генерировать изображения по промпту\n"
        "• редактировать фото и работать с референсами\n"
        "• создавать видео из текста, фото и видео\n"
        "• анимировать персонажей через Motion Control\n\n"
        f"🍌 <b>Ваш баланс:</b> <code>{credits}</code> бананов\n\n"
        f"{bonus_block}"
        '📢 <b>Наш канал:</b> <a href="https://t.me/ai_neir_set">@ai_neir_set</a>\n\n'
        "<i>Выберите нужный режим ниже.</i>\n\n"
        "⚠️ <b>Важно:</b>\n"
        "Запрещено создавать порнографические материалы. За нарушение доступ к боту может быть ограничен без возврата потраченных бананов."
    )


def _mask_card(card_number: str) -> str:
    digits = re.sub(r"\D", "", card_number or "")
    if len(digits) < 4:
        return "****"
    return f"**** **** **** {digits[-4:]}"


def _normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("8") and len(digits) == 11:
        digits = f"7{digits[1:]}"
    if len(digits) != 11 or not digits.startswith("7"):
        raise ValueError("Телефон должен быть в формате +79991234567")
    return f"+{digits}"


def _split_full_name(full_name: str) -> str:
    normalized = re.sub(r"\s+", " ", (full_name or "").strip())
    if len(normalized.split(" ")) < 2:
        raise ValueError("Укажите минимум фамилию и имя")
    return normalized


async def _sync_partner_withdrawals(user_id: int) -> None:
    if not config.has_jump_finance:
        return
    withdrawals = await get_recent_partner_withdrawals(user_id, limit=10)
    for withdrawal in withdrawals:
        if not withdrawal.get("external_payment_id"):
            continue
        if withdrawal.get("status") in {"completed", "failed", "cancelled"}:
            continue
        try:
            payment = await jump_finance_service.get_payment(
                withdrawal["external_payment_id"]
            )
            status = payment.get("status") or {}
            status_id = status.get("id")
            status_title = status.get("title")
            internal_status = {
                1: "completed",
                2: "failed",
                3: "processing",
                4: "requested",
                5: "failed",
                6: "cancelled",
                7: "processing",
                8: "processing",
            }.get(status_id, "processing")
            await update_partner_withdrawal_status(
                withdrawal["id"],
                status=internal_status,
                status_title=status_title,
                external_status_id=status_id,
                error_message=(payment.get("error") or {}).get("detail")
                if isinstance(payment.get("error"), dict)
                else None,
            )
        except Exception:
            logger.exception("Failed to sync partner withdrawal %s", withdrawal["id"])


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
                # Проверяем статус у провайдера — поддерживаем Т-Банк и Crypto Bot
                try:
                    # T-Bank проверка
                    result = await tbank_service.get_state(transaction.payment_id)
                except Exception:
                    result = None

                paid = False
                # T-Bank: Status == CONFIRMED
                if result and result.get("Status") == "CONFIRMED":
                    paid = True

                # Если не T-Bank или не подтверждён — пробуем Crypto Bot
                if not paid and transaction.provider == "cryptobot":
                    try:
                        from bot.services.cryptobot_service import cryptobot_service

                        invoice = await cryptobot_service.get_invoice(
                            transaction.payment_id
                        )
                        if invoice and (invoice.get("status") or "").lower() == "paid":
                            paid = True
                    except Exception:
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

    welcome_text = _build_welcome_text(user.credits, referral_bonus_text)

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
• Banana Pro / Banana 2 / GPT Image 2 / Seedream
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
📖 <b>Помощь бота</b>

<b>💡 Что ты можешь спросить у ИИ-ассистента:</b>

Я — ИИ-ассистент в этом боте. Ты можешь написать мне ЛЮБОЙ вопрос, и я помогу!

🖼 <b>Генерация изображений:</b>
• Какую модель выбрать для фотореализма?
• Как написать хороший промпт для аниме?
• Чем отличается GPT Image 2 от Banana Pro?

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
Например: "как сделать крутой логотип?" или "помоги с промптом для космоса"

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

    welcome_text = _build_welcome_text(user.credits)

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
🎁 Приглашено друзей: <code>{stats.get('referrals_count', 0)}</code>
💰 Заработано на рефералах: <code>{stats.get('referral_earned', 0)}</code>
"""

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
async def show_partner(callback: types.CallbackQuery, state: FSMContext):
    """Показывает партнёрскую программу."""
    await state.clear()
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
    await _sync_partner_withdrawals(user_id)
    user = await get_or_create_user(user_id)
    stats = await get_partner_overview(user_id)
    withdrawals = await get_recent_partner_withdrawals(user_id, limit=3)

    bot = target.bot
    me = await bot.get_me()
    referral_code = user.referral_code or ""
    referral_link = (
        f"https://t.me/{me.username}?start=ref_{referral_code}" if referral_code else ""
    )

    tier = stats.get("tier", "basic")
    percent = stats.get("percent", 30)
    recent_lines = []
    for item in withdrawals:
        status_title = item.get("status_title") or item.get("status") or "unknown"
        recent_lines.append(
            f"• {item.get('amount_rub', 0)} ₽ · {item.get('card_mask') or item.get('method') or 'карта'} · <code>{status_title}</code>"
        )
    recent_text = (
        "\n".join(recent_lines)
        if recent_lines
        else "• Пока нет созданных заявок на вывод"
    )

    text = (
        "💼 <b>Партнёрская программа</b>\n\n"
        "Здесь вы можете отслеживать рефералов, начисления и заявки на вывод.\n"
        "Юридически значимые условия размещены в публичной оферте.\n\n"
        f"🔗 Ваша ссылка: <code>{referral_link or 'Ссылка появится после активации'}</code>\n"
        f"👥 Всего рефералов: <code>{stats.get('referrals_count', 0)}</code>\n"
        f"🧾 Всего оплат: <code>{stats.get('total_payments', 0)}</code>\n"
        f"💰 Баланс к выводу: <code>{stats.get('balance_rub', 0)}</code> ₽\n"
        f"💸 Уже выведено: <code>{stats.get('withdrawn_rub', 0)}</code> ₽\n"
        f"🏷 Уровень: <code>{tier}</code> · <code>{percent}%</code>\n\n"
        "<b>Ставки партнёрской программы:</b>\n"
        "• 30% — базовый уровень\n"
        "• 35% — от 100 000 ₽ оборота рефералов\n"
        "• 50% — от 1 000 000 ₽ оборота рефералов\n\n"
        "<b>Как это работает:</b>\n"
        "• пользователь переходит по вашей ссылке\n"
        "• регистрируется и закрепляется за вами\n"
        "• после первой оплаты начисляется вознаграждение\n"
        "• активным партнёрам начисляется денежный бонус в ₽\n\n"
        "<b>Последние заявки на вывод:</b>\n"
        f"{recent_text}"
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
        "✅ <b>Партнёрский статус активирован</b>\n\n"
        "Теперь вы участвуете в партнёрской программе и получаете вознаграждение за оплаты рефералов.\n"
        "Процент зависит от общего оборота и обновляется автоматически.",
        reply_markup=get_partner_program_keyboard(referral_link, is_partner=True),
        parse_mode="HTML",
    )
    await callback.answer("Партнёрская программа активирована")


@router.callback_query(F.data == "partner_stats")
async def partner_stats(callback: types.CallbackQuery):
    """Показывает детальную статистику партнёра."""
    await _sync_partner_withdrawals(callback.from_user.id)
    stats = await get_partner_overview(callback.from_user.id)
    text = (
        "📈 <b>Детальная статистика</b>\n\n"
        f"• Всего рефералов: <code>{stats.get('referrals_count', 0)}</code>\n"
        f"• Активных за 7 дней: <code>{stats.get('active_7d', 0)}</code>\n"
        f"• Всего оплат: <code>{stats.get('total_payments', 0)}</code>\n"
        f"• Оборот за месяц: <code>{stats.get('monthly_revenue', 0)}</code> ₽\n"
        f"• Оплат сегодня: <code>{stats.get('today_payments', 0)}</code>\n"
        f"• Оборот сегодня: <code>{stats.get('today_revenue', 0)}</code> ₽\n"
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
async def partner_withdraw(callback: types.CallbackQuery, state: FSMContext):
    """Запускает вывод партнёрского заработка."""
    stats = await get_partner_overview(callback.from_user.id)
    min_withdraw = config.PARTNER_MIN_WITHDRAWAL_RUB

    if not stats.get("is_partner"):
        await callback.answer(
            "Сначала активируйте партнёрскую программу", show_alert=True
        )
        return
    if not config.has_jump_finance:
        await callback.answer(
            "Автовыплаты пока не настроены в окружении",
            show_alert=True,
        )
        return
    if stats.get("balance_rub", 0) < min_withdraw:
        await callback.answer(
            f"Минимальная сумма вывода: {min_withdraw} ₽",
            show_alert=True,
        )
        return

    await callback.message.edit_text(
        "🎟️ <b>Вывод заработка</b>\n\n"
        f"Доступно к выводу: <code>{stats.get('balance_rub', 0)}</code> ₽\n"
        f"Минимальная сумма: <code>{min_withdraw}</code> ₽\n\n"
        "Шаг 1 из 4.\n"
        "Введите сумму вывода в рублях без копеек или с копейками.",
        reply_markup=get_back_keyboard("menu_partner"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(PartnerWithdrawalStates.waiting_amount)


@router.message(PartnerWithdrawalStates.waiting_amount)
async def partner_withdraw_amount(message: types.Message, state: FSMContext):
    stats = await get_partner_overview(message.from_user.id)
    min_withdraw = config.PARTNER_MIN_WITHDRAWAL_RUB
    try:
        amount = float(message.text.replace(",", ".").strip())
    except Exception:
        await message.answer(
            "Введите сумму числом, например <code>2500</code>.", parse_mode="HTML"
        )
        return

    if amount < min_withdraw:
        await message.answer(
            f"Минимальная сумма вывода: <code>{min_withdraw}</code> ₽.",
            parse_mode="HTML",
        )
        return
    if amount > float(stats.get("balance_rub", 0)):
        await message.answer(
            f"Недостаточно средств. Доступно: <code>{stats.get('balance_rub', 0)}</code> ₽.",
            parse_mode="HTML",
        )
        return

    await state.update_data(partner_withdraw_amount=round(amount, 2))
    await state.set_state(PartnerWithdrawalStates.waiting_full_name)
    await message.answer(
        "Шаг 2 из 4.\n\n"
        "Введите ФИО получателя полностью.\n"
        "Пример: <code>Иванов Иван Иванович</code>",
        reply_markup=get_back_keyboard("menu_partner"),
        parse_mode="HTML",
    )


@router.message(PartnerWithdrawalStates.waiting_full_name)
async def partner_withdraw_full_name(message: types.Message, state: FSMContext):
    try:
        full_name = _split_full_name(message.text)
    except ValueError as e:
        await message.answer(str(e))
        return

    await state.update_data(partner_withdraw_full_name=full_name)
    await state.set_state(PartnerWithdrawalStates.waiting_phone)
    await message.answer(
        "Шаг 3 из 4.\n\n"
        "Введите номер телефона получателя в формате <code>+79991234567</code>.",
        reply_markup=get_back_keyboard("menu_partner"),
        parse_mode="HTML",
    )


@router.message(PartnerWithdrawalStates.waiting_phone)
async def partner_withdraw_phone(message: types.Message, state: FSMContext):
    try:
        phone = _normalize_phone(message.text)
    except ValueError as e:
        await message.answer(str(e))
        return

    await state.update_data(partner_withdraw_phone=phone)
    await state.set_state(PartnerWithdrawalStates.waiting_card)
    await message.answer(
        "Шаг 4 из 4.\n\n"
        "Введите номер банковской карты РФ без пробелов или с пробелами.\n"
        "Пример: <code>5469 5500 5321 9652</code>",
        reply_markup=get_back_keyboard("menu_partner"),
        parse_mode="HTML",
    )


@router.message(PartnerWithdrawalStates.waiting_card)
async def partner_withdraw_card(message: types.Message, state: FSMContext):
    data = await state.get_data()
    digits = re.sub(r"\D", "", message.text or "")
    if len(digits) < 16 or len(digits) > 19:
        await message.answer("Номер карты должен содержать от 16 до 19 цифр.")
        return

    amount = float(data["partner_withdraw_amount"])
    full_name = data["partner_withdraw_full_name"]
    phone = data["partner_withdraw_phone"]
    card_mask = _mask_card(digits)

    await message.answer(
        "⏳ Создаю выплату...\n"
        "Проверяю исполнителя и отправляю заявку в платёжный сервис."
    )

    try:
        contractor = await jump_finance_service.upsert_contractor(
            phone=phone,
            full_name=full_name,
        )
        payment = await jump_finance_service.create_payment(
            contractor_id=int(contractor["id"]),
            amount_rub=amount,
            card_number=digits,
            customer_payment_id=str(uuid.uuid4()),
            service_name=config.JUMP_FINANCE_PAYOUT_SERVICE_NAME,
            payment_purpose=config.JUMP_FINANCE_PAYOUT_PURPOSE,
        )
        status = payment.get("status") or {}
        requisite = payment.get("requisite") or {}
        internal_status = {
            1: "completed",
            2: "failed",
            3: "processing",
            4: "requested",
            5: "failed",
            6: "cancelled",
            7: "processing",
            8: "processing",
        }.get(status.get("id"), "processing")
        stored_status = (
            "requested"
            if internal_status in {"failed", "cancelled"}
            else internal_status
        )
        withdrawal_id = await create_partner_withdrawal(
            telegram_id=message.from_user.id,
            amount_rub=amount,
            method="bank_card",
            requisites=card_mask,
            recipient_name=full_name,
            phone=phone,
            card_mask=card_mask,
            external_payment_id=str(payment.get("id")),
            external_contractor_id=int(contractor["id"]),
            external_requisite_id=requisite.get("id"),
            external_status_id=status.get("id"),
            status_title=status.get("title"),
            status=stored_status,
        )
        if withdrawal_id and internal_status in {"failed", "cancelled"}:
            await update_partner_withdrawal_status(
                withdrawal_id,
                status=internal_status,
                status_title=status.get("title"),
                external_status_id=status.get("id"),
                error_message="Выплата была отклонена сразу после создания",
            )
        await state.clear()
        await message.answer(
            "✅ <b>Заявка на вывод создана</b>\n\n"
            f"Сумма: <code>{amount}</code> ₽\n"
            f"Карта: <code>{card_mask}</code>\n"
            f"Статус: <code>{status.get('title') or 'создана'}</code>\n"
            f"ID выплаты: <code>{payment.get('id')}</code>\n\n"
            "Обновлённый статус можно посмотреть в разделе партнёрки.",
            reply_markup=get_back_keyboard("menu_partner"),
            parse_mode="HTML",
        )
    except JumpFinanceError as e:
        await state.clear()
        await message.answer(
            f"❌ Не удалось создать выплату.\n\n<code>{str(e)}</code>",
            reply_markup=get_back_keyboard("menu_partner"),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Partner withdrawal payout failed")
        await state.clear()
        await message.answer(
            "❌ Не удалось создать выплату из-за внутренней ошибки.",
            reply_markup=get_back_keyboard("menu_partner"),
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
        image_service=resolve_image_model(
            db_settings.get("image_service", "banana_pro")
        ),
    )

    settings_text = """
⚙️ <b>Настройки</b>

🖼 Изображения:
• Banana Pro / Banana 2 / GPT Image 2
• Seedream 5.0 Lite / Seedream 4.5

🎬 Текст→Видео:
• Kling 3 Std / Kling 3 Pro / Runway / Grok Imagine

🖼→🎬 Фото→Видео:
• Kling 3 Std / Kling 3 Pro / Seedance 2.0 / Runway
"""

    await callback.message.edit_text(
        settings_text,
        reply_markup=get_settings_keyboard_with_ai(
            db_settings["preferred_model"],
            db_settings["preferred_video_model"],
            db_settings["preferred_i2v_model"],
            resolve_image_model(db_settings.get("image_service", "banana_pro")),
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

💰 Баланс: {user_credits}🍌

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
@s_k7222

Мы ответим вам в ближайшее время!
"""

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

    history_text = f"""
📋 <b>История</b>

📊 Всего генераций: <code>{stats['generations']}</code>
💸 Потрачено бананов: <code>{stats['total_spent']}</code>
💎 Текущий баланс: <code>{user.credits}</code>🍌
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
        f"🎬 <b>Motion Control Standard</b>"
        f"Стоимость: {cost}🍌"
        f"📸 <b>Шаг 1:</b> Загрузи фото персонажа,\n"
        f"которое нужно анимировать"
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
        f"💎 <b>Motion Control Pro</b>"
        f"Стоимость: {cost}🍌"
        f"📸 <b>Шаг 1:</b> Загрузи фото персонажа,\n"
        f"которое нужно анимировать"
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
        "runway": "Runway",
        "grok_imagine": "Grok Imagine",
        "seedance2": "Seedance 2.0",
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
        "seedance2": "Seedance 2.0",
        "runway": "Runway",
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
    """Обработка выбора сервиса для генерации изображений."""
    service = resolve_image_model(callback.data.replace("settings_service_", ""))

    # Сохраняем выбор сервиса в БД
    await save_user_settings(callback.from_user.id, image_service=service)

    # Сохраняем в состояние
    await state.update_data(image_service=service)

    # Названия сервисов
    service_name = get_image_model_config(service)["settings_label"]

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
                f"🍌 <b>Banana Boom AI:</b>{response}",
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
        "available_models": "Banana Pro, Banana 2, GPT Image 2, Seedream, Kling 3 (Std/Pro/Omni)",
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
   - Banana / GPT Image 2 / Seedream - генерация изображений

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
                f"🍌 <b>Banana Boom AI:</b>{response}",
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
