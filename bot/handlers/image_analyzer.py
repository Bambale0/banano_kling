"""Photo to prompt handler."""

import asyncio
import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.config import config
from bot.keyboards import (
    get_back_keyboard,
    get_main_menu_button_keyboard,
    get_photo_prompt_result_keyboard,
)
from bot.services.photo_prompt_service import photo_prompt_service
from bot.services.media_input_utils import resolve_local_upload_path
from bot.states import ImageAnalyzerStates

logger = logging.getLogger(__name__)
router = Router()

AUDIO_PROMPT_PENDING_WAIT_SECONDS = 8.0
AUDIO_PROMPT_PENDING_POLL_SECONDS = 0.2

AUDIO_PROMPT_MIME_TYPES = (
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/aac",
    "audio/aiff",
    "audio/x-aiff",
    "audio/ogg",
    "audio/oga",
    "audio/flac",
    "audio/x-flac",
)

GPT_AUDIO_PROMPT_FORMATS = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/aac": "aac",
    "audio/aiff": "aiff",
    "audio/x-aiff": "aiff",
    "audio/ogg": "ogg",
    "audio/oga": "ogg",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
}


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
    voice_summary = (result.get("voice_prompt_summary_ru") or "").strip()
    voice_description = (result.get("voice_description_ru") or "").strip()
    gemini_omni_prompt = (result.get("gemini_omni_prompt") or "").strip()
    source_mode = (result.get("source_mode") or "").strip()

    provider_note = ""
    if provider and provider != "gpt-5.5":
        provider_note = f"\n\n<i>Fallback: {html.escape(provider)}</i>"

    has_voice_context = bool(voice_summary or voice_description or gemini_omni_prompt)
    prompt_ru_limit = 680 if has_voice_context else 900
    prompt_en_limit = 980 if has_voice_context else 1400
    negative_limit = 320 if has_voice_context else 450
    model_hint_limit = 360 if has_voice_context else 500

    voice_note = ""
    if voice_summary or voice_description:
        voice_lines = []
        if voice_summary:
            voice_lines.append(_escape_clip_text(voice_summary, 360))
        if voice_description:
            voice_lines.append(
                "Голос: " + _escape_clip_text(voice_description, 260)
            )
        voice_note = "\n\n<b>Учтён голосовой промпт:</b>\n" + "\n".join(voice_lines)

    omni_note = ""
    if gemini_omni_prompt:
        omni_note = (
            "\n\n<b>Gemini Omni prompt:</b>\n"
            f"<pre>{_escape_clip_text(gemini_omni_prompt, 680)}</pre>"
        )

    if source_mode == "voice":
        title = "✅ <b>Промпт по голосу готов</b>"
    elif source_mode == "photo_voice":
        title = "✅ <b>Промпт по фото и голосу готов</b>"
    else:
        title = "✅ <b>Промпт по фото готов</b>"

    return (
        f"{title}\n\n"
        "<b>Prompt RU:</b>\n"
        f"<pre>{_escape_clip_text(prompt_ru or '—', prompt_ru_limit)}</pre>\n\n"
        "<b>Prompt EN:</b>\n"
        f"<pre>{_escape_clip_text(prompt_en or '—', prompt_en_limit)}</pre>\n\n"
        "<b>Negative prompt:</b>\n"
        f"<pre>{_escape_clip_text(negative_prompt or '—', negative_limit)}</pre>\n\n"
        "<b>Рекомендация:</b>\n"
        f"{_escape_clip_text(model_hint or '—', model_hint_limit)}"
        f"{voice_note}"
        f"{omni_note}"
        f"{provider_note}"
    )


def _audio_prompt_media(message: Message):
    if message.voice:
        return message.voice
    if message.audio:
        return message.audio
    if message.document and message.document.mime_type in AUDIO_PROMPT_MIME_TYPES:
        return message.document
    return None


def _audio_prompt_mime_type(message: Message) -> str:
    if message.voice:
        return "audio/ogg"
    if message.audio:
        return message.audio.mime_type or "audio/mpeg"
    if message.document:
        return message.document.mime_type or "audio/mpeg"
    return "audio/ogg"


def _audio_prompt_format(mime_type: str) -> str:
    value = (mime_type or "").strip().lower()
    return GPT_AUDIO_PROMPT_FORMATS.get(value, "")


async def _download_audio_prompt(message: Message) -> tuple[bytes, str, str]:
    media = _audio_prompt_media(message)
    if not media:
        raise ValueError("audio prompt media is required")

    file_size = getattr(media, "file_size", 0) or 0
    if file_size and file_size > config.PHOTO_PROMPT_MAX_AUDIO_BYTES:
        raise ValueError("audio prompt is too large")

    file = await message.bot.get_file(media.file_id)
    audio_io = await message.bot.download_file(file.file_path)
    audio_bytes = audio_io.read()
    if len(audio_bytes) > config.PHOTO_PROMPT_MAX_AUDIO_BYTES:
        raise ValueError("audio prompt is too large")

    mime_type = _audio_prompt_mime_type(message)
    audio_format = _audio_prompt_format(mime_type)
    if not audio_format:
        raise ValueError("audio prompt mime type is not supported")

    return audio_bytes, mime_type, audio_format


