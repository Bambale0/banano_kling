import asyncio
import base64
import io
import logging
import os
import random
import time
import uuid
from datetime import datetime
from typing import Optional

from aiogram import Bot, F, Router, types
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.database import (
    add_credits,
    add_generation_history,
    add_generation_task,
    check_can_afford,
    complete_video_task,
    deduct_credits,
    get_or_create_user,
    get_task_by_id,
    get_user_credits,
    get_user_settings,
)
from bot.keyboards import (
    get_back_keyboard,
    get_create_image_keyboard,
    get_create_video_keyboard,
    get_grok_i2i_keyboard,
    get_image_model_label,
    get_main_menu_keyboard,
    get_reference_images_upload_keyboard,
    get_reference_videos_upload_keyboard,
    get_video_model_label,
    get_video_type_label,
)
from bot.services.gemini_service import gemini_service
from bot.services.grok_service import grok_service
from bot.services.nano_banana_2_service import nano_banana_2_service
from bot.services.nano_banana_pro_service import nano_banana_pro_service
from bot.services.preset_manager import preset_manager
from bot.states import GenerationStates, GrokI2IStates
from bot.utils.help_texts import (
    UserHints,
    format_generation_options,
    get_prompt_tips,
    get_reference_images_help,
)

logger = logging.getLogger(__name__)
router = Router()


# =============================================================================
# НОВЫЙ UX: МЕНЮ СОЗДАНИЯ ВИДЕО (get_create_video_keyboard)
# =============================================================================


@router.callback_query(F.data == "create_video_new")
async def show_create_video_menu(callback: types.CallbackQuery, state: FSMContext):
    """Показывает меню создания видео - начинаем с загрузки референсов"""
    from bot.database import get_user_credits

    user_credits = await get_user_credits(callback.from_user.id)

    # Инициализируем опции по умолчанию
    await state.update_data(
        generation_type="video",
        v_type="text",  # text или imgtxt
        v_model="v3_std",  # модель видео
        v_duration=5,
        v_ratio="16:9",
        v_mode="720p",
        v_orientation="video",
        reference_images=[],  # Реф. изображения для всех режимов (до 14)
        v_reference_videos=[],  # Реф. видео для video+text (до 5)
        user_prompt="",  # Инициализируем пустой промпт
        grok_mode="normal",
        veo_generation_type="TEXT_2_VIDEO",
        veo_translation=True,
        veo_resolution="720p",
        veo_seed=None,
        veo_watermark="",
    )

    # СРАЗУ показываем экран с параметрами видео и полем для промпта (без загрузки референсов)
    await _show_video_creation_screen(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "create_image_refs_new")
async def show_create_image_menu(callback: types.CallbackQuery, state: FSMContext):
    """Показывает меню создания фото - начинаем с загрузки референсов"""
    from bot.database import get_user_credits

    user_credits = await get_user_credits(callback.from_user.id)

    # Инициализируем опции по умолчанию
    await state.update_data(
        generation_type="image",
        img_service="banana_pro",  # модель изображения по умолчанию
        img_ratio="1:1",
        img_count=1,
        reference_images=[],  # Инициализируем пустой список референсов
        preset_id="new",  # Для нового UX - указываем, что это "new" режим
    )

    # Показываем экран загрузки референсов (ШАГ 1)
    text = (
        "🖼 <b>Создание фото</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "<b>Шаг 1. Референсы</b>\n"
        "Загрузка необязательна, но может помочь, если важно:\n"
        "• сохранить внешность объекта или персонажа\n"
        "• удержать стиль и детали\n"
        "• опереться на конкретные исходники\n\n"
        "<i>Можно загрузить до 14 фото.</i>\n"
        "Когда всё готово, нажмите <b>▶️ Продолжить</b>.\n"
        "Если референсы не нужны — выберите <b>⏭ Пропустить</b>."
    )
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_reference_images_upload_keyboard(0, 14, "new"),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=get_reference_images_upload_keyboard(0, 14, "new"),
            parse_mode="HTML",
        )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_images)


@router.callback_query(F.data == "motion_control")
async def start_motion_control(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    """Запуск Motion Control Kling 2.6"""
    from bot.database import get_user_credits

    user_credits = await get_user_credits(callback.from_user.id)

    await state.update_data(
        generation_type="motion_control",
        motion_mode="720p",
        motion_orientation="video",
        motion_image_url=None,
        motion_video_url=None,
        motion_prompt="",
    )

    text = (
        "🎯 <b>Kling 2.6 Motion Control</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code>\n\n"
        "<b>Шаг 1. Фото персонажа</b>\n"
        "Загрузите чёткое фото, которое нужно анимировать.\n\n"
        "Подойдёт:\n"
        "• портрет или персонаж по пояс\n"
        "• иллюстрация или рендер\n"
        "• JPEG/PNG до 10 MB\n\n"
        "<i>Движение будет перенесено из референсного видео на это изображение.</i>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard("back_main"),
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_motion_character_image)


@router.callback_query(F.data == "photo_prompt")
async def show_photo_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Простой промпт для фото (без референсов и выбора параметров)"""
    from bot.database import get_user_credits

    user_credits = await get_user_credits(callback.from_user.id)

    await state.update_data(
        generation_type="image",
        img_service="banana_pro",
        img_ratio="1:1",
        img_count=1,
    )
    await _show_image_creation_screen(callback, state)

    await callback.answer()


@router.callback_query(F.data == "img_ref_upload_new")
async def handle_img_ref_upload_new(callback: types.CallbackQuery, state: FSMContext):
    """Показывает меню загрузки референсных изображений для нового UX"""
    data = await state.get_data()
    current_service = data.get("img_service", "banana_pro")
    current_ratio = data.get("img_ratio", "1:1")

    # Показываем клавиатуру загрузки референсов
    await callback.message.edit_text(
        "📎 <b>Загрузка референсов</b>\n"
        "Добавьте изображения, если хотите точнее передать стиль, персонажа или объект.\n\n"
        "<i>Можно загрузить до 14 фото.</i>\n"
        "Когда всё готово, нажмите <b>Продолжить</b> или <b>Пропустить</b>.",
        reply_markup=get_reference_images_upload_keyboard(0, 14, "new"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_images)


# =============================================================================
# СЛУЖЕБНЫЕ ФУНКЦИИ ДЛЯ UNIFIED UX
# =============================================================================


async def _show_video_creation_screen(
    message_or_callback, state: FSMContext, edit: bool = True
):
    """
    Показывает единый экран создания видео с параметрами и промптом.
    Используется после загрузки референсов или при пропуске.
    """
    data = await state.get_data()

    # Получаем текущие параметры
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v3_std")
    current_duration = data.get("v_duration", 5)
    current_ratio = data.get("v_ratio", "16:9")
    reference_images = data.get("reference_images", [])
    v_reference_videos = data.get("v_reference_videos", [])
    v_image_url = data.get("v_image_url")
    user_prompt = data.get("user_prompt", "")
    grok_mode = data.get("grok_mode", "normal")
    veo_generation_type = data.get("veo_generation_type", "TEXT_2_VIDEO")
    veo_translation = data.get("veo_translation", True)
    veo_resolution = data.get("veo_resolution", "720p")
    veo_seed = data.get("veo_seed")
    veo_watermark = data.get("veo_watermark", "")

    await _normalize_veo_state(state)
    data = await state.get_data()
    current_v_type = data.get("v_type", current_v_type)
    current_model = data.get("v_model", current_model)
    current_ratio = data.get("v_ratio", current_ratio)
    grok_mode = data.get("grok_mode", grok_mode)
    veo_generation_type = data.get("veo_generation_type", veo_generation_type)
    veo_translation = data.get("veo_translation", veo_translation)
    veo_resolution = data.get("veo_resolution", veo_resolution)
    veo_seed = data.get("veo_seed", veo_seed)
    veo_watermark = data.get("veo_watermark", veo_watermark)

    # Формируем текст о референсах
    ref_text = ""
    if reference_images:
        ref_text = f"📎 Изображений реф: <code>{len(reference_images)}</code>\n"
    if v_reference_videos:
        ref_text += f"📹 Видео реф: <code>{len(v_reference_videos)}</code>\n"

    # Формируем статус медиа в зависимости от типа
    media_status = ""
    if current_v_type == "imgtxt":
        start_count = 1 if v_image_url else 0
        ref_count = len(reference_images)
        total = start_count + ref_count
        if total > 0:
            media_status = f"✅ <b>Фото загружено: {total}/9</b> (старт + рефы)\n"
        else:
            media_status = "📷 <b>Загрузите стартовое изображение</b>\n"
    elif current_v_type == "video":
        if v_reference_videos:
            media_status = (
                f"✅ <b>{len(v_reference_videos)} реф. видео загружено!</b>\n"
            )
        else:
            media_status = "📹 <b>Загрузите референсные видео (до 5)</b>\n"

    # Формируем текст о промпте
    prompt_text = ""
    if user_prompt:
        prompt_text = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:100]}{'...' if len(user_prompt) > 100 else ''}</code>\n"

    settings_lines = [
        f"   📝 Тип: <code>{get_video_type_label(current_v_type)}</code>",
        f"   🤖 Модель: <code>{get_video_model_label(current_model)}</code>",
    ]
    if not current_model.startswith("veo3"):
        settings_lines.append(f"   ⏱ Длительность: <code>{current_duration} сек</code>")
    settings_lines.append(f"   📐 Формат: <code>{current_ratio}</code>")

    if current_model == "grok_imagine":
        settings_lines.append(f"   🧠 Режим Grok: <code>{grok_mode}</code>")
    if current_model.startswith("veo3"):
        veo_mode_label_map = {
            "TEXT_2_VIDEO": "Text -> Video",
            "FIRST_AND_LAST_FRAMES_2_VIDEO": "Frames -> Video",
            "REFERENCE_2_VIDEO": "Reference -> Video",
        }
        settings_lines.append(
            f"   🎥 Veo режим: <code>{veo_mode_label_map.get(veo_generation_type, veo_generation_type)}</code>"
        )
        settings_lines.append(
            f"   🌐 Перевод: <code>{'вкл' if veo_translation else 'выкл'}</code>"
        )
        settings_lines.append(f"   🖥 Resolution: <code>{veo_resolution}</code>")
        if veo_seed is not None:
            settings_lines.append(f"   🎲 Seed: <code>{veo_seed}</code>")
        if veo_watermark:
            settings_lines.append(f"   🏷 Watermark: <code>{veo_watermark}</code>")

    text = (
        f"🎬 <b>Создание видео</b>"
        f"{ref_text}"
        f"⚙️ <b>Текущие настройки:</b>\n" + "\n".join(settings_lines) + "\n"
        f"{media_status}"
        f"{prompt_text}\n"
        f"<b>Введите промпт для генерации:</b>"
        f"Опишите видео, которое хотите создать:\n"
        f"• Что происходит в сцене\n"
        f"• Движение камеры\n"
        f"• Стиль и атмосфера"
    )

    # Напоминание о загрузке медиа
    if current_v_type == "imgtxt" and not v_image_url:
        text += f"<i>📷 Загрузите фото, которое станет первым кадром видео</i>"
    elif current_v_type == "video" and not v_reference_videos:
        text += (
            f"<i>📹 Загрузите референсные видео (до 5, 3-10 сек) для стиля/движения</i>"
        )

    # Используем edit для callback, send для message
    try:
        await message_or_callback.message.edit_text(
            text,
            reply_markup=_build_video_creation_keyboard(data),
            parse_mode="HTML",
        )
    except Exception:
        await message_or_callback.answer(
            text,
            reply_markup=_build_video_creation_keyboard(data),
            parse_mode="HTML",
        )

    # Устанавливаем состояние ожидания промпта для видео
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    logger.info(
        f"[DEBUG] State set to waiting_for_video_prompt for user {message_or_callback.from_user.id if hasattr(message_or_callback, 'from_user') else 'callback'}"
    )


def _build_video_creation_keyboard(data: dict):
    return get_create_video_keyboard(
        current_v_type=data.get("v_type", "text"),
        current_model=data.get("v_model", "v3_std"),
        current_duration=data.get("v_duration", 5),
        current_ratio=data.get("v_ratio", "16:9"),
        current_mode=data.get("v_mode", "720p"),
        current_orientation=data.get("v_orientation", "video"),
        current_grok_mode=data.get("grok_mode", "normal"),
        current_veo_generation_type=data.get("veo_generation_type", "TEXT_2_VIDEO"),
        current_veo_translation=data.get("veo_translation", True),
        current_veo_resolution=data.get("veo_resolution", "720p"),
        current_veo_seed=data.get("veo_seed"),
        current_veo_watermark=data.get("veo_watermark", ""),
    )


async def _normalize_veo_state(state: FSMContext):
    data = await state.get_data()
    current_model = data.get("v_model", "v3_std")
    if not current_model.startswith("veo3"):
        return

    updates = {}
    current_v_type = data.get("v_type", "text")
    current_ratio = data.get("v_ratio", "16:9")
    veo_generation_type = data.get("veo_generation_type")

    if current_ratio not in {"16:9", "9:16", "Auto"}:
        updates["v_ratio"] = "16:9"

    if current_v_type == "text":
        if veo_generation_type != "TEXT_2_VIDEO":
            updates["veo_generation_type"] = "TEXT_2_VIDEO"
    elif current_v_type == "imgtxt":
        if veo_generation_type not in {
            "FIRST_AND_LAST_FRAMES_2_VIDEO",
            "REFERENCE_2_VIDEO",
        }:
            updates["veo_generation_type"] = "FIRST_AND_LAST_FRAMES_2_VIDEO"
        if current_model != "veo3_fast" and veo_generation_type == "REFERENCE_2_VIDEO":
            updates["veo_generation_type"] = "FIRST_AND_LAST_FRAMES_2_VIDEO"
    else:
        updates["v_type"] = "text"
        updates["veo_generation_type"] = "TEXT_2_VIDEO"

    if "veo_translation" not in data:
        updates["veo_translation"] = True
    if "veo_resolution" not in data:
        updates["veo_resolution"] = "720p"
    if "veo_watermark" not in data:
        updates["veo_watermark"] = ""

    if updates:
        await state.update_data(**updates)


def _build_video_run_summary(
    v_model: str,
    v_type: str,
    v_ratio: str,
    v_duration: int,
    data: dict,
) -> str:
    parts = [
        f"🤖 <code>{get_video_model_label(v_model)}</code>",
        f"📝 <code>{get_video_type_label(v_type)}</code>",
        f"📐 <code>{v_ratio}</code>",
    ]
    if not v_model.startswith("veo3"):
        parts.append(f"⏱ <code>{v_duration}s</code>")

    if v_model == "grok_imagine":
        parts.append(f"🧠 <code>{data.get('grok_mode', 'normal')}</code>")

    if v_model.startswith("veo3"):
        veo_mode = data.get("veo_generation_type", "TEXT_2_VIDEO")
        veo_mode_label_map = {
            "TEXT_2_VIDEO": "Text -> Video",
            "FIRST_AND_LAST_FRAMES_2_VIDEO": "Frames -> Video",
            "REFERENCE_2_VIDEO": "Reference -> Video",
        }
        parts.append(f"🎥 <code>{veo_mode_label_map.get(veo_mode, veo_mode)}</code>")
        parts.append(
            f"🌐 <code>{'перевод вкл' if data.get('veo_translation', True) else 'перевод выкл'}</code>"
        )
        parts.append(f"🖥 <code>{data.get('veo_resolution', '720p')}</code>")
        veo_seed = data.get("veo_seed")
        if veo_seed is not None:
            parts.append(f"🎲 <code>{veo_seed}</code>")
        veo_watermark = data.get("veo_watermark")
        if veo_watermark:
            parts.append(f"🏷 <code>{veo_watermark}</code>")

    return " | ".join(parts)


def _build_image_creation_text(data: dict) -> str:
    current_service = data.get("img_service", "banana_pro")
    current_ratio = data.get("img_ratio", "1:1")
    current_count = data.get("img_count", 1)
    reference_images = data.get("reference_images", [])
    nsfw_enabled = data.get("nsfw_enabled", False)
    ratio_label = current_ratio.replace(":", "∶")
    unit_cost = preset_manager.get_generation_cost(current_service)
    total_cost = unit_cost * current_count

    info_lines = [
        f"• Модель: <code>{get_image_model_label(current_service)}</code>",
        f"• Формат: <code>{ratio_label}</code>",
        f"• Количество: <code>{current_count}</code>",
        f"• Стоимость: <code>{unit_cost}🍌 × {current_count} = {total_cost}🍌</code>",
    ]
    if reference_images:
        info_lines.append(f"• Референсы: <code>{len(reference_images)}</code>")
    if current_service == "grok_imagine_i2i":
        info_lines.append(f"• NSFW: <code>{'Вкл' if nsfw_enabled else 'Выкл'}</code>")

    prompt_hint = (
        "Опишите, что нужно изменить на загруженных фото."
        if current_service == "grok_imagine_i2i"
        else "Опишите, что хотите создать."
    )

    return (
        "🖼 <b>Создание фото</b>\n"
        + "<b>Текущие настройки</b>\n"
        + "\n".join(info_lines)
        + "\n\n<b>Промпт</b>\n"
        + prompt_hint
    )


async def _show_image_creation_screen(message_or_callback, state: FSMContext):
    data = await state.get_data()
    text = _build_image_creation_text(data)
    reply_markup = get_create_image_keyboard(
        current_service=data.get("img_service", "banana_pro"),
        current_ratio=data.get("img_ratio", "1:1"),
        current_count=data.get("img_count", 1),
        num_refs=len(data.get("reference_images", [])),
        nsfw_enabled=data.get("nsfw_enabled", False),
    )

    try:
        await message_or_callback.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
    except Exception:
        await message_or_callback.answer(
            text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )

    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "img_ref_skip_new")
async def handle_img_ref_skip_new(callback: types.CallbackQuery, state: FSMContext):
    """Пропускает загрузку референсов и переходит к вводу промпта"""
    data = await state.get_data()
    generation_type = data.get("generation_type")

    # Очищаем референсы
    await state.update_data(reference_images=[])

    if generation_type == "video":
        # Для видео - показываем параметры видео и промпт
        await _show_video_creation_screen(callback.message, state)
        await callback.answer()
    else:
        await _show_image_creation_screen(callback, state)
        await callback.answer()


@router.callback_query(F.data == "img_ref_continue_new")
async def handle_img_ref_continue_new(callback: types.CallbackQuery, state: FSMContext):
    """Продолжает после загрузки референсов - сразу к параметрам видео (без проверки наличия референсов)"""
    # УБРАНА ПРОВЕРКА: референсы опциональны, всегда продолжаем
    data = await state.get_data()
    generation_type = data.get("generation_type")

    if generation_type == "video":
        # Сразу показываем единый экран с параметрами и промптом (без подтверждения)
        await _show_video_creation_screen(callback.message, state)
        await callback.answer()
        return
    else:
        await _show_image_creation_screen(callback, state)
        await callback.answer()


@router.callback_query(F.data == "ref_reload_new")
async def handle_ref_reload_new(callback: types.CallbackQuery, state: FSMContext):
    """Перезагружает референсы (очищает и начинает заново) для нового UX"""
    data = await state.get_data()
    generation_type = data.get("generation_type")

    # Очищаем референсы
    await state.update_data(reference_images=[])

    # Определяем preset_id для клавиатуры
    preset_id = "new" if generation_type != "video" else "video_new"

    await callback.message.edit_text(
        f"📎 <b>Перезагрузка референсов</b>"
        f"Загружено: <code>0/14</code>"
        f"Отправьте новые фотографии для загрузки референсов:",
        reply_markup=get_reference_images_upload_keyboard(0, 14, preset_id),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_images)


@router.callback_query(F.data == "ref_confirm_new")
async def handle_ref_confirm_new(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждает референсы для нового UX - переходит к выбору модели/формата"""
    data = await state.get_data()
    current_refs = data.get("reference_images", [])

    if not current_refs:
        await callback.answer("Нет загруженных изображений", show_alert=True)
        return

    await _show_image_creation_screen(callback, state)
    await callback.answer()


# Обработчики для меню создания видео
@router.callback_query(F.data == "v_type_text")
async def handle_v_type_text(callback: types.CallbackQuery, state: FSMContext):
    """Выбор типа генерации: текст"""
    data = await state.get_data()
    current_model = data.get("v_model", "v26_pro")
    current_duration = data.get("v_duration", 5)
    current_ratio = data.get("v_ratio", "16:9")

    updates = {"v_type": "text"}
    if current_model.startswith("veo3"):
        updates["veo_generation_type"] = "TEXT_2_VIDEO"
    await state.update_data(**updates)
    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "v_type_imgtxt")
