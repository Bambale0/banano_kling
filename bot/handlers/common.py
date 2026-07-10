import logging
import os
from typing import Any as Message
from typing import List, Optional

from vkbottle import BotBlueprint as Blueprint
from vkbottle import Callback, PhotoMessageUploader
from vkbottle.framework.labeler.base import ABCRule
from vkbottle.tools.dev.keyboard import Keyboard

from bot.config import config
from bot.database import (
    add_credits,
    deduct_credits,
    get_or_create_user,
    get_transaction_by_order,
    get_user_credits,
    get_user_settings,
    get_user_stats,
    save_user_settings,
    update_transaction_status,
    update_user_referral_code,
)
from bot.keyboards import (
    get_ai_assistant_keyboard,
    get_back_keyboard,
    get_create_image_keyboard,
    get_create_video_keyboard,
    get_main_menu_keyboard,
    get_main_menu_reply_keyboard,
    get_reference_images_skip_keyboard,
    get_reference_images_upload_keyboard,
    get_video_models_keyboard,
    get_video_params_keyboard,
    get_video_ready_keyboard,
    get_video_type_keyboard,
    merge_with_main_menu_reply,
)
from bot.services.ai_assistant_service import ai_assistant_service
from bot.services.gemini_service import gemini_service
from bot.services.kie_service import kie_service
from bot.services.kling_service import kling_service
from bot.services.preset_manager import preset_manager
from bot.services.tbank_service import tbank_service
from bot.services.yookassa_service import yookassa_service
from bot.states import AdminStates, GenerationStates, PaymentStates, VideoCreationStates
from bot.vk_rules import (
    PayloadEq,
    PayloadStartsWith,
    PeerStateEq,
    PhotoRule,
    StateEq,
    TextStartsWith,
)

logger = logging.getLogger(__name__)

common = Blueprint("common")
# Backwards compatible alias expected by handlers.__init__.py
common_bp = common

# String states for AI assistant (vkbottle FSM uses strings)
AI_MAIN_MENU = "AI_MAIN_MENU"
AI_WAITING_MESSAGE = "AI_WAITING_MESSAGE"
AI_SETTINGS = "AI_SETTINGS"

_user_last_menu = {}


async def safe_set_state(peer_id: int, state):
    """Безопасная установка состояния"""
    try:
        dispenser = _get_state_dispenser()
        if dispenser is None:
            logger.warning(
                f"safe_set_state: no dispenser for peer_id={peer_id}, state={state}"
            )
            return
        current = await dispenser.get(peer_id)
        payload = (
            dict(current.payload)
            if current and getattr(current, "payload", None)
            else {}
        )
        state_key = getattr(state, "value", str(state))
        await dispenser.set(peer_id, state_key, **payload)
        logger.info(f"FSM state set: peer_id={peer_id}, state={state_key}")
    except Exception as e:
        logger.debug(f"safe_set_state failed for {peer_id}: {e}")


def _get_state_dispenser():
    for obj in (
        getattr(common, "bot", None),
        getattr(common, "router", None),
        getattr(common, "labeler", None),
        common,
    ):
        if obj is None:
            continue
        dispenser = getattr(obj, "state_dispenser", None)
        if dispenser is not None:
            return dispenser
    return None


def _get_cast_state_data(message) -> dict:
    """Пытается взять cast state data из сообщения, если vkbottle уже подставил его."""
    casted = getattr(message, "state_peer", None)
    if casted and hasattr(casted, "payload") and isinstance(casted.payload, dict):
        return casted.payload
    return {}


def _current_state_contains(current_state, expected_name: str) -> bool:
    if current_state is None:
        return False
    current_str = str(current_state)
    if expected_name in current_str:
        return True
    current_value = getattr(current_state, "value", None)
    if current_value and expected_name in str(current_value):
        return True
    return False


async def safe_get_data(peer_id: int):
    """Безопасное получение данных"""
    try:
        dispenser = _get_state_dispenser()
        if dispenser is None:
            logger.warning(f"safe_get_data: no dispenser for peer_id={peer_id}")
            return {}
        current = await dispenser.get(peer_id)
        return (
            dict(current.payload)
            if current and getattr(current, "payload", None)
            else {}
        )
    except Exception:
        return {}


async def safe_update_data(peer_id: int, **kwargs):
    """Безопасное обновление данных"""
    try:
        dispenser = _get_state_dispenser()
        if dispenser is None:
            logger.warning(
                f"safe_update_data: no dispenser for peer_id={peer_id}, keys={list(kwargs.keys())}"
            )
            return
        current = await dispenser.get(peer_id)
        state = current.state if current else ""
        data = (
            dict(current.payload)
            if current and getattr(current, "payload", None)
            else {}
        )
        data.update(kwargs)
        await dispenser.set(peer_id, state, **data)
        logger.info(f"FSM data updated: peer_id={peer_id}, keys={list(kwargs.keys())}")
    except Exception as e:
        logger.debug(f"safe_update_data failed for {peer_id}: {e}")


async def safe_clear_state(peer_id: int):
    """Безопасная очистка состояния"""
    try:
        dispenser = _get_state_dispenser()
        if dispenser is None:
            logger.warning(f"safe_clear_state: no dispenser for peer_id={peer_id}")
            return
        await dispenser.delete(peer_id)
    except Exception as e:
        logger.debug(f"safe_clear_state failed for {peer_id}: {e}")


async def get_peer_state(peer_id: int):
    try:
        dispenser = _get_state_dispenser()
        if dispenser is None:
            return None
        current = await dispenser.get(peer_id)
        state_str = current.state if current else None
        logger.info(f"FSM current state: peer_id={peer_id}, state={state_str}")
        return state_str
    except Exception:
        return None


def _state_names_match(current_state, expected_state) -> bool:
    if current_state == expected_state:
        return True
    current_str = str(current_state)
    expected_str = str(expected_state)
    current_name = getattr(current_state, "__name__", None) or getattr(
        current_state, "name", None
    )
    expected_name = getattr(expected_state, "__name__", None) or getattr(
        expected_state, "name", None
    )
    return (
        current_str == expected_str
        or (
            current_name is not None
            and expected_name is not None
            and current_name == expected_name
        )
        or current_str.endswith(expected_str)
        or expected_str.endswith(current_str)
    )


from vkbottle.tools.dev.uploader.photo import PhotoMessageUploader

from bot.utils.media_utils import download_media_bytes


def _save_uploaded_file(file_bytes: bytes, file_ext: str = "png") -> Optional[str]:
    """Сохранить файл в static/uploads и вернуть публичный URL."""
    try:
        import uuid
        from datetime import datetime

        from bot.config import config

        date_str = datetime.now().strftime("%Y%m%d")
        upload_dir = os.path.join("static", "uploads", date_str)
        os.makedirs(upload_dir, exist_ok=True)

        file_id = str(uuid.uuid4())[:8]
        filename = f"{file_id}.{file_ext}"
        filepath = os.path.join(upload_dir, filename)

        with open(filepath, "wb") as f:
            f.write(file_bytes)

        return f"{config.static_base_url}/uploads/{date_str}/{filename}"
    except Exception as e:
        logger.exception("Error saving uploaded file: %s", e)
        return None


