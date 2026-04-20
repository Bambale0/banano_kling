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
    get_advanced_options_keyboard,
    get_aspect_ratio_keyboard,
    get_back_keyboard,
    get_category_keyboard,
    get_create_image_keyboard,
    get_create_video_keyboard,
    get_duration_keyboard,
    get_image_aspect_ratio_keyboard,
    get_image_aspect_ratio_no_preset_edit_keyboard,
    get_image_aspect_ratio_no_preset_keyboard,
    get_image_editing_options_keyboard,
    get_main_menu_keyboard,
    get_model_selection_keyboard,
    get_motion_control_keyboard,
    get_motion_upload_keyboard,
    get_multiturn_keyboard,
    get_prompt_tips_keyboard,
    get_reference_images_confirmation_keyboard,
    get_reference_images_keyboard,
    get_reference_images_upload_keyboard,
    get_reference_videos_upload_keyboard,
    get_resolution_keyboard,
    get_search_grounding_keyboard,
    get_video_edit_confirm_keyboard,
    get_video_edit_input_type_keyboard,
    get_video_edit_keyboard,
    get_video_options_no_preset_keyboard,
)
from bot.services.aleph_service import aleph_service
from bot.services.gemini_service import gemini_service
from bot.services.grok_service import grok_service
from bot.services.nano_banana_2_service import nano_banana_2_service
from bot.services.nano_banana_pro_service import nano_banana_pro_service
from bot.services.preset_manager import preset_manager
from bot.services.seedream_service import seedream_lite_service as seedream_service
from bot.states import GenerationStates
from bot.utils.help_texts import (
    UserHints,
    format_generation_options,
    get_aspect_ratio_help,
    get_editing_help,
    get_error_handling,
    get_model_selection_help,
    get_multiturn_help,
    get_prompt_tips,
    get_reference_images_help,
    get_resolution_help,
    get_search_grounding_help,
    get_success_message,
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
        reference_images=[],  # Реф. изображения для всех режимов (до 14)
        v_reference_videos=[],  # Реф. видео для video+text (до 5)
        user_prompt="",  # Инициализируем пустой промпт
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
        img_service="flux_pro",  # модель изображения
        img_ratio="1:1",
        reference_images=[],  # Инициализируем пустой список референсов
        preset_id="new",  # Для нового UX - указываем, что это "new" режим
    )

    # Показываем экран загрузки референсов (ШАГ 1)
    text = (
        f"🖼 <b>Создание фото</b>\n\n"
        f"💎 Ваш баланс: <code>{user_credits}</code> GOEов\n\n"
        f"<b>Шаг 1: Загрузка референсов (опционально)</b>\n\n"
        f"Загрузите изображения для:\n"
        f"• Точного сходства с объектом\n"
        f"• Сохранения стиля\n"
        f"• Персонажей (до 14 фото)\n\n"
        f"После загрузки нажмите ▶️ Продолжить\n"
        f"Или ⏭ Пропустить, если референсы не нужны"
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
    from bot.database import get_user_credits

    user_credits = await get_user_credits(callback.from_user.id)

    # Инициализируем опции по умолчанию
    await state.update_data(
        generation_type="image",
        img_service="flux_pro",  # модель изображения
        img_ratio="1:1",
        reference_images=[],  # Инициализируем пустой список референсов
        preset_id="new",  # Для нового UX - указываем, что это "new" режим
    )

    # Показываем экран загрузки референсов (ШАГ 1)
    text = (
        f"🖼 <b>Создание фото</b>\n\n"
        f"💎 Ваш баланс: <code>{user_credits}</code> GOEов\n\n"
        f"<b>Шаг 1: Загрузка референсов (опционально)</b>\n\n"
        f"Загрузите изображения для:\n"
        f"• Точного сходства с объектом\n"
        f"• Сохранения стиля\n"
        f"• Персонажей (до 14 фото)\n\n"
        f"После загрузки нажмите ▶️ Продолжить\n"
        f"Или ⏭ Пропустить, если референсы не нужны"
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
        f"🎯 <b>Kling 2.6 Motion Control</b>\n\n"
        f"💎 Баланс: <code>{user_credits}</code>\n\n"
        f"<b>Шаг 1: Reference Image</b>\n\n"
        f"Загрузите четкое фото субъекта:\n"
        f"• Голова, плечи, торс (JPEG/PNG, макс 10MB)\n\n"
        f"<i>Фото станет персонажем с движением из видео</i>"
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
        img_service="flux_pro",
        img_ratio="1:1",
    )

    current_service = "flux_pro"
    current_ratio = "1:1"

    await callback.message.edit_text(
        f"🖼 <b>Создание фото</b>\n\n"
        f"✨ Модель: <code>{current_service}</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>\n\n"
        f"Введите промпт для генерации:",
        reply_markup=get_create_image_keyboard(
            current_service, current_ratio, num_refs=0
        ),
        parse_mode="HTML",
    )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "img_ref_upload_new")
async def handle_img_ref_upload_new(callback: types.CallbackQuery, state: FSMContext):
    """Показывает меню загрузки референсных изображений для нового UX"""
    data = await state.get_data()
    current_service = data.get("img_service", "flux_pro")
    current_ratio = data.get("img_ratio", "1:1")

    # Показываем клавиатуру загрузки референсов
    await callback.message.edit_text(
        f"📎 <b>Загрузка референсов</b>\n\n"
        f"Загрузите изображения для референса (до 14 штук)\n"
        f"После загрузки нажмите 'Продолжить' или 'Пропустить'",
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

    # Тип в настройках
    type_text = (
        "Текст → Видео"
        if current_v_type == "text"
        else (
            "Фото + Текст → Видео"
            if current_v_type == "imgtxt"
            else "Видео + Текст → Видео"
        )
    )

    text = (
        f"🎬 <b>Создание видео</b>\n\n"
        f"{ref_text}"
        f"⚙️ <b>Текущие настройки:</b>\n"
        f"   📝 Тип: <code>{type_text}</code>\n"
        f"   🤖 Модель: <code>{current_model}</code>\n"
        f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
        f"   📐 Формат: <code>{current_ratio}</code>\n"
        f"{media_status}"
        f"{prompt_text}\n"
        f"<b>Введите промпт для генерации:</b>\n\n"
        f"Опишите видео, которое хотите создать:\n"
        f"• Что происходит в сцене\n"
        f"• Движение камеры\n"
        f"• Стиль и атмосфера"
    )

    # Напоминание о загрузке медиа
    if current_v_type == "imgtxt" and not v_image_url:
        text += f"\n\n<i>📷 Загрузите фото, которое станет первым кадром видео</i>"
    elif current_v_type == "video" and not v_reference_videos:
        text += f"\n\n<i>📹 Загрузите референсные видео (до 5, 3-10 сек) для стиля/движения</i>"

    # Используем edit для callback, send для message
    try:
        await message_or_callback.message.edit_text(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
    except Exception:
        await message_or_callback.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )

    # Устанавливаем состояние ожидания промпта для видео
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    logger.info(
        f"[DEBUG] State set to waiting_for_video_prompt for user {message_or_callback.from_user.id if hasattr(message_or_callback, 'from_user') else 'callback'}"
    )


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
        # Для фото - показываем параметры фото
        current_service = data.get("img_service", "flux_pro")
        current_ratio = data.get("img_ratio", "1:1")

        await callback.message.edit_text(
            f"🖼 <b>Создание фото</b>\n\n"
            f"✨ Модель: <code>{current_service}</code>\n"
            f"📐 Формат: <code>{current_ratio}</code>\n\n"
            f"Введите промпт для генерации:",
            reply_markup=get_create_image_keyboard(
                current_service, current_ratio, num_refs=0
            ),
            parse_mode="HTML",
        )

        await callback.answer()
        await state.set_state(GenerationStates.waiting_for_input)


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
        # Для фото - показываем параметры фото
        current_service = data.get("img_service", "flux_pro")
        current_ratio = data.get("img_ratio", "1:1")
        current_refs = data.get("reference_images", [])

        # Сразу показываем экран выбора модели и формата (без экрана подтверждения референсов)
        ref_text = (
            f"📎 Референсов: <code>{len(current_refs)}</code>\n\n"
            if current_refs
            else ""
        )

        await callback.message.edit_text(
            f"🖼 <b>Создание фото</b>\n\n"
            f"{ref_text}"
            f"✨ Модель: <code>{current_service}</code>\n"
            f"📐 Формат: <code>{current_ratio}</code>\n\n"
            f"<b>Введите промпт для генерации:</b>\n\n"
            f"Опишите что хотите создать:",
            reply_markup=get_create_image_keyboard(
                current_service, current_ratio, num_refs=len(current_refs)
            ),
            parse_mode="HTML",
        )

        await callback.answer()
        await state.set_state(GenerationStates.waiting_for_input)


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
        f"📎 <b>Перезагрузка референсов</b>\n\n"
        f"Загружено: <code>0/14</code>\n\n"
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
    current_service = data.get("img_service", "flux_pro")
    current_ratio = data.get("img_ratio", "1:1")

    if not current_refs:
        await callback.answer("Нет загруженных изображений", show_alert=True)
        return

    # Сразу показываем экран выбора модели и формата (пропускаем экран подтверждения референсов)
    ref_text = f"📎 Референсов: <code>{len(current_refs)}</code>\n\n"

    await callback.message.edit_text(
        f"🖼 <b>Создание фото</b>\n\n"
        f"{ref_text}"
        f"✨ Модель: <code>{current_service}</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>\n\n"
        f"<b>Введите промпт для генерации:</b>\n\n"
        f"Опишите что хотите создать:",
        reply_markup=get_create_image_keyboard(current_service, current_ratio),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


# Обработчики для меню создания видео
@router.callback_query(F.data == "v_type_text")
async def handle_v_type_text(callback: types.CallbackQuery, state: FSMContext):
    """Выбор типа генерации: текст"""
    data = await state.get_data()
    current_model = data.get("v_model", "v26_pro")
    current_duration = data.get("v_duration", 5)
    current_ratio = data.get("v_ratio", "16:9")

    await state.update_data(v_type="text")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type="text",
            current_model=current_model,
            current_duration=current_duration,
            current_ratio=current_ratio,
        )
    )
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

    await state.update_data(v_type="imgtxt")

    # Показываем сообщение с просьбой загрузить изображение на ТОМ ЖЕ экране
    image_status = ""
    if v_image_url:
        image_status = "\n✅ <b>Изображение загружено!</b>\n"

    text = (
        f"🎬 <b>Создание видео</b>\n\n"
        f"⚙️ <b>Текущие настройки:</b>\n"
        f"   📝 Тип: <code>Фото + Текст → Видео</code>\n"
        f"   🤖 Модель: <code>{current_model}</code>\n"
        f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
        f"   📐 Формат: <code>{current_ratio}</code>\n"
        f"{image_status}\n"
        f"<b>📷 Загрузите стартовое изображение</b>\n\n"
        f"Отправьте фото, которое станет первым кадром видео.\n"
        f"После загрузки введите промпт для генерации.\n\n"
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
        f"🎬 <b>Видео + Текст → Видео</b>\n\n"
        f"💎 Баланс: <code>{user_credits}</code>\n\n"
        f"<b>Шаг 1: Загрузка референсов видео (опционально, до 5 шт)</b>\n\n"
        f"Загрузите короткие видео (3-10 сек) для:\n"
        f"• Стиля движения\n"
        f"• Камеры\n"
        f"• Атмосферы\n\n"
        f"После загрузки нажмите ▶️ Продолжить\n"
        f"Или ⏭ Пропустить"
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


async def _apply_video_model_selection(
    callback: types.CallbackQuery, state: FSMContext, model: str
):
    """Apply video model selection across all keyboard variants."""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_duration = data.get("v_duration", 5)
    current_ratio = data.get("v_ratio", "16:9")

    # WanX LoRA is text-to-video only, so we force the UI into text mode
    # to expose aspect ratio and duration controls immediately.
    if model.startswith("wanx"):
        current_v_type = "text"

    await state.update_data(v_model=model, v_type=current_v_type)
    if model.startswith("wanx"):
        await state.update_data(
            wanx_lora_settings=[{"lora_type": "nsfw-general", "lora_strength": 1.0}]
        )

    if model.startswith("wanx"):
        await callback.message.edit_text(
            "🎬 <b>WanX LoRA</b>\n\n"
            "Выберите формат и длительность для генерации:\n"
            "• 📐 Доступные aspect ratio\n"
            "• ⏱ Доступное время\n\n"
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
        await callback.message.edit_reply_markup(
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            )
        )
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

    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type=current_v_type,
            current_model=current_model,
            current_duration=current_duration,
            current_ratio="1:1",
        )
    )
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

    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type=current_v_type,
            current_model=current_model,
            current_duration=current_duration,
            current_ratio="16:9",
        )
    )
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

    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type=current_v_type,
            current_model=current_model,
            current_duration=current_duration,
            current_ratio="9:16",
        )
    )
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

    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type=current_v_type,
            current_model=current_model,
            current_duration=current_duration,
            current_ratio="4:3",
        )
    )
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

    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type=current_v_type,
            current_model=current_model,
            current_duration=current_duration,
            current_ratio="3:2",
        )
    )
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

    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type=current_v_type,
            current_model=current_model,
            current_duration=5,
            current_ratio=current_ratio,
        )
    )
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

    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type=current_v_type,
            current_model=current_model,
            current_duration=10,
            current_ratio=current_ratio,
        )
    )
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

    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type=current_v_type,
            current_model=current_model,
            current_duration=15,
            current_ratio=current_ratio,
        )
    )
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

    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type=current_v_type,
            current_model="grok_imagine",
            current_duration=6,
            current_ratio=current_ratio,
        )
    )
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

    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type=current_v_type,
            current_model="grok_imagine",
            current_duration=20,
            current_ratio=current_ratio,
        )
    )
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

    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type=current_v_type,
            current_model="grok_imagine",
            current_duration=30,
            current_ratio=current_ratio,
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


