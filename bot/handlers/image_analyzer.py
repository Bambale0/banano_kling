"""Photo to prompt handler."""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import get_back_keyboard, get_main_menu_button_keyboard
from bot.services.photo_prompt_service import photo_prompt_service
from bot.states import ImageAnalyzerStates

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "photo_to_prompt")
async def photo_to_prompt_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(ImageAnalyzerStates.waiting_for_photo)

    text = (
        "📸 <b>Промпт по фото</b>\n\n"
        "Загрузите изображение — я подробно опишу его для повторной генерации похожего кадра.\n\n"
        "В результате вы получите:\n"
        "• точный prompt на английском\n"
        "• понятную версию на русском\n"
        "• negative prompt\n"
        "• рекомендацию модели\n\n"
        "<i>Лучше загружать чёткое фото без сильного блюра.</i>"
    )

    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("Cannot edit message in photo_to_prompt_handler: %s", e)
        await callback.message.answer(
            text,
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )

    await callback.answer()


@router.message(ImageAnalyzerStates.waiting_for_photo, F.photo)
async def analyze_photo(message: Message, state: FSMContext):
    processing = await message.answer("🔍 Анализирую фото и собираю точный prompt…")

    try:
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_io = await message.bot.download_file(file.file_path)

        image_bytes = image_io.read()
        from bot.handlers.generation import save_uploaded_file

        image_url = save_uploaded_file(image_bytes, "jpg")

        if not image_url:
            await processing.edit_text(
                "❌ Не удалось сохранить фото. Попробуйте загрузить другое изображение.",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return

        result = await photo_prompt_service.analyze_photo(
            image_url=image_url,
            preserve="внешность/объект, композицию, свет, одежду, фон, стиль и цветовую палитру",
            goal="создать максимально похожее изображение по этому референсу",
        )

        prompt_en = result["prompt_en"]
        prompt_ru = result["prompt_ru"]
        negative_prompt = result["negative_prompt"]
        model_hint = result["model_hint"]

        text = (
            "✅ <b>Промпт по фото готов</b>\n\n"
            "<b>Prompt EN:</b>\n"
            f"<code>{prompt_en}</code>\n\n"
            "<b>Описание RU:</b>\n"
            f"{prompt_ru}\n\n"
            "<b>Negative prompt:</b>\n"
            f"<code>{negative_prompt}</code>\n\n"
            "<b>Рекомендация:</b>\n"
            f"{model_hint}"
        )

        await processing.edit_text(
            text,
            reply_markup=get_main_menu_button_keyboard(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await state.clear()

    except Exception as e:
        logger.exception("Photo to prompt analysis failed")
        await processing.edit_text(
            f"❌ Не удалось разобрать фото: {e}",
            reply_markup=get_main_menu_button_keyboard(),
        )
        await state.clear()


@router.message(ImageAnalyzerStates.waiting_for_photo)
async def photo_prompt_wrong_input(message: Message):
    await message.answer(
        "Пожалуйста, отправьте именно фото изображением.",
        reply_markup=get_back_keyboard("back_main"),
    )
