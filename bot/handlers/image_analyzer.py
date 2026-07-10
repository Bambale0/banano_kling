import logging
import re
from typing import Any as Message

from vkbottle import BotBlueprint as Blueprint

try:
    from vkbottle.filter import F
except Exception:
    pass  # F imported from vkbottle.filter


try:
    from vkbottle.types import Callback
except Exception:
    try:
        from vkbottle_types.codegen.objects import Callback
    except Exception:

        class Callback:
            pass


from bot.database import get_or_create_user
from bot.keyboards import get_back_keyboard, get_main_menu_keyboard
from bot.services import image_analyzer_service
from bot.states import ImageAnalyzerStates
from bot.vk_rules import PayloadEq

logger = logging.getLogger(__name__)
image_analyzer_bp = Blueprint("image_analyzer")


from bot.utils.media_utils import download_media_bytes


@image_analyzer_bp.on.message(PayloadEq("photo_to_prompt"))
async def photo_to_prompt_handler(c: Callback):
    """Обработчик кнопки 'Фото=Промпт' в главном меню"""
    dispenser = _get_state_dispenser()  # from common
    if dispenser:
        await dispenser.set(c.peer_id, ImageAnalyzerStates.waiting_for_photo.value)
    else:
        logger.warning("No state dispenser for photo_to_prompt")

    user = await get_or_create_user(c.from_id)

    text = f"📸 <b>Анализ фото → Промпт</b>\n\n"
    text += f"🍌 Баланс: <code>{user.credits}</code>🍌\n\n"
    text += "Отправьте фото для анализа.\n"
    text += "🤖 ИИ создаст точный промпт для повторения:\n"
    text += "• Лица и люди\n"
    text += "• Позы и одежда\n"
    text += "• Освещение и фон\n\n"
    text += "<i>Это бесплатно!</i>"

    await c.answer(text, keyboard=get_back_keyboard("back_main"), parse_mode="HTML")


@image_analyzer_bp.on.message(state=ImageAnalyzerStates.waiting_for_photo)
async def analyze_photo(m: Message, state):
    """Анализирует загруженное фото и возвращает промпт"""
    if not m.attachments or m.attachments[0].type != "photo":
        await m.answer("📸 Отправьте фото для анализа.")
        return

    photo = m.attachments[0]
    try:
        image_bytes = await download_media_bytes(photo)
    except Exception as e:
        logger.error(f"Photo download error: {e}")
        await m.answer("❌ Ошибка загрузки фото. Попробуйте другое.")
        return

    try:
        prompt = image_analyzer_service.analyze_image(image_bytes)
        prompt = re.sub(r"<[^>]*>", "", prompt).strip()
    except Exception as e:
        logger.error(f"Image analysis error: {e}")
        await m.answer("❌ Ошибка анализа фото.")
        await state.clear()
        return

    user = await get_or_create_user(m.from_id)

    short_caption = (
        f"✅ <b>Готовый промпт!</b>\n\n🍌 Баланс: <code>{user.credits}</code>🍌"
    )

    await m.answer_photo(
        photo=photo,
        message=short_caption,
        keyboard=get_main_menu_keyboard(user.credits),
        parse_mode="HTML",
    )

    # Отправляем полный промпт без обрезки — пользователь просил убрать лимит
    await m.answer(
        f"📋 <code>{prompt}</code>\n\n<i>Скопируйте промпт и используйте в 'Создать фото'!</i>",
        keyboard=get_main_menu_keyboard(user.credits),
        parse_mode="HTML",
    )

    await state.clear()