def _load_saved_audio_prompt(audio_prompt: dict | None) -> tuple[bytes | None, str]:
    if not isinstance(audio_prompt, dict):
        return None, ""

    audio_url = str(audio_prompt.get("url") or "").strip()
    audio_format = str(audio_prompt.get("format") or "").strip()
    if not audio_url or not audio_format:
        return None, ""

    local_path = resolve_local_upload_path(audio_url)
    if not local_path:
        raise RuntimeError("Не удалось найти сохранённый голосовой промпт")

    with open(local_path, "rb") as audio_file:
        return audio_file.read(), audio_format


def _photo_prompt_audio_token(message: Message) -> str:
    return str(getattr(message, "message_id", "") or id(message))


async def _wait_for_photo_prompt_audio(state: FSMContext) -> dict | None:
    attempts = int(AUDIO_PROMPT_PENDING_WAIT_SECONDS / AUDIO_PROMPT_PENDING_POLL_SECONDS)
    for _ in range(attempts):
        data = await state.get_data()
        audio_prompt = data.get("photo_prompt_audio")
        if isinstance(audio_prompt, dict):
            return audio_prompt
        if not data.get("photo_prompt_audio_pending"):
            return None
        await asyncio.sleep(AUDIO_PROMPT_PENDING_POLL_SECONDS)

    data = await state.get_data()
    audio_prompt = data.get("photo_prompt_audio")
    return audio_prompt if isinstance(audio_prompt, dict) else None


async def _clear_photo_prompt_audio_if_current(
    state: FSMContext,
    *,
    audio_url: str = "",
    pending_token: str = "",
) -> None:
    data = await state.get_data()
    updates = {}

    if pending_token and data.get("photo_prompt_audio_pending") == pending_token:
        updates["photo_prompt_audio_pending"] = None

    current_audio = data.get("photo_prompt_audio")
    consumed_url = str(data.get("photo_prompt_audio_consumed_url") or "")
    if (
        audio_url
        and isinstance(current_audio, dict)
        and current_audio.get("url") == audio_url
        and consumed_url != audio_url
    ):
        updates["photo_prompt_audio"] = None
        updates["photo_prompt_audio_consumed_url"] = None

    if updates:
        await state.update_data(**updates)


async def _safe_edit_or_answer(
    processing: Message,
    source_message: Message,
    text: str,
    reply_markup=None,
    parse_mode=None,
    disable_web_page_preview=None,
) -> None:
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


async def _send_photo_prompt_result(
    message: Message,
    result: dict,
    *,
    filename: str = "photo_prompt_full.txt",
    document_caption: str = "📝 Полный prompt: RU + EN + negative",
) -> None:
    prompt_en = (result.get("prompt_en") or "").strip()
    prompt_ru = (result.get("prompt_ru") or "").strip()
    negative_prompt = (result.get("negative_prompt") or "").strip()
    text = _format_photo_prompt_result_text(result)

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
        "VOICE PROMPT\n"
        "------------\n"
        f"{result.get('voice_transcript') or '—'}\n\n"
        "VOICE SUMMARY\n"
        "-------------\n"
        f"{result.get('voice_prompt_summary_ru') or '—'}\n\n"
        "VOICE DESCRIPTION\n"
        "-----------------\n"
        f"{result.get('voice_description_ru') or '—'}\n\n"
        "GEMINI OMNI PROMPT\n"
        "------------------\n"
        f"{result.get('gemini_omni_prompt') or '—'}\n\n"
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
            filename=filename,
        ),
        caption=document_caption,
    )