async def safe_send_vk_photo(message, image_bytes: bytes, caption: str, keyboard=None):
    """Upload and send photo via VK PhotoMessageUploader when available.

    Falls back to sending a plain link message if upload fails or ctx_api missing.
    """
    try:
        api = getattr(message, "ctx_api", None)
        if api is None or not isinstance(image_bytes, (bytes, bytearray)):
            return False

        # VK messages have upload size limits for photos (~5 MB). If the image
        # is larger, try to compress it to fit before uploading.
        max_size = 5 * 1024 * 1024
        bytes_to_upload = bytes(image_bytes)
        if len(bytes_to_upload) > max_size:
            try:
                import io as _io

                from PIL import Image

                img = Image.open(_io.BytesIO(bytes_to_upload)).convert("RGB")
                quality = 90
                while True:
                    buf = _io.BytesIO()
                    img.save(buf, format="JPEG", quality=quality)
                    data = buf.getvalue()
                    if len(data) <= max_size or quality <= 30:
                        bytes_to_upload = data
                        break
                    quality -= 10
            except Exception:
                logger.exception("Image compression failed")

        uploader = PhotoMessageUploader(api=api)
        attachment = await uploader.upload(bytes_to_upload, peer_id=message.peer_id)
        await message.answer(
            caption, attachment=attachment, keyboard=keyboard, parse_mode="HTML"
        )
        return True
    except Exception:
        logger.exception("VK photo upload failed, falling back to URL message")

    return False


def _set_user_menu(user_id: int, menu: str):
    _user_last_menu[user_id] = menu


def _get_user_menu(user_id: int) -> str:
    return _user_last_menu.get(user_id, "")


def _with_main_menu_reply(inline_keyboard=None):
    """Возвращает переданную inline-клавиатуру; reply-кнопка живет отдельно в главном меню."""
    return (
        inline_keyboard
        if inline_keyboard is not None
        else get_main_menu_reply_keyboard()
    )


@common.on.message(TextStartsWith("/start"))
async def cmd_start(m: Message):
    logger.info(
        f"cmd_start handler triggered for user {m.from_id}, text='{m.text}', peer_id={m.peer_id}"
    )
    logger.info("cmd_start proceeding with /start logic")
    user = await get_or_create_user(m.from_id)

    args = m.text.split()[1:] if len(m.text.split()) > 1 else []

    if args and args[0].startswith("success_"):
        order_id = args[0].replace("success_", "")
        transaction = await get_transaction_by_order(order_id)

        if transaction:
            if transaction.status == "completed":
                await m.answer(
                    f"✅ <b>Оплата уже обработана!</b>\n\n"
                    f"🍌 Ваш баланс: <code>{user.credits}</code> бананов",
                    keyboard=get_main_menu_keyboard(user.credits),
                    parse_mode="HTML",
                )
                return
            elif transaction.status == "pending":
                try:
                    result = await tbank_service.get_state(transaction.payment_id)
                except Exception:
                    result = None

                paid = False
                if result and result.get("Status") == "CONFIRMED":
                    paid = True

                if not paid:
                    try:
                        yk = await yookassa_service.get_payment(transaction.payment_id)
                        if yk and (
                            yk.get("paid")
                            or (yk.get("status") or "").lower()
                            in ("succeeded", "paid", "captured")
                        ):
                            paid = True
                    except Exception:
                        pass

                if paid:
                    await add_credits(m.from_id, transaction.credits)
                    await update_transaction_status(order_id, "completed")
                    user = await get_or_create_user(m.from_id)

                    await m.answer(
                        f"🎉 <b>Оплата успешно обработана!</b>\n\n"
                        f"🍌 Начислено: <code>{transaction.credits}</code> бананов\n"
                        f"💰 Сумма: <code>{transaction.amount_rub}</code> ₽\n\n"
                        f"💎 Ваш баланс: <code>{user.credits}</code> бананов",
                        keyboard=get_main_menu_keyboard(user.credits),
                        parse_mode="HTML",
                    )
                    return
                else:
                    await m.answer(
                        "⏳ <b>Оплата в обработке...</b>\n\n"
                        "Пожалуйста, подождите. Кредиты будут начислены в течение нескольких минут.",
                        keyboard=get_main_menu_keyboard(user.credits),
                        parse_mode="HTML",
                    )
                    return
        else:
            await m.answer(
                "❌ <b>Транзакция не найдена</b>\n\n"
                "Пожалуйста, свяжитесь с поддержкой.",
                keyboard=get_main_menu_keyboard(user.credits),
                parse_mode="HTML",
            )
            return

    elif args and args[0].startswith("fail_"):
        await m.answer(
            "❌ <b>Оплата не была завершена</b>\n\n"
            "Вы можете попробовать снова в любое время.",
            keyboard=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )
        return

    referral_bonus_text = ""
    if args and args[0].startswith("ref_"):
        referral_code = args[0].replace("ref_", "", 1)
        processed = await process_referral(m.from_id, referral_code)
        if processed:
            referral_bonus_text = (
                "\n🎁 <b>Реферальный бонус активирован!</b>\n"
                "Вы получили бонус за регистрацию по приглашению."
            )

    welcome_text = f"""
Хватит просто смотреть — создавай с AI! 🔥

✅ <b>Генерация артов:</b> Пиши промпт — получай шедевр.
✅ <b>Фото-магия:</b> Стилизация и замена объектов в пару кликов.
✅ <b>Видео-продакшн:</b> Делаю ролики из слов и фото.
✅ <b>FX-эффекты:</b> Твои видео станут выглядеть на миллион.

🍌 <b>Ваш баланс:</b> <code>{user.credits}</code> бананов

{referral_bonus_text}

📢 <b>Наш канал:</b> <a href="https://t.me/ai_neir_set">@ai_neir_set</a>

<i>Попробуй прямо сейчас! 👇</i>

⚠️ <b><u>ВАЖНО:</u></b>
Запрещено создавать порнографические материалы. Нарушители блокируются без возврата потраченных бананов. Администрация не несет ответственности за действия пользователей.
"""

    await m.answer(
        "Сначала выберите модель:",
        keyboard=get_create_image_keyboard(),
        parse_mode="HTML",
    )

    _set_user_menu(m.from_id, "main_menu")


@common.on.message(TextStartsWith("/help"))
async def cmd_help(m: Message):
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
• <b>Nano Banana Pro</b> — профессиональное качество, 4K (5🍌)

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

    await m.answer(help_text, keyboard=get_back_keyboard(), parse_mode="HTML")


@common.on.message(PayloadEq("menu_help"))
async def show_help(m: Message):
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
Например: "как сделать крутой логотип?" или "помоги с промптом для космоса"

