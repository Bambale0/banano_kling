"""Photo to prompt handler."""

import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.keyboards import (
    get_back_keyboard,
    get_main_menu_button_keyboard,
    get_photo_prompt_result_keyboard,
)
from bot.services.photo_prompt_service import photo_prompt_service
from bot.states import ImageAnalyzerStates

logger = logging.getLogger(__name__)
router = Router()


def _clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _escape_clip_text(text: str, escaped_limit: int) -> str:
    raw = str(text or "")
    escaped = html.escape(raw)
    if len(escaped) <= escaped_limit:
        return escaped

    suffix = "…"
    low = 0
    high = len(raw)
    best = suffix
    while low <= high:
        mid = (low + high) // 2
        candidate = html.escape(raw[:mid].rstrip() + suffix)
        if len(candidate) <= escaped_limit:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best


def _format_photo_prompt_result_text(result: dict) -> str:
    prompt_en = (result.get("prompt_en") or "").strip()
    prompt_ru = (result.get("prompt_ru") or "").strip()
    negative_prompt = (result.get("negative_prompt") or "").strip()
    model_hint = (result.get("model_hint") or "").strip()
    provider = (result.get("provider") or "").strip()

    provider_note = ""
    if provider and provider != "gpt-5.4":
        provider_note = f"\n\n<i>Fallback: {html.escape(provider)}</i>"

    return (
        "✅ <b>Промпт по фото готов</b>\n\n"
        "<b>Prompt RU:</b>\n"
        f"<pre>{_escape_clip_text(prompt_ru or '—', 900)}</pre>\n\n"
        "<b>Prompt EN:</b>\n"
        f"<pre>{_escape_clip_text(prompt_en or '—', 1400)}</pre>\n\n"
        "<b>Negative prompt:</b>\n"
        f"<pre>{_escape_clip_text(negative_prompt or '—', 450)}</pre>\n\n"
        "<b>Рекомендация:</b>\n"
        f"{_escape_clip_text(model_hint or '—', 500)}"
        f"{provider_note}"
    )


async def _safe_edit_or_answer(processing: Message, source_message: Message, text: str, reply_markup=None, parse_mode=None, disable_web_page_preview=None) -> None:
    try:
        await processing.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
    except TelegramBadRequest as e:
        error_text = str(e).lower()
        if "message to edit not found" in error_text or "there is no text in the message to edit" in error_text:
            await source_message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
            return
        raise


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
        if not (isinstance(e, TelegramBadRequest) and "there is no text in the message to edit" in str(e).lower()):
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
            await _safe_edit_or_answer(
                processing,
                message,
                "❌ Не удалось сохранить фото. Попробуйте загрузить другое изображение.",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return

        result = await photo_prompt_service.analyze_photo(
            image_url=image_url,
            preserve="внешность/объект, композицию, свет, одежду, фон, стиль и цветовую палитру",
            goal="создать максимально похожее изображение по этому референсу",
        )

        prompt_en = (result.get("prompt_en") or "").strip()
        prompt_ru = (result.get("prompt_ru") or "").strip()
        negative_prompt = (result.get("negative_prompt") or "").strip()
        text = _format_photo_prompt_result_text(result)

        try:
            await processing.delete()
        except Exception:
            pass

        await message.answer(
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=get_photo_prompt_result_keyboard(
                prompt_en=prompt_en,
                prompt_ru=prompt_ru,
                negative_prompt=negative_prompt,
            ),
        )
        full_prompt_text = (
            "PROMPT RU\n"
            "---------\n"
            f"{prompt_ru or '—'}\n\n"
            "PROMPT EN\n"
            "---------\n"
            f"{prompt_en or '—'}\n\n"
            "NEGATIVE PROMPT\n"
            "---------------\n"
            f"{negative_prompt or '—'}\n\n"
            "РЕКОМЕНДАЦИЯ\n"
            "------------\n"
            f"{result.get('model_hint') or '—'}\n"
        )
        await message.answer_document(
            document=BufferedInputFile(
                full_prompt_text.encode("utf-8"),
                filename="photo_prompt_full.txt",
            ),
            caption="📝 Полный prompt: RU + EN + negative",
        )
        await state.clear()

    except Exception as e:
        logger.exception("Photo to prompt analysis failed")
        await _safe_edit_or_answer(
            processing,
            message,
            _clip_text(f"❌ Не удалось разобрать фото: {e}", 700),
            reply_markup=get_main_menu_button_keyboard(),
        )
        await state.clear()


@router.message(ImageAnalyzerStates.waiting_for_photo)
async def photo_prompt_wrong_input(message: Message):
    await message.answer(
        "Пожалуйста, отправьте именно фото изображением.",
        reply_markup=get_back_keyboard("back_main"),
    )