# =============================================================================
# НОВЫЙ UX: МЕНЮ СОЗДАНИЯ ФОТО (get_create_image_keyboard)
# =============================================================================


@router.callback_query(F.data == "model_flux_pro")
async def handle_model_flux_pro(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели FLUX.2 Pro"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")
    reference_images = data.get("reference_images", [])
    ref_text = (
        f"📎 Референсов: <code>{len(reference_images)}</code>\n\n"
        if reference_images
        else ""
    )

    await state.update_data(img_service="flux_pro")

    text = (
        f"🖼 <b>Создание фото</b>\n\n"
        f"{ref_text}"
        f"✨ Модель: <code>flux_pro</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>\n\n"
        f"<b>Введите промпт для генерации:</b>\n\n"
        f"Опишите что хотите создать:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_create_image_keyboard(
            current_service="flux_pro",
            current_ratio=current_ratio,
            num_refs=len(reference_images),
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_nanobanana")
async def handle_model_nanobanana(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Nano Banana"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")
    reference_images = data.get("reference_images", [])
    ref_text = (
        f"📎 Референсов: <code>{len(reference_images)}</code>\n\n"
        if reference_images
        else ""
    )

    await state.update_data(img_service="nanobanana")

    text = (
        f"🖼 <b>Создание фото</b>\n\n"
        f"{ref_text}"
        f"✨ Модель: <code>nanobanana</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>\n\n"
        f"<b>Введите промпт для генерации:</b>\n\n"
        f"Опишите что хотите создать:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_create_image_keyboard(
            current_service="nanobanana",
            current_ratio=current_ratio,
            num_refs=len(reference_images),
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_banana_pro")
async def handle_model_banana_pro(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Banana Pro"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")
    reference_images = data.get("reference_images", [])
    ref_text = (
        f"📎 Референсов: <code>{len(reference_images)}</code>\n\n"
        if reference_images
        else ""
    )

    await state.update_data(img_service="banana_pro")

    text = (
        f"🖼 <b>Создание фото</b>\n\n"
        f"{ref_text}"
        f"✨ Модель: <code>banana_pro</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>\n\n"
        f"<b>Введите промпт для генерации:</b>\n\n"
        f"Опишите что хотите создать:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_create_image_keyboard(
            current_service="banana_pro",
            current_ratio=current_ratio,
            num_refs=len(reference_images),
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_seedream")
async def handle_model_seedream(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Seedream 5.0 (Novita)"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")
    reference_images = data.get("reference_images", [])
    ref_text = (
        f"📎 Референсов: <code>{len(reference_images)}</code>\n\n"
        if reference_images
        else ""
    )

    await state.update_data(img_service="seedream")

    text = (
        f"🖼 <b>Создание фото</b>\n\n"
        f"{ref_text}"
        f"✨ Модель: <code>seedream</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>\n\n"
        f"<b>Введите промпт для генерации:</b>\n\n"
        f"Опишите что хотите создать:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_create_image_keyboard(
            current_service="seedream",
            current_ratio=current_ratio,
            num_refs=len(reference_images),
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_seedream_45")
async def handle_model_seedream_45(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Seedream 4.5 (Novita)"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")
    reference_images = data.get("reference_images", [])
    ref_text = (
        f"📎 Референсов: <code>{len(reference_images)}</code>\n\n"
        if reference_images
        else ""
    )

    await state.update_data(img_service="seedream_45")

    text = (
        f"🖼 <b>Создание фото</b>\n\n"
        f"{ref_text}"
        f"✨ Модель: <code>seedream_45</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>\n\n"
        f"<b>Введите промпт для генерации:</b>\n\n"
        f"Опишите что хотите создать:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_create_image_keyboard(
            current_service="seedream_45",
            current_ratio=current_ratio,
            num_refs=len(reference_images),
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_z_image_turbo_lora")
async def handle_model_z_image_turbo_lora(
    callback: types.CallbackQuery, state: FSMContext
):
    """Выбор модели Z-Image Turbo LoRA"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")
    reference_images = data.get("reference_images", [])
    ref_text = (
        f"📎 Референсов: <code>{len(reference_images)}</code>\n\n"
        if reference_images
        else ""
    )

    await state.update_data(img_service="z_image_turbo_lora")

    text = (
        f"🖼 <b>Создание фото</b>\n\n"
        f"{ref_text}"
        f"✨ Модель: <code>z_image_turbo_lora</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>\n\n"
        f"<b>Введите промпт для генерации:</b>\n\n"
        f"Опишите что хотите создать:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_create_image_keyboard(
            current_service="z_image_turbo_lora",
            current_ratio=current_ratio,
            num_refs=len(reference_images),
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_banana_2")
async def handle_model_banana_2(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Banana 2 (Gemini 3.1 Flash Image Preview)"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")

    await state.update_data(img_service="banana_2")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service="banana_2",
            current_ratio=current_ratio,
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_seedream_5_lite")
async def handle_model_seedream_5_lite(
    callback: types.CallbackQuery, state: FSMContext
):
    """Выбор модели Seedream 5.0 Lite Image-to-Image"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")

    await state.update_data(img_service="seedream_5_lite")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service="seedream_5_lite",
            current_ratio=current_ratio,
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_seedream_edit")
async def handle_model_seedream_edit(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Seedream 4.5"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")

    await state.update_data(img_service="seedream_edit")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service="seedream_edit",
            current_ratio=current_ratio,
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


# Обработчики формата изображения
@router.callback_query(F.data == "img_ratio_1_1")
async def handle_img_ratio_1_1(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 1:1"""
    data = await state.get_data()
    current_service = data.get("img_service", "flux_pro")

    await state.update_data(img_ratio="1:1")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service=current_service,
            current_ratio="1:1",
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "img_ratio_16_9")
async def handle_img_ratio_16_9(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 16:9"""
    data = await state.get_data()
    current_service = data.get("img_service", "flux_pro")

    await state.update_data(img_ratio="16:9")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service=current_service,
            current_ratio="16:9",
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "img_ratio_9_16")
async def handle_img_ratio_9_16(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 9:16"""
    data = await state.get_data()
    current_service = data.get("img_service", "flux_pro")

    await state.update_data(img_ratio="9:16")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service=current_service,
            current_ratio="9:16",
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "img_ratio_4_3")
async def handle_img_ratio_4_3(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 4:3"""
    data = await state.get_data()
    current_service = data.get("img_service", "flux_pro")

    await state.update_data(img_ratio="4:3")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service=current_service,
            current_ratio="4:3",
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "img_ratio_3_2")
async def handle_img_ratio_3_2(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 3:2"""
    data = await state.get_data()
    current_service = data.get("img_service", "flux_pro")

    await state.update_data(img_ratio="3:2")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service=current_service,
            current_ratio="3:2",
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


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
        model_name = "💎 Nano Banana"
        model_cost = str(preset_manager.get_generation_cost("gemini-2.5-flash"))

    # Шаг 1: Загрузка референсов
    await callback.message.edit_text(
        f"🖼 <b>Генерация фото</b>\n\n"
        f"💎 Ваш баланс: <code>{user_credits}</code> GOEов\n"
        f"🤖 Модель: {model_name} ({model_cost}💎)\n\n"
        f"<b>Шаг 1: Референсы (опционально)</b>\n\n"
        f"Загрузите изображения для:\n"
        f"• Точного сходства с объектом\n"
        f"• Сохранения стиля\n"
        f"• Персонажей (до 4 фото)\n\n"
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
        f"✏️ <b>Редактирование фото</b>\n\n"
        f"💎 Ваш баланс: <code>{user_credits}</code> GOEов\n"
        f"🤖 Модель: 💎 Banano Pro ({edit_cost}💎, 4K, сохранение лиц)\n\n"
        f"<b>Как редактировать:</b>\n"
        f"1. Загрузите <b>главное фото</b> для редактирования\n"
        f"2. Добавьте до <b>4 фото лица</b> для сохранения (опционально)\n"
        f"3. Опишите что изменить\n\n"
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
        "v3_std": "⚡ Standard",
        "v3_pro": "💎 Pro",
        "v3_omni_std": "🌀 Omni Std",
        "v3_omni_pro": "🌀 Omni Pro",
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
        f"🎬 <b>Генерация видео</b>\n\n"
        f"💎 Ваш баланс: <code>{user_credits}</code> GOEов\n"
        f"🤖 Модель: {model_name} ({model_cost}💎)\n\n"
        f"<b>Опции видео:</b>\n"
        f"   ⏱ Длительность: <code>{video_options.get('duration', 5)} сек</code>\n"
        f"   📐 Формат: <code>{video_options.get('aspect_ratio', '16:9')}</code>\n"
        f"   🔊 Со звуком: <code>{'Да' if video_options.get('generate_audio') else 'Нет'}</code>\n\n"
        f"Опишите видео, которое хотите создать:\n"
        f"• Что происходит в сцене\n"
        f"• Движение камеры\n"
        f"• Стиль и атмосфера\n\n"
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
        f"🎬 <b>Настройка видео</b>\n\n"
        f"Промпт: <code>{prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}</code>\n\n"
        f"Выберите параметры и нажмите ▶️ Запустить:\n\n"
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
        "v3_std": "⚡ Standard",
        "v3_pro": "💎 Pro",
        "v3_omni_std": "🌀 Omni Std",
        "v3_omni_pro": "🌀 Omni Pro",
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
        f"✂️ <b>Видео-эффекты</b>\n\n"
        f"💎 Ваш баланс: <code>{user_credits}</code> GOEов\n"
        f"🤖 Модель: {model_name} ({model_cost}💎)\n\n"
        f"<b>Kling 3 Omni</b>\n"
        f"Выберите, что хотите загрузить:\n\n"
        f"🎬 <b>Видео</b> - преобразование видео\n"
        f"🖼 <b>Фото</b> - создание видео из изображения\n\n"
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
        "v3_std": "⚡ Standard",
        "v3_pro": "💎 Pro",
        "v3_omni_std": "🌀 Omni Std",
        "v3_omni_pro": "🌀 Omni Pro",
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
        f"🖼 <b>Фото в видео</b>\n\n"
        f"💎 Ваш баланс: <code>{user_credits}</code> GOEов\n"
        f"🤖 Модель: {model_name} ({model_cost}💎)\n\n"
        f"<b>Kling 3 - Image to Video</b>\n"
        f"Загрузите изображение,\n"
        f"которое хотите превратить в видео.\n"
        f"После загрузки опишите движение.\n\n"
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
            "✂️ <b>Видео-эффекты</b>\n\n"
            "<b>Режим: Преобразование видео</b>\n\n"
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
            "✂️ <b>Видео-эффекты</b>\n\n"
            "<b>Режим: Создание видео из фото</b>\n\n"
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
        f"✂️ <b>Видео-эффекты</b>\n\n"
        f"💎 Ваш баланс: <code>{user_credits}</code> GOEов\n\n"
        f"<b>Kling 3 Omni</b>\n"
        f"Выберите, что хотите загрузить:\n\n"
        f"🎬 <b>Видео</b> - преобразование видео\n"
        f"🖼 <b>Фото</b> - создание видео из изображения\n\n"
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

    text = f"✂️ <b>Видео-эффекты</b>\n\n"
    text += f"<b>Опции:</b>\n"
    text += f"   {quality_emoji} Качество: <code>{quality.upper()}</code>\n"
    text += f"   ⏱ Длительность: <code>{options.get('duration', 5)} сек</code>\n"
    text += f"   📐 Формат: <code>{options.get('aspect_ratio', '16:9')}</code>\n\n"
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
            text = f"✅ <b>Модель изменена</b>\n\n"
            text += f"{model_emoji} Теперь используется: <code>{model}</code>\n\n"

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
            text = f"✅ <b>Разрешение изменено</b>\n\n"
            text += f"{res_emoji} Теперь используется: <code>{resolution}</code>\n\n"

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
            text = f"✅ <b>Формат изменён</b>\n\n"
            text += f"📐 Теперь используется: <code>{ratio}</code>\n\n"

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
            text = f"✅ <b>Поиск в интернете: {status}</b>\n\n"

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
            f"📎 <b>Загрузка референсных изображений</b>\n\n"
            f"Загружено: <code>{len(current_refs)}/{max_refs}</code>\n\n"
            f"Отправьте фотографии (до {max_refs} штук), которые будут использоваться как референсы:\n"
            f"• До 10 объектов с высокой точностью\n"
            f"• До 4 персонажей для консистентности\n"
            f"• До 14 изображений суммарно\n\n"
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
            f"📎 <b>Референсы очищены</b>\n\n"
            f"Загружено: <code>0/{max_refs}</code>\n\n"
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
            data = await state.get_data()
            current_service = data.get("img_service", "flux_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>\n\n"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>\n\n"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>\n\n"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(
                    current_service, current_ratio, num_refs=len(current_refs)
                ),
                parse_mode="HTML",
            )
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
                data = await state.get_data()
                current_service = data.get("img_service", "flux_pro")
                current_ratio = data.get("img_ratio", "1:1")
                await callback.message.edit_text(
                    f"✨ <b>Создание фото</b>\n\n"
                    f"📎 Референсы загружены: <code>{len(current_refs)}</code>\n\n"
                    f"✨ Модель: <code>{current_service}</code>\n"
                    f"📐 Формат: <code>{current_ratio}</code>\n\n"
                    f"Введите промпт для генерации:",
                    reply_markup=get_create_image_keyboard(
                        current_service, current_ratio
                    ),
                    parse_mode="HTML",
                )
                await state.set_state(GenerationStates.waiting_for_input)

    elif action == "reload":
        # Перезагружаем — очищаем и начинаем заново
        await state.update_data(reference_images=[])
        await state.set_state(GenerationStates.uploading_reference_images)

        await callback.message.edit_text(
            f"📎 <b>Перезагрузка референсов</b>\n\n"
            f"Загружено: <code>0/{max_refs}</code>\n\n"
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
            current_service = data.get("img_service", "flux_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>\n\n"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>\n\n"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>\n\n"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(current_service, current_ratio),
                parse_mode="HTML",
            )
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
            f"📎 <b>Загрузите изображение</b>\n\n"
            f"Для пресета: {preset.name}\n\n"
            f"После загрузки изображения, {preset.input_prompt or 'введите описание'}\n\n"
            f"<i>{hint}</i>",
            reply_markup=get_back_keyboard(f"preset_{preset_id}"),
            parse_mode="HTML",
        )
    else:
        await state.set_state(GenerationStates.waiting_for_input)

        hint = UserHints.get_hint_for_stage("input")
        await callback.message.edit_text(
            f"✏️ <b>Введите ваш вариант</b>\n\n"
            f"{preset.input_prompt or 'Опишите, что хотите создать'}\n\n"
            f"Примеры для вдохновения:\n"
            f"• Стиль: минимализм, винтаж, футуризм\n"
            f"• Цветовая схема: яркий, пастельный, тёмный\n"
            f"• Эмоция: радостное, удивлённое, задумчивое\n\n"
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
        f"▶️ <b>Подтвердите генерацию</b>\n\n"
        f"Пресет: <b>{preset.name}</b>\n"
        f"Стоимость: <code>{preset.cost}</code>💎\n\n"
        f"<b>Промпт:</b>\n"
        f"<code>{final_prompt[:300]}{'...' if len(final_prompt) > 300 else ''}</code>\n\n"
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
        f"🎬 <b>Фото + Текст → Видео</b>\n\n"
        f"📎 Фото: <code>{total_photos}/9</code> (старт + рефы)\n\n"
        f"{status}\n\n"
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
                f"📹 <b>Загрузка видео референсов</b>\n\n"
                f"Загружено: <code>{current_count}/{max_refs}</code>\n\n"
                f"✅ Видео добавлено!\n\n"
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
            f"📎 <b>Загрузка референсов</b>\n\n"
            f"Загружено: <code>{current_count}/{max_refs}</code>\n\n"
            f"✅ Фото добавлено!\n\n"
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
        await message.answer("⚠️ Введите промпт для генерации изображения.")
        return

    img_service = data.get("img_service", "nanobanana")
    img_ratio = data.get("img_ratio", "1:1")
    reference_images = data.get("reference_images", [])

    import uuid

    user = await get_or_create_user(message.from_user.id)
    cost = preset_manager.get_generation_cost(img_service)

    if user.credits < cost:
        await message.answer(
            f"❌ Недостаточно GOEов! Нужно: <code>{cost}</code>💎",
            reply_markup=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )
        return

    await deduct_credits(message.from_user.id, cost)

    # Create local task ID and store in DB
    local_task_id = f"img_{uuid.uuid4().hex[:12]}"
    await add_generation_task(
        user.id,
        message.from_user.id,
        local_task_id,
        "image",
        img_service,
        model=img_service,
        aspect_ratio=img_ratio,
        cost=cost,
    )

    processing_msg = await message.answer("🖼 Генерирую изображение...")

    try:
        callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None

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
            "seedream_5_lite",
        ]:
            model_map = {
                "flux_pro": "seedream/flux-pro",
                "seedream": "seedream/4.5",
                "seedream_45": "seedream 4.5",
                "seedream_edit": "seedream/4.5-edit",
                "seedream_5_lite": "seedream 4.5",
            }
            api_model = model_map.get(img_service, "seedream 4.5")
            result = await seedream_service.generate_image(
                prompt=prompt,
                model=api_model,
                aspect_ratio=img_ratio,
                image_urls=reference_images,
                callback_url=callback_url,
            )
        else:
            # Fallback
            result = await nano_banana_pro_service.generate_image(
                prompt=prompt,
                aspect_ratio=img_ratio,
                image_input=reference_images,
                callback_url=callback_url,
            )

        await processing_msg.delete()

        if isinstance(result, dict) and "task_id" in result:
            # Async task - update DB with API task_id and notify user
            api_task_id = result["task_id"]
            import aiosqlite

            from bot.database import DATABASE_PATH

            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute(
                    "UPDATE generation_tasks SET task_id = ? WHERE task_id = ? AND user_id = ?",
                    (api_task_id, local_task_id, user.id),
                )
                await db.commit()
            await message.answer(
                f"🚀 Генерация запущена!\n🆔 <code>{api_task_id}</code>\n💰 <code>{cost}</code>💎 списано\n\nОжидайте результат (1-3 мин).",
                parse_mode="HTML",
            )
        elif result:  # bytes
            # Sync result - bytes, complete task immediately
            saved_url = save_uploaded_file(result, "png")
            await message.answer_photo(
                photo=types.BufferedInputFile(result, filename="generated.png"),
                caption=f"✅ Изображение готово!\n💰 <code>{cost}</code>💎 списано",
                parse_mode="HTML",
            )
            await _send_original_document(message.answer_document, result, saved_url)
            await complete_video_task(local_task_id, saved_url)
        else:
            await add_credits(message.from_user.id, cost)
            await complete_video_task(local_task_id, None)
            await message.answer("❌ Ошибка генерации. GOE возвращены.")

    except Exception as e:
        logger.exception(f"Image generation error: {e}")
        await add_credits(message.from_user.id, cost)
        await complete_video_task(local_task_id, None)
        await message.answer("❌ Ошибка генерации.")

    await state.clear()


@router.message(GenerationStates.waiting_for_reference_video)
async def invalid_reference_video_input(message: types.Message, state: FSMContext):
    """
    Обрабатывает невалидный ввод в состоянии waiting_for_reference_video.
    """
    await message.answer(
        "⚠️ Пожалуйста, отправьте видео файл (макс 50MB).\n\n"
        "Это видео будет использовано как референс для стиля/движения."
    )


@router.callback_query(F.data.startswith("v_mode_"))
async def handle_v_mode(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик режимов видео (720p/1080p)"""
    mode = callback.data.replace("v_mode_", "")
    await state.update_data(v_mode=mode)
    data = await state.get_data()
    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type=data.get("v_type", "text"),
            current_model=data.get("v_model", "v3_std"),
            current_duration=data.get("v_duration", 5),
            current_ratio=data.get("v_ratio", "16:9"),
            current_mode=mode,
        )
    )
    await callback.answer()


@router.callback_query(F.data.startswith("v_orientation_"))
async def handle_v_orientation(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик ориентации видео (image/video)"""
    orientation = callback.data.replace("v_orientation_", "")
    await state.update_data(v_orientation=orientation)
    data = await state.get_data()
    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type=data.get("v_type", "text"),
            current_model=data.get("v_model", "v3_std"),
            current_duration=data.get("v_duration", 5),
            current_ratio=data.get("v_ratio", "16:9"),
            current_orientation=orientation,
        )
    )
    await callback.answer()


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
    if v_type == "video":
        v_model = "aleph"
    v_model = data.get("v_model", "v3_std")
    v_duration = int(data.get("v_duration", 5))
    # Cap duration for imgtxt except for Grok Imagine which supports up to 30s
    if v_type == "imgtxt" and v_model != "grok_imagine":
        v_duration = min(v_duration, 10)
    v_ratio = data.get("v_ratio", "16:9")
    v_image_url = data.get("v_image_url")
    v_video_url = data.get("v_video_url")

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
                f"❌ Недостаточно GOEов!\nНужно: <code>{cost}</code>💎\nПополните баланс.",
                reply_markup=get_main_menu_keyboard(
                    await get_user_credits(message.from_user.id)
                ),
                parse_mode="HTML",
            )
            await state.clear()
            return
        await deduct_credits(message.from_user.id, cost)

    processing_msg = await message.answer(
        f"🎬 <b>Видео генерируется...</b>\n\n"
        f"🤖 Модель: <code>{v_model}</code>\n"
        f"⏱ Длительность: <code>{v_duration}s</code>\n"
        f"📐 Формат: <code>{v_ratio}</code>\n"
        f"💰 Стоимость: <code>{cost}</code>💎\n\n"
        f"<i>Ожидайте 1-5 минут</i>",
        parse_mode="HTML",
    )

    try:
        from bot.services.grok_service import grok_service
        from bot.services.kling_service import kling_service

        if v_model == "grok_imagine":
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
            result = await grok_service.generate_image_to_video(
                image_urls=grok_image_urls,
                prompt=prompt,
                duration=grok_duration,
                aspect_ratio=v_ratio,
                callBackUrl=(
                    config.kling_notification_url if config.WEBHOOK_HOST else None
                ),
            )
        elif v_model == "aleph":
            if not video_urls:
                await message.answer(
                    "❌ Aleph Video требует референсное видео (видео+текст режим)."
                )
                if not is_admin:
                    await add_credits(message.from_user.id, cost)
                await processing_msg.delete()
                await state.clear()
                return
            result = await aleph_service.generate_video(
                prompt=prompt,
                video_url=video_urls[0],
                duration=v_duration,
                aspect_ratio=v_ratio,
                callback_url=(
                    config.kling_notification_url if config.WEBHOOK_HOST else None
                ),
            )
        elif v_model == "runway":
            from bot.services.runway_service import runway_service

            if v_type == "video":
                await message.answer(
                    "❌ Runway не поддерживает видео референсы. Используйте текст или фото+текст."
                )
                if not is_admin:
                    await add_credits(message.from_user.id, cost)
                await processing_msg.delete()
                await state.clear()
                return
            callback_url = (
                config.kling_notification_url if config.WEBHOOK_HOST else None
            )
            result = await runway_service.generate_video(
                prompt=prompt,
                image_url=image_url,
                duration=v_duration,
                quality="720p",
                aspect_ratio=v_ratio,
                callback_url=callback_url,
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
                f"✅ <b>Видео задача запущена!</b>\n\n"
                f"🆔 <code>{result['task_id']}</code>\n"
                f"🎯 <code>{v_model}</code> | {v_duration}s | {v_ratio}\n"
                f"💰 <code>{cost}</code>💎 {'списано' if not is_admin else '(админ бесплатно)'}\n\n"
                f"⏳ Результат через 1-5 мин в этом чате.",
                parse_mode="HTML",
            )
        else:
            if not is_admin:
                await add_credits(message.from_user.id, cost)
            await message.answer("❌ Не удалось создать задачу. GOE возвращены.")
    except Exception as e:
        logger.exception(f"Video generation error: {e}")
        if not is_admin:
            await add_credits(message.from_user.id, cost)
        await message.answer("❌ Ошибка генерации. GOE возвращены.")

    await state.clear()


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
            text = f"✅ <b>Модель изменена</b>\n\n"
            text += f"{model_emoji} Теперь используется: <code>{model}</code>\n\n"

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
            text = f"✅ <b>Разрешение изменено</b>\n\n"
            text += f"{res_emoji} Теперь используется: <code>{resolution}</code>\n\n"

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
            text = f"✅ <b>Формат изменён</b>\n\n"
            text += f"📐 Теперь используется: <code>{ratio}</code>\n\n"

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
            text = f"✅ <b>Поиск в интернете: {status}</b>\n\n"

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
            f"📎 <b>Загрузка референсных изображений</b>\n\n"
            f"Загружено: <code>{len(current_refs)}/{max_refs}</code>\n\n"
            f"Отправьте фотографии (до {max_refs} штук), которые будут использоваться как референсы:\n"
            f"• До 10 объектов с высокой точностью\n"
            f"• До 4 персонажей для консистентности\n"
            f"• До 14 изображений суммарно\n\n"
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
            f"📎 <b>Референсы очищены</b>\n\n"
            f"Загружено: <code>0/{max_refs}</code>\n\n"
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
            data = await state.get_data()
            current_service = data.get("img_service", "flux_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>\n\n"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>\n\n"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>\n\n"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(
                    current_service, current_ratio, num_refs=len(current_refs)
                ),
                parse_mode="HTML",
            )
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
                data = await state.get_data()
                current_service = data.get("img_service", "flux_pro")
                current_ratio = data.get("img_ratio", "1:1")
                await callback.message.edit_text(
                    f"✨ <b>Создание фото</b>\n\n"
                    f"📎 Референсы загружены: <code>{len(current_refs)}</code>\n\n"
                    f"✨ Модель: <code>{current_service}</code>\n"
                    f"📐 Формат: <code>{current_ratio}</code>\n\n"
                    f"Введите промпт для генерации:",
                    reply_markup=get_create_image_keyboard(
                        current_service, current_ratio
                    ),
                    parse_mode="HTML",
                )
                await state.set_state(GenerationStates.waiting_for_input)

    elif action == "reload":
        # Перезагружаем — очищаем и начинаем заново
        await state.update_data(reference_images=[])
        await state.set_state(GenerationStates.uploading_reference_images)

        await callback.message.edit_text(
            f"📎 <b>Перезагрузка референсов</b>\n\n"
            f"Загружено: <code>0/{max_refs}</code>\n\n"
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
            current_service = data.get("img_service", "flux_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>\n\n"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>\n\n"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>\n\n"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(current_service, current_ratio),
                parse_mode="HTML",
            )
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
            f"📎 <b>Загрузите изображение</b>\n\n"
            f"Для пресета: {preset.name}\n\n"
            f"После загрузки изображения, {preset.input_prompt or 'введите описание'}\n\n"
            f"<i>{hint}</i>",
            reply_markup=get_back_keyboard(f"preset_{preset_id}"),
            parse_mode="HTML",
        )
    else:
        await state.set_state(GenerationStates.waiting_for_input)

        hint = UserHints.get_hint_for_stage("input")
        await callback.message.edit_text(
            f"✏️ <b>Введите ваш вариант</b>\n\n"
            f"{preset.input_prompt or 'Опишите, что хотите создать'}\n\n"
            f"Примеры для вдохновения:\n"
            f"• Стиль: минимализм, винтаж, футуризм\n"
            f"• Цветовая схема: яркий, пастельный, тёмный\n"
            f"• Эмоция: радостное, удивлённое, задумчивое\n\n"
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
        f"▶️ <b>Подтвердите генерацию</b>\n\n"
        f"Пресет: <b>{preset.name}</b>\n"
        f"Стоимость: <code>{preset.cost}</code>💎\n\n"
        f"<b>Промпт:</b>\n"
        f"<code>{final_prompt[:300]}{'...' if len(final_prompt) > 300 else ''}</code>\n\n"
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
    Обрабатывает загруженное фото когда пользователь в состоянии waiting_for_video_prompt.
    Это нужно для режима imgtxt (фото+текст → видео), когда пользователь загружает фото
    ДО ввода промпта.
    """
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    # Проверяем, что это режим создания видео и выбран тип imgtxt
    if generation_type == "video" and v_type == "imgtxt":
        # Скачиваем изображение
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()

        # Validate image dimensions for Kling API (Kie.ai requires min 300x300)
        try:
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(image_data))
            width, height = img.size
            if width < 300 or height < 300:
                await message.answer(
                    f"❌ <b>Изображение слишком маленькое!</b>\\n\\n"
                    f"Размер: {width}×{height} px\\n\\n"
                    "Kie.ai API требует минимум 300×300 px.\\n"
                    "Загрузите фото большего размера.",
                    parse_mode="HTML",
                    reply_markup=get_create_video_keyboard(
                        current_v_type=data.get("v_type", "imgtxt"),
                        current_model=data.get("v_model", "v26_pro"),
                        current_duration=data.get("v_duration", 5),
                        current_ratio=data.get("v_ratio", "16:9"),
                    ),
                )
                return
            logger.info(f"Image validated for Kling: {width}×{height}")
        except Exception as e:
            logger.error(f"Image validation failed: {e}")

        # Сохраняем изображение и получаем URL
        image_url = save_uploaded_file(image_data, "png")

        if image_url:
            await state.update_data(v_image_url=image_url)
            logger.info(
                f"Saved start image for video (waiting_for_video_prompt state): {image_url}"
            )
        else:
            await message.answer(
                "❌ Не удалось сохранить изображение. Попробуйте ещё раз."
            )
            return

        # Получаем обновлённые данные
        data = await state.get_data()
        current_v_type = data.get("v_type", "imgtxt")
        current_model = data.get("v_model", "v26_pro")
        current_duration = data.get("v_duration", 5)
        current_ratio = data.get("v_ratio", "16:9")
        user_prompt = data.get("user_prompt", "")

        # Показываем подтверждение с обновлённым экраном
        image_status = "\n✅ <b>Изображение загружено!</b>\n"

        prompt_display = ""
        if user_prompt:
            prompt_display = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}</code>\n"

        text = (
            f"🎬 <b>Создание видео</b>\n\n"
            f"{image_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Фото + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>\n\n"
            f"Опишите движение, которое хотите создать:\n"
            f"• Как двигается объект\n"
            f"• Движение камеры\n"
            f"• Стиль и атмосфера"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
        return

    # Если это не режим imgtxt - игнорируем
    await message.answer("Пожалуйста, отправьте текстовое описание.")
    return


@router.message(
    GenerationStates.waiting_for_reference_video,
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def process_reference_video_upload(message: types.Message, state: FSMContext):
    """
    Обрабатывает загрузку референсного видео для режима video (видео+текст → видео).
    Сохраняет видео и переключает в состояние ожидания промпта.
    """
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    if generation_type == "video" and v_type == "video":
        # Определяем источник файла (video или document)
        if message.video:
            video_obj = message.video
        elif message.document and message.document.mime_type.startswith("video/"):
            video_obj = message.document
        else:
            await message.answer("❌ Неверный тип файла. Отправьте видео.")
            return

        file = await message.bot.get_file(video_obj.file_id)

        # Проверяем размер (макс 20MB для стабильности)
        file_size = getattr(video_obj, "file_size", 0)
        if file_size > 20 * 1024 * 1024:
            await message.answer("❌ Видео слишком большое (макс 20MB).")
            return

        video_bytes = await message.bot.download_file(file.file_path)
        video_data = video_bytes.read()

        # Сохраняем видео и получаем URL
        video_url = save_uploaded_file(video_data, "mp4")

        if video_url:
            await state.update_data(v_video_url=video_url)
            logger.info(f"Saved reference video for video mode: {video_url}")
        else:
            await message.answer("❌ Не удалось сохранить видео. Попробуйте ещё раз.")
            return

        # Переключаемся в состояние ожидания промпта
        await state.set_state(GenerationStates.waiting_for_video_prompt)

        # Получаем обновлённые данные
        data = await state.get_data()
        current_v_type = data.get("v_type", "video")
        current_model = data.get("v_model", "v26_pro")
        current_duration = data.get("v_duration", 5)
        current_ratio = data.get("v_ratio", "16:9")
        user_prompt = data.get("user_prompt", "")

        # Показываем экран с промптом
        video_status = "\n✅ <b>Референсное видео загружено!</b>\n"

        prompt_display = ""
        if user_prompt:
            prompt_display = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}</code>\n"

        text = (
            f"🎬 <b>Создание видео</b>\n\n"
            f"{video_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Видео + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>\n\n"
            f"Опишите желаемый эффект/стиль:\n"
            f"• Стиль видео\n"
            f"• Дополнительные эффекты\n"
            f"• Атмосфера\n\n"
            f"<i>Видео будет использовано как референс для движения/стиля (@Video1)</i>"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
        return

    await message.answer("Пожалуйста, отправьте текстовое описание.")


@router.message(GenerationStates.waiting_for_reference_video)
async def invalid_reference_video_input(message: types.Message, state: FSMContext):
    """
    Обрабатывает невалидный ввод в состоянии waiting_for_reference_video.
    """
    await message.answer(
        "⚠️ Пожалуйста, отправьте видео файл (макс 50MB).\n\n"
        "Это видео будет использовано как референс для стиля/движения."
    )


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
            text = f"✅ <b>Модель изменена</b>\n\n"
            text += f"{model_emoji} Теперь используется: <code>{model}</code>\n\n"

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
            text = f"✅ <b>Разрешение изменено</b>\n\n"
            text += f"{res_emoji} Теперь используется: <code>{resolution}</code>\n\n"

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
            text = f"✅ <b>Формат изменён</b>\n\n"
            text += f"📐 Теперь используется: <code>{ratio}</code>\n\n"

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
            text = f"✅ <b>Поиск в интернете: {status}</b>\n\n"

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
            f"📎 <b>Загрузка референсных изображений</b>\n\n"
            f"Загружено: <code>{len(current_refs)}/{max_refs}</code>\n\n"
            f"Отправьте фотографии (до {max_refs} штук), которые будут использоваться как референсы:\n"
            f"• До 10 объектов с высокой точностью\n"
            f"• До 4 персонажей для консистентности\n"
            f"• До 14 изображений суммарно\n\n"
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
            f"📎 <b>Референсы очищены</b>\n\n"
            f"Загружено: <code>0/{max_refs}</code>\n\n"
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
            data = await state.get_data()
            current_service = data.get("img_service", "flux_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>\n\n"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>\n\n"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>\n\n"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(
                    current_service, current_ratio, num_refs=len(current_refs)
                ),
                parse_mode="HTML",
            )
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
                data = await state.get_data()
                current_service = data.get("img_service", "flux_pro")
                current_ratio = data.get("img_ratio", "1:1")
                await callback.message.edit_text(
                    f"✨ <b>Создание фото</b>\n\n"
                    f"📎 Референсы загружены: <code>{len(current_refs)}</code>\n\n"
                    f"✨ Модель: <code>{current_service}</code>\n"
                    f"📐 Формат: <code>{current_ratio}</code>\n\n"
                    f"Введите промпт для генерации:",
                    reply_markup=get_create_image_keyboard(
                        current_service, current_ratio
                    ),
                    parse_mode="HTML",
                )
                await state.set_state(GenerationStates.waiting_for_input)

    elif action == "reload":
        # Перезагружаем — очищаем и начинаем заново
        await state.update_data(reference_images=[])
        await state.set_state(GenerationStates.uploading_reference_images)

        await callback.message.edit_text(
            f"📎 <b>Перезагрузка референсов</b>\n\n"
            f"Загружено: <code>0/{max_refs}</code>\n\n"
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
            current_service = data.get("img_service", "flux_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>\n\n"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>\n\n"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>\n\n"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(current_service, current_ratio),
                parse_mode="HTML",
            )
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
            f"📎 <b>Загрузите изображение</b>\n\n"
            f"Для пресета: {preset.name}\n\n"
            f"После загрузки изображения, {preset.input_prompt or 'введите описание'}\n\n"
            f"<i>{hint}</i>",
            reply_markup=get_back_keyboard(f"preset_{preset_id}"),
            parse_mode="HTML",
        )
    else:
        await state.set_state(GenerationStates.waiting_for_input)

        hint = UserHints.get_hint_for_stage("input")
        await callback.message.edit_text(
            f"✏️ <b>Введите ваш вариант</b>\n\n"
            f"{preset.input_prompt or 'Опишите, что хотите создать'}\n\n"
            f"Примеры для вдохновения:\n"
            f"• Стиль: минимализм, винтаж, футуризм\n"
            f"• Цветовая схема: яркий, пастельный, тёмный\n"
            f"• Эмоция: радостное, удивлённое, задумчивое\n\n"
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
        f"▶️ <b>Подтвердите генерацию</b>\n\n"
        f"Пресет: <b>{preset.name}</b>\n"
        f"Стоимость: <code>{preset.cost}</code>💎\n\n"
        f"<b>Промпт:</b>\n"
        f"<code>{final_prompt[:300]}{'...' if len(final_prompt) > 300 else ''}</code>\n\n"
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


@router.message(GenerationStates.waiting_for_input, F.photo)
async def process_photo_for_video_imgtxt(message: types.Message, state: FSMContext):
    """Обрабатывает загруженное фото для режима imgtxt (фото+текст → видео)"""
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    # Проверяем, что это режим создания видео и выбран тип imgtxt
    if generation_type == "video" and v_type == "imgtxt":
        # Скачиваем изображение
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()

        # Validate image dimensions for Kling API (Kie.ai requires min 300x300)
        try:
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(image_data))
            width, height = img.size
            if width < 300 or height < 300:
                await message.answer(
                    f"❌ <b>Изображение слишком маленькое!</b>\\n\\n"
                    f"Размер: {width}×{height} px\\n\\n"
                    "Kie.ai API требует минимум 300×300 px.\\n"
                    "Загрузите фото большего размера.",
                    parse_mode="HTML",
                    reply_markup=get_create_video_keyboard(
                        current_v_type=data.get("v_type", "imgtxt"),
                        current_model=data.get("v_model", "v26_pro"),
                        current_duration=data.get("v_duration", 5),
                        current_ratio=data.get("v_ratio", "16:9"),
                    ),
                )
                return
            logger.info(f"Image validated for Kling: {width}×{height}")
        except Exception as e:
            logger.error(f"Image validation failed: {e}")

        # Сохраняем изображение и получаем URL
        image_url = save_uploaded_file(image_data, "png")

        if image_url:
            await state.update_data(v_image_url=image_url)
            logger.info(f"Saved start image for video: {image_url}")
        else:
            await message.answer(
                "❌ Не удалось сохранить изображение. Попробуйте ещё раз."
            )
            return

        # Получаем обновлённые данные
        data = await state.get_data()
        current_v_type = data.get("v_type", "imgtxt")
        current_model = data.get("v_model", "v26_pro")
        current_duration = data.get("v_duration", 5)
        current_ratio = data.get("v_ratio", "16:9")
        user_prompt = data.get("user_prompt", "")

        # Показываем подтверждение с обновлённым экраном
        image_status = "\n✅ <b>Изображение загружено!</b>\n"

        prompt_display = ""
        if user_prompt:
            prompt_display = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}</code>\n"

        text = (
            f"🎬 <b>Создание видео</b>\n\n"
            f"{image_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Фото + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>\n\n"
            f"Опишите движение, которое хотите создать:\n"
            f"• Как двигается объект\n"
            f"• Движение камеры\n"
            f"• Стиль и атмосфера"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
        return

    # Если это не режим imgtxt - игнорируем (другие обработчики обработают)
    await message.answer("Пожалуйста, отправьте текстовое описание.")
    return


@router.message(GenerationStates.waiting_for_video_prompt, F.photo)
async def process_photo_for_video_prompt_state(
    message: types.Message, state: FSMContext
):
    """
    Обрабатывает загруженное фото когда пользователь в состоянии waiting_for_video_prompt.
    Это нужно для режима imgtxt (фото+текст → видео), когда пользователь загружает фото
    ДО ввода промпта.
    """
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    # Проверяем, что это режим создания видео и выбран тип imgtxt
    if generation_type == "video" and v_type == "imgtxt":
        # Скачиваем изображение
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()

        # Validate image dimensions for Kling API (Kie.ai requires min 300x300)
        try:
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(image_data))
            width, height = img.size
            if width < 300 or height < 300:
                await message.answer(
                    f"❌ <b>Изображение слишком маленькое!</b>\\n\\n"
                    f"Размер: {width}×{height} px\\n\\n"
                    "Kie.ai API требует минимум 300×300 px.\\n"
                    "Загрузите фото большего размера.",
                    parse_mode="HTML",
                    reply_markup=get_create_video_keyboard(
                        current_v_type=data.get("v_type", "imgtxt"),
                        current_model=data.get("v_model", "v26_pro"),
                        current_duration=data.get("v_duration", 5),
                        current_ratio=data.get("v_ratio", "16:9"),
                    ),
                )
                return
            logger.info(f"Image validated for Kling: {width}×{height}")
        except Exception as e:
            logger.error(f"Image validation failed: {e}")

        # Сохраняем изображение и получаем URL
        image_url = save_uploaded_file(image_data, "png")

        if image_url:
            await state.update_data(v_image_url=image_url)
            logger.info(
                f"Saved start image for video (waiting_for_video_prompt state): {image_url}"
            )
        else:
            await message.answer(
                "❌ Не удалось сохранить изображение. Попробуйте ещё раз."
            )
            return

        # Получаем обновлённые данные
        data = await state.get_data()
        current_v_type = data.get("v_type", "imgtxt")
        current_model = data.get("v_model", "v26_pro")
        current_duration = data.get("v_duration", 5)
        current_ratio = data.get("v_ratio", "16:9")
        user_prompt = data.get("user_prompt", "")

        # Показываем подтверждение с обновлённым экраном
        image_status = "\n✅ <b>Изображение загружено!</b>\n"

        prompt_display = ""
        if user_prompt:
            prompt_display = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}</code>\n"

        text = (
            f"🎬 <b>Создание видео</b>\n\n"
            f"{image_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Фото + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>\n\n"
            f"Опишите движение, которое хотите создать:\n"
            f"• Как двигается объект\n"
            f"• Движение камеры\n"
            f"• Стиль и атмосфера"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
        return

    # Если это не режим imgtxt - игнорируем
    await message.answer("Пожалуйста, отправьте текстовое описание.")
    return


@router.message(
    GenerationStates.waiting_for_reference_video,
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def process_reference_video_upload(message: types.Message, state: FSMContext):
    """
    Обрабатывает загрузку референсного видео для режима video (видео+текст → видео).
    Сохраняет видео и переключает в состояние ожидания промпта.
    """
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    if generation_type == "video" and v_type == "video":
        # Определяем источник файла (video или document)
        if message.video:
            video_obj = message.video
        elif message.document and message.document.mime_type.startswith("video/"):
            video_obj = message.document
        else:
            await message.answer("❌ Неверный тип файла. Отправьте видео.")
            return

        file = await message.bot.get_file(video_obj.file_id)

        # Проверяем размер (макс 20MB для стабильности)
        file_size = getattr(video_obj, "file_size", 0)
        if file_size > 20 * 1024 * 1024:
            await message.answer("❌ Видео слишком большое (макс 20MB).")
            return

        video_bytes = await message.bot.download_file(file.file_path)
        video_data = video_bytes.read()

        # Сохраняем видео и получаем URL
        video_url = save_uploaded_file(video_data, "mp4")

        if video_url:
            await state.update_data(v_video_url=video_url)
            logger.info(f"Saved reference video for video mode: {video_url}")
        else:
            await message.answer("❌ Не удалось сохранить видео. Попробуйте ещё раз.")
            return

        # Переключаемся в состояние ожидания промпта
        await state.set_state(GenerationStates.waiting_for_video_prompt)

        # Получаем обновлённые данные
        data = await state.get_data()
        current_v_type = data.get("v_type", "video")
        current_model = data.get("v_model", "v26_pro")
        current_duration = data.get("v_duration", 5)
        current_ratio = data.get("v_ratio", "16:9")
        user_prompt = data.get("user_prompt", "")

        # Показываем экран с промптом
        video_status = "\n✅ <b>Референсное видео загружено!</b>\n"

        prompt_display = ""
        if user_prompt:
            prompt_display = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}</code>\n"

        text = (
            f"🎬 <b>Создание видео</b>\n\n"
            f"{video_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Видео + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>\n\n"
            f"Опишите желаемый эффект/стиль:\n"
            f"• Стиль видео\n"
            f"• Дополнительные эффекты\n"
            f"• Атмосфера\n\n"
            f"<i>Видео будет использовано как референс для движения/стиля (@Video1)</i>"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
        return

    await message.answer("Пожалуйста, отправьте текстовое описание.")


@router.message(GenerationStates.waiting_for_reference_video)
async def invalid_reference_video_input(message: types.Message, state: FSMContext):
    """
    Обрабатывает невалидный ввод в состоянии waiting_for_reference_video.
    """
    await message.answer(
        "⚠️ Пожалуйста, отправьте видео файл (макс 50MB).\n\n"
        "Это видео будет использовано как референс для стиля/движения."
    )


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
            text = f"✅ <b>Модель изменена</b>\n\n"
            text += f"{model_emoji} Теперь используется: <code>{model}</code>\n\n"

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
            text = f"✅ <b>Разрешение изменено</b>\n\n"
            text += f"{res_emoji} Теперь используется: <code>{resolution}</code>\n\n"

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
            text = f"✅ <b>Формат изменён</b>\n\n"
            text += f"📐 Теперь используется: <code>{ratio}</code>\n\n"

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
            text = f"✅ <b>Поиск в интернете: {status}</b>\n\n"

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
            f"📎 <b>Загрузка референсных изображений</b>\n\n"
            f"Загружено: <code>{len(current_refs)}/{max_refs}</code>\n\n"
            f"Отправьте фотографии (до {max_refs} штук), которые будут использоваться как референсы:\n"
            f"• До 10 объектов с высокой точностью\n"
            f"• До 4 персонажей для консистентности\n"
            f"• До 14 изображений суммарно\n\n"
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
            f"📎 <b>Референсы очищены</b>\n\n"
            f"Загружено: <code>0/{max_refs}</code>\n\n"
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
            data = await state.get_data()
            current_service = data.get("img_service", "flux_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>\n\n"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>\n\n"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>\n\n"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(
                    current_service, current_ratio, num_refs=len(current_refs)
                ),
                parse_mode="HTML",
            )
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
                data = await state.get_data()
                current_service = data.get("img_service", "flux_pro")
                current_ratio = data.get("img_ratio", "1:1")
                await callback.message.edit_text(
                    f"✨ <b>Создание фото</b>\n\n"
                    f"📎 Референсы загружены: <code>{len(current_refs)}</code>\n\n"
                    f"✨ Модель: <code>{current_service}</code>\n"
                    f"📐 Формат: <code>{current_ratio}</code>\n\n"
                    f"Введите промпт для генерации:",
                    reply_markup=get_create_image_keyboard(
                        current_service, current_ratio
                    ),
                    parse_mode="HTML",
                )
                await state.set_state(GenerationStates.waiting_for_input)

    elif action == "reload":
        # Перезагружаем — очищаем и начинаем заново
        await state.update_data(reference_images=[])
        await state.set_state(GenerationStates.uploading_reference_images)

        await callback.message.edit_text(
            f"📎 <b>Перезагрузка референсов</b>\n\n"
            f"Загружено: <code>0/{max_refs}</code>\n\n"
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
            current_service = data.get("img_service", "flux_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>\n\n"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>\n\n"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>\n\n"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(current_service, current_ratio),
                parse_mode="HTML",
            )
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
            f"📎 <b>Загрузите изображение</b>\n\n"
            f"Для пресета: {preset.name}\n\n"
            f"После загрузки изображения, {preset.input_prompt or 'введите описание'}\n\n"
            f"<i>{hint}</i>",
            reply_markup=get_back_keyboard(f"preset_{preset_id}"),
            parse_mode="HTML",
        )
    else:
        await state.set_state(GenerationStates.waiting_for_input)

        hint = UserHints.get_hint_for_stage("input")
        await callback.message.edit_text(
            f"✏️ <b>Введите ваш вариант</b>\n\n"
            f"{preset.input_prompt or 'Опишите, что хотите создать'}\n\n"
            f"Примеры для вдохновения:\n"
            f"• Стиль: минимализм, винтаж, футуризм\n"
            f"• Цветовая схема: яркий, пастельный, тёмный\n"
            f"• Эмоция: радостное, удивлённое, задумчивое\n\n"
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
        f"▶️ <b>Подтвердите генерацию</b>\n\n"
        f"Пресет: <b>{preset.name}</b>\n"
        f"Стоимость: <code>{preset.cost}</code>💎\n\n"
        f"<b>Промпт:</b>\n"
        f"<code>{final_prompt[:300]}{'...' if len(final_prompt) > 300 else ''}</code>\n\n"
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


@router.message(GenerationStates.waiting_for_input, F.photo)
async def process_photo_for_video_imgtxt(message: types.Message, state: FSMContext):
    """Обрабатывает загруженное фото для режима imgtxt (фото+текст → видео)"""
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    # Проверяем, что это режим создания видео и выбран тип imgtxt
    if generation_type == "video" and v_type == "imgtxt":
        # Скачиваем изображение
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()

        # Validate image dimensions for Kling API (Kie.ai requires min 300x300)
        try:
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(image_data))
            width, height = img.size
            if width < 300 or height < 300:
                await message.answer(
                    f"❌ <b>Изображение слишком маленькое!</b>\\n\\n"
                    f"Размер: {width}×{height} px\\n\\n"
                    "Kie.ai API требует минимум 300×300 px.\\n"
                    "Загрузите фото большего размера.",
                    parse_mode="HTML",
                    reply_markup=get_create_video_keyboard(
                        current_v_type=data.get("v_type", "imgtxt"),
                        current_model=data.get("v_model", "v26_pro"),
                        current_duration=data.get("v_duration", 5),
                        current_ratio=data.get("v_ratio", "16:9"),
                    ),
                )
                return
            logger.info(f"Image validated for Kling: {width}×{height}")
        except Exception as e:
            logger.error(f"Image validation failed: {e}")

        # Сохраняем изображение и получаем URL
        image_url = save_uploaded_file(image_data, "png")

        if image_url:
            await state.update_data(v_image_url=image_url)
            logger.info(f"Saved start image for video: {image_url}")
        else:
            await message.answer(
                "❌ Не удалось сохранить изображение. Попробуйте ещё раз."
            )
            return

        # Получаем обновлённые данные
        data = await state.get_data()
        current_v_type = data.get("v_type", "imgtxt")
        current_model = data.get("v_model", "v26_pro")
        current_duration = data.get("v_duration", 5)
        current_ratio = data.get("v_ratio", "16:9")
        user_prompt = data.get("user_prompt", "")

        # Показываем подтверждение с обновлённым экраном
        image_status = "\n✅ <b>Изображение загружено!</b>\n"

        prompt_display = ""
        if user_prompt:
            prompt_display = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}</code>\n"

        text = (
            f"🎬 <b>Создание видео</b>\n\n"
            f"{image_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Фото + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>\n\n"
            f"Опишите движение, которое хотите создать:\n"
            f"• Как двигается объект\n"
            f"• Движение камеры\n"
            f"• Стиль и атмосфера"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
        return

    # Если это не режим imgtxt - игнорируем (другие обработчики обработают)
    await message.answer("Пожалуйста, отправьте текстовое описание.")
    return


@router.message(GenerationStates.waiting_for_video_prompt, F.photo)
async def process_photo_for_video_prompt_state(
    message: types.Message, state: FSMContext
):
    """
    Обрабатывает загруженное фото когда пользователь в состоянии waiting_for_video_prompt.
    Это нужно для режима imgtxt (фото+текст → видео), когда пользователь загружает фото
    ДО ввода промпта.
    """
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    # Проверяем, что это режим создания видео и выбран тип imgtxt
    if generation_type == "video" and v_type == "imgtxt":
        # Скачиваем изображение
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()

        # Validate image dimensions for Kling API (Kie.ai requires min 300x300)
        try:
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(image_data))
            width, height = img.size
            if width < 300 or height < 300:
                await message.answer(
                    f"❌ <b>Изображение слишком маленькое!</b>\\n\\n"
                    f"Размер: {width}×{height} px\\n\\n"
                    "Kie.ai API требует минимум 300×300 px.\\n"
                    "Загрузите фото большего размера.",
                    parse_mode="HTML",
                    reply_markup=get_create_video_keyboard(
                        current_v_type=data.get("v_type", "imgtxt"),
                        current_model=data.get("v_model", "v26_pro"),
                        current_duration=data.get("v_duration", 5),
                        current_ratio=data.get("v_ratio", "16:9"),
                    ),
                )
                return
            logger.info(f"Image validated for Kling: {width}×{height}")
        except Exception as e:
            logger.error(f"Image validation failed: {e}")

        # Сохраняем изображение и получаем URL
        image_url = save_uploaded_file(image_data, "png")

        if image_url:
            await state.update_data(v_image_url=image_url)
            logger.info(
                f"Saved start image for video (waiting_for_video_prompt state): {image_url}"
            )
        else:
            await message.answer(
                "❌ Не удалось сохранить изображение. Попробуйте ещё раз."
            )
            return

        # Получаем обновлённые данные
        data = await state.get_data()
        current_v_type = data.get("v_type", "imgtxt")
        current_model = data.get("v_model", "v26_pro")
        current_duration = data.get("v_duration", 5)
        current_ratio = data.get("v_ratio", "16:9")
        user_prompt = data.get("user_prompt", "")

        # Показываем подтверждение с обновлённым экраном
        image_status = "\n✅ <b>Изображение загружено!</b>\n"

        prompt_display = ""
        if user_prompt:
            prompt_display = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}</code>\n"

        text = (
            f"🎬 <b>Создание видео</b>\n\n"
            f"{image_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Фото + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>\n\n"
            f"Опишите движение, которое хотите создать:\n"
            f"• Как двигается объект\n"
            f"• Движение камеры\n"
            f"• Стиль и атмосфера"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
        return

    # Если это не режим imgtxt - игнорируем
    await message.answer("Пожалуйста, отправьте текстовое описание.")
    return


@router.message(
    GenerationStates.waiting_for_reference_video,
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def process_reference_video_upload(message: types.Message, state: FSMContext):
    """
    Обрабатывает загрузку референсного видео для режима video (видео+текст → видео).
    Сохраняет видео и переключает в состояние ожидания промпта.
    """
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    if generation_type == "video" and v_type == "video":
        # Определяем источник файла (video или document)
        if message.video:
            video_obj = message.video
        elif message.document and message.document.mime_type.startswith("video/"):
            video_obj = message.document
        else:
            await message.answer("❌ Неверный тип файла. Отправьте видео.")
            return

        file = await message.bot.get_file(video_obj.file_id)

        # Проверяем размер (макс 20MB для стабильности)
        file_size = getattr(video_obj, "file_size", 0)
        if file_size > 20 * 1024 * 1024:
            await message.answer("❌ Видео слишком большое (макс 20MB).")
            return

        video_bytes = await message.bot.download_file(file.file_path)
        video_data = video_bytes.read()

        # Сохраняем видео и получаем URL
        video_url = save_uploaded_file(video_data, "mp4")

        if video_url:
            await state.update_data(v_video_url=video_url)
            logger.info(f"Saved reference video for video mode: {video_url}")
        else:
            await message.answer("❌ Не удалось сохранить видео. Попробуйте ещё раз.")
            return

        # Переключаемся в состояние ожидания промпта
        await state.set_state(GenerationStates.waiting_for_video_prompt)

        # Получаем обновлённые данные
        data = await state.get_data()
        current_v_type = data.get("v_type", "video")
        current_model = data.get("v_model", "v26_pro")
        current_duration = data.get("v_duration", 5)
        current_ratio = data.get("v_ratio", "16:9")
        user_prompt = data.get("user_prompt", "")

        # Показываем экран с промптом
        video_status = "\n✅ <b>Референсное видео загружено!</b>\n"

        prompt_display = ""
        if user_prompt:
            prompt_display = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}</code>\n"

        text = (
            f"🎬 <b>Создание видео</b>\n\n"
            f"{video_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Видео + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>\n\n"
            f"Опишите желаемый эффект/стиль:\n"
            f"• Стиль видео\n"
            f"• Дополнительные эффекты\n"
            f"• Атмосфера\n\n"
            f"<i>Видео будет использовано как референс для движения/стиля (@Video1)</i>"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
        return

    await message.answer("Пожалуйста, отправьте текстовое описание.")


@router.message(GenerationStates.waiting_for_reference_video)
async def invalid_reference_video_input(message: types.Message, state: FSMContext):
    """
    Обрабатывает невалидный ввод в состоянии waiting_for_reference_video.
    """
    await message.answer(
        "⚠️ Пожалуйста, отправьте видео файл (макс 50MB).\n\n"
        "Это видео будет использовано как референс для стиля/движения."
    )


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
            text = f"✅ <b>Модель изменена</b>\n\n"
            text += f"{model_emoji} Теперь используется: <code>{model}</code>\n\n"

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
            text = f"✅ <b>Разрешение изменено</b>\n\n"
            text += f"{res_emoji} Теперь используется: <code>{resolution}</code>\n\n"

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
            text = f"✅ <b>Формат изменён</b>\n\n"
            text += f"📐 Теперь используется: <code>{ratio}</code>\n\n"

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
            text = f"✅ <b>Поиск в интернете: {status}</b>\n\n"

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
            f"📎 <b>Загрузка референсных изображений</b>\n\n"
            f"Загружено: <code>{len(current_refs)}/{max_refs}</code>\n\n"
            f"Отправьте фотографии (до {max_refs} штук), которые будут использоваться как референсы:\n"
            f"• До 10 объектов с высокой точностью\n"
            f"• До 4 персонажей для консистентности\n"
            f"• До 14 изображений суммарно\n\n"
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
            f"📎 <b>Референсы очищены</b>\n\n"
            f"Загружено: <code>0/{max_refs}</code>\n\n"
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
            data = await state.get_data()
            current_service = data.get("img_service", "flux_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>\n\n"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>\n\n"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>\n\n"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(
                    current_service, current_ratio, num_refs=len(current_refs)
                ),
                parse_mode="HTML",
            )
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
                data = await state.get_data()
                current_service = data.get("img_service", "flux_pro")
                current_ratio = data.get("img_ratio", "1:1")
                await callback.message.edit_text(
                    f"✨ <b>Создание фото</b>\n\n"
                    f"📎 Референсы загружены: <code>{len(current_refs)}</code>\n\n"
                    f"✨ Модель: <code>{current_service}</code>\n"
                    f"📐 Формат: <code>{current_ratio}</code>\n\n"
                    f"Введите промпт для генерации:",
                    reply_markup=get_create_image_keyboard(
                        current_service, current_ratio
                    ),
                    parse_mode="HTML",
                )
                await state.set_state(GenerationStates.waiting_for_input)

    elif action == "reload":
        # Перезагружаем — очищаем и начинаем заново
        await state.update_data(reference_images=[])
        await state.set_state(GenerationStates.uploading_reference_images)

        await callback.message.edit_text(
            f"📎 <b>Перезагрузка референсов</b>\n\n"
            f"Загружено: <code>0/{max_refs}</code>\n\n"
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
            current_service = data.get("img_service", "flux_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>\n\n"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>\n\n"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>\n\n"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(current_service, current_ratio),
                parse_mode="HTML",
            )
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
            f"📎 <b>Загрузите изображение</b>\n\n"
            f"Для пресета: {preset.name}\n\n"
            f"После загрузки изображения, {preset.input_prompt or 'введите описание'}\n\n"
            f"<i>{hint}</i>",
            reply_markup=get_back_keyboard(f"preset_{preset_id}"),
            parse_mode="HTML",
        )
    else:
        await state.set_state(GenerationStates.waiting_for_input)

        hint = UserHints.get_hint_for_stage("input")
        await callback.message.edit_text(
            f"✏️ <b>Введите ваш вариант</b>\n\n"
            f"{preset.input_prompt or 'Опишите, что хотите создать'}\n\n"
            f"Примеры для вдохновения:\n"
            f"• Стиль: минимализм, винтаж, футуризм\n"
            f"• Цветовая схема: яркий, пастельный, тёмный\n"
            f"• Эмоция: радостное, удивлённое, задумчивое\n\n"
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
        f"▶️ <b>Подтвердите генерацию</b>\n\n"
        f"Пресет: <b>{preset.name}</b>\n"
        f"Стоимость: <code>{preset.cost}</code>💎\n\n"
        f"<b>Промпт:</b>\n"
        f"<code>{final_prompt[:300]}{'...' if len(final_prompt) > 300 else ''}</code>\n\n"
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


@router.message(GenerationStates.waiting_for_input, F.photo)
async def process_photo_for_video_imgtxt(message: types.Message, state: FSMContext):
    """Обрабатывает загруженное фото для режима imgtxt (фото+текст → видео)"""
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    # Проверяем, что это режим создания видео и выбран тип imgtxt
    if generation_type == "video" and v_type == "imgtxt":
        # Скачиваем изображение
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()

        # Validate image dimensions for Kling API (Kie.ai requires min 300x300)
        try:
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(image_data))
            width, height = img.size
            if width < 300 or height < 300:
                await message.answer(
                    f"❌ <b>Изображение слишком маленькое!</b>\\n\\n"
                    f"Размер: {width}×{height} px\\n\\n"
                    "Kie.ai API требует минимум 300×300 px.\\n"
                    "Загрузите фото большего размера.",
                    parse_mode="HTML",
                    reply_markup=get_create_video_keyboard(
                        current_v_type=data.get("v_type", "imgtxt"),
                        current_model=data.get("v_model", "v26_pro"),
                        current_duration=data.get("v_duration", 5),
                        current_ratio=data.get("v_ratio", "16:9"),
                    ),
                )
                return
            logger.info(f"Image validated for Kling: {width}×{height}")
        except Exception as e:
            logger.error(f"Image validation failed: {e}")

        # Сохраняем изображение и получаем URL
        image_url = save_uploaded_file(image_data, "png")

        if image_url:
            await state.update_data(v_image_url=image_url)
            logger.info(f"Saved start image for video: {image_url}")
        else:
            await message.answer(
                "❌ Не удалось сохранить изображение. Попробуйте ещё раз."
            )
            return

        # Получаем обновлённые данные
        data = await state.get_data()
        current_v_type = data.get("v_type", "imgtxt")
        current_model = data.get("v_model", "v26_pro")
        current_duration = data.get("v_duration", 5)
        current_ratio = data.get("v_ratio", "16:9")
        user_prompt = data.get("user_prompt", "")

        # Показываем подтверждение с обновлённым экраном
        image_status = "\n✅ <b>Изображение загружено!</b>\n"

        prompt_display = ""
        if user_prompt:
            prompt_display = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}</code>\n"

        text = (
            f"🎬 <b>Создание видео</b>\n\n"
            f"{image_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Фото + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>\n\n"
            f"Опишите движение, которое хотите создать:\n"
            f"• Как двигается объект\n"
            f"• Движение камеры\n"
            f"• Стиль и атмосфера"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
        return

    # Если это не режим imgtxt - игнорируем (другие обработчики обработают)
    await message.answer("Пожалуйста, отправьте текстовое описание.")
    return


@router.message(GenerationStates.waiting_for_video_prompt, F.photo)
async def process_photo_for_video_prompt_state(
    message: types.Message, state: FSMContext
):
    """
    Обрабатывает загруженное фото когда пользователь в состоянии waiting_for_video_prompt.
    Это нужно для режима imgtxt (фото+текст → видео), когда пользователь загружает фото
    ДО ввода промпта.
    """
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    # Проверяем, что это режим создания видео и выбран тип imgtxt
    if generation_type == "video" and v_type == "imgtxt":
        # Скачиваем изображение
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()

        # Validate image dimensions for Kling API (Kie.ai requires min 300x300)
        try:
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(image_data))
            width, height = img.size
            if width < 300 or height < 300:
                await message.answer(
                    f"❌ <b>Изображение слишком маленькое!</b>\\n\\n"
                    f"Размер: {width}×{height} px\\n\\n"
                    "Kie.ai API требует минимум 300×300 px.\\n"
                    "Загрузите фото большего размера.",
                    parse_mode="HTML",
                    reply_markup=get_create_video_keyboard(
                        current_v_type=data.get("v_type", "imgtxt"),
                        current_model=data.get("v_model", "v26_pro"),
                        current_duration=data.get("v_duration", 5),
                        current_ratio=data.get("v_ratio", "16:9"),
                    ),
                )
                return
            logger.info(f"Image validated for Kling: {width}×{height}")
        except Exception as e:
            logger.error(f"Image validation failed: {e}")

        # Сохраняем изображение и получаем URL
        image_url = save_uploaded_file(image_data, "png")

        if image_url:
            await state.update_data(v_image_url=image_url)
            logger.info(
                f"Saved start image for video (waiting_for_video_prompt state): {image_url}"
            )
        else:
            await message.answer(
                "❌ Не удалось сохранить изображение. Попробуйте ещё раз."
            )
            return

        # Получаем обновлённые данные
        data = await state.get_data()
        current_v_type = data.get("v_type", "imgtxt")
        current_model = data.get("v_model", "v26_pro")
        current_duration = data.get("v_duration", 5)
        current_ratio = data.get("v_ratio", "16:9")
        user_prompt = data.get("user_prompt", "")

        # Показываем подтверждение с обновлённым экраном
        image_status = "\n✅ <b>Изображение загружено!</b>\n"

        prompt_display = ""
        if user_prompt:
            prompt_display = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}</code>\n"

        text = (
            f"🎬 <b>Создание видео</b>\n\n"
            f"{image_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Фото + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>\n\n"
            f"Опишите движение, которое хотите создать:\n"
            f"• Как двигается объект\n"
            f"• Движение камеры\n"
            f"• Стиль и атмосфера"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
        return

    # Если это не режим imgtxt - игнорируем
    await message.answer("Пожалуйста, отправьте текстовое описание.")
    return


@router.message(
    GenerationStates.waiting_for_reference_video,
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def process_reference_video_upload(message: types.Message, state: FSMContext):
    """
    Обрабатывает загрузку референсного видео для режима video (видео+текст → видео).
    Сохраняет видео и переключает в состояние ожидания промпта.
    """
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    if generation_type == "video" and v_type == "video":
        # Определяем источник файла (video или document)
        if message.video:
            video_obj = message.video
        elif message.document and message.document.mime_type.startswith("video/"):
            video_obj = message.document
        else:
            await message.answer("❌ Неверный тип файла. Отправьте видео.")
            return

        file = await message.bot.get_file(video_obj.file_id)

        # Проверяем размер (макс 20MB для стабильности)
        file_size = getattr(video_obj, "file_size", 0)
        if file_size > 20 * 1024 * 1024:
            await message.answer("❌ Видео слишком большое (макс 20MB).")
            return

        video_bytes = await message.bot.download_file(file.file_path)
        video_data = video_bytes.read()

        # Сохраняем видео и получаем URL
        video_url = save_uploaded_file(video_data, "mp4")

        if video_url:
            await state.update_data(v_video_url=video_url)
            logger.info(f"Saved reference video for video mode: {video_url}")
        else:
            await message.answer("❌ Не удалось сохранить видео. Попробуйте ещё раз.")
            return

        # Переключаемся в состояние ожидания промпта
        await state.set_state(GenerationStates.waiting_for_video_prompt)

        # Получаем обновлённые данные
        data = await state.get_data()
        current_v_type = data.get("v_type", "video")
        current_model = data.get("v_model", "v26_pro")
        current_duration = data.get("v_duration", 5)
        current_ratio = data.get("v_ratio", "16:9")
        user_prompt = data.get("user_prompt", "")

        # Показываем экран с промптом
        video_status = "\n✅ <b>Референсное видео загружено!</b>\n"

        prompt_display = ""
        if user_prompt:
            prompt_display = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}</code>\n"

        text = (
            f"🎬 <b>Создание видео</b>\n\n"
            f"{video_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Видео + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>\n\n"
            f"Опишите желаемый эффект/стиль:\n"
            f"• Стиль видео\n"
            f"• Дополнительные эффекты\n"
            f"• Атмосфера\n\n"
            f"<i>Видео будет использовано как референс для движения/стиля (@Video1)</i>"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
        return

    await message.answer("Пожалуйста, отправьте текстовое описание.")


@router.message(GenerationStates.waiting_for_reference_video)
async def invalid_reference_video_input(message: types.Message, state: FSMContext):
    """
    Обрабатывает невалидный ввод в состоянии waiting_for_reference_video.
    """
    await message.answer(
        "⚠️ Пожалуйста, отправьте видео файл (макс 50MB).\\n\\n"
        "Это видео будет использовано как референс для стиля/движения."
    )