<b>❓ Или выбери "Тех. поддержка" для связи с нами</b>
"""

    await m.answer(help_text, keyboard=get_back_keyboard(), parse_mode="HTML")


@common.on.message(PayloadEq("back_main"))
async def back_to_main(m: Message):
    await safe_clear_state(m.peer_id)

    user = await get_or_create_user(m.from_id)

    _set_user_menu(m.from_id, "main_menu")

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
        await m.answer(
            welcome_text,
            keyboard=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Cannot edit message: {e}")
        await m.answer(
            welcome_text,
            keyboard=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )


@common.on.message(PayloadEq("menu_balance"))
async def show_balance(m: Message):
    user = await get_or_create_user(m.from_id)
    stats = await get_user_stats(m.from_id)

    balance_text = f"""
💎 <b>Ваш баланс</b>

🍌 Доступно бананов: <code>{stats['credits']}</code>
📊 Всего генераций: <code>{stats['generations']}</code>
💸 Потрачено бананов: <code>{stats['total_spent']}</code>
📅 Дата регистрации: <code>{stats['member_since']}</code>
🎁 Приглашено друзей: <code>{stats.get('referrals_count', 0)}</code>
💰 Заработано на рефералах: <code>{stats.get('referral_earned', 0)}</code>
"""

    await m.answer(
        balance_text,
        keyboard=get_main_menu_keyboard(user.credits),
        parse_mode="HTML",
    )


# Partner program functions removed


@common.on.message(PayloadEq("placeholder_removed_partner"))
async def accept_partner(m: Message):
    await accept_partner_agreement(m.from_id)

    user = await get_or_create_user(m.from_id)
    try:
        if not user.referral_code:
            new_code = await generate_referral_code()
            await update_user_referral_code(m.from_id, new_code)
            user = await get_or_create_user(m.from_id)
    except Exception:
        logger.exception("Failed to ensure referral code on partner accept")

    api = common.api
    group = await api.groups.get_by_id(groups_ids=[api.context.group_id])
    me = group.groups[0]
    referral_code = user.referral_code
    referral_link = (
        f"https://vk.com/im?sel={me.id}&media=&msg={me.screen_name}?start=ref_{referral_code}"
        if referral_code
        else ""
    )

    await m.answer(
        "✅ <b>Партнёрский статус активирован</b>\n\n"
        "Теперь вы получаете денежное вознаграждение за оплату рефералов.\n"
        "Ваш процент зависит от оборота рефералов и обновляется автоматически.",
        keyboard=get_partner_program_keyboard(referral_link, is_partner=True),
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("partner_stats"))
async def partner_stats(m: Message):
    stats = await get_partner_overview(m.from_id)
    text = (
        "📈 <b>Детальная статистика</b>\n\n"
        f"• Всего рефералов: <code>{stats.get('referrals_count', 0)}</code>\n"
        f"• Активных за 7 дней: <code>{stats.get('active_7d', 0)}</code>\n"
        f"• Всего покупок: <code>{stats.get('total_payments', 0)}</code>\n"
        f"• Доход за месяц: <code>{stats.get('monthly_revenue', 0)}</code> ₽\n"
        f"• Новые за сегодня: <code>{stats.get('today_payments', 0)}</code>\n"
        f"• Доход за сегодня: <code>{stats.get('today_revenue', 0)}</code> ₽\n"
    )
    user = await get_or_create_user(m.from_id)
    api = common.api
    group = await api.groups.get_by_id(groups_ids=[api.context.group_id])
    me = group.groups[0]
    referral_code = user.referral_code
    referral_link = (
        f"https://vk.com/im?sel={me.id}&media=&msg={me.screen_name}?start=ref_{referral_code}"
        if referral_code
        else ""
    )

    await m.answer(
        text,
        keyboard=get_partner_program_keyboard(
            referral_link, is_partner=stats.get("is_partner", False)
        ),
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("partner_withdraw"))
async def partner_withdraw(m: Message):
    stats = await get_partner_overview(m.from_id)
    min_withdraw = 2000
    user = await get_or_create_user(m.from_id)
    api = common.api
    group = await api.groups.get_by_id(groups_ids=[api.context.group_id])
    me = group.groups[0]
    referral_code = user.referral_code
    referral_link = (
        f"https://vk.com/im?sel={me.id}&media=&msg={me.screen_name}?start=ref_{referral_code}"
        if referral_code
        else ""
    )

    await m.answer(
        "🎟️ <b>Вывод заработка</b>\n\n"
        f"Доступно: <code>{stats.get('balance_rub', 0)}</code> ₽\n"
        f"Минимальная сумма вывода: <code>{min_withdraw}</code> ₽\n\n"
        "Для оформления вывода напишите реквизиты и сумму в поддержку или добавим форму следующим шагом.",
        keyboard=get_partner_program_keyboard(
            referral_link, is_partner=stats.get("is_partner", False)
        ),
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("menu_settings"))
async def show_settings(m: Message):
    from bot.keyboards import get_settings_keyboard_with_ai

    _set_user_menu(m.from_id, "settings")

    db_settings = await get_user_settings(m.from_id)

    await m.state.update_data(
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

    await m.answer(
        settings_text,
        keyboard=get_settings_keyboard_with_ai(
            db_settings["preferred_model"],
            db_settings["preferred_video_model"],
            db_settings["preferred_i2v_model"],
            db_settings.get("image_service", "nanobanana"),
        ),
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("menu_motion_control"))
async def show_motion_control_menu(m: Message):
    from bot.database import get_user_credits
    from bot.keyboards import get_motion_control_keyboard

    user_credits = await get_user_credits(m.from_id)

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

    await m.answer(
        motion_text,
        keyboard=get_motion_control_keyboard(),
        parse_mode="HTML",
    )


@common.on.message(PayloadStartsWith("model_"))
async def handle_image_model_select(m: Message):
    import json

    payload_dict = json.loads(m.payload)
    button_value = payload_dict.get("button", "")
    current_service = button_value.replace("model_", "")
    data = await safe_get_data(m.peer_id)
    current_ratio = data.get("current_ratio", "1:1")
    service_names = {
        "banana_2": "Banana 2",
        "nano_banana_pro": "Nano Banana Pro",
        "seedream45": "Seedream 4.5",
    }
    service_display = service_names.get(current_service, current_service)
    await safe_update_data(m.peer_id, current_service=current_service)
    await m.answer(
        f"🖼 <b>Модель:</b> {service_display}\n"
        f"<b>Формат:</b> {current_ratio}\n\n"
        "Выберите формат или загрузите рефы:",
        keyboard=get_create_image_keyboard(
            current_service=current_service, current_ratio=current_ratio
        ),
        parse_mode="HTML",
    )


@common.on.message(PayloadStartsWith("img_ratio_"))
async def handle_image_ratio_select(m: Message):
    import json

    payload_dict = json.loads(m.payload)
    button_value = payload_dict.get("button", "")
    ratio = button_value.replace("img_ratio_", "").replace("_", ":")
    data = await safe_get_data(m.peer_id)
    current_service = data.get("current_service")
    if not current_service:
        await m.answer(
            "Сначала выберите модель:",
            keyboard=get_create_image_keyboard(),
            parse_mode="HTML",
        )

        return
    service_names = {
        "banana_2": "Banana 2",
        "nano_banana_pro": "Nano Banana Pro",
        "seedream45": "Seedream 4.5",
    }
    service_display = service_names.get(current_service, current_service)
    await safe_update_data(m.peer_id, current_ratio=ratio)
    await m.answer(
        f"🖼 <b>Модель:</b> {service_display}\n"
        f"<b>Формат:</b> {ratio}\n\n"
        "Выберите или загрузите рефы:",
        keyboard=get_create_image_keyboard(
            current_service=current_service, current_ratio=ratio
        ),
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("img_ref_skip_new"))
async def handle_img_ref_skip_new_vk(m: Message):
    await safe_set_state(m.peer_id, "waiting_for_input")
    data = await safe_get_data(m.peer_id)
    current_service = data.get("current_service")
    current_ratio = data.get("current_ratio")
    if not current_service or not current_ratio:
        await m.answer(
            "Сначала выберите модель и формат:",
            keyboard=get_create_image_keyboard(),
            parse_mode="HTML",
        )

        return
    await m.answer(
        f"✍️ Отправьте текстовый промпт для генерации изображения.\n\n"
        f"Модель: <code>{current_service}</code>\n"
        f"Формат: <code>{current_ratio}</code>\n"
        f"Референсов: <code>{len(data.get('reference_images', []))}</code>",
        keyboard=get_main_menu_reply_keyboard(),
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("video_no_refs"))
async def handle_video_no_refs(m: Message):
    try:
        await safe_set_state(m.peer_id, GenerationStates.waiting_for_video_prompt)
    except Exception:
        pass
    await m.answer(
        "✍️ Отправьте текстовый промпт для генерации видео без референсов.",
        keyboard=get_main_menu_reply_keyboard(),
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("video_continue"))
async def handle_video_continue(m: Message):
    data = await safe_get_data(m.peer_id)
    v_type = data.get("v_type", "text")
    if v_type == "imgtxt":
        await safe_set_state(m.peer_id, GenerationStates.waiting_for_video_start_image)
        await m.answer(
            "🖼 Отправьте стартовое изображение для image-to-video.",
            keyboard=get_main_menu_reply_keyboard(),
            parse_mode="HTML",
        )
        return
    if v_type == "video":
        await safe_set_state(m.peer_id, GenerationStates.waiting_for_reference_video)
        await m.answer(
            "🎬 Отправьте референсное видео.",
            keyboard=get_main_menu_reply_keyboard(),
            parse_mode="HTML",
        )
        return
    await safe_set_state(m.peer_id, GenerationStates.waiting_for_video_prompt)
    await m.answer(
        "✍️ Отправьте текстовый промпт для генерации видео.",
        keyboard=get_main_menu_reply_keyboard(),
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("img_ref_continue_new"))
async def handle_img_ref_continue_new_vk(m: Message):
    data = await safe_get_data(m.peer_id)
    current_state = await get_peer_state(m.peer_id)
    refs: List[str] = data.get("reference_images", [])
    logger.info(
        "handle_img_ref_continue_new_vk: peer_id=%s state=%s refs=%s",
        m.peer_id,
        current_state,
        len(refs),
    )

    if _state_names_match(current_state, "uploading_reference_images"):
        if refs:
            current_service = data.get("current_service")
            current_ratio = data.get("current_ratio", "1:1")
            if not current_service:
                await m.answer(
                    "Сначала выберите модель:",
                    keyboard=get_create_image_keyboard(),
                    parse_mode="HTML",
                )
                return
            service_names = {
                "banana_2": "Banana 2",
                "nano_banana_pro": "Nano Banana Pro",
                "seedream45": "Seedream 4.5",
            }
            service_display = service_names.get(current_service, current_service)
            await safe_update_data(
                m.peer_id, current_service=current_service, current_ratio=current_ratio
            )
            await safe_set_state(m.peer_id, "waiting_for_input")
            await m.answer(
                f"✍️ <b>Отправьте промпт</b>\n\n"
                f"🖼 <b>Модель:</b> {service_display}\n"
                f"📐 <b>Формат:</b> {current_ratio}\n"
                f"📎 <b>Референсов:</b> {len(refs)}",
                keyboard=_with_main_menu_reply(),
                parse_mode="HTML",
            )
            return

        await m.answer(
            f"📎 Загрузка референсов продолжается.\n\nЗагружено: <code>{len(refs)}/14</code>\n"
            "Отправьте ещё фото или нажмите '✅ Продолжить'/'⏭ Пропустить'.",
            keyboard=get_reference_images_upload_keyboard(len(refs), 14, "new"),
            parse_mode="HTML",
        )
        return

    if refs:
        current_service = data.get("current_service")
        current_ratio = data.get("current_ratio", "1:1")
        if not current_service:
            await m.answer(
                "Сначала выберите модель:",
                keyboard=get_create_image_keyboard(),
                parse_mode="HTML",
            )
            return
        service_names = {
            "banana_2": "Banana 2",
            "nano_banana_pro": "Nano Banana Pro",
            "seedream45": "Seedream 4.5",
        }
        service_display = service_names.get(current_service, current_service)
        await safe_set_state(m.peer_id, GenerationStates.waiting_for_input)
        await m.answer(
            f"✍️ <b>Отправьте промпт</b>\n\n"
            f"🖼 <b>Модель:</b> {service_display}\n"
            f"📐 <b>Формат:</b> {current_ratio}\n"
            f"📎 <b>Референсов:</b> {len(refs)}",
            keyboard=_with_main_menu_reply(),
            parse_mode="HTML",
        )
        return

    await safe_set_state(m.peer_id, GenerationStates.uploading_reference_images)
    await safe_update_data(m.peer_id, reference_images=[])
    await m.answer(
        "📎 Отправьте одно или несколько фото-референсов для image-to-image.\nПосле загрузки нажмите '✅ Продолжить' или '⏭ Пропустить'.",
        keyboard=get_reference_images_upload_keyboard(0, 14, "new"),
        parse_mode="HTML",
    )


@common.on.message(PayloadStartsWith("v_type_"))
async def handle_video_type_select(m: Message):
    import json

    payload_dict = json.loads(m.payload)
    button_value = payload_dict.get("button", "")
    v_type = button_value.replace("v_type_", "")
    await safe_update_data(m.peer_id, v_type=v_type)
    if v_type == "imgtxt":
        await safe_set_state(m.peer_id, "waiting_for_image")
        await m.answer(
            "🖼 Загрузите стартовое фото для видео:",
            keyboard=get_reference_images_upload_keyboard(0, 1, "imgtxt"),
            parse_mode="HTML",
        )
    elif v_type == "video":
        await safe_set_state(m.peer_id, "waiting_for_video")
        await m.answer(
            "🎬 Загрузите референсное видео:",
            keyboard=get_reference_images_upload_keyboard(0, 1, "video"),
            parse_mode="HTML",
        )
    else:  # text
        await safe_set_state(m.peer_id, VideoCreationStates.video_model_select)
        await m.answer(
            "📝 Выберите модель для Текст → Видео:",
            keyboard=get_video_models_keyboard(),
            parse_mode="HTML",
        )


@common.on.message(PayloadStartsWith("v_model_"))
async def handle_video_model_select(m: Message):
    import json

    payload_dict = json.loads(m.payload)
    button_value = payload_dict.get("button", "")
    current_model = button_value.replace("v_model_", "")
    data = await safe_get_data(m.peer_id)
    v_type = data.get("v_type", "text")
    current_ratio = data.get("current_video_ratio", "16:9")
    current_duration = data.get("current_duration", 5)
    await safe_update_data(m.peer_id, current_model=current_model)
    await m.answer(
        f"🎬 Параметры видео (тип: {v_type})\n\nНастройте ratio/duration:",
        keyboard=get_video_params_keyboard(current_duration, current_ratio),
        parse_mode="HTML",
    )


@common.on.message(PayloadStartsWith("ratio_"))
async def handle_video_ratio_select(m: Message):
    import json

    payload_dict = json.loads(m.payload)
    button_value = payload_dict.get("button", "")
    ratio = button_value.replace("ratio_", "").replace("_", ":")
    data = await safe_get_data(m.peer_id)
    v_type = data.get("v_type", "text")
    current_model = data.get("current_model", "v3_std")
    current_duration = data.get("current_duration", 5)
    await safe_update_data(m.peer_id, current_video_ratio=ratio)
    await m.answer(
        f"Параметры сохранены (ratio: {ratio}). Готовы к генерации?",
        keyboard=get_video_ready_keyboard(),
        parse_mode="HTML",
    )


@common.on.message(PayloadStartsWith("video_dur_"))
async def handle_video_duration_select(m: Message):
    import json

    payload_dict = json.loads(m.payload)
    button_value = payload_dict.get("button", "")
    duration = int(button_value.replace("video_dur_", ""))
    data = await safe_get_data(m.peer_id)
    v_type = data.get("v_type", "text")
    current_model = data.get("current_model", "v3_std")
    current_ratio = data.get("current_video_ratio", "16:9")
    await safe_update_data(m.peer_id, current_duration=duration)
    await m.answer(
        f"Параметры сохранены (duration: {duration}s). Готовы к генерации?",
        keyboard=get_video_ready_keyboard(),
        parse_mode="HTML",
    )


# Helper для скачивания по прямой URL (обход VK photo вложенности)
async def download_from_url(url: str) -> Optional[bytes]:
    """Download bytes from direct URL."""
    if not url:
        return None
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
                logger.warning(f"Download failed: {resp.status} for {url}")
                return None
    except Exception as e:
        logger.exception(f"Download from URL failed: %s", e)
        return None


@common.on.message(PeerStateEq("waiting_for_image", get_peer_state))
async def handle_waiting_for_image(m: Message):
    """Handle image upload or remind for motion control flow."""
    data = await safe_get_data(m.peer_id)
    v_type = data.get("v_type")

    # Download photo
    photo_attachment = None
    for att in m.attachments:
        att_type = str(getattr(att, "type", None)).lower()
        if att_type.endswith("photo"):
            photo_attachment = att
            break

    if not photo_attachment:
        await m.answer(
            "📸 <b>Ожидаю фото персонажа</b>\n\n"
            "VK не распознал вложение как фото. Отправьте именно фото (не документ/стикер).",
            keyboard=_with_main_menu_reply(),
            parse_mode="HTML",
        )
        return

    logger.info(
        "handle_waiting_for_image called: peer_id=%s attachments=%s photo_resolved=%s",
        m.peer_id,
        [getattr(att, "type", None) for att in m.attachments],
        bool(photo_attachment),
    )

    try:
        # Extract max_url like in reference handler (VK photo nested structure)
        photo = getattr(photo_attachment, "photo", None) or photo_attachment
        sizes = getattr(photo, "sizes", None) or []
        logger.info("Photo sizes: %s", len(sizes))

        max_url = next(
            (s.url for s in sizes if getattr(s, "type", None) == "max"), None
        )
        if not max_url and sizes:
            max_size = max(
                sizes,
                key=lambda s: getattr(s, "height", 0) * getattr(s, "width", 0),
            )
            max_url = getattr(max_size, "url", None)

        if not max_url:
            raise ValueError("No downloadable photo URL found in VK attachment")

        logger.info("Using photo URL: %s", max_url)

        image_bytes = await download_from_url(max_url)
        if not image_bytes:
            raise ValueError("Failed to download image bytes")

        image_url = _save_uploaded_file(image_bytes, "png")
        if image_url:
            await safe_update_data(m.peer_id, v_image_url=image_url)
            logger.info("Motion image saved: %s", image_url)
        else:
            await m.answer("❌ Не удалось сохранить фото.")
            return

        if v_type == "imgtxt":
            await safe_update_data(m.peer_id, v_image_url=image_url)
            await safe_set_state(m.peer_id, "waiting_for_video_prompt")
            await m.answer(
                "✅ Фото сохранено. Отправьте промпт для видео:",
                keyboard=get_video_ready_keyboard(),
            )
        else:
            # regular image gen refs
            refs = data.get("reference_images", [])
            refs.append(image_url)
            await safe_update_data(m.peer_id, reference_images=refs)
            len_refs = len(refs)
            if len_refs >= 14:
                await safe_set_state(m.peer_id, GenerationStates.waiting_for_input)
                await m.answer(
                    f"Референсы готовы ({len_refs}). Промпт:",
                    keyboard=_with_main_menu_reply(),
                )
            else:
                await m.answer(
                    f"Добавлено ({len_refs}/14). Ещё?",
                    keyboard=get_reference_images_upload_keyboard(len_refs, 14),
                )

    except Exception as e:
        logger.exception("Failed to process motion image: %s", e)
        await m.answer("❌ Не удалось обработать фото.")


@common.on.message(PeerStateEq("waiting_for_video", get_peer_state))
async def handle_waiting_for_video(m: Message):
    """Handle video upload or remind for motion control flow."""
    data = await safe_get_data(m.peer_id)
    v_type = data.get("v_type")

    if not getattr(m, "attachments", None):
        await m.answer(
            "📹 <b>Ожидаю видео-референс</b>\n\n"
            "• 📎 Файл → MP4 (3-30 сек, <50MB)\n"
            "• НЕ видео-плеер!\n\n"
            "<i>Движения перенесутся на фото</i>",
            keyboard=_with_main_menu_reply(),
            parse_mode="HTML",
        )
        return

    attachment = m.attachments[0]
    att_type = str(getattr(attachment, "type", None)).lower()
    logger.info("Motion video attachment type: %s", att_type)

    if att_type == "video":
        await m.answer(
            "❌ Плеер не поддерживается.\n📎 Файл MP4!",
            keyboard=_with_main_menu_reply(),
            parse_mode="HTML",
        )
        return

    if att_type != "doc":
        await m.answer("📹 Только MP4-файл (📎 Файл).")
        return

    doc = getattr(attachment, "doc", attachment)
    ext = getattr(doc, "ext", "").lower()
    size = getattr(doc, "size", 0)
    doc_url = getattr(doc, "url", None)
    logger.info("Doc fields: url=%s ext=%s size=%d bytes", doc_url, ext, size)

    if ext not in ("mp4", "mov", "avi", "mkv", "webm"):
        await m.answer(f"📎 Видео (MP4/MOV). Получен .{ext}")
        return

    if size > 100 * 1024 * 1024:
        await m.answer(f"❌ {size//1024//1024}MB >100MB")
        return

    if not doc_url:
        await m.answer("❌ Нет URL видео (VK limit). <50MB публичный MP4.")
        return

    await safe_update_data(m.peer_id, v_video_url=doc_url)
    logger.info("Motion video URL set: %s (%dB)", doc_url, size)

    await safe_set_state(m.peer_id, "waiting_for_video_prompt")
    video_model = data.get("video_model", "v26_motion_std")
    mode_display = "720p" if "std" in video_model else "1080p"
    cost = data.get("cost", 8)
    await m.answer(
        f"✅ Видео готово! ({size//1024//1024}MB)\n\n"
        f"📸 Фото: ✅\n"
        f"📹 Видео: <code>{doc_url}</code>\n"
        f"💎 {mode_display}\n"
        f"💰 {cost}🍌\n\n"
        f"✍️ Промпт:",
        keyboard=_with_main_menu_reply(),
        parse_mode="HTML",
    )


@common.on.message(PeerStateEq("waiting_for_video_prompt", get_peer_state))
async def handle_video_prompt(m: Message):

    current_state = await get_peer_state(m.peer_id)
    if not _current_state_contains(current_state, "waiting_for_video_prompt"):
        return False
    if not getattr(m, "text", None):
        await m.answer(
            "✍️ Отправьте текстовый промпт для генерации видео.",
            keyboard=_with_main_menu_reply(),
        )
        return

    data = await safe_get_data(m.peer_id)
    v_type = data.get("v_type", "text")
    video_model = data.get("video_model", "v3_std")
    current_ratio = data.get("current_video_ratio", "16:9")
    current_duration = data.get("current_duration", 5)
    image_url = data.get("v_image_url")
    video_url = data.get("v_video_url")

    # Calculate cost
    mode = (
        "pro"
        if "pro" in (data.get("video_model") or data.get("current_model", "v3_std"))
        else "std"
    )
    duration = data.get("current_duration", 5)
    cost = 8  # default for video
    user = await get_or_create_user(m.from_id)
    if user.credits < cost:
        await m.answer(f"❌ Недостаточно бананов: нужно {cost}🍌")
        await safe_clear_state(m.peer_id)
        return
    await deduct_credits(m.from_id, cost)
    await safe_clear_state(m.peer_id)

    await m.answer(
        "⏳ Генерирую видео... Результат придет автоматически.",
        keyboard=get_main_menu_keyboard(user.credits),
    )

    try:
        webhook_url = f"{config.static_base_url}/kie_webhook"
        user_id_str = str(m.from_id)
        if v_type == "video" and image_url and video_url:
            # Kling 2.6 Motion Control via Kie
            mode = "720p" if "std" in video_model else "1080p"
            task = await kie_service.generate_kling_motion_control(
                prompt=m.text,
                input_urls=[image_url],
                video_urls=[video_url],
                character_orientation="video",
                mode=mode,
                callback_url=webhook_url,
                user_id=user_id_str,
            )
        else:
            mode = "pro" if "pro" in video_model else "std"
            task = await kling_service.generate_video_generation(
                prompt=m.text,
                mode=mode,
                duration=current_duration,
                aspect_ratio=current_ratio,
                image_url=image_url,
                callback_url=webhook_url,
                user_id=user_id_str,
            )

        if not task:
            await m.answer(
                "❌ Не удалось создать задачу генерации видео.",
                keyboard=_with_main_menu_reply(),
            )
            return

        logger.info(f"Kie task created: {task.get('task_id')}, waiting for webhook...")

    except Exception as e:
        logger.exception("Video generation failed: %s", e)
        await m.answer("❌ Ошибка генерации видео.", keyboard=_with_main_menu_reply())


@common.on.message(PayloadEq("menu_support"))
async def show_support(m: Message):
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

    await m.answer(
        support_text,
        keyboard=get_support_keyboard(),
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("menu_history"))
async def show_history(m: Message):
    from bot.database import get_user_stats
    from bot.keyboards import get_main_menu_keyboard

    user = await get_or_create_user(m.from_id)
    stats = await get_user_stats(m.from_id)

    history_text = f"""