@router.callback_query(F.data == "photo_to_prompt")
async def photo_to_prompt_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(ImageAnalyzerStates.waiting_for_photo)

    text = (
        "📸 <b>Промпт по фото</b>\n\n"
        "Отправьте фото, голосовой промпт или сначала голос, а затем фото.\n"
        "GPT-5.5 разберёт фото отдельно, голос отдельно или объединит голос с последующим фото.\n\n"
        "В результате вы получите:\n"
        "• точный prompt на английском\n"
        "• понятную версию на русском\n"
        "• negative prompt\n"
        "• рекомендацию модели\n"
        "• Gemini Omni prompt, если был голосовой промпт\n\n"
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


@router.message(
    ImageAnalyzerStates.waiting_for_photo,
    F.voice
    | F.audio
    | (F.document & F.document.mime_type.in_(AUDIO_PROMPT_MIME_TYPES)),
)
async def analyze_voice_prompt(message: Message, state: FSMContext):
    audio_token = _photo_prompt_audio_token(message)
    await state.update_data(
        photo_prompt_audio=None,
        photo_prompt_audio_consumed_url=None,
        photo_prompt_audio_pending=audio_token,
    )
    processing = await message.answer("🎙 Анализирую голосовой промпт через GPT-5.5…")
    audio_url = ""

    try:
        audio_bytes, mime_type, audio_format = await _download_audio_prompt(message)
        from bot.handlers.generation import save_uploaded_file

        audio_url = save_uploaded_file(audio_bytes, audio_format)
        if not audio_url:
            raise RuntimeError("Не удалось сохранить голосовой промпт")

        await state.update_data(
            photo_prompt_audio={
                "url": audio_url,
                "mime_type": mime_type,
                "format": audio_format,
                "token": audio_token,
            },
            photo_prompt_audio_pending=None,
            photo_prompt_audio_consumed_url=None,
        )

        result = await photo_prompt_service.analyze_photo(
            image_url="",
            preserve=(
                "смысл голосового запроса, стиль, настроение, действие, камеру, "
                "сеттинг и ограничения пользователя"
            ),
            goal="создать качественный prompt по голосовому описанию",
            audio_bytes=audio_bytes,
            audio_format=audio_format,
        )
        result["source_mode"] = "voice"

        current_data = await state.get_data()
        current_audio = current_data.get("photo_prompt_audio")
        consumed_url = str(current_data.get("photo_prompt_audio_consumed_url") or "")
        if not (
            isinstance(current_audio, dict)
            and current_audio.get("url") == audio_url
            and consumed_url != audio_url
        ):
            try:
                await processing.delete()
            except Exception:
                pass
            return

        try:
            await processing.delete()
        except Exception:
            pass

        await _send_photo_prompt_result(
            message,
            result,
            filename="voice_prompt_full.txt",
            document_caption="📝 Полный prompt по голосу: RU + EN + negative",
        )
        await message.answer(
            "Можно отправить фото следующим сообщением — тогда GPT-5.5 объединит его с этим голосовым промптом.",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
    except ValueError:
        await _clear_photo_prompt_audio_if_current(
            state,
            audio_url=audio_url,
            pending_token=audio_token,
        )
        await _safe_edit_or_answer(
            processing,
            message,
            "❌ Голосовой файл слишком большой или не поддерживается. Максимум 10MB.",
            reply_markup=get_back_keyboard("back_main"),
        )
    except Exception as e:
        logger.exception("Photo prompt voice analysis failed")
        await _clear_photo_prompt_audio_if_current(
            state,
            audio_url=audio_url,
            pending_token=audio_token,
        )
        await _safe_edit_or_answer(
            processing,
            message,
            _clip_text(
                f"❌ Не удалось разобрать голосовой промпт: {e}",
                700,
            ),
            reply_markup=get_back_keyboard("back_main"),
        )


@router.message(ImageAnalyzerStates.waiting_for_photo, F.photo)
async def analyze_photo(message: Message, state: FSMContext):
    processing = await message.answer("🔍 Анализирую фото и собираю точный prompt…")

    try:
        data = await state.get_data()
        audio_prompt = data.get("photo_prompt_audio")
        if not isinstance(audio_prompt, dict) and data.get("photo_prompt_audio_pending"):
            audio_prompt = await _wait_for_photo_prompt_audio(state)
            if not isinstance(audio_prompt, dict):
                latest_data = await state.get_data()
                latest_audio_prompt = latest_data.get("photo_prompt_audio")
                if isinstance(latest_audio_prompt, dict):
                    audio_prompt = latest_audio_prompt
                elif latest_data.get("photo_prompt_audio_pending"):
                    await _safe_edit_or_answer(
                        processing,
                        message,
                        "🎙 Голосовой промпт ещё загружается. Отправьте фото ещё раз через несколько секунд — я объединю его с голосом.",
                        reply_markup=get_back_keyboard("back_main"),
                        parse_mode="HTML",
                    )
                    return

        audio_url = ""
        if isinstance(audio_prompt, dict):
            audio_url = str(audio_prompt.get("url") or "")
            if audio_url:
                await state.update_data(photo_prompt_audio_consumed_url=audio_url)

        audio_bytes, audio_format = _load_saved_audio_prompt(audio_prompt)
        user_note = (message.caption or "").strip()
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
            user_note=user_note,
            audio_bytes=audio_bytes,
            audio_format=audio_format,
        )
        result["source_mode"] = "photo_voice" if audio_bytes else "photo"

        try:
            await processing.delete()
        except Exception:
            pass

        await _send_photo_prompt_result(message, result)
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
        "Пожалуйста, отправьте фото или голосовой промпт. Можно отправлять их отдельно или сначала голос, затем фото.",
        reply_markup=get_back_keyboard("back_main"),
    )
