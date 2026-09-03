"""Seedance-only compatibility for reference-only photo workflows.

Seedance 2.0 uses uploaded photos only as references in the public Telegram flow.
No uploaded image is exposed to the provider as a literal first frame.
"""

from __future__ import annotations

from functools import wraps
from typing import Any

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards import (
    get_main_menu_button_keyboard,
    get_reference_videos_upload_keyboard,
)
from bot.states import GenerationStates

from . import generation as generation_module

router = Router()

SEEDANCE_MODELS = {"seedance_2"}
SEEDANCE_MAX_IMAGES = 9
SEEDANCE_MAX_VIDEOS = 3
SEEDANCE_MAX_VIDEO_BYTES = 50 * 1024 * 1024
SEEDANCE_MIN_REFERENCE_VIDEO_SECONDS = 2
SEEDANCE_MAX_REFERENCE_VIDEO_SECONDS = 15
SEEDANCE_MAX_TOTAL_REFERENCE_VIDEO_SECONDS = 15


def is_seedance_model(model: object) -> bool:
    return str(model or "").strip() in SEEDANCE_MODELS


def default_video_type(v_type: str | None) -> str:
    """Use Photo + Text for the ordinary create-video flow by default."""
    return "imgtxt" if v_type is None else v_type


def _clean_reference_urls(values, *, max_count: int) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        url = str(value or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        cleaned.append(url)
        if len(cleaned) >= max_count:
            break
    return cleaned


def reference_only_seedance_media_inputs(
    generation_type: str,
    image_url: str | None,
    reference_images,
    reference_videos,
) -> tuple[None, list[str], list[str]]:
    """Collapse legacy primary-image state into ordinary Seedance references."""
    del generation_type
    images = _clean_reference_urls(
        [image_url, *(reference_images or [])],
        max_count=SEEDANCE_MAX_IMAGES,
    )
    videos = _clean_reference_urls(
        reference_videos,
        max_count=SEEDANCE_MAX_VIDEOS,
    )
    return None, images, videos


async def _normalize_seedance_reference_state(state: FSMContext) -> dict[str, Any]:
    """Migrate old Seedance sessions from v_image_url to reference_images."""
    data = await state.get_data()
    if not is_seedance_model(data.get("v_model")):
        return data

    images = _clean_reference_urls(
        [data.get("v_image_url"), *(data.get("reference_images") or [])],
        max_count=SEEDANCE_MAX_IMAGES,
    )
    updates: dict[str, Any] = {}
    if data.get("v_image_url"):
        updates["v_image_url"] = None
    if images != list(data.get("reference_images") or []):
        updates["reference_images"] = images
    if updates:
        await state.update_data(**updates)
        data = await state.get_data()
    return data


async def _prepare_seedance_runtime_state(state: FSMContext) -> list[str] | None:
    """Satisfy legacy imgtxt validation without restoring first-frame semantics.

    The legacy launcher still checks v_image_url before entering its Seedance
    branch. Temporarily split the first reference into that field, while the
    patched media builder immediately folds it back into references and the
    provider boundary also rejects first-frame semantics.
    """
    data = await _normalize_seedance_reference_state(state)
    if not is_seedance_model(data.get("v_model")):
        return None

    images = _clean_reference_urls(
        data.get("reference_images"),
        max_count=SEEDANCE_MAX_IMAGES,
    )
    if data.get("v_type") == "imgtxt" and images:
        await state.update_data(
            v_image_url=images[0],
            reference_images=images[1:],
            seedance_reference_only_runtime=True,
        )
    return images


async def _restore_seedance_reference_state(
    state: FSMContext,
    original_images: list[str] | None,
) -> None:
    if original_images is None:
        return
    data = await state.get_data()
    if not data or not is_seedance_model(data.get("v_model")):
        return
    await state.update_data(
        v_image_url=None,
        reference_images=original_images,
        seedance_reference_only_runtime=False,
    )


def _seedance_media_keyboard(data: dict[str, Any]) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    current_v_type = str(data.get("v_type") or "imgtxt")
    image_count = len(data.get("reference_images") or [])
    video_count = len(data.get("v_reference_videos") or [])

    builder.button(
        text=f"{'✅ ' if current_v_type == 'text' else ''}📝 Текст → Видео",
        callback_data="v_type_text",
    )
    builder.button(
        text=f"{'✅ ' if current_v_type == 'imgtxt' else ''}🖼 Фото + Текст → Видео",
        callback_data="v_type_imgtxt",
    )
    builder.button(
        text=f"{'✅ ' if current_v_type == 'video' else ''}🎬 Видео + Текст → Видео",
        callback_data="v_type_video",
    )

    if current_v_type == "imgtxt":
        builder.button(
            text=f"📎 Фото-референсы: {image_count}/{SEEDANCE_MAX_IMAGES}",
            callback_data="ignore",
        )
        builder.button(text="▶️ К настройкам", callback_data="video_media_continue")
    elif current_v_type == "video":
        builder.button(
            text=f"📹 Видео-референсы: {video_count}/{SEEDANCE_MAX_VIDEOS}",
            callback_data="ignore",
        )
        builder.button(text="⏭ Без видео-рефов", callback_data="video_media_skip")
        builder.button(text="▶️ К настройкам", callback_data="video_media_continue")
    else:
        builder.button(text="▶️ К настройкам", callback_data="video_media_continue")

    builder.button(text="🤖 Сменить модель", callback_data="video_change_model")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    if current_v_type == "imgtxt":
        builder.adjust(3, 1, 1, 2)
    elif current_v_type == "video":
        builder.adjust(3, 1, 2, 2)
    else:
        builder.adjust(3, 1, 2)
    return builder.as_markup()


async def _render_text(
    message_or_callback,
    text: str,
    *,
    reply_markup,
    edit: bool,
) -> None:
    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            if edit:
                await message_or_callback.message.edit_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
            else:
                await message_or_callback.message.answer(
                    text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
        elif edit:
            await message_or_callback.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await message_or_callback.answer(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            target = (
                message_or_callback.message
                if isinstance(message_or_callback, types.CallbackQuery)
                else message_or_callback
            )
            await target.answer(text, reply_markup=reply_markup, parse_mode="HTML")
    except AttributeError:
        target = (
            message_or_callback.message
            if isinstance(message_or_callback, types.CallbackQuery)
            else message_or_callback
        )
        await target.answer(text, reply_markup=reply_markup, parse_mode="HTML")


async def _show_seedance_media_screen(
    message_or_callback,
    state: FSMContext,
    edit: bool = True,
) -> None:
    data = await _normalize_seedance_reference_state(state)
    current_v_type = str(data.get("v_type") or "imgtxt")
    image_count = len(data.get("reference_images") or [])
    video_count = len(data.get("v_reference_videos") or [])
    user_id = getattr(getattr(message_or_callback, "from_user", None), "id", None)
    user_credits = await generation_module.get_user_credits(user_id) if user_id else 0

    if current_v_type == "imgtxt":
        body = (
            "<b>Шаг 2. Тип и медиа</b>\n"
            f"Модель: <code>{generation_module.get_video_model_label('seedance_2')}</code>\n\n"
            "Выбран режим <b>Фото + Текст → Видео</b>.\n"
            "Отправьте одно или несколько фото-референсов. Можно отправить их одним альбомом.\n\n"
            "<b>Все фото используются только как референсы.</b>\n"
            "Стартовый кадр не задаётся — видео начинается по вашему промпту.\n\n"
            f"Фото: <code>{image_count}/{SEEDANCE_MAX_IMAGES}</code> · "
            f"Видео-рефы: <code>{video_count}/{SEEDANCE_MAX_VIDEOS}</code>"
        )
        next_state = GenerationStates.waiting_for_video_prompt
    elif current_v_type == "video":
        body = (
            "<b>Шаг 2. Тип и медиа</b>\n"
            f"Модель: <code>{generation_module.get_video_model_label('seedance_2')}</code>\n\n"
            "Выбран режим <b>Видео + Текст → Видео</b>.\n"
            f"Загрузите до {SEEDANCE_MAX_VIDEOS} коротких видео-референсов "
            "или продолжите без них.\n"
            f"Видео: <code>{video_count}/{SEEDANCE_MAX_VIDEOS}</code>"
        )
        next_state = GenerationStates.uploading_reference_videos
    else:
        body = (
            "<b>Шаг 2. Тип и медиа</b>\n"
            f"Модель: <code>{generation_module.get_video_model_label('seedance_2')}</code>\n\n"
            "Выбран режим <b>Текст → Видео</b>.\n"
            "Медиа не обязательно. Можно сразу перейти к настройкам."
        )
        next_state = GenerationStates.waiting_for_video_prompt

    text = (
        "🎬 <b>Создание видео</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        f"{body}"
    )
    await _render_text(
        message_or_callback,
        text,
        reply_markup=_seedance_media_keyboard(data),
        edit=edit,
    )
    await state.set_state(next_state)


async def _show_seedance_creation_screen(
    message_or_callback,
    state: FSMContext,
    edit: bool = True,
) -> None:
    data = await _normalize_seedance_reference_state(state)
    image_count = len(data.get("reference_images") or [])
    video_count = len(data.get("v_reference_videos") or [])
    prompt = str(data.get("user_prompt") or "").strip()
    prompt_line = (
        f"\n📝 Промпт: <code>{prompt[:120]}{'…' if len(prompt) > 120 else ''}</code>\n"
        if prompt
        else ""
    )

    text = (
        "🎬 <b>Создание видео</b>\n"
        "<b>Шаг 3. Настройки и промпт</b>\n\n"
        f"🤖 Модель: <code>{generation_module.get_video_model_label('seedance_2')}</code>\n"
        f"📝 Тип: <code>{generation_module.get_video_type_label(data.get('v_type', 'imgtxt'))}</code>\n"
        f"⏱ Длительность: <code>{int(data.get('v_duration', 5))} сек</code>\n"
        f"📐 Формат: <code>{data.get('v_ratio', '16:9')}</code>\n"
        f"📎 Фото-референсы: <code>{image_count}/{SEEDANCE_MAX_IMAGES}</code>\n"
        f"📹 Видео-референсы: <code>{video_count}/{SEEDANCE_MAX_VIDEOS}</code>\n"
        f"{prompt_line}\n"
        "<b>Опишите видео</b>\n"
        "• что происходит в сцене\n"
        "• как двигается камера\n"
        "• какой нужен стиль и настроение\n\n"
        "<i>Фото остаются референсами и не превращаются в стартовый кадр.</i>"
    )
    await _render_text(
        message_or_callback,
        text,
        reply_markup=generation_module._build_video_creation_keyboard(data),
        edit=edit,
    )
    await state.set_state(GenerationStates.waiting_for_video_prompt)


def install_seedance_multimodal_runtime_compat() -> None:
    """Install Seedance reference-only behavior without changing other models."""
    if getattr(generation_module, "_seedance_multimodal_runtime_installed", False):
        return

    original_init_video_state = generation_module._init_default_video_state
    original_media_screen = generation_module._show_video_media_screen
    original_creation_screen = generation_module._show_video_creation_screen
    original_message_launch = generation_module.run_no_preset_video_from_message
    original_callback_launch = generation_module.run_no_preset_video_from_callback

    async def init_video_state_with_photo_default(
        state,
        *,
        v_type: str | None = None,
        v_model: str = "v3_std",
        v_duration: int = 5,
        v_ratio: str = "16:9",
    ):
        return await original_init_video_state(
            state,
            v_type=default_video_type(v_type),
            v_model=v_model,
            v_duration=v_duration,
            v_ratio=v_ratio,
        )

    @wraps(original_media_screen)
    async def media_screen_without_seedance_first_frame(
        message_or_callback,
        state,
        edit=True,
    ):
        data = await state.get_data()
        if is_seedance_model(data.get("v_model")):
            return await _show_seedance_media_screen(
                message_or_callback,
                state,
                edit=edit,
            )
        return await original_media_screen(message_or_callback, state, edit=edit)

    @wraps(original_creation_screen)
    async def creation_screen_without_seedance_first_frame(
        message_or_callback,
        state,
        edit=True,
    ):
        data = await state.get_data()
        if is_seedance_model(data.get("v_model")):
            return await _show_seedance_creation_screen(
                message_or_callback,
                state,
                edit=edit,
            )
        return await original_creation_screen(message_or_callback, state, edit=edit)

    @wraps(original_message_launch)
    async def message_launch_with_seedance_refs(message, state, prompt):
        original_images = await _prepare_seedance_runtime_state(state)
        try:
            return await original_message_launch(message, state, prompt)
        finally:
            await _restore_seedance_reference_state(state, original_images)

    @wraps(original_callback_launch)
    async def callback_launch_with_seedance_refs(
        callback,
        state,
        prompt,
        cost,
        is_admin,
    ):
        original_images = await _prepare_seedance_runtime_state(state)
        try:
            return await original_callback_launch(
                callback,
                state,
                prompt,
                cost,
                is_admin,
            )
        finally:
            await _restore_seedance_reference_state(state, original_images)

    generation_module._init_default_video_state = init_video_state_with_photo_default
    generation_module._show_video_media_screen = media_screen_without_seedance_first_frame
    generation_module._show_video_creation_screen = creation_screen_without_seedance_first_frame
    generation_module._seedance_media_inputs = reference_only_seedance_media_inputs
    generation_module.run_no_preset_video_from_message = message_launch_with_seedance_refs
    generation_module.run_no_preset_video_from_callback = callback_launch_with_seedance_refs
    generation_module._seedance_multimodal_runtime_installed = True


@router.callback_query(F.data == "video_media_continue")
async def continue_seedance_reference_only_media(
    callback: types.CallbackQuery,
    state: FSMContext,
) -> None:
    data = await _normalize_seedance_reference_state(state)
    if not is_seedance_model(data.get("v_model")):
        raise SkipHandler

    if data.get("v_type") == "imgtxt" and not data.get("reference_images"):
        await callback.answer(
            "Сначала отправьте хотя бы одно фото-референс.",
            show_alert=True,
        )
        return

    await state.update_data(video_flow_step="configure")
    await generation_module._show_video_creation_screen(callback, state)
    await callback.answer()


@router.message(
    StateFilter(
        GenerationStates.waiting_for_video_prompt,
        GenerationStates.uploading_reference_videos,
    ),
    F.photo
    | (
        F.document
        & F.document.mime_type.in_(("image/jpeg", "image/png", "image/webp"))
    ),
)
async def accept_seedance_photo_reference(
    message: types.Message,
    state: FSMContext,
) -> None:
    """Store every Seedance photo in reference_images, including albums."""
    user_id = message.from_user.id
    async with generation_module._get_reference_upload_lock(user_id):
        data = await _normalize_seedance_reference_state(state)
        if not is_seedance_model(data.get("v_model")):
            raise SkipHandler

        reference_images = _clean_reference_urls(
            data.get("reference_images"),
            max_count=SEEDANCE_MAX_IMAGES,
        )
        if len(reference_images) >= SEEDANCE_MAX_IMAGES:
            await message.answer(
                f"❌ Для Seedance можно загрузить максимум {SEEDANCE_MAX_IMAGES} фото.",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return

        image_url, error_message = (
            await generation_module._save_reference_image_from_message(
                message,
                original_filename_prefix="seedance_reference",
            )
        )
        if not image_url:
            await message.answer(
                error_message or "❌ Не удалось сохранить фото-референс.",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return

        reference_images = _clean_reference_urls(
            [*reference_images, image_url],
            max_count=SEEDANCE_MAX_IMAGES,
        )
        await state.update_data(
            v_image_url=None,
            reference_images=reference_images,
            video_flow_step="configure",
        )
        video_count = len(data.get("v_reference_videos") or [])

    await message.answer(
        "✅ Фото-референс Seedance добавлен.\n"
        f"Фото: <code>{len(reference_images)}/{SEEDANCE_MAX_IMAGES}</code> · "
        f"Видео: <code>{video_count}/{SEEDANCE_MAX_VIDEOS}</code>\n"
        "Можно отправить ещё фото одним сообщением/альбомом или сразу написать промпт.",
        parse_mode="HTML",
    )
    await generation_module._show_video_creation_screen(message, state, edit=False)


@router.message(
    StateFilter(
        GenerationStates.waiting_for_video_prompt,
        GenerationStates.uploading_reference_videos,
    ),
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def accept_seedance_video_reference(
    message: types.Message,
    state: FSMContext,
) -> None:
    """Accept Seedance motion videos in both media sub-flows."""
    data = await state.get_data()
    if not is_seedance_model(data.get("v_model")):
        raise SkipHandler

    video_obj = message.video or message.document
    if not video_obj:
        raise SkipHandler

    file_size = int(getattr(video_obj, "file_size", 0) or 0)
    if file_size > SEEDANCE_MAX_VIDEO_BYTES:
        await message.answer(
            "❌ Видео слишком большое. Для Seedance максимум 50 MB.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    duration = int(getattr(video_obj, "duration", 0) or 0)
    if duration and not (
        SEEDANCE_MIN_REFERENCE_VIDEO_SECONDS
        <= duration
        <= SEEDANCE_MAX_REFERENCE_VIDEO_SECONDS
    ):
        await message.answer(
            "❌ Видео-референс Seedance должен длиться от 2 до 15 секунд.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    existing_urls = _clean_reference_urls(
        data.get("v_reference_videos"),
        max_count=SEEDANCE_MAX_VIDEOS,
    )
    durations = [
        max(0, int(value or 0))
        for value in (data.get("seedance_reference_video_durations") or [])
    ]
    if len(existing_urls) >= SEEDANCE_MAX_VIDEOS:
        await message.answer(
            f"❌ Для Seedance можно загрузить максимум {SEEDANCE_MAX_VIDEOS} видео.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    known_total_duration = sum(durations)
    if duration and known_total_duration + duration > SEEDANCE_MAX_TOTAL_REFERENCE_VIDEO_SECONDS:
        await message.answer(
            "❌ Общая длительность видео-референсов Seedance не должна превышать 15 секунд.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    file = await message.bot.get_file(video_obj.file_id)
    downloaded = await message.bot.download_file(file.file_path)
    mime_type = str(getattr(video_obj, "mime_type", "") or "video/mp4")
    file_ext = "mov" if mime_type == "video/quicktime" else "mp4"
    video_url = await generation_module._persist_reusable_media_reference(
        message.from_user.id,
        downloaded.read(),
        file_ext,
        kind="video",
        original_filename=f"seedance_ref_{video_obj.file_id}.{file_ext}",
        content_type=mime_type,
    )
    if not video_url:
        await message.answer(
            "❌ Не удалось сохранить видео-референс.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    if video_url not in existing_urls:
        existing_urls.append(video_url)
        durations.append(duration)
    await state.update_data(
        v_reference_videos=existing_urls,
        seedance_reference_video_durations=durations,
    )

    data = await _normalize_seedance_reference_state(state)
    image_count = len(data.get("reference_images") or [])
    text = (
        "✅ Видео-референс Seedance добавлен.\n"
        f"Фото: <code>{image_count}/{SEEDANCE_MAX_IMAGES}</code> · "
        f"Видео: <code>{len(existing_urls)}/{SEEDANCE_MAX_VIDEOS}</code>"
    )
    if (await state.get_state()) == GenerationStates.uploading_reference_videos.state:
        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=get_reference_videos_upload_keyboard(
                len(existing_urls),
                SEEDANCE_MAX_VIDEOS,
                "video_new",
            ),
        )
    else:
        await message.answer(text, parse_mode="HTML")