async def handle_v_type_imgtxt(callback: types.CallbackQuery, state: FSMContext):
    """Выбор типа генерации: фото+текст - запрашиваем изображение на том же экране"""
    data = await state.get_data()
    current_model = data.get("v_model", "v26_pro")
    current_duration = data.get("v_duration", 5)
    current_ratio = data.get("v_ratio", "16:9")
    v_image_url = data.get("v_image_url")

    updates = {"v_type": "imgtxt"}
    if current_model.startswith("veo3"):
        updates["veo_generation_type"] = "FIRST_AND_LAST_FRAMES_2_VIDEO"
    await state.update_data(**updates)

    # Показываем сообщение с просьбой загрузить изображение на ТОМ ЖЕ экране
    image_status = ""
    if v_image_url:
        image_status = "\n✅ <b>Изображение загружено!</b>\n"

    text = (
        f"🎬 <b>Создание видео</b>"
        f"⚙️ <b>Текущие настройки:</b>\n"
        f"   📝 Тип: <code>Фото + Текст → Видео</code>\n"
        f"   🤖 Модель: <code>{get_video_model_label(current_model)}</code>\n"
        f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
        f"   📐 Формат: <code>{current_ratio}</code>\n"
        f"{image_status}\n"
        f"<b>📷 Загрузите стартовое изображение</b>"
        f"Отправьте фото, которое станет первым кадром видео.\n"
        f"После загрузки введите промпт для генерации."
        f"<i>Пример: птица летит в небе, волны накатывают на берег</i>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_create_video_keyboard(
            current_v_type="imgtxt",
            current_model=current_model,
            current_duration=current_duration,
            current_ratio=current_ratio,
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    # Не меняем состояние - оставляем waiting_for_input для приёма и фото, и текста
    # State will be waiting_for_input from previous handler


@router.callback_query(F.data == "v_type_video")
async def handle_v_type_video(callback: types.CallbackQuery, state: FSMContext):
    """Выбор типа генерации: видео+текст - запрашиваем несколько видео референсов"""
    from bot.database import get_user_credits

    user_credits = await get_user_credits(callback.from_user.id)

    await state.update_data(v_type="video")

    text = (
        "🎬 <b>Видео + Текст -> Видео</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code>\n\n"
        "<b>Шаг 1. Видео-референсы</b>\n"
        "Загрузка необязательна, но помогает точнее передать:\n"
        "• характер движения\n"
        "• работу камеры\n"
        "• атмосферу сцены\n\n"
        "<i>Можно добавить до 5 коротких видео по 3-10 секунд.</i>\n"
        "Когда всё готово, нажмите <b>▶️ Продолжить</b>.\n"
        "Если референсы не нужны — выберите <b>⏭ Пропустить</b>."
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_reference_videos_upload_keyboard(0, 5, "video_new"),
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.uploading_reference_videos)
    await callback.answer()


@router.callback_query(F.data == "vid_ref_skip_new")
async def handle_vid_ref_skip_new(callback: types.CallbackQuery, state: FSMContext):
    """Пропускает загрузку видео референсов для video+text"""
    await state.update_data(v_reference_videos=[])
    await _show_video_creation_screen(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "vid_ref_continue_new")
async def handle_vid_ref_continue_new(callback: types.CallbackQuery, state: FSMContext):
    """Продолжает после загрузки видео референсов"""
    await _show_video_creation_screen(callback.message, state)
    await callback.answer()


@router.callback_query(F.data.startswith("v_model_"))
async def handle_v_model(callback: types.CallbackQuery, state: FSMContext):
    """Generic handler for all video model selections"""
    model = callback.data.replace("v_model_", "")
    await _apply_video_model_selection(callback, state, model)


@router.callback_query(F.data.startswith("video_model_"))
async def handle_video_model_legacy(callback: types.CallbackQuery, state: FSMContext):
    """Legacy handler for get_video_models_inline_keyboard callbacks"""
    model = callback.data.replace("video_model_", "")
    await _apply_video_model_selection(callback, state, model)


@router.callback_query(F.data.startswith("video_gen_model_"))
async def handle_video_generation_model_legacy(
    callback: types.CallbackQuery, state: FSMContext
):
    """Legacy handler for get_video_generation_model_keyboard callbacks"""
    model = callback.data.replace("video_gen_model_", "")
    await _apply_video_model_selection(callback, state, model)


@router.callback_query(F.data.startswith("opt_v_model_"))
async def handle_video_options_model_legacy(
    callback: types.CallbackQuery, state: FSMContext
):
    """Legacy handler for opt_v_model_* callbacks"""
    model = callback.data.replace("opt_v_model_", "")
    await _apply_video_model_selection(callback, state, model)


@router.callback_query(F.data.startswith("grok_mode_"))
async def handle_grok_mode(callback: types.CallbackQuery, state: FSMContext):
    """Handler for Grok Imagine mode selection (normal/fun/spicy)"""
    mode = callback.data.replace("grok_mode_", "")
    await state.update_data(grok_mode=mode)
    await _show_video_creation_screen(callback, state)
    await callback.answer(f"Режим Grok: {mode.title()}")


async def _apply_video_model_selection(
    callback: types.CallbackQuery, state: FSMContext, model: str
):
    """Apply video model selection across all keyboard variants."""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_duration = data.get("v_duration", 5)
    current_ratio = data.get("v_ratio", "16:9")

    # Set default grok_mode for grok_imagine
    if model == "grok_imagine":
        await state.update_data(grok_mode="normal")
    elif model.startswith("veo3"):
        await state.update_data(
            veo_generation_type=(
                "TEXT_2_VIDEO"
                if current_v_type == "text"
                else "FIRST_AND_LAST_FRAMES_2_VIDEO"
            ),
            veo_translation=data.get("veo_translation", True),
            veo_resolution=data.get("veo_resolution", "720p"),
        )

    # WanX LoRA is text-to-video only, so we force the UI into text mode
    # to expose aspect ratio and duration controls immediately.
    if model.startswith("wanx"):
        current_v_type = "text"
    if model.startswith("veo3") and current_v_type == "video":
        current_v_type = "text"

    await state.update_data(v_model=model, v_type=current_v_type)
    await _normalize_veo_state(state)
    if model.startswith("wanx"):
        await state.update_data(
            wanx_lora_settings=[{"lora_type": "nsfw-general", "lora_strength": 1.0}]
        )

    if model.startswith("wanx"):
        await callback.message.edit_text(
            "🎬 <b>WanX LoRA</b>"
            "Выберите формат и длительность для генерации:\n"
            "• 📐 Доступные aspect ratio\n"
            "• ⏱ Доступное время"
            "После выбора параметров введите промпт.",
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
    else:
        await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


# Обработчики формата видео
@router.callback_query(F.data == "ratio_1_1")
async def handle_video_ratio_1_1(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата 1:1"""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v26_pro")
    current_duration = data.get("v_duration", 5)

    await state.update_data(v_ratio="1:1")

    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "ratio_16_9")
async def handle_video_ratio_16_9(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата 16:9"""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v26_pro")
    current_duration = data.get("v_duration", 5)

    await state.update_data(v_ratio="16:9")

    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "ratio_9_16")
async def handle_video_ratio_9_16(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата 9:16"""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v26_pro")
    current_duration = data.get("v_duration", 5)

    await state.update_data(v_ratio="9:16")

    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "ratio_4_3")
async def handle_video_ratio_4_3(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата 4:3"""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v26_pro")
    current_duration = data.get("v_duration", 5)

    await state.update_data(v_ratio="4:3")

    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "ratio_3_2")
async def handle_video_ratio_3_2(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата 3:2"""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v26_pro")
    current_duration = data.get("v_duration", 5)

    await state.update_data(v_ratio="3:2")

    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "ratio_2_3")
async def handle_video_ratio_2_3(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата 2:3"""
    await state.update_data(v_ratio="2:3")
    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "ratio_Auto")
async def handle_video_ratio_auto(callback: types.CallbackQuery, state: FSMContext):
    """Выбор автоматического формата для Veo"""
    await state.update_data(v_ratio="Auto")
    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


# Обработчики длительности видео
@router.callback_query(F.data == "video_dur_5")
async def handle_video_dur_5(callback: types.CallbackQuery, state: FSMContext):
    """Выбор длительности 5 сек"""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v26_pro")
    current_ratio = data.get("v_ratio", "16:9")

    await state.update_data(v_duration=5)

    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "video_dur_10")
async def handle_video_dur_10(callback: types.CallbackQuery, state: FSMContext):
    """Выбор длительности 10 сек"""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v26_pro")
    current_ratio = data.get("v_ratio", "16:9")

    await state.update_data(v_duration=10)

    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "video_dur_15")
