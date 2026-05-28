import asyncio
import html
import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.database import get_or_create_user
from bot.keyboards import get_back_keyboard, get_main_menu_keyboard
from bot.services.image_analyzer_service import image_analyzer_service
from bot.states import ImageAnalyzerStates

logger = logging.getLogger(__name__)
router = Router()


PHOTO_TO_PROMPT_TEXT = (
    "📸 <b>Анализ фото → Промпт</b>\n"
    "🍌 Баланс: <code>{credits}</code>🍌\n\n"
    "Отправьте фото для анализа.\n"
    "🤖 ИИ создаст точный промпт для повторения:\n"
    "• Лица и люди\n"
    "• Позы и одежда\n"
    "• Освещение и фон\n\n"
    "<i>Это бесплатно!</i>"
)


def _build_prompt_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🆕 Новый промпт", callback_data="photo_to_prompt"
                )
            ],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main")],
        ]
    )


@router.callback_query(F.data == "photo_to_prompt")
async def photo_to_prompt_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Фото=Промпт' в главном меню"""
    await state.set_state(ImageAnalyzerStates.waiting_for_photo)

    user = await get_or_create_user(callback.from_user.id)
    text = PHOTO_TO_PROMPT_TEXT.format(credits=user.credits)

    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Cannot edit message in photo_to_prompt_handler: {e}")
        await callback.message.answer(
            text,
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
        user = await get_or_create_user(message.from_user.id)

        await message.answer(
            "🔎 Анализирую фото. Это может занять до минуты, результат пришлю сюда.",
            reply_markup=get_back_keyboard("back_main"),
        )
        asyncio.create_task(
            _send_photo_prompt_result(
                message=message,
                image_bytes=image_bytes.read(),
                photo_file_id=photo.file_id,
                user_credits=user.credits,
            )
        )
        await state.clear()

    except Exception as e:
        logger.error(f"Photo analysis start error: {e}")
        await message.answer(
            "❌ Ошибка загрузки фото. Попробуйте другое изображение.",
            reply_markup=get_back_keyboard("back_main"),
        )
        await state.clear()


async def _send_photo_prompt_result(
    message: Message,
    image_bytes: bytes,
    photo_file_id: str,
    user_credits: int,
) -> None:
    """Runs slow image analysis outside the webhook response path."""
    try:
        prompt = await asyncio.to_thread(
            image_analyzer_service.analyze_image, image_bytes
        )
        prompt = re.sub(r"<[^>]*>", "", prompt).strip()

        if not prompt or prompt.lower().startswith("ошибка анализа:"):
            logger.warning(f"Photo analysis returned error text: {prompt[:300]}")
            await message.answer(
                "❌ Ошибка анализа фото. Попробуйте другое изображение.",
                reply_markup=get_back_keyboard("back_main"),
            )
            return

        short_caption = (
            f"✅ <b>Готовый промпт!</b>\n"
            f"🍌 Баланс: <code>{user_credits}</code>🍌"
        )
        await message.answer_photo(
            photo=photo_file_id,
            caption=short_caption,
            reply_markup=get_main_menu_keyboard(user_credits),
            parse_mode="HTML",
        )

        max_len = 3800
        if len(prompt) > max_len:
            prompt = prompt[:max_len] + "... (промпт укорочен для Telegram лимита)"

        escaped_prompt = html.escape(prompt)
        prompt_text = (
            "📋 <b>Промпт</b>\n"
            f"<code>{escaped_prompt}</code>\n\n"
            "<i>Нажмите на текст выше, чтобы скопировать его в Telegram, или удерживайте сообщение.</i>"
        )

        try:
            await message.answer(
                prompt_text,
                reply_markup=_build_prompt_result_keyboard(),
                parse_mode="HTML",
            )
        except TelegramBadRequest as e:
            logger.warning(f"Prompt message send failed with HTML formatting: {e}")
            await message.answer(
                f"Промпт:\n\n{prompt}",
                reply_markup=_build_prompt_result_keyboard(),
            )

    except Exception as e:
        logger.error(f"Photo analysis error: {e}")
        await message.answer(
            "❌ Ошибка анализа фото. Попробуйте другое изображение.",
            reply_markup=get_back_keyboard("back_main"),
        )
