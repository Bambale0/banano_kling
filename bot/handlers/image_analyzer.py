import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.database import get_or_create_user
from bot.keyboards import get_back_keyboard, get_main_menu_keyboard
from bot.services.image_analyzer_service import image_analyzer_service
from bot.states import ImageAnalyzerStates

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "photo_to_prompt")
async def photo_to_prompt_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Фото=Промпт' в главном меню"""
    await state.set_state(ImageAnalyzerStates.waiting_for_photo)

    user = await get_or_create_user(callback.from_user.id)

    try:
        await callback.message.edit_text(
            "📸 <b>Анализ фото -> Промпт</b>\n"
            f"🍌 Баланс: <code>{user.credits}</code> бананов\n\n"
            "<b>Что делает этот режим</b>\n"
            "Отправьте фото, и бот соберёт по нему аккуратный промпт для дальнейшей генерации.\n\n"
            "Обычно хорошо распознаются:\n"
            "• персонажи, лица и одежда\n"
            "• поза, композиция и ракурс\n"
            "• свет, фон и общее настроение\n\n"
            "<i>Анализ бесплатный.</i>",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Cannot edit message in photo_to_prompt_handler: {e}")
        await callback.message.answer(
            "📸 <b>Анализ фото -> Промпт</b>\n"
            f"🍌 Баланс: <code>{user.credits}</code> бананов\n\n"
            "<b>Что делает этот режим</b>\n"
            "Отправьте фото, и бот соберёт по нему аккуратный промпт для дальнейшей генерации.\n\n"
            "Обычно хорошо распознаются:\n"
            "• персонажи, лица и одежда\n"
            "• поза, композиция и ракурс\n"
            "• свет, фон и общее настроение\n\n"
            "<i>Анализ бесплатный.</i>",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(ImageAnalyzerStates.waiting_for_photo, F.photo)
async def analyze_photo(message: Message, state: FSMContext):
    """Анализирует загруженное фото и возвращает промпт"""
    try:
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file.file_path)

        # Анализируем фото
        prompt = image_analyzer_service.analyze_image(image_bytes.read())
        prompt = re.sub(r"<[^>]*>", "", prompt)
        prompt = prompt.strip()

        user = await get_or_create_user(message.from_user.id)

        short_caption = (
            "✅ <b>Промпт готов</b>\n" f"🍌 Баланс: <code>{user.credits}</code> бананов"
        )
        await message.answer_photo(
            photo=photo.file_id,
            caption=short_caption,
            reply_markup=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )

        max_len = 3800
        if len(prompt) > max_len:
            prompt = prompt[:max_len] + "... (промпт укорочен для Telegram лимита)"

        await message.answer(
            "📋 <b>Готовый промпт</b>\n"
            f"<code>{prompt}</code>\n\n"
            "<i>Можете сразу использовать его в меню «Создать фото».</i>",
            reply_markup=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"Photo analysis error: {e}")
        await message.answer(
            "Не получилось проанализировать фото.\n"
            "Попробуйте отправить другое изображение с более чётким объектом в кадре.",
            reply_markup=get_back_keyboard("back_main"),
        )

    await state.clear()