async def handle_video_dur_15(callback: types.CallbackQuery, state: FSMContext):
    """Выбор длительности 15 сек"""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v26_pro")
    current_ratio = data.get("v_ratio", "16:9")

    await state.update_data(v_duration=15)

    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "video_dur_6")
async def handle_video_dur_6(callback: types.CallbackQuery, state: FSMContext):
    """Выбор длительности 6 сек (Grok Imagine)"""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v26_pro")
    current_ratio = data.get("v_ratio", "16:9")

    await state.update_data(v_duration=6, v_model="grok_imagine")

    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "video_dur_20")
async def handle_video_dur_20(callback: types.CallbackQuery, state: FSMContext):
    """Выбор длительности 20 сек (Grok Imagine)"""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v26_pro")
    current_ratio = data.get("v_ratio", "16:9")

    await state.update_data(v_duration=20, v_model="grok_imagine")

    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "video_dur_30")
async def handle_video_dur_30(callback: types.CallbackQuery, state: FSMContext):
    """Выбор длительности 30 сек (Grok Imagine)"""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_model = data.get("v_model", "v26_pro")
    current_ratio = data.get("v_ratio", "16:9")

    await state.update_data(v_duration=30, v_model="grok_imagine")

    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


# =============================================================================
# НОВЫЙ UX: МЕНЮ СОЗДАНИЯ ФОТО (get_create_image_keyboard)
# =============================================================================