📋 <b>История</b>

📊 Всего генераций: <code>{stats['generations']}</code>
💸 Потрачено бананов: <code>{stats['total_spent']}</code>
💎 Текущий баланс: <code>{user.credits}</code>🍌
📅 Дата регистрации: <code>{stats['member_since']}</code>

<i>Детальная история скоро будет доступна!</i>
"""

    try:
        await m.answer(
            history_text,
            keyboard=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Cannot edit message: {e}")
        await m.answer(
            history_text,
            keyboard=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )


@common.on.message(PayloadEq("motion_control_std"))
async def start_motion_control_std(m: Message):
    from bot.database import get_user_credits
    from bot.services.preset_manager import preset_manager

    user_credits = await get_user_credits(m.from_id)
    cost = preset_manager.get_video_cost("v26_motion_std", 5)

    if user_credits < cost:
        await m.answer(
            f"❌ Недостаточно бананов: нужно {cost}🍌",
            keyboard=get_motion_control_keyboard(),
        )
        return

    await safe_set_state(m.peer_id, "waiting_for_image")
    await safe_update_data(
        m.peer_id,
        generation_type="motion_control",
        video_model="v26_motion_std",
        cost=cost,
    )

    await m.answer(
        f"🎬 <b>Motion Control Standard</b>\n\n"
        f"Стоимость: {cost}🍌\n\n"
        f"📸 <b>Шаг 1:</b> Загрузи фото персонажа,\n"
        f"которое нужно анимировать\n\n"
        "Это может быть:\n"
        f"• Фото человека\n"
        f"• Фото персонажа\n"
        f"• Любое изображение для анимации",
        keyboard=_with_main_menu_reply(),
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("motion_control_pro"))
async def start_motion_control_pro(m: Message):
    from bot.database import get_user_credits
    from bot.services.preset_manager import preset_manager

    user_credits = await get_user_credits(m.from_id)
    cost = preset_manager.get_video_cost("v26_motion_pro", 5)

    if user_credits < cost:
        await m.answer(
            f"❌ Недостаточно бананов: нужно {cost}🍌",
            keyboard=get_motion_control_keyboard(),
        )
        return

    await safe_set_state(m.peer_id, "waiting_for_image")
    await safe_update_data(
        m.peer_id,
        generation_type="motion_control",
        video_model="v26_motion_pro",
        cost=cost,
    )

    await m.answer(
        f"💎 <b>Motion Control Pro</b>\n\n"
        f"Стоимость: {cost}🍌\n\n"
        f"📸 <b>Шаг 1:</b> Загрузи фото персонажа,\n"
        f"которое нужно анимировать\n\n"
        "Это может быть:\n"
        f"• Фото человека\n"
        f"• Фото персонажа\n"
        f"• Любое изображение для анимации",
        keyboard=_with_main_menu_reply(),
        parse_mode="HTML",
    )


@common.on.message(PayloadStartsWith("settings_model_"))
async def handle_settings_model(m: Message):
    model_type = m.payload.replace("settings_model_", "")

    await save_user_settings(m.from_id, preferred_model=model_type)

    await m.state.update_data(preferred_model=model_type)

    model_name = "Flash" if model_type == "flash" else "Pro"

    from bot.keyboards import get_settings_keyboard_with_ai

    data = await m.state.get_data()
    current_video_model = data.get("preferred_video_model", "v3_std")
    current_i2v_model = data.get("preferred_i2v_model", "v3_std")
    current_image_service = data.get("image_service", "nanobanana")

    await m.answer(
        f"✅ Изображение: {model_name}",
        keyboard=get_settings_keyboard_with_ai(
            model_type,
            current_video_model,
            current_i2v_model,
            image_service=current_image_service,
        ),
        parse_mode="HTML",
    )


@common.on.message(PayloadStartsWith("settings_video_"))
async def handle_settings_video_model(m: Message):
    video_model = m.payload.replace("settings_video_", "")

    await save_user_settings(m.from_id, preferred_video_model=video_model)

    await m.state.update_data(preferred_video_model=video_model)

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

    data = await m.state.get_data()
    current_model = data.get("preferred_model", "flash")
    current_i2v_model = data.get("preferred_i2v_model", "v3_std")
    current_image_service = data.get("image_service", "nanobanana")

    await m.answer(
        f"✅ Видео: {model_name}",
        keyboard=get_settings_keyboard_with_ai(
            current_model,
            video_model,
            current_i2v_model,
            image_service=current_image_service,
        ),
        parse_mode="HTML",
    )


@common.on.message(PayloadStartsWith("settings_i2v_"))
async def handle_settings_i2v_model(m: Message):
    i2v_model = m.payload.replace("settings_i2v_", "")

    await save_user_settings(m.from_id, preferred_i2v_model=i2v_model)

    await m.state.update_data(preferred_i2v_model=i2v_model)

    i2v_names = {
        "v3_std": "Std",
        "v3_pro": "Pro",
        "v3_omni_std": "Omni Std",
        "v3_omni_pro": "Omni Pro",
    }

    model_name = i2v_names.get(i2v_model, i2v_model)

    from bot.keyboards import get_settings_keyboard_with_ai

    data = await m.state.get_data()
    current_model = data.get("preferred_model", "flash")
    current_video_model = data.get("preferred_video_model", "v3_std")
    current_image_service = data.get("image_service", "nanobanana")

    await m.answer(
        f"✅ Фото→Видео: {model_name}",
        keyboard=get_settings_keyboard_with_ai(
            current_model,
            current_video_model,
            i2v_model,
            image_service=current_image_service,
        ),
        parse_mode="HTML",
    )


@common.on.message(PayloadStartsWith("settings_service_"))
async def handle_settings_service(m: Message):
    service = m.payload.replace("settings_service_", "")

    await save_user_settings(m.from_id, image_service=service)

    await m.state.update_data(image_service=service)

    service_names = {
        "nanobanana": "🍌 Nano Banana",
        "novita": "✨ FLUX.2 Pro (Novita)",
        "banana_pro": "💎 Nano Banana Pro",
        "nano_banana_pro": "💎 Nano Banana Pro",
        "seedream": "🎨 Seedream (Novita)",
        "z_image_turbo": "🚀 Z-Image Turbo LoRA",
    }

    service_name = service_names.get(service, service)

    from bot.keyboards import get_settings_keyboard_with_ai

    data = await m.state.get_data()
    current_model = data.get("preferred_model", "flash")
    current_video_model = data.get("preferred_video_model", "v3_std")
    current_i2v_model = data.get("preferred_i2v_model", "v3_std")

    await m.answer(
        f"✅ Сервис: {service_name}",
        keyboard=get_settings_keyboard_with_ai(
            current_model, current_video_model, current_i2v_model, image_service=service
        ),
        parse_mode="HTML",
    )


@common.on.message(PayloadStartsWith("back_cat_"))
async def back_to_category(m: Message):
    from bot.handlers.generation import show_category
    from bot.services.preset_manager import preset_manager

    category = m.payload.replace("back_cat_", "")

    presets = preset_manager.get_category_presets(category)
    categories = preset_manager.get_categories()

    if not presets:
        return

    user_credits = 0
    try:
        user_credits = await get_user_credits(m.from_id)
    except:
        pass

    from bot.keyboards import get_category_keyboard

    await m.answer(
        f"📂 <b>{categories[category]['name']}</b>\n"
        f"📝 {categories[category].get('description', '')}\n\n"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n\n"
        f"Выберите пресет:",
        keyboard=get_category_keyboard(category, presets, user_credits),
        parse_mode="HTML",
    )


# AI Assistant handlers
@common.on.message(PayloadEq("create_video_new"))
async def handle_create_video_new(m: Message):
    await safe_update_data(m.peer_id, video_step=True)
    await safe_set_state(m.peer_id, VideoCreationStates.video_type_select)
    await m.answer(
        "🎬 <b>Создать видео</b>\n\nВыберите тип генерации:",
        keyboard=get_video_type_keyboard(),
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("v_type_text"))
async def video_type_text(m: Message):
    """Тип: Текст → Видео → выбор модели"""
    await safe_update_data(m.peer_id, v_type="text", video_step="model")
    await safe_set_state(m.peer_id, VideoCreationStates.video_model_select)
    await m.answer(
        "📝 <b>Текст → Видео</b>\n\nВыберите модель:",
        keyboard=get_video_models_keyboard(),
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("v_type_imgtxt"))
async def video_type_imgtxt(m: Message):
    """Тип: Фото + Текст → Видео → выбор модели + загрузка фото"""
    await safe_update_data(m.peer_id, v_type="imgtxt")
    await safe_set_state(
        m.peer_id, "waiting_for_image"
    )  # or VideoCreationStates.waiting_for_v_image if defined
    await m.answer(
        "🖼 <b>Фото + Текст → Видео</b>\n\nЗагрузите стартовое фото (референс):",
        keyboard=get_reference_images_upload_keyboard(
            0, 1, "video_img"
        ),  # single photo
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("v_type_video"))
async def video_type_video(m: Message):
    """Тип: Видео + Текст → Видео → выбор модели + загрузка видео"""
    await safe_update_data(m.peer_id, v_type="video", video_step="model")
    await safe_set_state(m.peer_id, VideoCreationStates.video_model_select)
    await m.answer(
        "🎬 <b>Видео + Текст → Видео</b>\n\nВыберите модель, затем загрузите референсное видео:",
        keyboard=get_video_models_keyboard(),
        parse_mode="HTML",
    )


@common.on.message(PayloadStartsWith("v_model_"))
async def video_model_select(m: Message):
    """Выбор модели → параметры"""
    model = m.payload.replace("v_model_", "")
    data = await safe_get_data(m.peer_id)
    await safe_update_data(m.peer_id, current_model=model, video_step="params")
    await safe_set_state(m.peer_id, VideoCreationStates.video_params_select)
    await m.answer(
        f"🤖 <b>Модель: {model}</b>\n\nНастройте параметры видео:",
        keyboard=get_video_params_keyboard(),
        parse_mode="HTML",
    )


@common.on.message(PayloadStartsWith("video_dur_") | PayloadStartsWith("ratio_"))
async def video_params_update(m: Message):
    """Обновление параметров → промпт"""
    data = await safe_get_data(m.peer_id)
    await safe_update_data(m.peer_id, video_step="prompt")
    await safe_set_state(m.peer_id, VideoCreationStates.waiting_video_prompt)
    v_type = data.get("v_type", "text")
    model = data.get("current_model", "kling_3_std")
    duration = data.get("current_duration", 5)
    ratio = data.get("current_video_ratio", "16:9")
    type_text = "Текст → Видео" if v_type == "text" else "Фото/Видео + Текст → Видео"
    await m.answer(
        f"⚙️ <b>Параметры сохранены</b>\n\n"
        f"📝 Тип: {type_text}\n"
        f"🤖 Модель: {model}\n"
        f"⏱ Длительность: {duration}с\n"
        f"📐 Формат: {ratio}\n\n"
        f"✍️ <b>Введите промпт:</b>\n\n"
        f"Опишите сцену подробно:\n"
        f"• Действие/движение\n"
        f"• Камера/ракурс\n"
        f"• Стиль/атмосфера",
        keyboard=get_main_menu_reply_keyboard(),
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("video_ready_prompt"))
async def video_ready_prompt(m: Message):
    """Готов к промпту → waiting_video_prompt"""
    await safe_set_state(m.peer_id, VideoCreationStates.waiting_video_prompt)
    data = await safe_get_data(m.peer_id)
    v_type = data.get("v_type", "text")
    model = data.get("current_model", "kling_3_std")
    duration = data.get("current_duration", 5)
    ratio = data.get("current_video_ratio", "16:9")
    type_text = "Текст → Видео" if v_type == "text" else "Фото/Видео + Текст → Видео"
    await m.answer(
        f"⚙️ <b>Параметры готовы</b>\n\n"
        f"📝 Тип: {type_text}\n"
        f"🤖 Модель: {model}\n"
        f"⏱ Длительность: {duration}с\n"
        f"📐 Формат: {ratio}\n\n"
        f"✍️ <b>Введите промпт:</b>",
        keyboard=get_main_menu_reply_keyboard(),
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("create_image_refs_new"))
async def create_image_refs_new(m: Message):
    await safe_clear_state(m.peer_id)
    await safe_update_data(
        m.peer_id,
        reference_images=[],
    )
    user = await get_or_create_user(m.from_id)
    user_credits = user.credits
    await m.answer(
        f"🖼 <b>Создание фото</b>\n\n"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n\n"
        f"<b>Шаг 1: Выбор модели и формата</b>\n\n"
        f"Выберите модель:",
        keyboard=get_create_image_keyboard(),
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("img_ref_upload_new"))
async def handle_img_ref_upload_new(m: Message):
    logger.info("img_ref_upload_new handler triggered for peer_id=%s", m.peer_id)
    await safe_update_data(
        m.peer_id,
        reference_images=[],
    )
    await safe_set_state(m.peer_id, "uploading_reference_images")
    await m.answer(
        "📎 <b>Загрузка референсных изображений</b>\n\n"
        "Отправьте фото (рекомендуем квадрат 1024x1024).\n"
        "Макс. 14 шт.\n\n"
        "✅ Готово? Нажмите «✅ Продолжить»",
        keyboard=get_reference_images_upload_keyboard(0, 14, "new"),
        parse_mode="HTML",
    )


@common.on.message(PayloadEq("menu_topup"))
async def menu_topup(m: Message):
    from bot.handlers.payments import show_topup_menu

    await show_topup_menu(m)


@common.on.message(PayloadEq("menu_ai_assistant"))
async def open_ai_assistant_main(m: Message):
    await m.state.set_state(AI_WAITING_MESSAGE)
    await m.state.update_data(ai_mode="main_menu")

    user = await get_or_create_user(m.from_id)

    context = {
        "user_credits": user.credits,
        "menu_location": "главное меню",
        "available_models": "Flash (1🍌), Pro (2🍌), видео Std/Pro/Omni",
    }

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

    await m.answer(welcome_ai, keyboard=get_ai_assistant_keyboard(), parse_mode="HTML")


@common.on.message(StateEq(AI_WAITING_MESSAGE))
async def handle_ai_assistant_message(m: Message):
    # This handler only runs when state == AI_WAITING_MESSAGE
    from bot.database import get_user_credits, get_user_settings
    from bot.keyboards import get_ai_assistant_keyboard

    data = await m.state.get_data()
    ai_mode = data.get("ai_mode", "main_menu")

    user = await get_or_create_user(m.from_id)
    db_settings = await get_user_settings(m.from_id)

    context = {
        "user_credits": user.credits,
        "preferred_model": db_settings["preferred_model"],
        "preferred_video_model": db_settings["preferred_video_model"],
        "image_service": db_settings.get("image_service", "nanobanana"),
        "menu_location": "главное меню" if ai_mode == "main_menu" else "настройки",
    }

    try:
        response = await ai_assistant_service.get_assistant_response(
            user_message=m.text, context=context
        )

        if response:
            await m.answer(
                f"🍌 <b>Banana Boom AI:</b>\n\n{response}",
                keyboard=get_ai_assistant_keyboard(),
                parse_mode="HTML",
            )
        else:
            await m.answer(
                "😕 Извини, я временно недоступен. Попробуй ещё раз позже или напиши в поддержку @S_k7222",
                keyboard=get_ai_assistant_keyboard(),
                parse_mode="HTML",
            )

    except Exception as e:
        logger.exception(f"AI Assistant error: {e}")
        await m.answer(
            "😕 Что-то пошло не так. Попробуй ещё раз или обратись в поддержку @S_k7222",
            keyboard=get_ai_assistant_keyboard(),
            parse_mode="HTML",
        )


@common.on.message(PayloadEq("back_video_type"))
async def back_to_video_type(m: Message):
    await safe_clear_state(m.peer_id)
    await m.answer(
        "🎬 <b>Создать видео</b>\n\nВыберите тип генерации:",
        keyboard=get_video_type_keyboard(),
        parse_mode="HTML",
    )


@common.on.message(PayloadStartsWith("ignore_"))
@common.on.message(PayloadEq("ignore"))
async def handle_ignore_callback(m: Message):
    # Ignore this callback - do nothing
    pass