@router.callback_query(F.data == "model_flux_pro")
async def handle_model_flux_pro(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели FLUX.2 Pro"""
    await state.update_data(img_service="flux_pro")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "model_nanobanana")
async def handle_model_nanobanana(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Nano Banana"""
    await state.update_data(img_service="nanobanana")
    await _show_image_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_banana_pro")
async def handle_model_banana_pro(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Banana Pro"""
    await state.update_data(img_service="banana_pro")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "model_banana_2")
async def handle_model_banana_2(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Banana 2 (Gemini 3.1 Flash Image Preview)"""
    await state.update_data(img_service="banana_2")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "model_seedream_edit")
async def handle_model_seedream_edit(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Seedream 4.5"""
    await state.update_data(img_service="seedream_edit")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "model_grok_i2i")
async def handle_model_grok_i2i(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Grok Imagine i2i (фото + текст)"""
    data = await state.get_data()
    nsfw_enabled = data.get("nsfw_enabled", False)

    await state.update_data(img_service="grok_imagine_i2i", nsfw_enabled=nsfw_enabled)
    await _show_image_creation_screen(callback, state)
    await callback.answer()


# Обработчики формата изображения
@router.callback_query(F.data == "img_ratio_1_1")
async def handle_img_ratio_1_1(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 1:1"""
    await state.update_data(img_ratio="1:1")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ratio_16_9")
async def handle_img_ratio_16_9(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 16:9"""
    await state.update_data(img_ratio="16:9")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ratio_9_16")
async def handle_img_ratio_9_16(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 9:16"""
    await state.update_data(img_ratio="9:16")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ratio_4_3")
async def handle_img_ratio_4_3(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 4:3"""
    await state.update_data(img_ratio="4:3")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ratio_3_2")
async def handle_img_ratio_3_2(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 3:2"""
    await state.update_data(img_ratio="3:2")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data.startswith("img_count_"))
async def handle_img_count(callback: types.CallbackQuery, state: FSMContext):
    """Выбор количества изображений для пакетной генерации."""
    try:
        img_count = int(callback.data.replace("img_count_", ""))
    except ValueError:
        await callback.answer()
        return

    if img_count not in {1, 2, 4, 6}:
        await callback.answer()
        return

    await state.update_data(img_count=img_count)
    await _show_image_creation_screen(callback, state)
    await callback.answer(f"Количество: {img_count}")


# =============================================================================
# СЛУЖЕБНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С ФАЙЛАМИ
# =============================================================================


def save_uploaded_file(file_bytes: bytes, file_ext: str = "png") -> Optional[str]:
    """
    Сохраняет загруженный файл в папку static/uploads и возвращает публичный URL.
    """
    try:
        # Создаём поддиректорию по дате
        date_str = datetime.now().strftime("%Y%m%d")
        upload_dir = os.path.join("static", "uploads", date_str)
        os.makedirs(upload_dir, exist_ok=True)

        # Генерируем уникальное имя файла
        file_id = str(uuid.uuid4())[:8]
        filename = f"{file_id}.{file_ext}"
        filepath = os.path.join(upload_dir, filename)

        # Сохраняем файл
        with open(filepath, "wb") as f:
            f.write(file_bytes)

        # Формируем публичный URL
        # nginx настроен на /uploads/ -> static/uploads/
        base_url = config.static_base_url
        public_url = f"{base_url}/uploads/{date_str}/{filename}"

        logger.info(f"Saved uploaded file: {public_url}")
        return public_url

    except Exception as e:
        logger.exception(f"Error saving uploaded file: {e}")
        return None


async def _send_original_document(
    send_callable,
    result: bytes,
    saved_url: Optional[str],
    filename: str = "original.png",
):
    """Helper to send original document with fallbacks and logging.

    send_callable: coroutine function like message.answer_document
    """
    try:
        logger.info("Sending original document via BufferedInputFile")
        doc = types.BufferedInputFile(result, filename=filename)
        await send_callable(
            document=doc, caption="📥 Исходный файл (оригинал)", parse_mode="HTML"
        )
        logger.info("Original document sent (BufferedInputFile)")
        return
    except Exception:
        logger.exception(
            "Failed to send original document via BufferedInputFile, trying fallback"
        )

    try:
        if saved_url:
            logger.info("Sending original document via saved URL")
            await send_callable(
                document=saved_url,
                caption="📥 Исходный файл (оригинал)",
                parse_mode="HTML",
            )
            logger.info("Original document sent via URL")
            return

        bio = io.BytesIO(result)
        bio.name = filename
        bio.seek(0)
        logger.info("Sending original document via BytesIO fallback")
        await send_callable(
            document=bio, caption="📥 Исходный файл (оригинал)", parse_mode="HTML"
        )
        logger.info("Original document sent via BytesIO")
    except Exception:
        logger.exception("Fallback to send original document failed")


async def _send_download_link(send_callable, saved_url: str):
    """Send a small message with an inline URL button to download the original file."""
    try:
        kb = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="📥 Скачать оригинал", url=saved_url)]
            ]
        )
        await send_callable(
            f"📥 <b>Исходник</b> — можно скачать по ссылке:",
            reply_markup=kb,
            parse_mode="HTML",
        )
        logger.info("Sent download link to user")
    except Exception:
        logger.exception("Failed to send download link")


# =============================================================================
# ОСНОВНЫЕ ОБРАБОТЧИКИ БЕЗ ПРЕСЕТОВ
# =============================================================================


@router.callback_query(F.data == "generate_image")
async def start_image_generation(callback: types.CallbackQuery, state: FSMContext):
    """Начинает генерацию изображения - Шаг 1: загрузка референсов"""
    user_credits = await get_user_credits(callback.from_user.id)
    settings = await get_user_settings(callback.from_user.id)
    image_service = settings.get("image_service", "nanobanana")

    # Инициализируем опции
    await state.set_state(GenerationStates.waiting_for_image)
    await state.update_data(
        generation_type="image",
        image_service=image_service,
        reference_images=[],
        generation_options={
            "model": image_service,
            "aspect_ratio": "1:1",
            "quality": "pro",
        },
    )

    # Названия и стоимость в зависимости от сервиса
    if image_service == "novita" or image_service == "flux_pro":
        model_name = "✨ FLUX.2 Pro"
        model_cost = str(preset_manager.get_generation_cost("z_image_turbo"))
    elif image_service == "seedream":
        model_name = "🎨 Seedream"
        model_cost = str(preset_manager.get_generation_cost("seedream"))
    elif image_service == "z_image_turbo":
        model_name = "🚀 Z-Image Turbo LoRA"
        model_cost = str(preset_manager.get_generation_cost("z_image_turbo"))
    else:  # nanobanana
        model_name = "🍌 Nano Banana"
        model_cost = str(preset_manager.get_generation_cost("gemini-2.5-flash"))

    # Шаг 1: Загрузка референсов
    await callback.message.edit_text(
        f"🖼 <b>Генерация фото</b>"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: {model_name} ({model_cost}🍌)"
        f"<b>Шаг 1: Референсы (опционально)</b>"
        f"Загрузите изображения для:\n"
        f"• Точного сходства с объектом\n"
        f"• Сохранения стиля\n"
        f"• Персонажей (до 4 фото)"
        f"После загрузки нажмите ▶️ Продолжить\n"
        f"Или ⏭ Пропустить, если референсы не нужны",
        reply_markup=get_reference_images_upload_keyboard(0, 14, "generate_image"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "edit_image")
async def start_image_editing(callback: types.CallbackQuery, state: FSMContext):
    """Начинает редактирование изображения с возможностью сохранения лиц через референсы"""
    await state.set_state(GenerationStates.waiting_for_image)

    user_credits = await get_user_credits(callback.from_user.id)

    # Сохраняем модель и тип генерации в state + инициализируем референсы
    await state.update_data(
        generation_type="image_edit",
        preferred_model="pro",  # Для редактирования используем Pro для лучшего качества
        reference_images=[],  # Для сохранения лиц
    )

    # Получаем стоимость редактирования через preset_manager
    edit_cost = preset_manager.get_generation_cost("gemini-3-pro-image-preview")

    await callback.message.edit_text(
        f"✏️ <b>Редактирование фото</b>"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: 💎 Banano Pro ({edit_cost}🍌, 4K, сохранение лиц)"
        f"<b>Как редактировать:</b>\n"
        f"1. Загрузите <b>главное фото</b> для редактирования\n"
        f"2. Добавьте до <b>4 фото лица</b> для сохранения (опционально)\n"
        f"3. Опишите что изменить"
        f"<i>💡 Для сохранения лица: загрузите сначала главное фото,\n"
        f"потом фото лица для сохранения, затем введите промпт</i>",
        reply_markup=get_back_keyboard("back_main"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "generate_video")
async def start_video_generation(callback: types.CallbackQuery, state: FSMContext):
    """Начинает генерацию видео без пресета - сразу запрашивает промпт"""
    await state.set_state(GenerationStates.waiting_for_input)
    await state.update_data(generation_type="video")

    user_credits = await get_user_credits(callback.from_user.id)
    settings = await get_user_settings(callback.from_user.id)
    video_model = settings["preferred_video_model"]

    # Map model codes to names
    model_names = {
        "v3_std": "Kling 3 Std",
        "v3_pro": "Kling 3 Pro",
        "v3_omni_std": "Kling 3 Std",
        "v3_omni_pro": "Kling 3 Pro",
    }
    # Используем preset_manager для получения стоимости
    model_cost = str(preset_manager.get_video_cost(video_model, 5))
    model_name = model_names.get(video_model, video_model)

    # Простые опции видео
    video_options = {
        "duration": 5,
        "aspect_ratio": "16:9",
        "quality": "std",
        "generate_audio": True,
    }
    await state.update_data(video_options=video_options)

    await callback.message.edit_text(
        f"🎬 <b>Генерация видео</b>"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: {model_name} ({model_cost}🍌)"
        f"<b>Опции видео:</b>\n"
        f"   ⏱ Длительность: <code>{video_options.get('duration', 5)} сек</code>\n"
        f"   📐 Формат: <code>{video_options.get('aspect_ratio', '16:9')}</code>\n"
        f"   🔊 Со звуком: <code>{'Да' if video_options.get('generate_audio') else 'Нет'}</code>"
        f"Опишите видео, которое хотите создать:\n"
        f"• Что происходит в сцене\n"
        f"• Движение камеры\n"
        f"• Стиль и атмосфера"
        f"<i>Чем подробнее описание — тем лучше результат!</i>",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="⚙️ Изменить опции", callback_data="video_options_change"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="🔙 Назад", callback_data="back_main"
                    )
                ],
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "video_options_change")
async def handle_video_options_change(callback: types.CallbackQuery, state: FSMContext):
    """Показывает клавиатуру опций видео (длительность, формат, звук)"""
    data = await state.get_data()
    video_options = data.get(
        "video_options",
        {
            "duration": 5,
            "aspect_ratio": "16:9",
            "quality": "std",
            "generate_audio": True,
        },
    )

    user_prompt = data.get("user_prompt", "")

    # Если промпт ещё не введён, показываем дефолтный текст
    prompt_text = user_prompt if user_prompt else "<i>Опишите видео ниже</i>"

    await callback.message.edit_text(
        f"🎬 <b>Настройка видео</b>"
        f"Промпт: <code>{prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}</code>"
        f"Выберите параметры и нажмите ▶️ Запустить:"
        f"<i>⏱ Длительность: {video_options.get('duration', 5)} сек\n"
        f"📐 Формат: {video_options.get('aspect_ratio', '16:9')}\n"
        f"🔊 Звук: {'Да' if video_options.get('generate_audio') else 'Нет'}</i>",
        reply_markup=get_video_options_no_preset_keyboard(
            video_options.get("duration", 5),
            video_options.get("aspect_ratio", "16:9"),
            video_options.get("generate_audio", True),
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "edit_video")
async def start_video_editing(callback: types.CallbackQuery, state: FSMContext):
    """Начинает редактирование видео - предлагает выбрать тип входных данных"""
    await state.clear()

    user_credits = await get_user_credits(callback.from_user.id)
    settings = await get_user_settings(callback.from_user.id)
    video_model = settings["preferred_i2v_model"]

    # Map model codes to names
    model_names = {
        "v3_std": "Kling 3 Std",
        "v3_pro": "Kling 3 Pro",
        "v3_omni_std": "Kling 3 Std",
        "v3_omni_pro": "Kling 3 Pro",
    }
    # Используем preset_manager для получения стоимости
    model_cost = str(preset_manager.get_video_cost(video_model, 5))
    model_name = model_names.get(video_model, video_model)

    # Инициализируем опции для видео-эффектов
    video_edit_options = {
        "quality": "std",  # std или pro
        "duration": 5,
        "aspect_ratio": "16:9",
    }
    await state.update_data(video_edit_options=video_edit_options)

    from bot.keyboards import get_video_edit_input_type_keyboard

    await callback.message.edit_text(
        f"✂️ <b>Видео-эффекты</b>"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: {model_name} ({model_cost}🍌)"
        f"<b>Преобразование видео</b>\n"
        f"Выберите, что хотите загрузить:"
        f"🎬 <b>Видео</b> - преобразование видео\n"
        f"🖼 <b>Фото</b> - создание видео из изображения"
        f"<i>Загрузите медиафайл и опишите эффект</i>",
        reply_markup=get_video_edit_input_type_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "image_to_video")
async def start_image_to_video(callback: types.CallbackQuery, state: FSMContext):
    """Начинает генерацию видео из фото - запрашивает фото"""
    await state.set_state(GenerationStates.waiting_for_image)
    await state.update_data(generation_type="image_to_video")

    user_credits = await get_user_credits(callback.from_user.id)
    settings = await get_user_settings(callback.from_user.id)
    video_model = settings["preferred_i2v_model"]

    # Map model codes to names
    model_names = {
        "v3_std": "Kling 3 Std",
        "v3_pro": "Kling 3 Pro",
        "v3_omni_std": "Kling 3 Std",
        "v3_omni_pro": "Kling 3 Pro",
    }
    # Используем preset_manager для получения стоимости
    model_cost = str(preset_manager.get_video_cost(video_model, 5))
    model_name = model_names.get(video_model, video_model)

    # Простые опции видео
    video_options = {
        "duration": 5,
        "aspect_ratio": "16:9",
        "quality": "std",
        "generate_audio": True,
    }
    await state.update_data(video_options=video_options)

    await callback.message.edit_text(
        f"🖼 <b>Фото в видео</b>"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: {model_name} ({model_cost}🍌)"
        f"<b>Image to Video</b>\n"
        f"Загрузите изображение,\n"
        f"которое хотите превратить в видео.\n"
        f"После загрузки опишите движение."
        f"<i>Например: птица летит в небе, волны накатывают на берег</i>",
        reply_markup=get_back_keyboard("back_main"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


# =============================================================================
# ОБРАБОТЧИКИ ОПЦИЙ ВИДЕО-ЭФФЕКТОВ
# =============================================================================


@router.callback_query(F.data.startswith("video_edit_input_"))
async def handle_video_edit_input_type(
    callback: types.CallbackQuery, state: FSMContext
):
    """Выбор типа входного медиа для видео-эффектов: видео или изображение"""
    choice = callback.data.replace("video_edit_input_", "")

    if choice == "video":
        await state.set_state(GenerationStates.waiting_for_video)
        await state.update_data(
            generation_type="video_edit",
            video_edit_input_type="video",
            has_video=False,
            has_image=False,
        )
        text = (
            "✂️ <b>Видео-эффекты</b>"
            "<b>Режим: Преобразование видео</b>"
            "Загрузите видео (3-10 секунд), которое хотите преобразить.\n"
            "После загрузки опишите желаем эффект."
        )
    else:
        await state.set_state(GenerationStates.waiting_for_image)
        await state.update_data(
            generation_type="video_edit_image",
            video_edit_input_type="image",
            has_video=False,
            has_image=False,
        )
        text = (
            "✂️ <b>Видео-эффекты</b>"
            "<b>Режим: Создание видео из фото</b>"
            "Загрузите изображение, которое хотите превратить в видео.\n"
            "После загрузки опишите движение и эффект."
        )

    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard("edit_video"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "video_edit_change_type")
async def handle_video_edit_change_type(
    callback: types.CallbackQuery, state: FSMContext
):
    """Сброс и выбор нового типа входного медиа для видео-эффектов"""
    video_edit_options = {"quality": "std", "duration": 5, "aspect_ratio": "16:9"}
    await state.update_data(video_edit_options=video_edit_options)

    from bot.keyboards import get_video_edit_input_type_keyboard

    user_credits = await get_user_credits(callback.from_user.id)

    await callback.message.edit_text(
        f"✂️ <b>Видео-эффекты</b>"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов"
        f"<b>Преобразование видео</b>\n"
        f"Выберите, что хотите загрузить:"
        f"🎬 <b>Видео</b> - преобразование видео\n"
        f"🖼 <b>Фото</b> - создание видео из изображения"
        f"<i>Загрузите медиафайл и опишите эффект</i>",
        reply_markup=get_video_edit_input_type_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("video_edit_quality_"))
async def handle_video_edit_quality(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора качества для видео-эффектов"""
    quality = callback.data.replace("video_edit_quality_", "")

    data = await state.get_data()
    video_edit_options = data.get("video_edit_options", {})
    video_edit_options["quality"] = quality
    await state.update_data(video_edit_options=video_edit_options)

    await show_video_edit_options(callback, state, quality, video_edit_options)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("video_edit_duration_"))
async def handle_video_edit_duration(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора длительности для видео-эффектов"""
    duration = int(callback.data.replace("video_edit_duration_", ""))

    data = await state.get_data()
    video_edit_options = data.get("video_edit_options", {})
    video_edit_options["duration"] = duration
    await state.update_data(video_edit_options=video_edit_options)

    await show_video_edit_options(
        callback, state, video_edit_options.get("quality", "std"), video_edit_options
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("video_edit_ratio_"))
async def handle_video_edit_ratio(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора формата для видео-эффектов"""
    # Формат: video_edit_ratio_9_16 -> 9:16
    ratio_part = callback.data.replace("video_edit_ratio_", "")
    aspect_ratio = ratio_part.replace("_", ":")

    data = await state.get_data()
    video_edit_options = data.get("video_edit_options", {})
    video_edit_options["aspect_ratio"] = aspect_ratio
    await state.update_data(video_edit_options=video_edit_options)

    await show_video_edit_options(
        callback, state, video_edit_options.get("quality", "std"), video_edit_options
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


async def show_video_edit_options(
    callback: types.CallbackQuery, state: FSMContext, quality: str, options: dict
):
    data = await state.get_data()
    input_type = data.get("video_edit_input_type", "video")
    has_video = data.get("has_video", False)
    has_image = data.get("has_image", False)
    user_prompt = data.get("video_edit_prompt", "")

    quality_emoji = "💎" if quality == "pro" else "⚡"

    if input_type == "video":
        media_status = "✅ Загружено" if has_video else "⏳ Ожидание загрузки"
        media_text = "🎬 Видео"
    else:
        media_status = "✅ Загружено" if has_image else "⏳ Ожидание загрузки"
        media_text = "🖼 Изображение"

    text = f"✂️ <b>Видео-эффекты</b>"
    text += f"<b>Опции:</b>\n"
    text += f"   {quality_emoji} Качество: <code>{quality.upper()}</code>\n"
    text += f"   ⏱ Длительность: <code>{options.get('duration', 5)} сек</code>\n"
    text += f"   📐 Формат: <code>{options.get('aspect_ratio', '16:9')}</code>"
    text += f"{media_text}: {media_status}\n"
    if user_prompt:
        text += f"📝 Промпт: <code>{user_prompt[:50]}...</code>\n"
    text += f"\n<i>Загрузите {'видео' if input_type == 'video' else 'фото'} и опишите эффект</i>"

    await callback.message.edit_text(
        text,
        reply_markup=get_video_edit_keyboard(
            input_type=input_type,
            quality=quality,
            duration=options.get("duration", 5),
            aspect_ratio=options.get("aspect_ratio", "16:9"),
        ),
        parse_mode="HTML",
    )


# =============================================================================
# ОБРАБОТЧИКИ ПРЕСЕТОВ (ЕСЛИ НУЖНО ВЕРНУТЬ)
# =============================================================================


# =============================================================================
# ОБРАБОТЧИКИ ОПЦИЙ ГЕНЕРАЦИИ (НОВОЕ СОГЛАСНО banana_api.md)
# =============================================================================


@router.callback_query(F.data.startswith("model_"))
async def handle_model_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора модели генерации"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        model_type = parts[2]  # "flash" или "pro"

        model = (
            "gemini-2.5-flash-image"
            if model_type == "flash"
            else "gemini-3-pro-image-preview"
        )

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["model"] = model
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            model_emoji = "💎" if "pro" in model else "⚡"
            text = f"✅ <b>Модель изменена</b>"
            text += f"{model_emoji} Теперь используется: <code>{model}</code>"

            if model_type == "flash":
                text += "<i>Быстрая генерация, до 1024px</i>\n"
            else:
                text += "<i>Высокое качество, до 4K, с thinking</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("resolution_"))
async def handle_resolution_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора разрешения изображения"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        resolution = parts[2]  # "1K", "2K", "4K"

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["resolution"] = resolution
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            res_emoji = {"1K": "⚡", "2K": "💎", "4K": "👑"}.get(resolution, "⚡")
            text = f"✅ <b>Разрешение изменено</b>"
            text += f"{res_emoji} Теперь используется: <code>{resolution}</code>"

            resolutions = {
                "1K": "Стандартное качество, 1024px",
                "2K": "HD качество, 2048px",
                "4K": "Максимальное качество, 4096px",
            }
            text += f"<i>{resolutions.get(resolution, '')}</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(
    F.data.startswith("img_ratio_") & ~F.data.startswith("img_ratio_no_preset")
)
async def handle_image_ratio_selection(
    callback: types.CallbackQuery, state: FSMContext
):
    """Обработка выбора формата изображения для пресетов"""
    parts = callback.data.split("_")
    if len(parts) >= 4:
        preset_id = parts[1]
        ratio = f"{parts[2]}:{parts[3]}"  # "16:9"

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["aspect_ratio"] = ratio
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            text = f"✅ <b>Формат изменён</b>"
            text += f"📐 Теперь используется: <code>{ratio}</code>"

            ratios_desc = {
                "1:1": "Квадрат (Instagram, Facebook)",
                "16:9": "Горизонтальный (YouTube)",
                "9:16": "Вертикальный (TikTok, Reels)",
                "4:5": "Портретный (Instagram)",
                "21:9": "Панорамный (Кино)",
            }
            text += f"<i>{ratios_desc.get(ratio, '')}</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("grounding_"))
async def handle_search_grounding(callback: types.CallbackQuery, state: FSMContext):
    """Обработка поискового заземления (Grounding)"""
    parts = callback.data.split("_")
    if len(parts) >= 2:
        preset_id = parts[1]

        # Переключаем опцию
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["enable_search"] = not generation_options.get(
            "enable_search", False
        )
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            enabled = generation_options["enable_search"]
            status = "🟢 ВКЛ" if enabled else "🔴 ВЫКЛ"
            text = f"✅ <b>Поиск в интернете: {status}</b>"

            if enabled:
                text += "<i>AI будет использовать Google Search для актуальной информации</i>\n"
                text += "\nПримеры:\n"
                text += "• Погода на 5 дней\n"
                text += "• Последние новости\n"
                text += "• Актуальные события"
            else:
                text += "<i>Поиск отключён</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("ref_"))
async def handle_reference_images(callback: types.CallbackQuery, state: FSMContext):
    """
    Обработка работы с референсными изображениями (до 14 шт)
    Поддерживает загрузку, управление и подтверждение референсов
    """
    parts = callback.data.split("_")
    action = parts[1] if len(parts) > 1 else ""
    preset_id = parts[2] if len(parts) > 2 else None

    data = await state.get_data()
    current_refs = data.get("reference_images", [])
    max_refs = 14

    if action == "upload":
        # Начинаем загрузку референсных изображений
        await state.set_state(GenerationStates.uploading_reference_images)
        await state.update_data(preset_id=preset_id, reference_images=current_refs)

        await callback.message.edit_text(
            f"📎 <b>Загрузка референсных изображений</b>"
            f"Загружено: <code>{len(current_refs)}/{max_refs}</code>"
            f"Отправьте фотографии (до {max_refs} штук), которые будут использоваться как референсы:\n"
            f"• До 10 объектов с высокой точностью\n"
            f"• До 4 персонажей для консистентности\n"
            f"• До 14 изображений суммарно"
            f"После загрузки нажмите ▶️ Продолжить",
            reply_markup=get_reference_images_upload_keyboard(
                len(current_refs), max_refs, preset_id
            ),
            parse_mode="HTML",
        )

    elif action == "clear":
        # Очищаем все референсы
        await state.update_data(reference_images=[])
        await callback.message.edit_text(
            f"📎 <b>Референсы очищены</b>"
            f"Загружено: <code>0/{max_refs}</code>"
            f"Отправьте фотографии для загрузки референсов:",
            reply_markup=get_reference_images_upload_keyboard(0, max_refs, preset_id),
            parse_mode="HTML",
        )

    elif action == "confirm":
        # Переходим к подтверждению
        if not current_refs:
            await callback.answer("❌ Нет загруженных изображений", show_alert=True)
            return

        # Для нового UX (preset_id == "new") - сразу переходим к выбору модели
        # (пропускаем экран подтверждения референсов)
        if preset_id == "new":
            await _show_image_creation_screen(callback, state)
            await callback.answer()
            await state.set_state(GenerationStates.waiting_for_input)
        else:
            # Для пресетов - сразу переходим к экрану пресета (пропускаем экран подтверждения)
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id
                )
            else:
                # Fallback - показать параметры генерации
                await _show_image_creation_screen(callback, state)
                await state.set_state(GenerationStates.waiting_for_input)

    elif action == "reload":
        # Перезагружаем — очищаем и начинаем заново
        await state.update_data(reference_images=[])
        await state.set_state(GenerationStates.uploading_reference_images)

        await callback.message.edit_text(
            f"📎 <b>Перезагрузка референсов</b>"
            f"Загружено: <code>0/{max_refs}</code>"
            f"Отправьте новые фотографии для загрузки референсов:",
            reply_markup=get_reference_images_upload_keyboard(0, max_refs, preset_id),
            parse_mode="HTML",
        )

    elif action == "accept":
        # Сохраняем референсы в generation_options
        generation_options = data.get("generation_options", {})
        generation_options["reference_images"] = current_refs
        await state.update_data(generation_options=generation_options)

        # Для нового UX (preset_id == "new") - переходим к экрану выбора модели/формата
        # (пропускаем промежуточное меню подтверждения)
        if preset_id == "new":
            await _show_image_creation_screen(callback, state)
            await state.set_state(GenerationStates.waiting_for_input)
        else:
            # Для пресетов - возвращаемся к экрану пресета
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id
                )
            else:
                # Этот код не должен достигаться в нормальном потоке, но оставим для совместимости
                await callback.message.edit_text(
                    "✅ Референсы сохранены!",
                    reply_markup=get_back_keyboard("back_main"),
                )

    else:
        # Показываем справку о референсах (стандартное поведение)
        help_text = get_reference_images_help()

        await callback.message.edit_text(
            help_text,
            reply_markup=get_reference_images_keyboard(preset_id),
            parse_mode="HTML",
        )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


# =============================================================================
# ОБРАБОТЧИКИ ВВОДА ПОЛЬЗОВАТЕЛЯ
# =============================================================================


@router.callback_query(F.data.startswith("custom_"))
async def request_custom_input(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает пользовательский ввод для пресета"""
    preset_id = callback.data.replace("custom_", "")
    preset = preset_manager.get_preset(preset_id)

    if not preset:
        await callback.answer("Пресет не найден")
        return

    await state.update_data(preset_id=preset_id, input_type="custom")

    # UX: Показываем подсказки по промптам
    tips_text = get_prompt_tips()

    # Если требуется загрузка файла
    if preset.requires_upload:
        await state.set_state(GenerationStates.waiting_for_image)

        hint = UserHints.get_hint_for_stage("input")
        await callback.message.edit_text(
            f"📎 <b>Загрузите изображение</b>"
            f"Для пресета: {preset.name}"
            f"После загрузки изображения, {preset.input_prompt or 'введите описание'}"
            f"<i>{hint}</i>",
            reply_markup=get_back_keyboard(f"preset_{preset_id}"),
            parse_mode="HTML",
        )
    else:
        await state.set_state(GenerationStates.waiting_for_input)

        hint = UserHints.get_hint_for_stage("input")
        await callback.message.edit_text(
            f"✏️ <b>Введите ваш вариант</b>"
            f"{preset.input_prompt or 'Опишите, что хотите создать'}"
            f"Примеры для вдохновения:\n"
            f"• Стиль: минимализм, винтаж, футуризм\n"
            f"• Цветовая схема: яркий, пастельный, тёмный\n"
            f"• Эмоция: радостное, удивлённое, задумчивое"
            f"<i>{hint}</i>",
            reply_markup=get_back_keyboard(f"preset_{preset_id}"),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("default_"))
async def use_default_values(callback: types.CallbackQuery, state: FSMContext):
    """Использует пример значений для пресета"""
    preset_id = callback.data.replace("default_", "")
    preset = preset_manager.get_preset(preset_id)

    if not preset:
        await callback.answer("Пресет не найден")
        return

    # Заполняем плейсхолдеры значениями по умолчанию
    defaults = preset_manager.get_default_values("styles") or ["минимализм"]
    color_defaults = preset_manager.get_default_values("color_schemes") or ["яркий"]
    expr_defaults = preset_manager.get_default_values("expressions") or ["радостное"]

    placeholder_values = {}
    for placeholder in preset.placeholders:
        if "style" in placeholder.lower():
            placeholder_values[placeholder] = defaults[0]
        elif "color" in placeholder.lower():
            placeholder_values[placeholder] = color_defaults[0]
        elif "expr" in placeholder.lower():
            placeholder_values[placeholder] = expr_defaults[0]
        else:
            placeholder_values[placeholder] = "пример"

    try:
        final_prompt = preset.format_prompt(**placeholder_values)
    except:
        final_prompt = preset.prompt.replace("{", "").replace("}", "")

    await state.update_data(
        preset_id=preset_id, final_prompt=final_prompt, input_type="default"
    )

    # Показываем финальный промпт с подтверждением
    data = await state.get_data()
    generation_options = data.get("generation_options", {})

    await callback.message.edit_text(
        f"▶️ <b>Подтвердите генерацию</b>"
        f"Пресет: <b>{preset.name}</b>\n"
        f"Стоимость: <code>{preset.cost}</code>🍌"
        f"<b>Промпт:</b>\n"
        f"<code>{final_prompt[:300]}{'...' if len(final_prompt) > 300 else ''}</code>"
        f"{format_generation_options(generation_options)}",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="✅ Запустить", callback_data=f"run_{preset_id}"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="❌ Отмена", callback_data=f"preset_{preset_id}"
                    )
                ],
            ]
        ),
        parse_mode="HTML",
    )


@router.message(GenerationStates.waiting_for_video_prompt, F.photo)
async def process_photo_for_video_prompt_state(
    message: types.Message, state: FSMContext
):
    """
    Обрабатывает фото для imgtxt видео в состоянии waiting_for_video_prompt.
    Первое фото - v_image_url (старт кадр), остальные - reference_images (до 8 рефов, total 9).
    """
    data = await state.get_data()
    v_type = data.get("v_type")
    if v_type != "imgtxt":
        await message.answer("Пожалуйста, отправьте текстовое описание.")
        return

    # Download photo
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)
    image_data = image_bytes.read()

    # Validate
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(image_data))
        width, height = img.size
        logger.info(f"Image validated for Kling: {width}×{height}")
        if width < 300 or height < 300:
            await message.answer(
                f"❌ Изображение слишком маленькое: {width}×{height} (мин 300px)"
            )
            return
    except Exception as e:
        logger.error(f"Image validation failed: {e}")
        await message.answer("❌ Не удалось обработать изображение.")
        return

    image_url = save_uploaded_file(image_data, "png")
    if not image_url:
        await message.answer("❌ Не удалось сохранить фото.")
        return

    v_image_url = data.get("v_image_url")
    reference_images = data.get("reference_images", [])

    start_count = 1 if v_image_url else 0
    current_refs = len(reference_images)
    total = start_count + current_refs + 1  # +1 for this photo
    if total > 9:
        await message.answer("❌ Максимум 9 фото (1 старт + 8 рефов). Введите промпт.")
        return

    if not v_image_url:
        # Первое фото - стартовый кадр
        await state.update_data(v_image_url=image_url)
        logger.info(f"Saved start image for video (1st photo): {image_url}")
        status = "✅ Старт фото установлено! (1/9)"
    else:
        # Последующие - референсы
        reference_images.append(image_url)
        await state.update_data(reference_images=reference_images)
        logger.info(
            f"Saved reference image for video (ref #{current_refs + 1}): {image_url}"
        )
        status = f"✅ Реф. фото добавлено! (total {total}/9)"

    # Update UI with current count
    data = await state.get_data()
    current_model = data.get("v_model", "v3_std")
    current_duration = data.get("v_duration", 5)
    current_ratio = data.get("v_ratio", "16:9")

    start_count = 1 if data.get("v_image_url") else 0
    ref_count = len(data.get("reference_images", []))
    total_photos = start_count + ref_count

    text = (
        f"🎬 <b>Фото + Текст → Видео</b>"
        f"📎 Фото: <code>{total_photos}/9</code> (старт + рефы)"
        f"{status}"
        f"⚙️ Модель: <code>{current_model}</code> | {current_duration}с | {current_ratio}\n"
        f"<b>Отправьте ещё фото или промпт:</b>"
    )

    await message.answer(
        text,
        reply_markup=get_create_video_keyboard(
            current_v_type="imgtxt",
            current_model=current_model,
            current_duration=current_duration,
            current_ratio=current_ratio,
        ),
        parse_mode="HTML",
    )


@router.message(
    GenerationStates.uploading_reference_videos,
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def process_reference_video_upload(message: types.Message, state: FSMContext):
    """
    Обрабатывает загрузку нескольких референсных видео для режима video+text.
    """
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")
    v_reference_videos = data.get("v_reference_videos", [])

    if generation_type == "video" and v_type == "video":
        # Определяем источник файла
        if message.video:
            video_obj = message.video
        elif message.document and message.document.mime_type.startswith("video/"):
            video_obj = message.document
        else:
            await message.answer("❌ Неверный тип файла. Отправьте видео.")
            return

        # Проверяем размер (макс 20MB)
        file_size = getattr(video_obj, "file_size", 0)
        if file_size > 20 * 1024 * 1024:
            await message.answer("❌ Видео слишком большое (макс 20MB).")
            return

        if len(v_reference_videos) >= 5:
            await message.answer(
                "❌ Максимум 5 видео референсов. Нажмите 'Продолжить'.",
                parse_mode="HTML",
            )
            return

        file = await message.bot.get_file(video_obj.file_id)
        video_bytes = await message.bot.download_file(file.file_path)
        video_data = video_bytes.read()

        # Сохраняем видео и получаем URL
        video_url = save_uploaded_file(video_data, "mp4")
        if video_url:
            v_reference_videos.append(video_url)
            await state.update_data(v_reference_videos=v_reference_videos)
            logger.info(f"Added reference video {len(v_reference_videos)}: {video_url}")

            current_count = len(v_reference_videos)
            max_refs = 5
            text = (
                f"📹 <b>Загрузка видео референсов</b>"
                f"Загружено: <code>{current_count}/{max_refs}</code>"
                f"✅ Видео добавлено!"
                f"Отправьте следующее или нажмите кнопку ниже:"
            )
            await message.reply(
                text,
                reply_markup=get_reference_videos_upload_keyboard(
                    current_count, max_refs, "video_new"
                ),
                parse_mode="HTML",
            )
        else:
            await message.answer("❌ Не удалось сохранить видео. Попробуйте ещё раз.")
        return

    await message.answer("Пожалуйста, отправьте видео.")


@router.message(
    GenerationStates.uploading_reference_images,
    F.photo
    | (
        F.document & F.document.mime_type.in_(["image/jpeg", "image/png", "image/webp"])
    ),
)
async def process_reference_photo_upload(message: types.Message, state: FSMContext):
    """Handles reference photo uploads during image creation (up to 14 refs or 9 for video imgtxt)"""
    data = await state.get_data()
    reference_images = data.get("reference_images", [])
    v_type = data.get("v_type")
    max_refs = 9 if v_type == "imgtxt" else 14

    if len(reference_images) >= max_refs:
        await message.answer(
            f"❌ Максимум {max_refs} референсов. Нажмите 'Продолжить' или очистите.",
            parse_mode="HTML",
        )
        return

    # Get the highest quality photo or document
    if message.photo:
        photo = message.photo[-1]
    else:
        photo = message.document

    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)
    image_data = image_bytes.read()

    # Validate image size (min 300x300 for Kie.ai)
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(image_data))
        width, height = img.size
        if width < 300 or height < 300:
            await message.answer(
                f"❌ Изображение слишком маленькое: {width}×{height}\n"
                "Загрузите фото не менее 300×300 px.",
                parse_mode="HTML",
            )
            return
    except Exception as e:
        logger.error(f"Image validation failed: {e}")
        await message.answer("❌ Не удалось обработать изображение. Попробуйте другое.")
        return

    # Save and get URL
    if message.photo:
        file_ext = "jpg"
    else:
        mime_type = message.document.mime_type
        if mime_type == "image/jpeg":
            file_ext = "jpg"
        elif mime_type == "image/png":
            file_ext = "png"
        elif mime_type == "image/webp":
            file_ext = "webp"
        else:
            file_ext = "png"
    image_url = save_uploaded_file(image_data, file_ext)

    if image_url:
        reference_images.append(image_url)
        await state.update_data(reference_images=reference_images)

        preset_id = data.get("preset_id", "new")
        current_count = len(reference_images)

        text = (
            f"📎 <b>Загрузка референсов</b>"
            f"Загружено: <code>{current_count}/{max_refs}</code>"
            f"✅ Фото добавлено!"
            f"Отправьте следующее или нажмите кнопку ниже:"
        )

        try:
            await message.reply(
                text,
                reply_markup=get_reference_images_upload_keyboard(
                    current_count, max_refs, preset_id
                ),
                parse_mode="HTML",
            )
        except:
            await message.answer(
                text,
                reply_markup=get_reference_images_upload_keyboard(
                    current_count, max_refs, preset_id
                ),
                parse_mode="HTML",
            )
        logger.info(f"Reference photo {current_count} added: {image_url}")
    else:
        await message.answer("❌ Не удалось сохранить фото. Попробуйте ещё раз.")


@router.message(GenerationStates.waiting_for_input, F.text)
async def handle_image_prompt_text(message: types.Message, state: FSMContext):
    """Handles text prompt for image generation in waiting_for_input state"""
    data = await state.get_data()
    if data.get("generation_type") != "image":
        return  # Not for images, let other handlers catch

    prompt = message.text.strip()
    if not prompt:
        await message.answer(
            "Нужен текстовый промпт — опишите, какое изображение хотите получить."
        )
        return

    img_service = data.get("img_service", "nanobanana")
    img_ratio = data.get("img_ratio", "1:1")
    img_count = data.get("img_count", 1)
    reference_images = data.get("reference_images", [])
    nsfw_enabled = data.get("nsfw_enabled", False)

    if img_service == "grok_imagine_i2i" and not reference_images:
        await message.answer(
            "Для Grok Imagine сначала добавьте хотя бы одно фото-референс."
        )
        return

    import uuid

    user = await get_or_create_user(message.from_user.id)
    unit_cost = preset_manager.get_generation_cost(img_service)
    total_cost = unit_cost * img_count

    if user.credits < total_cost:
        await message.answer(
            f"❌ Недостаточно бананов! Нужно: <code>{total_cost}</code>🍌",
            reply_markup=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )
        return

    await deduct_credits(message.from_user.id, total_cost)

    model_label = get_image_model_label(img_service)
    ratio_label = img_ratio.replace(":", "∶")
    processing_msg = await message.answer(
        "🖼 <b>Запускаю генерацию</b>\n"
        f"• Модель: <code>{model_label}</code>\n"
        f"• Формат: <code>{ratio_label}</code>\n"
        f"• Количество: <code>{img_count}</code>\n"
        f"• Референсы: <code>{len(reference_images)}</code>",
        parse_mode="HTML",
    )

    started_task_ids = []
    immediate_success_count = 0
    refunded_count = 0
    current_local_task_id = None

    try:
        callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None
        for index in range(img_count):
            local_task_id = f"img_{uuid.uuid4().hex[:12]}"
            current_local_task_id = local_task_id
            await add_generation_task(
                user.id,
                message.from_user.id,
                local_task_id,
                "image",
                img_service,
                model=img_service,
                aspect_ratio=img_ratio,
                prompt=prompt,
                cost=unit_cost,
            )

            if img_service == "banana_2":
                result = await nano_banana_2_service.generate_image(
                    prompt=prompt,
                    aspect_ratio=img_ratio,
                    image_input=reference_images,
                    callback_url=callback_url,
                )
            elif img_service == "banana_pro" or img_service == "nanobanana":
                result = await nano_banana_pro_service.generate_image(
                    prompt=prompt,
                    aspect_ratio=img_ratio,
                    image_input=reference_images,
                    callback_url=callback_url,
                )
            elif img_service in [
                "flux_pro",
                "seedream",
                "seedream_45",
                "seedream_edit",
            ]:
                model_map = {
                    "flux_pro": "seedream/flux-pro",
                    "seedream": "seedream/4.5",
                    "seedream_45": "seedream 4.5",
                    "seedream_edit": "seedream/4.5-edit",
                }
                api_model = model_map.get(img_service, "seedream 4.5")
                result = await seedream_service.generate_image(
                    prompt=prompt,
                    model=api_model,
                    aspect_ratio=img_ratio,
                    image_urls=reference_images,
                    callback_url=callback_url,
                )
            elif img_service == "grok_imagine_i2i":
                result = await grok_service.generate_image_to_image(
                    image_urls=reference_images,
                    prompt=prompt,
                    nsfw_checker=nsfw_enabled,
                    callBackUrl=callback_url,
                )
            else:
                result = await nano_banana_pro_service.generate_image(
                    prompt=prompt,
                    aspect_ratio=img_ratio,
                    image_input=reference_images,
                    callback_url=callback_url,
                )

            if isinstance(result, dict) and "task_id" in result:
                api_task_id = result["task_id"]
                import aiosqlite

                from bot.database import DATABASE_PATH

                async with aiosqlite.connect(DATABASE_PATH) as db:
                    await db.execute(
                        "UPDATE generation_tasks SET task_id = ? WHERE task_id = ? AND user_id = ?",
                        (api_task_id, local_task_id, user.id),
                    )
                    await db.commit()
                started_task_ids.append(api_task_id)
                current_local_task_id = None
            elif result:  # bytes
                immediate_success_count += 1
                saved_url = save_uploaded_file(result, "png")
                await message.answer_photo(
                    photo=types.BufferedInputFile(
                        result, filename=f"generated_{index + 1}.png"
                    ),
                    caption=(
                        "✅ <b>Изображение готово</b>\n"
                        f"• Вариант: <code>{index + 1}/{img_count}</code>\n"
                        f"• Модель: <code>{model_label}</code>\n"
                        f"• Списано: <code>{unit_cost}</code>🍌"
                    ),
                    parse_mode="HTML",
                )
                await _send_original_document(
                    message.answer_document, result, saved_url
                )
                await complete_video_task(local_task_id, saved_url)
                current_local_task_id = None
            else:
                refunded_count += 1
                await add_credits(message.from_user.id, unit_cost)
                await complete_video_task(local_task_id, None)
                current_local_task_id = None

        await processing_msg.delete()

        if started_task_ids:
            ids_preview = "\n".join(
                f"• <code>{task_id}</code>" for task_id in started_task_ids[:6]
            )
            await message.answer(
                "🚀 <b>Генерация запущена</b>\n"
                f"• Модель: <code>{model_label}</code>\n"
                f"• Формат: <code>{ratio_label}</code>\n"
                f"• Запущено задач: <code>{len(started_task_ids)}</code>\n"
                f"• Списано: <code>{unit_cost * len(started_task_ids) + unit_cost * immediate_success_count}</code>🍌\n\n"
                f"{ids_preview}\n\n"
                "Обычно результат приходит в течение 1-3 минут.",
                parse_mode="HTML",
            )

        if refunded_count:
            await message.answer(
                "Часть вариантов не удалось запустить.\n"
                f"Возвращено: <code>{refunded_count * unit_cost}</code>🍌",
                parse_mode="HTML",
            )

        if not started_task_ids and not immediate_success_count:
            await message.answer(
                "Не получилось запустить генерацию.\n"
                "Бананы за эту попытку уже вернулись на баланс."
            )

    except Exception as e:
        logger.exception(f"Image generation error: {e}")
        exception_refund_units = 0
        if current_local_task_id:
            refunded_count += 1
            exception_refund_units += 1
            await complete_video_task(current_local_task_id, None)
            current_local_task_id = None

        launched_or_refunded = (
            len(started_task_ids) + immediate_success_count + refunded_count
        )
        remaining_to_refund = max(0, img_count - launched_or_refunded)
        refund_amount = (exception_refund_units + remaining_to_refund) * unit_cost
        if refund_amount > 0:
            await add_credits(message.from_user.id, refund_amount)
        await message.answer(
            "Что-то пошло не так при запуске генерации.\n"
            "Незапущенные варианты уже возвращены на баланс."
        )

    await state.clear()


@router.message(GenerationStates.waiting_for_reference_video)
async def invalid_reference_video_input(message: types.Message, state: FSMContext):
    """
    Обрабатывает невалидный ввод в состоянии waiting_for_reference_video.
    """
    await message.answer(
        "⚠️ Пожалуйста, отправьте видео файл (макс 50MB)."
        "Это видео будет использовано как референс для стиля/движения."
    )


# =============================================================================
# GROK IMAGINE I2I HANDLERS
# =============================================================================


@router.message(GrokI2IStates.waiting_for_start_image, F.photo)
async def handle_grok_i2i_photo_upload(message: types.Message, state: FSMContext):
    """Загрузка стартового фото для Grok i2i"""
    data = await state.get_data()
    reference_images = data.get("reference_images", [])

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)
    image_data = image_bytes.read()

    # Validate
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(image_data))
        width, height = img.size
        if width < 512 or height < 512:
            await message.answer("❌ Фото слишком маленькое (мин 512x512 px).")
            return
    except:
        await message.answer("❌ Не удалось обработать фото.")
        return

    image_url = save_uploaded_file(image_data, "png")
    if not image_url:
        await message.answer("❌ Не удалось сохранить фото.")
        return

    await state.update_data(grok_start_image_url=image_url, nsfw_enabled=False)

    grok_cost = preset_manager.get_generation_cost("grok_imagine_i2i")

    await message.answer_photo(
        photo=photo.file_id,
        caption=f"✅ Фото загружено!\n💰 <code>{grok_cost}</code>🍌\n\nВыберите настройки:",
        reply_markup=get_grok_i2i_keyboard(
            nsfw_enabled=False, start_image_url=image_url
        ),
        parse_mode="HTML",
    )
    await state.set_state(GrokI2IStates.confirming_settings)


@router.callback_query(F.data == "grok_i2i_nsfw_toggle")
async def handle_grok_i2i_nsfw_toggle(callback: types.CallbackQuery, state: FSMContext):
    """Переключение NSFW для Grok i2i на общем экране создания фото"""
    data = await state.get_data()
    nsfw_enabled = not data.get("nsfw_enabled", False)
    await state.update_data(nsfw_enabled=nsfw_enabled)
    await _show_image_creation_screen(callback, state)
    await callback.answer(f"NSFW: {'Вкл' if nsfw_enabled else 'Выкл'}")
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "grok_i2i_change_image")
async def handle_grok_i2i_change_image(
    callback: types.CallbackQuery, state: FSMContext
):
    """Смена стартового фото"""
    await state.update_data(grok_start_image_url=None, nsfw_enabled=False)
    grok_cost = preset_manager.get_generation_cost("grok_imagine_i2i")
    await callback.message.edit_text(
        f"🖼 <b>Grok Imagine: Фото + Текст</b>\n💰 <code>{grok_cost}</code>🍌\n\n<b>📤 Загрузите новое референсное фото</b>",
        reply_markup=get_back_keyboard("back_main"),
        parse_mode="HTML",
    )
    await state.set_state(GrokI2IStates.waiting_for_start_image)
    await callback.answer()


@router.callback_query(F.data == "grok_i2i_generate")
async def handle_grok_i2i_generate(callback: types.CallbackQuery, state: FSMContext):
    """Переход к вводу промпта для Grok i2i"""
    data = await state.get_data()
    start_image_url = data.get("grok_start_image_url")
    nsfw_enabled = data.get("nsfw_enabled", False)
    if not start_image_url:
        await callback.answer("Сначала загрузите фото!", show_alert=True)
        return

    await state.update_data(
        grok_start_image_url=start_image_url, nsfw_enabled=nsfw_enabled
    )
    grok_cost = preset_manager.get_generation_cost("grok_imagine_i2i")

    await callback.message.edit_text(
        f"🧠 <b>Grok Imagine i2i</b>\n💰 <code>{grok_cost}</code>🍌\n\n"
        f"✅ Фото загружено\n"
        f"🔓 NSFW: {'Вкл' if nsfw_enabled else 'Выкл'}\n\n"
        f"<b>Введите промпт:</b>\n"
        f"Опишите изменения для фото (фото+текст):",
        reply_markup=get_back_keyboard("back_main"),
        parse_mode="HTML",
    )
    await state.set_state(GrokI2IStates.waiting_for_prompt)
    await callback.answer("Введите промпт!")


@router.message(GrokI2IStates.waiting_for_prompt, F.text)
async def handle_grok_i2i_prompt(message: types.Message, state: FSMContext):
    """Запуск Grok i2i задачи по промпту"""
    prompt = message.text.strip()
    if not prompt:
        await message.answer("Опишите, что именно нужно изменить на фото.")
        return

    data = await state.get_data()
    start_image_url = data.get("grok_start_image_url")
    nsfw_enabled = data.get("nsfw_enabled", False)
    reference_images = data.get("reference_images", [])

    if not start_image_url:
        await message.answer(
            "Не удалось найти загруженное фото. Давайте попробуем начать заново."
        )
        await state.clear()
        return

    user = await get_or_create_user(message.from_user.id)
    cost = preset_manager.get_generation_cost("grok_imagine_i2i")

    if not await check_can_afford(message.from_user.id, cost):
        await message.answer(f"Нужно <code>{cost}</code>🍌", parse_mode="HTML")
        return

    await deduct_credits(message.from_user.id, cost)

    task_id = f"grok_i2i_{uuid.uuid4().hex[:12]}"
    await add_generation_task(
        user.id,
        message.from_user.id,
        task_id,
        "image",
        "grok_imagine_i2i",
        prompt=prompt,
        cost=cost,
    )

    await message.answer(
        "🖼 <b>Запускаю генерацию</b>\n"
        "• Модель: <code>Grok Imagine i2i</code>\n"
        f"• Референсы: <code>{len(reference_images) + 1}</code>\n"
        f"• NSFW: <code>{'Вкл' if nsfw_enabled else 'Выкл'}</code>\n\n"
        "Обычно результат приходит в течение 1-3 минут.",
        parse_mode="HTML",
    )

    try:
        callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None
        image_urls = [start_image_url] + reference_images[:4]  # max 5 total

        result = await grok_service.generate_image_to_image(
            image_urls=image_urls,
            prompt=prompt,
            nsfw_checker=nsfw_enabled,
            callBackUrl=callback_url,
        )

        if result and "taskId" in result["data"]:
            api_task_id = result["data"]["taskId"]
            # Update DB with API task ID
            await message.answer(
                "🚀 <b>Генерация запущена</b>\n"
                f"• ID: <code>{api_task_id}</code>\n"
                f"• Списано: <code>{cost}</code>🍌",
                parse_mode="HTML",
            )
        else:
            await add_credits(message.from_user.id, cost)
            await message.answer(
                "Не получилось запустить задачу.\n"
                "Бананы за эту попытку уже вернулись на баланс."
            )
    except Exception as e:
        logger.exception("Grok i2i error")
        await add_credits(message.from_user.id, cost)
        await message.answer(
            "Что-то пошло не так при запуске Grok.\n"
            "Бананы за эту попытку уже возвращены."
        )

    await state.clear()


@router.callback_query(F.data.startswith("v_mode_"))
async def handle_v_mode(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик режимов видео (720p/1080p)"""
    mode = callback.data.replace("v_mode_", "")
    await state.update_data(v_mode=mode)
    await _show_video_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data.startswith("v_orientation_"))
async def handle_v_orientation(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик ориентации видео (image/video)"""
    orientation = callback.data.replace("v_orientation_", "")
    await state.update_data(v_orientation=orientation)
    await _show_video_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "veo_translation_toggle")
async def handle_veo_translation_toggle(
    callback: types.CallbackQuery, state: FSMContext
):
    """Toggle prompt translation for Veo."""
    data = await state.get_data()
    await state.update_data(veo_translation=not data.get("veo_translation", True))
    await _show_video_creation_screen(callback, state)
    await callback.answer("Настройка перевода обновлена")


@router.callback_query(F.data.startswith("veo_resolution_"))
async def handle_veo_resolution(callback: types.CallbackQuery, state: FSMContext):
    """Set Veo resolution."""
    resolution = callback.data.replace("veo_resolution_", "")
    await state.update_data(veo_resolution=resolution)
    await _show_video_creation_screen(callback, state)
    await callback.answer(f"Resolution: {resolution}")


@router.callback_query(F.data.startswith("veo_gen_"))
async def handle_veo_generation_type(callback: types.CallbackQuery, state: FSMContext):
    """Set Veo image generation subtype."""
    generation_type = callback.data.replace("veo_gen_", "")
    data = await state.get_data()
    current_model = data.get("v_model", "veo3_fast")
    if generation_type == "REFERENCE_2_VIDEO" and current_model != "veo3_fast":
        await callback.answer(
            "REFERENCE_2_VIDEO доступен только для Veo 3.1 Fast",
            show_alert=True,
        )
        return
    await state.update_data(
        v_type="imgtxt",
        veo_generation_type=generation_type,
    )
    await _show_video_creation_screen(callback, state)
    await callback.answer("Режим Veo обновлён")


@router.callback_query(F.data == "veo_seed_edit")
async def handle_veo_seed_edit(callback: types.CallbackQuery, state: FSMContext):
    """Prompt user to enter Veo seed."""
    data = await state.get_data()
    current_seed = data.get("veo_seed")
    await callback.message.answer(
        "🎲 Введите seed для Veo (целое число 10000-99999) или `auto`, чтобы сбросить автогенерацию.\n"
        f"Сейчас: <code>{current_seed if current_seed is not None else 'auto'}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_veo_seed)
    await callback.answer()


@router.callback_query(F.data == "veo_watermark_edit")
async def handle_veo_watermark_edit(callback: types.CallbackQuery, state: FSMContext):
    """Prompt user to enter Veo watermark."""
    data = await state.get_data()
    current_watermark = data.get("veo_watermark") or "off"
    await callback.message.answer(
        "🏷 Введите watermark для Veo или `off`, чтобы убрать его.\n"
        f"Сейчас: <code>{current_watermark}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_veo_watermark)
    await callback.answer()


@router.message(GenerationStates.waiting_for_veo_seed, F.text)
async def handle_veo_seed_input(message: types.Message, state: FSMContext):
    """Store Veo seed and return to video creation screen."""
    value = message.text.strip().lower()
    if value in {"auto", "off", "none", "random"}:
        await state.update_data(veo_seed=None)
    else:
        if not value.isdigit():
            await message.answer("❌ Seed должен быть числом 10000-99999 или `auto`.")
            return
        seed = int(value)
        if seed < 10000 or seed > 99999:
            await message.answer("❌ Seed должен быть в диапазоне 10000-99999.")
            return
        await state.update_data(veo_seed=seed)
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_veo_watermark, F.text)
async def handle_veo_watermark_input(message: types.Message, state: FSMContext):
    """Store Veo watermark and return to video creation screen."""
    value = message.text.strip()
    await state.update_data(
        veo_watermark="" if value.lower() in {"off", "none"} else value[:32]
    )
    await _show_video_creation_screen(message, state)


@router.callback_query(F.data.startswith("veo1080_"))
async def handle_veo_1080p_upgrade(callback: types.CallbackQuery, state: FSMContext):
    """Fetch or request Veo 1080p video."""
    task_id = callback.data.replace("veo1080_", "")
    task = await get_task_by_id(task_id)
    if not task or not (task.model or "").startswith("veo3"):
        await callback.answer("Задача Veo не найдена", show_alert=True)
        return

    from bot.services.veo_service import veo_service

    result = await veo_service.get_1080p_video(task_id)
    if not result:
        await callback.answer(
            "Пока не получилось получить версию 1080p. Попробуйте ещё раз чуть позже.",
            show_alert=True,
        )
        return

    if result.get("code") == 200:
        result_url = ((result.get("data") or {}).get("resultUrl")) or ""
        if result_url:
            await callback.message.answer_video(
                video=result_url,
                caption=f"✨ <b>Veo 1080p готово</b>\n🆔 <code>{task_id}</code>",
                parse_mode="HTML",
            )
            await callback.answer("1080p готово")
            return

    await callback.answer(
        result.get("msg", "1080p ещё обрабатывается, попробуйте чуть позже."),
        show_alert=True,
    )


@router.callback_query(F.data.startswith("veo4k_"))
async def handle_veo_4k_upgrade(callback: types.CallbackQuery, state: FSMContext):
    """Fetch or request Veo 4K video."""
    task_id = callback.data.replace("veo4k_", "")
    task = await get_task_by_id(task_id)
    if not task or not (task.model or "").startswith("veo3"):
        await callback.answer("Задача Veo не найдена", show_alert=True)
        return

    from bot.services.veo_service import veo_service

    result = await veo_service.get_4k_video(task_id)
    if not result:
        await callback.answer(
            "Пока не получилось запросить 4K-версию. Попробуйте ещё раз чуть позже.",
            show_alert=True,
        )
        return

    data = result.get("data") or {}
    result_urls = data.get("resultUrls") or []
    if result.get("code") == 200 and result_urls:
        await callback.message.answer_video(
            video=result_urls[0],
            caption=f"🖥 <b>Veo 4K готово</b>\n🆔 <code>{task_id}</code>",
            parse_mode="HTML",
        )
        await callback.answer("4K готово")
        return

    await callback.answer(
        result.get(
            "msg",
            "4K обрабатывается. Нажмите кнопку ещё раз через несколько минут.",
        ),
        show_alert=True,
    )


@router.callback_query(F.data.startswith("veoextend_"))
async def handle_veo_extend_request(callback: types.CallbackQuery, state: FSMContext):
    """Ask for extend prompt for Veo."""
    task_id = callback.data.replace("veoextend_", "")
    task = await get_task_by_id(task_id)
    if not task or not (task.model or "").startswith("veo3"):
        await callback.answer("Задача Veo не найдена", show_alert=True)
        return

    await state.update_data(veo_extend_task_id=task_id, veo_extend_model=task.model)
    await state.set_state(GenerationStates.waiting_for_veo_extend_prompt)
    await callback.message.answer(
        "➕ Отправьте промпт для продолжения Veo-видео.\n"
        "Опишите, как должна развиваться сцена дальше."
    )
    await callback.answer()


@router.message(GenerationStates.waiting_for_veo_extend_prompt, F.text)
async def handle_veo_extend_prompt(message: types.Message, state: FSMContext):
    """Start Veo extension task from user prompt."""
    prompt = message.text.strip()
    if not prompt:
        await message.answer("⚠️ Введите промпт для продолжения видео.")
        return

    data = await state.get_data()
    source_task_id = data.get("veo_extend_task_id")
    source_model = data.get("veo_extend_model", "veo3_fast")
    if not source_task_id:
        await message.answer("❌ Не найден исходный task_id Veo.")
        await state.clear()
        return

    extend_model_map = {
        "veo3": "quality",
        "veo3_fast": "fast",
        "veo3_lite": "lite",
    }
    extend_model = extend_model_map.get(source_model, "fast")
    cost_map = {"quality": 22, "fast": 15, "lite": 10}
    cost = cost_map.get(extend_model, 15)

    if not await check_can_afford(message.from_user.id, cost):
        await message.answer(
            f"❌ Недостаточно бананов для продления. Нужно: <code>{cost}</code>🍌",
            parse_mode="HTML",
        )
        return

    await deduct_credits(message.from_user.id, cost)
    await message.answer("🎬 Продлеваю Veo-видео...")

    from bot.services.veo_service import veo_service

    result = await veo_service.extend_video(
        task_id=source_task_id,
        prompt=prompt,
        model=extend_model,
        callBackUrl=(config.kie_notification_url if config.WEBHOOK_HOST else None),
    )

    if not result or "task_id" not in result:
        await add_credits(message.from_user.id, cost)
        await message.answer(
            "❌ Не получилось запустить продление. Бананы за попытку уже возвращены."
        )
        await state.clear()
        return

    user = await get_or_create_user(message.from_user.id)
    await add_generation_task(
        user.id,
        message.from_user.id,
        result["task_id"],
        "video",
        "veo_extend",
        model=source_model,
        prompt=prompt,
        cost=cost,
    )
    await message.answer(
        f"✅ Продление Veo запущено!\n🆔 <code>{result['task_id']}</code>\n💰 <code>{cost}</code>🍌",
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data.startswith("motion_mode_"))
async def handle_motion_mode(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик режимов Motion Control"""
    mode = callback.data.replace("motion_mode_", "")
    await state.update_data(motion_mode=mode)
    data = await state.get_data()
    current_orientation = data.get("motion_orientation", "video")
    await callback.message.edit_reply_markup(
        get_motion_control_keyboard(mode, current_orientation)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("motion_orientation_"))
async def handle_motion_orientation(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик ориентации Motion Control"""
    orientation = callback.data.replace("motion_orientation_", "")
    await state.update_data(motion_orientation=orientation)
    data = await state.get_data()
    current_mode = data.get("motion_mode", "720p")
    await callback.message.edit_reply_markup(
        get_motion_control_keyboard(current_mode, orientation)
    )
    await callback.answer()


@router.message(GenerationStates.waiting_for_video_prompt, F.text)
async def handle_video_prompt_text(message: types.Message, state: FSMContext):
    """Обрабатывает ввод промпта для видео и motion control (новый UX)."""
    logger.info(f"[DEBUG STATE] Current state: {await state.get_state()}")
    logger.info(f"Video prompt handler triggered for user {message.from_user.id}")
    prompt = message.text.strip()

    if not prompt:
        await message.answer("⚠️ Введите описание видео перед запуском генерации.")
        return

    data = await state.get_data()
    generation_type = data.get("generation_type", "")
    logger.info(f"Generation type: {generation_type}")

    await state.update_data(user_prompt=prompt)

    if generation_type == "motion_control":
        logger.info("Calling run_motion_control")
        await run_motion_control(message, state, prompt)
    else:
        logger.info("Calling run_no_preset_video_from_message")
        await run_no_preset_video_from_message(message, state, prompt)


async def run_no_preset_video_from_message(
    message: types.Message, state: FSMContext, prompt: str
):
    """Запускает видео генерацию без пресета (новый UX с v_type, v_model и т.д.)"""
    data = await state.get_data()
    v_type = data.get("v_type", "text")
    v_model = data.get("v_model", "v3_std")
    video_urls = data.get("v_reference_videos", [])

    v_duration = int(data.get("v_duration", 5))
    # Cap duration for imgtxt except for Grok Imagine which supports up to 30s
    if (
        v_type == "imgtxt"
        and v_model not in {"grok_imagine"}
        and not v_model.startswith("veo3")
    ):
        v_duration = min(v_duration, 10)
    v_ratio = data.get("v_ratio", "16:9")
    v_image_url = data.get("v_image_url")
    v_video_url = data.get("v_video_url")
    veo_generation_type = data.get("veo_generation_type", "TEXT_2_VIDEO")
    veo_translation = data.get("veo_translation", True)
    veo_resolution = data.get("veo_resolution", "720p")
    veo_seed = data.get("veo_seed")
    veo_watermark = data.get("veo_watermark", "")

    image_url = data.get("v_image_url")
    video_urls = data.get("v_reference_videos", []) if v_type == "video" else None
    image_refs = data.get("reference_images", [])

    elements_list = None
    if v_type == "imgtxt" and image_refs:
        elements_list = [
            {
                "description": "reference photos for video generation consistency and style",
                "reference_image_urls": image_refs[
                    :12
                ],  # Kling elements support up to 3x4=12 refs
            }
        ]

    cost = preset_manager.get_video_cost(v_model, v_duration)

    user = await get_or_create_user(message.from_user.id)
    is_admin = config.is_admin(message.from_user.id)

    # Admin free access
    if is_admin:
        logger.info(
            f"Admin {message.from_user.id} - free access (skipped {cost} credits)"
        )
    else:
        if not await check_can_afford(message.from_user.id, cost):
            await message.answer(
                f"❌ Недостаточно бананов!\nНужно: <code>{cost}</code>🍌\nПополните баланс.",
                reply_markup=get_main_menu_keyboard(
                    await get_user_credits(message.from_user.id)
                ),
                parse_mode="HTML",
            )
            await state.clear()
            return
        await deduct_credits(message.from_user.id, cost)

    run_summary = _build_video_run_summary(v_model, v_type, v_ratio, v_duration, data)

    processing_msg = await message.answer(
        f"🎬 <b>Видео генерируется...</b>"
        f"{run_summary}\n"
        f"💰 Стоимость: <code>{cost}</code>🍌"
        f"<i>Ожидайте 1-5 минут</i>",
        parse_mode="HTML",
    )

    try:
        from bot.services.grok_service import grok_service
        from bot.services.kling_service import kling_service
        from bot.services.veo_service import veo_service

        if v_model.startswith("veo3"):
            veo_image_urls = []
            if veo_generation_type == "TEXT_2_VIDEO":
                veo_image_urls = []
            elif veo_generation_type == "FIRST_AND_LAST_FRAMES_2_VIDEO":
                if image_url:
                    veo_image_urls.append(image_url)
                elif image_refs:
                    veo_image_urls.append(image_refs[0])
                if image_refs:
                    for ref_url in image_refs:
                        if ref_url not in veo_image_urls:
                            veo_image_urls.append(ref_url)
                            if len(veo_image_urls) >= 2:
                                break
            elif veo_generation_type == "REFERENCE_2_VIDEO":
                if v_model != "veo3_fast":
                    await message.answer(
                        "❌ REFERENCE_2_VIDEO доступен только для Veo 3.1 Fast."
                    )
                    if not is_admin:
                        await add_credits(message.from_user.id, cost)
                    await processing_msg.delete()
                    await state.clear()
                    return
                veo_image_urls = []
                if image_url:
                    veo_image_urls.append(image_url)
                for ref_url in image_refs:
                    if ref_url not in veo_image_urls:
                        veo_image_urls.append(ref_url)
                    if len(veo_image_urls) >= 3:
                        break

            if veo_generation_type != "TEXT_2_VIDEO" and not veo_image_urls:
                await message.answer(
                    "❌ Для выбранного режима Veo нужно загрузить фото."
                )
                if not is_admin:
                    await add_credits(message.from_user.id, cost)
                await processing_msg.delete()
                await state.clear()
                return

            result = await veo_service.generate_video(
                prompt=prompt,
                model=v_model,
                generation_type=veo_generation_type,
                image_urls=veo_image_urls or None,
                aspect_ratio=v_ratio,
                enable_translation=veo_translation,
                watermark=veo_watermark or None,
                resolution=veo_resolution,
                seeds=veo_seed,
                callBackUrl=(
                    config.kie_notification_url if config.WEBHOOK_HOST else None
                ),
            )

        elif v_model == "grok_imagine":
            if not image_url:
                await message.answer(
                    "❌ Grok Imagine требует стартовое изображение (фото+текст режим)."
                )
                if not is_admin:
                    await add_credits(message.from_user.id, cost)
                await processing_msg.delete()
                await state.clear()
                return

            # Pass start image + references (max 7 total for Grok)
            grok_image_urls = [image_url] + image_refs[:6]
            grok_duration = v_duration  # Supports 6,20,30 sec
            grok_mode = data.get("grok_mode", "normal")
            result = await grok_service.generate_image_to_video(
                image_urls=grok_image_urls,
                prompt=prompt,
                mode=grok_mode,
                duration=grok_duration,
                aspect_ratio=v_ratio,
                callBackUrl=(
                    config.kling_notification_url if config.WEBHOOK_HOST else None
                ),
            )
        else:
            result = await kling_service.generate_video(
                prompt=prompt,
                model=v_model,
                duration=v_duration,
                aspect_ratio=v_ratio,
                image_url=image_url,
                video_urls=video_urls,
                image_input=image_refs if v_type != "imgtxt" else None,
                elements=elements_list,
                webhook_url=(
                    config.kling_notification_url if config.WEBHOOK_HOST else None
                ),
            )

        await processing_msg.delete()

        if result and "task_id" in result:
            await add_generation_task(
                user.id,
                message.from_user.id,
                result["task_id"],
                "video",
                "no_preset_video",
                model=v_model,
                duration=v_duration,
                aspect_ratio=v_ratio,
                prompt=prompt,
                cost=cost,
            )
            await message.answer(
                f"✅ <b>Видео задача запущена!</b>"
                f"🆔 <code>{result['task_id']}</code>\n"
                f"{run_summary}\n"
                f"💰 <code>{cost}</code>🍌 {'списано' if not is_admin else '(админ бесплатно)'}"
                f"⏳ Результат через 1-5 мин в этом чате.",
                parse_mode="HTML",
            )
        else:
            if not is_admin:
                await add_credits(message.from_user.id, cost)
            await message.answer(
                "❌ Не получилось создать задачу. Бананы за попытку уже возвращены."
            )
    except Exception as e:
        logger.exception(f"Video generation error: {e}")
        if not is_admin:
            await add_credits(message.from_user.id, cost)
        await message.answer(
            "❌ Не получилось завершить запуск генерации. Бананы за попытку уже возвращены."
        )

    await state.clear()
