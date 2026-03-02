import asyncio
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
    get_duration_keyboard,
    get_image_aspect_ratio_keyboard,
    get_image_aspect_ratio_no_preset_edit_keyboard,
    get_image_aspect_ratio_no_preset_keyboard,
    get_image_editing_options_keyboard,
    get_main_menu_keyboard,
    get_model_selection_keyboard,
    get_multiturn_keyboard,
    get_preset_action_keyboard,
    get_prompt_tips_keyboard,
    get_reference_images_keyboard,
    get_resolution_keyboard,
    get_search_grounding_keyboard,
    get_video_edit_confirm_keyboard,
    get_video_edit_input_type_keyboard,
    get_video_edit_keyboard,
    get_video_options_no_preset_keyboard,
)
from bot.services.gemini_service import gemini_service
from bot.services.preset_manager import preset_manager
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
    """Начинает генерацию изображения без пресета - сразу запрашивает промпт"""
    await state.set_state(GenerationStates.waiting_for_input)

    user_credits = await get_user_credits(callback.from_user.id)
    settings = await get_user_settings(callback.from_user.id)

    # Получаем сервис для генерации изображений
    image_service = settings.get("image_service", "nanobanana")

    # Названия и стоимость в зависимости от сервиса
    if image_service == "novita":
        model_name = "✨ FLUX.2 Pro"
    elif image_service == "seedream":
        model_name = "🎨 Seedream"
    else:  # nanobanana
        model_name = "🍌 Nano Banana"
    model_cost = "2"

    # Сохраняем сервис и тип генерации в state
    await state.update_data(generation_type="image", image_service=image_service)

    await callback.message.edit_text(
        f"🖼 <b>Генерация фото</b>\n\n"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: {model_name} ({model_cost}🍌)\n\n"
        f"Опишите, что хотите создать:\n"
        f"• Что должно быть на изображении\n"
        f"• Стиль (фотореализм, аниме, живопись...)\n"
        f"• Цветовая гамма\n"
        f"• и т.д.\n\n"
        f"<i>Чем подробнее описание — тем лучше результат!</i>",
        reply_markup=get_back_keyboard("back_main"),
        parse_mode="HTML",
    )
    await callback.answer()


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

    await callback.message.edit_text(
        f"✏️ <b>Редактирование фото</b>\n\n"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: 💎 Banano Pro (3🍌, 4K, сохранение лиц)\n\n"
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
    model_costs = {
        "v3_std": "4",
        "v3_pro": "5",
        "v3_omni_std": "5",
        "v3_omni_pro": "6",
    }
    model_name = model_names.get(video_model, video_model)
    model_cost = model_costs.get(video_model, "4")

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
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: {model_name} ({model_cost}🍌)\n\n"
        f"<b>Опции видео:</b>\n"
        f"   ⏱ Длительность: <code>5 сек</code>\n"
        f"   📐 Формат: <code>16:9</code>\n"
        f"   🔊 Со звуком: <code>Да</code>\n\n"
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
                [types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")],
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


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
        f"🔊 Звук: {'Да' if video_options.get('generate_audio', True) else 'Нет'}</i>",
        reply_markup=get_video_options_no_preset_keyboard(
            video_options.get("duration", 5),
            video_options.get("aspect_ratio", "16:9"),
            video_options.get("generate_audio", True),
        ),
        parse_mode="HTML",
    )
    await callback.answer()


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
    model_costs = {
        "v3_std": "6",
        "v3_pro": "6",
        "v3_omni_std": "6",
        "v3_omni_pro": "6",
    }
    model_name = model_names.get(video_model, video_model)
    model_cost = model_costs.get(video_model, "6")

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
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: {model_name} ({model_cost}🍌)\n\n"
        f"<b>Kling 3 Omni</b>\n"
        f"Выберите, что хотите загрузить:\n\n"
        f"🎬 <b>Видео</b> - преобразование видео\n"
        f"🖼 <b>Фото</b> - создание видео из изображения\n\n"
        f"<i>Загрузите медиафайл и опишите эффект</i>",
        reply_markup=get_video_edit_input_type_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


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
    model_costs = {
        "v3_std": "6",
        "v3_pro": "6",
        "v3_omni_std": "6",
        "v3_omni_pro": "6",
    }
    model_name = model_names.get(video_model, video_model)
    model_cost = model_costs.get(video_model, "6")

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
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: {model_name} ({model_cost}🍌)\n\n"
        f"<b>Kling 3 - Image to Video</b>\n"
        f"Загрузите изображение,\n"
        f"которое хотите превратить в видео.\n"
        f"После загрузки опишите движение.\n\n"
        f"<i>Например: птица летит в небе, волны накатывают на берег</i>",
        reply_markup=get_back_keyboard("back_main"),
        parse_mode="HTML",
    )
    await callback.answer()


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
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n\n"
        f"<b>Kling 3 Omni</b>\n"
        f"Выберите, что хотите загрузить:\n\n"
        f"🎬 <b>Видео</b> - преобразование видео\n"
        f"🖼 <b>Фото</b> - создание видео из изображения\n\n"
        f"<i>Загрузите медиафайл и опишите эффект</i>",
        reply_markup=get_video_edit_input_type_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


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


@router.callback_query(F.data.startswith("cat_"))
async def show_category(callback: types.CallbackQuery):
    """Показывает пресеты выбранной категории"""
    category = callback.data.replace("cat_", "")
    presets = preset_manager.get_category_presets(category)
    categories = preset_manager.get_categories()

    if not presets:
        await callback.answer("Категория пуста")
        return

    if category not in categories:
        await callback.answer("Категория не найдена")
        return

    user_credits = await get_user_credits(callback.from_user.id)

    # UX: Добавляем подсказку для пользователя
    hint = UserHints.get_hint_for_stage("category")

    await callback.message.edit_text(
        f"📂 <b>{categories[category]['name']}</b>\n"
        f"📝 {categories[category].get('description', '')}\n\n"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n\n"
        f"Выберите пресет:\n\n"
        f"<i>{hint}</i>",
        reply_markup=get_category_keyboard(category, presets, user_credits),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("preset_"))
async def show_preset_details(callback: types.CallbackQuery, state: FSMContext):
    """Показывает детали пресета и варианты действий"""
    preset_id = callback.data.replace("preset_", "")
    preset = preset_manager.get_preset(preset_id)

    if not preset:
        await callback.answer("Пресет не найден")
        return

    # Инициализируем опции генерации согласно banana_api.md
    generation_options = {
        "model": preset.model,
        "aspect_ratio": preset.aspect_ratio or "1:1",
        "resolution": "1K",
        "enable_search": False,
        "reference_images": [],
        "person_references": [],
    }

    # Для видео свои опции
    video_options = {}
    if preset.category in ["video_generation", "video_editing"]:
        video_options = {
            "duration": preset.duration or 5,
            "aspect_ratio": preset.aspect_ratio or "16:9",
            "quality": getattr(preset, "quality", "std"),
            "generate_audio": True,
        }

    await state.update_data(
        preset_id=preset_id,
        video_options=video_options,
        generation_options=generation_options,
    )

    user_credits = await get_user_credits(callback.from_user.id)
    is_admin = config.is_admin(callback.from_user.id)

    # Админы могут использовать бесплатно
    if not is_admin and user_credits < preset.cost:
        error_msg = get_error_handling()["no_credits"].format(
            cost=preset.cost, credits=user_credits
        )
        await callback.message.edit_text(
            error_msg,
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
        return

    # Формируем текст с информацией о пресете
    text = f"🎯 <b>{preset.name}</b>\n\n"
    text += f"🍌 Стоимость: <code>{preset.cost}</code>🍌\n"
    text += f"🤖 Модель: <code>{preset.model}</code>\n"

    if hasattr(preset, "description") and preset.description:
        text += f"\n📝 {preset.description}\n"

    # Показываем опции для видео
    if preset.category in ["video_generation", "video_editing"]:
        opts = video_options
        quality_emoji = "💎" if opts.get("quality") == "pro" else "⚡"
        text += f"\n🎬 <b>Опции видео:</b>\n"
        text += f"   ⏱ Длительность: <code>{opts.get('duration', 5)} сек</code>\n"
        text += f"   📐 Формат: <code>{opts.get('aspect_ratio', '16:9')}</code>\n"
        text += f"   {quality_emoji} Качество: <code>{opts.get('quality', 'std').upper()}</code>\n"
        text += f"   🔊 Звук: <code>{'ВКЛ' if opts.get('generate_audio') else 'ВЫКЛ'}</code>\n"

    # Показываем опции для изображений
    elif preset.category in ["image_generation", "image_editing"]:
        # Добавляем секцию опций генерации (согласно banana_api.md)
        text += f"\n⚙️ <b>Опции генерации:</b>\n"
        model_emoji = "💎" if "pro" in generation_options["model"] else "⚡"
        text += f"   {model_emoji} Модель: <code>{generation_options['model']}</code>\n"
        text += f"   📐 Формат: <code>{generation_options['aspect_ratio']}</code>\n"
        text += f"   👁 Разрешение: <code>{generation_options['resolution']}</code>\n"
        if generation_options["enable_search"]:
            text += f"   🔍 Поиск: <code>ВКЛ</code>\n"

    if preset.aspect_ratio and preset.category not in [
        "video_generation",
        "video_editing",
    ]:
        text += f"   📐 Формат: <code>{preset.aspect_ratio}</code>\n"

    # Добавляем подсказку
    hint = UserHints.get_hint_for_stage("preset")
    text += f"\n<i>{hint}</i>"

    # Выбираем клавиатуру в зависимости от категории
    if preset.category in ["image_generation", "image_editing"]:
        reply_markup = get_preset_action_keyboard(
            preset_id, preset.requires_input, preset.category
        )
    else:
        reply_markup = get_preset_action_keyboard(
            preset_id, preset.requires_input, preset.category
        )

    await callback.message.edit_text(
        text,
        reply_markup=reply_markup,
        parse_mode="HTML",
    )


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

        await state.set_state(GenerationStates.confirming_reference_images)

        # Показываем превью загруженных изображений
        ref_count = len(current_refs)
        await callback.message.edit_text(
            f"✅ <b>Референсные изображения загружены</b>\n\n"
            f"Количество: <code>{ref_count}</code> из <code>{max_refs}</code>\n\n"
            f"Теперь вы можете:\n"
            f"• 🔄 Перезагрузить — загрузить другие изображения\n"
            f"• ✅ Подтвердить — продолжить с текущими референсами",
            reply_markup=get_reference_images_confirmation_keyboard(preset_id),
            parse_mode="HTML",
        )

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
        # Сохраняем референсы в generation_options и возвращаемся к пресету
        generation_options = data.get("generation_options", {})
        generation_options["reference_images"] = current_refs
        await state.update_data(generation_options=generation_options)

        preset = preset_manager.get_preset(preset_id)
        if preset:
            # Возвращаемся к экрану пресета
            await show_preset_details(callback.message, preset, callback.from_user.id)
        else:
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
        f"Стоимость: <code>{preset.cost}</code>🍌\n\n"
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


@router.message(GenerationStates.waiting_for_input)
async def process_custom_input(message: types.Message, state: FSMContext):
    """Обрабатывает текстовый ввод пользователя"""
    data = await state.get_data()
    preset_id = data.get("preset_id")
    generation_type = data.get("generation_type")

    # Guard: ensure we have text input — avoid NoneType slicing errors
    if not message.text:
        await message.answer("Пожалуйста, отправьте текстовый промпт (только текст).")
        return

    # Если это генерация изображения - показываем выбор формата
    if generation_type == "image":
        final_prompt = message.text
        await state.update_data(user_prompt=final_prompt)

        await message.answer(
            f"🖼 <b>Выберите формат изображения</b>\n\n"
            f"Промпт: <code>{final_prompt[:100]}{'...' if len(final_prompt) > 100 else ''}</code>\n\n"
            f"<i>Выберите формат и нажмите кнопку для запуска</i>",
            reply_markup=get_image_aspect_ratio_no_preset_keyboard("1:1"),
            parse_mode="HTML",
        )
        return

    # Если это генерация видео - показываем меню опций
    if generation_type == "video":
        final_prompt = message.text
        await state.update_data(user_prompt=final_prompt)

        # Показываем меню опций видео
        await message.answer(
            f"🎬 <b>Настройка видео</b>\n\n"
            f"Промпт: <code>{final_prompt[:100]}{'...' if len(final_prompt) > 100 else ''}</code>\n\n"
            f"Выберите параметры и нажмите ▶️ Запустить:",
            reply_markup=get_video_options_no_preset_keyboard(),
            parse_mode="HTML",
        )
        return

    # Если это редактирование изображения - показываем выбор формата
    if generation_type == "image_edit":
        user_prompt = message.text
        await state.update_data(user_prompt=user_prompt)

        # Показываем клавиатуру выбора формата
        await message.answer(
            f"✏️ <b>Выберите формат изображения</b>\n\n"
            f"Промпт: <code>{user_prompt[:100]}{'...' if len(user_prompt) > 100 else ''}</code>\n\n"
            f"<i>Выберите формат и нажмите кнопку для запуска</i>",
            reply_markup=get_image_aspect_ratio_no_preset_edit_keyboard("1:1"),
            parse_mode="HTML",
        )
        return

    # Если это редактирование видео - показываем подтверждение
    if generation_type == "video_edit":
        user_prompt = message.text
        await state.update_data(user_prompt=user_prompt)

        video_edit_options = data.get("video_edit_options", {})
        quality = video_edit_options.get("quality", "std")
        quality_emoji = "💎" if quality == "pro" else "⚡"

        # Стоимость видео: базовая 6 + доплата за длительность
        duration = video_edit_options.get("duration", 5)
        base_cost = 6
        if duration == 10:
            cost = 8
        elif duration == 15:
            cost = 10
        else:
            cost = base_cost

        await message.answer(
            f"✂️ <b>Подтвердите генерацию</b>\n\n"
            f"<b>Эффект:</b> <code>{user_prompt[:100]}{'...' if len(user_prompt) > 100 else ''}</code>\n\n"
            f"<b>Опции:</b>\n"
            f"   {quality_emoji} Качество: <code>{quality.upper()}</code>\n"
            f"   ⏱ Длительность: <code>{duration} сек</code>\n"
            f"   📐 Формат: <code>{video_edit_options.get('aspect_ratio', '16:9')}</code>\n\n"
            f"Стоимость: <code>{cost}🍌</code>",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(
                            text="▶️ Запустить", callback_data="run_video_edit"
                        )
                    ],
                    [
                        types.InlineKeyboardButton(
                            text="🔙 Назад", callback_data="edit_video"
                        )
                    ],
                ]
            ),
            parse_mode="HTML",
        )
        return

    # Стандартное поведение для пресетов
    final_prompt = message.text
    await state.update_data(final_prompt=final_prompt)

    preset = preset_manager.get_preset(preset_id)
    if preset:
        await state.set_state(GenerationStates.confirming_generation)

        # Показываем подтверждение с возможностью добавить референсы
        has_refs = bool(data.get("reference_images"))

        await message.answer(
            f"▶️ <b>Подтвердите генерацию</b>\n\n"
            f"Пресет: <b>{preset.name}</b>\n"
            f"Стоимость: <code>{preset.cost}</code>🍌\n\n"
            f"<b>Промпт:</b>\n"
            f"<code>{final_prompt[:300]}{'...' if len(final_prompt) > 300 else ''}</code>\n\n"
            f"📎 Референсы: {'✅ Загружено' if has_refs else '❌ Нет'} (до 14 изображений)",
            reply_markup=get_preset_action_keyboard(preset_id, has_input=True),
            parse_mode="HTML",
        )
        return

    # Если это создание видео из изображения через видео-эффекты
    if generation_type == "video_edit_image":
        user_prompt = message.text
        await state.update_data(user_prompt=user_prompt)

        video_edit_options = data.get("video_edit_options", {})
        quality = video_edit_options.get("quality", "std")
        quality_emoji = "💎" if quality == "pro" else "⚡"

        # Стоимость видео: базовая 6 + доплата за длительность
        duration = video_edit_options.get("duration", 5)
        base_cost = 6
        if duration == 10:
            cost = 8
        elif duration == 15:
            cost = 10
        else:
            cost = base_cost

        await message.answer(
            f"✂️ <b>Подтвердите генерацию</b>\n\n"
            f"<b>Эффект:</b> <code>{user_prompt[:100]}{'...' if len(user_prompt) > 100 else ''}</code>\n\n"
            f"<b>Опции:</b>\n"
            f"   {quality_emoji} Качество: <code>{quality.upper()}</code>\n"
            f"   ⏱ Длительность: <code>{duration} сек</code>\n"
            f"   📐 Формат: <code>{video_edit_options.get('aspect_ratio', '16:9')}</code>\n\n"
            f"🍌 Стоимость: <code>{cost}</code>🍌",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(
                            text="▶️ Запустить", callback_data="run_video_edit_image"
                        )
                    ],
                    [
                        types.InlineKeyboardButton(
                            text="🔙 Назад", callback_data="edit_video"
                        )
                    ],
                ]
            ),
            parse_mode="HTML",
        )
        return

    # Если это "Фото в видео" - запускаем генерацию
    if generation_type == "image_to_video":
        user_prompt = message.text
        await state.update_data(user_prompt=user_prompt)

        # Запускаем генерацию видео из фото
        await run_image_to_video(message, state, user_prompt)
        return

    # Старый код для пресетов
    if not preset_id:
        await message.answer("Ошибка: пресет не выбран. Начните заново.")
        await state.clear()
        return

    preset = preset_manager.get_preset(preset_id)

    if not preset:
        await message.answer("Ошибка: пресет не найден.")
        await state.clear()
        return

    # Формируем финальный промпт
    placeholder_values = {}
    if preset.placeholders:
        placeholder_values[preset.placeholders[0]] = message.text

        defaults = preset_manager.get_default_values("styles") or ["минимализм"]
        color_defaults = preset_manager.get_default_values("color_schemes") or ["яркий"]

        for placeholder in preset.placeholders[1:]:
            if "style" in placeholder.lower():
                placeholder_values[placeholder] = defaults[0]
            elif "color" in placeholder.lower():
                placeholder_values[placeholder] = color_defaults[0]
            else:
                placeholder_values[placeholder] = "пример"

    try:
        final_prompt = preset.format_prompt(**placeholder_values)
    except:
        final_prompt = preset.prompt.replace("{", "").replace("}", "")

    await state.update_data(final_prompt=final_prompt, user_input=message.text)

    # Подтверждение с опциями
    generation_options = data.get("generation_options", {})

    await message.answer(
        f"▶️ <b>Подтвердите генерацию</b>\n\n"
        f"Пресет: <b>{preset.name}</b>\n"
        f"Стоимость: <code>{preset.cost}</code>🍌\n\n"
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


async def start_no_preset_generation(
    message: types.Message, state: FSMContext, gen_type: str, prompt: str
):
    """Запускает генерацию без пресета"""
    # Определяем стоимость (изображения: 2-3, видео: 6+)
    cost = 2 if gen_type == "image" else 6

    # Проверяем баланс
    if not await check_can_afford(message.from_user.id, cost):
        await message.answer(
            f"❌ Недостаточно бананов!\n" f"Нужно: {cost}🍌\n" f"Пополните баланс.",
            reply_markup=get_main_menu_keyboard(),
        )
        await state.clear()
        return

    # Списываем
    await deduct_credits(message.from_user.id, cost)

    if gen_type == "image":
        # Генерируем изображение
        processing = await message.answer(
            "🎨 <b>Генерирую изображение...</b>\n\n" f"<i>Это займёт 10-30 секунд</i>",
            parse_mode="HTML",
        )

        try:
            from bot.services.gemini_service import gemini_service

            result = await gemini_service.generate_image(
                prompt=prompt,
                model="gemini-3-pro-image-preview",
                aspect_ratio="1:1",
                image_input=None,
            )

            await processing.delete()

            if result:
                # Сохраняем
                saved_url = save_uploaded_file(result, "png")

                # Сохраняем оригинальные байты и URL в состоянии для кнопки скачивания
                try:
                    await state.update_data(
                        last_generated_image_bytes=result,
                        last_generated_image_url=saved_url,
                    )
                except Exception:
                    logger.exception("Failed to update state with last_generated_image")

                # Создаём задачу в БД
                if saved_url:
                    from bot.database import add_generation_task, complete_video_task

                    user = await get_or_create_user(message.from_user.id)
                    task_id = f"img_{uuid.uuid4().hex[:12]}"
                    await add_generation_task(user.id, task_id, "image", "no_preset")
                    await complete_video_task(task_id, saved_url)

                # Отправляем превью (photo) и оригинал как документ
                photo = types.BufferedInputFile(result, filename="generated.png")
                await message.answer_photo(
                    photo=photo,
                    caption=f"✅ <b>Готово!</b>\n\n" f"<code>{cost}</code>🍌 списано",
                    parse_mode="HTML",
                    reply_markup=get_multiturn_keyboard("no_preset"),
                )

                await _send_original_document(
                    message.answer_document, result, saved_url
                )
            else:
                await add_credits(message.from_user.id, cost)
                await message.answer("❌ Не удалось сгенерировать. Бананы возвращены.")

        except Exception as e:
            logger.exception(f"Error: {e}")
            await add_credits(message.from_user.id, cost)
            await message.answer(f"❌ Ошибка: {str(e)[:100]}")
    else:
        # Генерируем видео
        data = await state.get_data()
        video_options = data.get("video_options", {})

        processing = await message.answer(
            "🎬 <b>Видео готовится...</b>\n\n"
            f"⏱ Длительность: {video_options.get('duration', 5)} сек\n"
            f"📐 Формат: {video_options.get('aspect_ratio', '16:9')}\n\n"
            "<i>Это займёт 1-3 минуты</i>",
            parse_mode="HTML",
        )

        try:
            from bot.services.kling_service import kling_service

            # Ensure duration is int (it might come as string from callback_data)
            duration = int(video_options.get("duration", 5))
            logger.info(
                f"Generating video: duration={duration} (type={type(duration).__name__}), options={video_options}"
            )
            result = await kling_service.generate_video(
                prompt=prompt,
                model="v3_std",
                duration=duration,
                aspect_ratio=video_options.get("aspect_ratio", "16:9"),
                webhook_url=config.kling_notification_url
                if config.WEBHOOK_HOST
                else None,
            )

            await processing.delete()

            if result and result.get("task_id"):
                from bot.database import add_generation_task

                user = await get_or_create_user(message.from_user.id)
                await add_generation_task(
                    user.id, result["task_id"], "video", "no_preset"
                )

                await message.answer(
                    f"✅ <b>Задача создана!</b>\n\n"
                    f"ID: <code>{result['task_id']}</code>\n"
                    f"<code>{cost}</code>🍌 списано\n\n"
                    "🎬 Видео будет готово через 1-3 минуты.",
                    parse_mode="HTML",
                )
            else:
                await add_credits(message.from_user.id, cost)
                await message.answer("❌ Ошибка. Бананы возвращены.")

        except Exception as e:
            logger.exception(f"Error: {e}")
            await add_credits(message.from_user.id, cost)
            await message.answer(f"❌ Ошибка: {str(e)[:100]}")

    await state.clear()


@router.message(GenerationStates.waiting_for_image, F.photo)
async def process_uploaded_image(message: types.Message, state: FSMContext):
    """Обрабатывает загруженное изображение"""
    data = await state.get_data()
    preset_id = data.get("preset_id")
    generation_type = data.get("generation_type")

    # Если это режим без пресета (редактирование)
    if generation_type in [
        "image_edit",
        "video_edit",
        "image_to_video",
        "video_edit_image",
    ]:
        # Скачиваем изображение
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file.file_path)

        # Читаем байты
        image_data = image_bytes.read()

        # Для image_edit: проверяем, есть ли уже главное фото
        if generation_type == "image_edit":
            uploaded_image = data.get("uploaded_image")
            ref_images = data.get("reference_images", [])

            if uploaded_image and len(ref_images) < 4:
                # Уже есть главное фото — добавляем как референс лица
                ref_images.append(image_data)
                await state.update_data(reference_images=ref_images)

                await message.answer(
                    f"✅ <b>Референс лица добавлен!</b>\n"
                    f"📎 Всего референсов: <code>{len(ref_images)}/4</code>\n\n"
                    f"Можете добавить ещё или нажмите «Пропустить» для ввода промпта",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                types.InlineKeyboardButton(
                                    text="✅ Продолжить, ввести промпт",
                                    callback_data="skip_face_ref",
                                )
                            ]
                        ]
                    ),
                    parse_mode="HTML",
                )
                return
            elif uploaded_image and len(ref_images) >= 4:
                # Достигнут лимит референсов
                await state.set_state(GenerationStates.waiting_for_input)
                await message.answer(
                    f"✅ <b>Достигнут лимит референсов (4)</b>\n\n"
                    f"Теперь опишите, что нужно сделать:\n"
                    f"• Изменить стиль\n"
                    f"• Добавить/удалить элементы\n"
                    f"• Сохранить лицо как на референсе\n"
                    f"• и т.д.",
                    reply_markup=get_back_keyboard("back_main"),
                    parse_mode="HTML",
                )
                return

        # Сохраняем в папку static/uploads (только для главного фото)
        if generation_type != "image_edit" or not data.get("uploaded_image"):
            image_url = save_uploaded_file(image_data, "png")

            if image_url:
                await state.update_data(
                    uploaded_image=image_data, uploaded_image_url=image_url
                )
            else:
                await state.update_data(uploaded_image=image_data)

        # Запрашиваем описание
        if generation_type == "image_edit":
            # Проверяем, есть ли уже референсы
            ref_images = data.get("reference_images", [])

            if not ref_images:
                # Первое фото — главное, предлагаем добавить референсы лиц
                await state.set_state(GenerationStates.waiting_for_image)
                await message.answer(
                    f"✅ <b>Главное фото получено!</b>\n\n"
                    f"Теперь вы можете:\n"
                    f"• Отправить до <b>4 фото лица</b> для сохранения\n"
                    f"• Или сразу ввести описание изменений\n\n"
                    f"<i>Для сохранения лица: отправьте фото лица крупным планом</i>",
                    reply_markup=types.InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                types.InlineKeyboardButton(
                                    text="✅ Пропустить, ввести промпт",
                                    callback_data="skip_face_ref",
                                )
                            ]
                        ]
                    ),
                    parse_mode="HTML",
                )
            else:
                # Уже есть референсы, переходим к промпту
                await state.set_state(GenerationStates.waiting_for_input)
                await message.answer(
                    f"✅ <b>Фото получено!</b>\n"
                    f"📎 Референсов лица: <code>{len(ref_images)}</code>\n\n"
                    f"Теперь опишите, что нужно сделать:\n"
                    f"• Изменить стиль\n"
                    f"• Добавить/удалить элементы\n"
                    f"• Сохранить лицо как на референсе\n"
                    f"• и т.д.",
                    reply_markup=get_back_keyboard("back_main"),
                    parse_mode="HTML",
                )
            return
        elif generation_type == "video_edit_image":
            prompt_text = (
                f"✅ Изображение получено!\n\n"
                f"Теперь опишите желаемое движение и эффект:\n"
                f"• Как должно двигаться изображение\n"
                f"• Какой стиль видео\n"
                f"• Особые эффекты\n\n"
                f"<i>Например: 'Плавное движение камеры влево, кинематографичный стиль'</i>"
            )
        else:
            edit_type = "видео"
            prompt_text = (
                f"✅ Изображение получено!\n\n"
                f"Теперь опишите, что нужно сделать с {edit_type}:\n"
                f"• Изменить стиль\n"
                f"• Добавить элемент\n"
                f"• Удалить объект\n"
                f"• и т.д."
            )

        await state.set_state(GenerationStates.waiting_for_input)
        await message.answer(
            prompt_text, parse_mode="HTML", reply_markup=get_back_keyboard("back_main")
        )
        return

    # Старый код для пресетов
    if not preset_id:
        await message.answer("Ошибка: пресет не выбран. Начните заново.")
        await state.clear()
        return

    preset = preset_manager.get_preset(preset_id)

    if not preset:
        await message.answer("Ошибка: пресет не найден.")
        await state.clear()
        return

    # Скачиваем изображение
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)

    # Читаем байты для сохранения в память
    image_data = image_bytes.read()

    # Сохраняем файл в папку static/uploads
    image_url = save_uploaded_file(image_data, "png")

    if image_url:
        logger.info(f"Image saved to static: {image_url}")
        # Сохраняем и байты (для AI), и URL
        await state.update_data(uploaded_image=image_data, uploaded_image_url=image_url)
    else:
        # Fallback - только байты в память
        logger.warning("Failed to save image to static, using in-memory only")
        await state.update_data(uploaded_image=image_data)

    if preset.requires_input:
        await state.set_state(GenerationStates.waiting_for_input)
        await message.answer(
            f"✅ Изображение получено!\n\n"
            f"{preset.input_prompt or 'Введите описание того, что нужно сделать с изображением:'}",
            reply_markup=get_back_keyboard(f"preset_{preset_id}"),
        )
    else:
        await state.set_state(GenerationStates.confirming_generation)
        await message.answer(
            f"✅ Изображение получено!\n\n"
            f"Пресет: <b>{preset.name}</b>\n"
            f"Стоимость: <code>{preset.cost}</code>🍌",
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


# =============================================================================
# ЗАГРУЗКА РЕФЕРЕНСНЫХ ИЗОБРАЖЕНИЙ (до 14 шт)
# =============================================================================


@router.message(GenerationStates.uploading_reference_images, F.photo)
async def process_reference_images_upload(message: types.Message, state: FSMContext):
    """
    Обрабатывает загрузку референсных изображений (до 14)
    Согласно документации: до 10 объектов с высокой точностью,
    до 4 персонажей для консистентности, до 14 суммарно
    """
    data = await state.get_data()
    current_refs = data.get("reference_images", [])
    preset_id = data.get("preset_id")
    max_refs = 14

    # Проверяем лимит
    if len(current_refs) >= max_refs:
        await message.answer(
            f"⚠️ <b>Достигнут лимит референсов</b>\n\n"
            f"Загружено максимальное количество: <code>{max_refs}/{max_refs}</code>\n"
            f"Нажмите ▶️ Продолжить для перехода к генерации.",
            reply_markup=get_reference_images_upload_keyboard(
                len(current_refs), max_refs, preset_id
            ),
            parse_mode="HTML",
        )
        return

    # Скачиваем изображение
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)
    image_data = image_bytes.read()

    # Добавляем к списку референсов
    current_refs.append(image_data)
    await state.update_data(reference_images=current_refs)

    remaining = max_refs - len(current_refs)

    await message.answer(
        f"✅ <b>Изображение добавлено!</b>\n\n"
        f"Загружено: <code>{len(current_refs)}/{max_refs}</code>\n"
        f"Осталось: <code>{remaining}</code>\n\n"
        f"Отправьте еще фото или нажмите ▶️ Продолжить",
        reply_markup=get_reference_images_upload_keyboard(
            len(current_refs), max_refs, preset_id
        ),
        parse_mode="HTML",
    )


@router.message(GenerationStates.uploading_reference_images)
async def invalid_reference_upload(message: types.Message, state: FSMContext):
    """Обрабатывает невалидный ввод при загрузке референсов"""
    data = await state.get_data()
    current_refs = data.get("reference_images", [])
    preset_id = data.get("preset_id")
    max_refs = 14

    await message.answer(
        f"⚠️ Пожалуйста, отправьте изображение (фото)\n\n"
        f"Или нажмите ▶️ Продолжить если загрузили все референсы",
        reply_markup=get_reference_images_upload_keyboard(
            len(current_refs), max_refs, preset_id
        ),
    )


# =============================================================================
# ЗАПУСК ГЕНЕРАЦИИ
# =============================================================================


@router.callback_query(F.data.startswith("run_") & ~F.data.startswith("run_no_preset"))
async def execute_generation(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    """Запускает процесс генерации через пресеты"""
    callback_data = callback.data

    preset_id = callback_data.replace("run_", "")
    preset = preset_manager.get_preset(preset_id)
    data = await state.get_data()

    if not preset:
        await callback.answer("Пресет не найден")
        return

    # Проверяем возможность оплаты (админы всегда могут)
    if not await check_can_afford(callback.from_user.id, preset.cost):
        await callback.answer("Недостаточно кредитов!", show_alert=True)
        return

    # Списываем кредиты (админам - бесплатно)
    success = await deduct_credits(callback.from_user.id, preset.cost)
    if not success:
        await callback.answer("Ошибка списания кредитов", show_alert=True)
        return

    await callback.answer("🚀 Запускаю генерацию...")

    # Получаем финальный промпт и опции
    final_prompt = data.get("final_prompt", preset.prompt)
    uploaded_image = data.get("uploaded_image")
    generation_options = data.get("generation_options", {})

    # Определяем тип генерации
    if preset.category in ["image_generation", "image_editing"]:
        await generate_image(
            callback,
            preset,
            final_prompt,
            uploaded_image,
            bot,
            state,
            generation_options,
        )
    else:
        await generate_video(callback, preset, final_prompt, uploaded_image, bot, state)

    # Сохраняем в историю
    user = await get_or_create_user(callback.from_user.id)
    await add_generation_history(user.id, preset_id, final_prompt, preset.cost)

    await state.clear()


async def generate_image(
    callback, preset, prompt, image_bytes, bot: Bot, state: FSMContext, options: dict
):
    """Генерация изображения через Gemini с расширенными опциями"""

    # UX: Показываем мотивирующее сообщение
    encouragements = UserHints.get_encouragement()
    random.shuffle(encouragements)

    processing_msg = await callback.message.answer(
        f"{encouragements[0]}\n\n"
        f"🎨 <b>Генерирую изображение...</b>\n\n"
        f"⏱ Это займёт 10-30 секунд\n\n"
        f"<i>Модель: {options.get('model', 'gemini-3-pro-image-preview')}</i>",
        parse_mode="HTML",
    )

    try:
        from bot.services.gemini_service import gemini_service

        result = await gemini_service.generate_image(
            prompt=prompt,
            model=options.get(
                "model", preset.model if preset.model else "gemini-3-pro-image-preview"
            ),
            aspect_ratio=options.get("aspect_ratio", preset.aspect_ratio),
            image_input=image_bytes,
            enable_search=options.get("enable_search", False),
            reference_images=options.get("reference_images", []),
            preserve_faces=True,  # Сохраняем лица при редактировании
        )

        if result:
            # Сохраняем изображение на сервере для возможности скачивания
            saved_url = save_uploaded_file(result, "png")

            # Сохраняем оригинальные байты и URL в состоянии для кнопки скачивания
            try:
                await state.update_data(
                    last_generated_image_bytes=result,
                    last_generated_image_url=saved_url,
                )
            except Exception:
                logger.exception("Failed to update state with last_generated_image")

            # Создаём задачу в БД для возможности скачивания
            if saved_url:
                from bot.database import add_generation_task

                user = await get_or_create_user(callback.from_user.id)
                await add_generation_task(
                    user_id=user.id,
                    task_id=task_id,
                    type="image",
                    preset_id=preset.id,
                )
                # Обновляем URL результата
                from bot.database import complete_video_task

                await complete_video_task(task_id, saved_url)

            # Отправляем результат с опциями многоходового редактирования
            photo = types.BufferedInputFile(result, filename="generated.png")

            success_text = get_success_message(preset.name, preset.cost)
            if saved_url:
                success_text += f"\n\n📥 <i>Вы можете скачать это изображение позже</i>"

            await callback.message.answer_photo(
                photo=photo,
                caption=success_text,
                reply_markup=get_multiturn_keyboard(preset.id),
                parse_mode="HTML",
            )

            # Отправляем оригинал как документ
            await _send_original_document(
                callback.message.answer_document, result, saved_url
            )
        else:
            # Возвращаем кредиты при ошибке
            await add_credits(callback.from_user.id, preset.cost)
            error_msg = get_error_handling()["generation_failed"]
            await callback.message.answer(
                error_msg,
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML",
            )

    except Exception as e:
        logger.exception(f"Image generation error: {e}")
        await add_credits(callback.from_user.id, preset.cost)
        error_msg = get_error_handling()["generation_failed"]
        await callback.message.answer(
            f"{error_msg}\n\nОшибка: {str(e)[:100]}",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
    finally:
        await processing_msg.delete()


async def generate_video(
    callback, preset, prompt, image_bytes, bot: Bot, state: FSMContext
):
    """Генерация видео через Kling (асинхронно)"""
    from bot.config import config
    from bot.services.kling_service import kling_service

    data = await state.get_data()
    video_options = data.get("video_options", {})

    # Ensure duration is int (it might come as string from callback_data)
    duration_raw = video_options.get("duration", preset.duration or 5)
    try:
        duration = int(duration_raw)
    except (ValueError, TypeError):
        duration = 5
        logger.warning(f"Invalid duration value: {duration_raw}, using default 5")
    aspect_ratio = video_options.get("aspect_ratio", preset.aspect_ratio or "16:9")
    quality = video_options.get("quality", "std")
    generate_audio = video_options.get("generate_audio", True)

    processing_msg = await callback.message.answer(
        "🎬 <b>Видео готовится</b>\n\n"
        f"⏱ Длительность: {duration} сек\n"
        f"📐 Формат: {aspect_ratio}\n"
        f"{'💎' if quality == 'pro' else '⚡'} Качество: {quality.upper()}\n\n"
        "Это может занять 1-3 минуты\n"
        "🔔 Я пришлю результат, когда будет готово",
        parse_mode="HTML",
    )

    image_url = None
    if image_bytes:
        # Сохраняем изображение локально и получаем публичный URL
        image_url = save_uploaded_file(image_bytes, "png")
        if not image_url:
            logger.error("Failed to save image for video generation")

    model_map = {
        ("video_generation", "pro"): "v3_pro",
        ("video_generation", "std"): "v3_std",
        ("video_editing", "pro"): "v3_omni_pro_r2v",
        ("video_editing", "std"): "v3_omni_std_r2v",
    }
    model = model_map.get((preset.category, quality), "v3_std")

    try:
        logger.info(
            f"generate_video: calling kling_service with duration={duration} (type={type(duration).__name__})"
        )
        result = await kling_service.generate_video(
            prompt=prompt,
            model=model,
            duration=duration,
            aspect_ratio=aspect_ratio,
            webhook_url=config.kling_notification_url if config.WEBHOOK_HOST else None,
            image_url=image_url,
        )

        if result and result.get("task_id"):
            user = await get_or_create_user(callback.from_user.id)
            await add_generation_task(
                user_id=user.id,
                task_id=result["task_id"],
                type="video",
                preset_id=preset.id,
            )

            await callback.message.answer(
                f"✅ <b>Задача создана</b>\n\n"
                f"ID: <code>{result['task_id']}</code>\n"
                f"🍌 Списано: <code>{preset.cost}</code>🍌\n\n"
                f"Я пришлю видео автоматически.",
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML",
            )

            # Запускаем фоновый опрос статуса
            asyncio.create_task(
                poll_video_task_status(
                    task_id=result["task_id"], user_id=callback.from_user.id, bot=bot
                )
            )
        else:
            await add_credits(callback.from_user.id, preset.cost)
            await callback.message.answer(
                "❌ <b>Ошибка создания задачи</b>\n\n"
                "Бананы возвращены. Попробуйте позже.",
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML",
            )

    except Exception as e:
        logger.exception(f"Video generation error: {e}")
        await add_credits(callback.from_user.id, preset.cost)
        await callback.message.answer(
            f"❌ <b>Ошибка генерации видео</b>\n\n"
            f"Бананы возвращены.\n"
            f"Ошибка: {str(e)[:100]}",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
    finally:
        await processing_msg.delete()


# =============================================================================
# ОБРАБОТЧИК БЕЗ ПРЕСЕТА ДЛЯ РЕДАКТИРОВАНИЯ
# =============================================================================


async def run_editing_inline(
    message: types.Message, state: FSMContext, generation_type: str, user_input: str
):
    """Запускает редактирование напрямую из текстового ввода"""
    data = await state.get_data()
    uploaded_image = data.get("uploaded_image")

    if not uploaded_image:
        await message.answer("Сначала загрузите изображение")
        return

    cost = 2 if generation_type == "image_edit" else 6

    # Проверяем баланс
    if not await check_can_afford(message.from_user.id, cost):
        await message.answer(
            f"❌ Недостаточно бананов!\n" f"Нужно: {cost}🍌\n" f"Пополните баланс.",
            reply_markup=get_main_menu_keyboard(),
        )
        await state.clear()
        return

    # Списываем
    await deduct_credits(message.from_user.id, cost)

    if generation_type == "image_edit":
        # Редактируем изображение
        processing = await message.answer(
            "✏️ <b>Редактирую изображение...</b>\n\n"
            f"<i>{user_input[:100]}...</i>\n\n"
            "<i>Это займёт 10-30 секунд</i>",
            parse_mode="HTML",
        )

        try:
            from bot.services.gemini_service import gemini_service

            result = await gemini_service.generate_image(
                prompt=user_input,
                model="gemini-3-pro-image-preview",
                aspect_ratio="1:1",
                image_input=uploaded_image,
            )

            await processing.delete()

            if result:
                saved_url = save_uploaded_file(result, "png")

                # Сохраняем оригинальные байты и URL в состоянии для кнопки скачивания
                try:
                    await state.update_data(
                        last_generated_image_bytes=result,
                        last_generated_image_url=saved_url,
                    )
                except Exception:
                    logger.exception("Failed to update state with last_generated_image")

                if saved_url:
                    from bot.database import add_generation_task, complete_video_task

                    user = await get_or_create_user(message.from_user.id)
                    task_id = f"img_{uuid.uuid4().hex[:12]}"
                    await add_generation_task(
                        user.id, task_id, "image", "no_preset_edit"
                    )
                    await complete_video_task(task_id, saved_url)

                photo = types.BufferedInputFile(result, filename="edited.png")
                await message.answer_photo(
                    photo=photo,
                    caption=f"✏️ <b>Готово!</b>\n\n" f"<code>{cost}</code>🍌 списано",
                    parse_mode="HTML",
                    reply_markup=get_multiturn_keyboard("no_preset_edit"),
                )
                # Попытка отправить оригинал как документ (иногда Telegram режет большие файлы)
                await _send_original_document(
                    message.answer_document, result, saved_url
                )

                # Всегда отправляем ссылку на скачивание, чтобы пользователь точно получил исходник
                if saved_url:
                    await _send_download_link(message.answer, saved_url)
            else:
                await add_credits(message.from_user.id, cost)
                await message.answer("❌ Не удалось отредактировать. Бананы возвращены.")

        except Exception as e:
            logger.exception(f"Edit error: {e}")
            await add_credits(message.from_user.id, cost)
            await message.answer(f"❌ Ошибка: {str(e)[:100]}")
    else:
        # Редактируем видео
        await message.answer(
            "🎬 Видео-эффекты скоро будут доступны!\n"
            "Пока доступна только генерация видео.",
            reply_markup=get_main_menu_keyboard(),
        )

    await state.clear()


@router.callback_query(F.data == "run_no_preset")
async def run_no_preset_editing(callback: types.CallbackQuery, state: FSMContext):
    """Запускает редактирование без пресета"""
    data = await state.get_data()
    generation_type = data.get("generation_type")
    user_input = data.get("user_input")
    uploaded_image = data.get("uploaded_image")

    if not uploaded_image:
        await callback.answer("Сначала загрузите изображение", show_alert=True)
        return

    cost = 2 if generation_type == "image_edit" else 6

    # Проверяем баланс
    if not await check_can_afford(callback.from_user.id, cost):
        await callback.answer("Недостаточно бананов!", show_alert=True)
        return

    # Списываем
    await deduct_credits(callback.from_user.id, cost)
    await callback.answer("🚀 Запускаю...")

    if generation_type == "image_edit":
        # Редактируем изображение
        processing = await callback.message.answer(
            "✏️ <b>Редактирую изображение...</b>\n\n"
            f"<i>{user_input[:100]}...</i>\n\n"
            "<i>Это займёт 10-30 секунд</i>",
            parse_mode="HTML",
        )

        try:
            from bot.services.gemini_service import gemini_service

            result = await gemini_service.generate_image(
                prompt=user_input,
                model="gemini-3-pro-image-preview",
                aspect_ratio="1:1",
                image_input=uploaded_image,
            )

            await processing.delete()

            if result:
                saved_url = save_uploaded_file(result, "png")

                # Сохраняем оригинальные байты и URL в состоянии для кнопки скачивания
                try:
                    await state.update_data(
                        last_generated_image_bytes=result,
                        last_generated_image_url=saved_url,
                    )
                except Exception:
                    logger.exception("Failed to update state with last_generated_image")

                if saved_url:
                    from bot.database import add_generation_task, complete_video_task

                    user = await get_or_create_user(callback.from_user.id)
                    task_id = f"img_{uuid.uuid4().hex[:12]}"
                    await add_generation_task(
                        user.id, task_id, "image", "no_preset_edit"
                    )
                    await complete_video_task(task_id, saved_url)

                photo = types.BufferedInputFile(result, filename="edited.png")
                await callback.message.answer_photo(
                    photo=photo,
                    caption=f"✏️ <b>Готово!</b>\n\n" f"<code>{cost}</code>🍌 списано",
                    parse_mode="HTML",
                    reply_markup=get_multiturn_keyboard("no_preset_edit"),
                )

                await _send_original_document(
                    callback.message.answer_document, result, saved_url
                )
                if saved_url:
                    await _send_download_link(callback.message.answer, saved_url)
                if saved_url:
                    await _send_download_link(callback.message.answer, saved_url)
            else:
                await add_credits(callback.from_user.id, cost)
                await callback.message.answer(
                    "❌ Не удалось отредактировать. Бананы возвращены."
                )

        except Exception as e:
            logger.exception(f"Edit error: {e}")
            await add_credits(callback.from_user.id, cost)
            await callback.message.answer(f"❌ Ошибка: {str(e)[:100]}")
    else:
        # Редактируем видео
        await callback.message.answer(
            "🎬 Видео-эффекты скоро будут доступны!\n"
            "Пока доступна только генерация видео.",
            reply_markup=get_main_menu_keyboard(),
        )

    await state.clear()


# =============================================================================
# ОБРАБОТЧИКИ ВИДЕО-ОПЦИЙ
# =============================================================================


@router.callback_query(F.data.startswith("duration_"))
async def handle_duration_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора длительности видео"""
    # Формат: duration_preset_id_durations (preset_id может содержать underscores)
    # Пример: duration_vid_text_to_video_std_5
    callback_data = callback.data
    prefix = "duration_"

    if not callback_data.startswith(prefix):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    # Убираем префикс
    data_part = callback_data[len(prefix) :]

    # Разделяем по последнему underscore - последняя часть это длительность
    # Но нужно сохранить preset_id который может содержать underscores
    # Поэтому просто берём последний элемент как duration, а всё остальное - preset_id
    parts = data_part.rsplit("_", 1)

    if len(parts) != 2:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    preset_id = parts[0]
    duration_str = parts[1]

    # Защита от некорректных данных
    try:
        duration = int(duration_str)
    except ValueError:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    data = await state.get_data()
    video_options = data.get("video_options", {})
    video_options["duration"] = duration
    await state.update_data(video_options=video_options)

    preset = preset_manager.get_preset(preset_id)
    if preset:
        quality = video_options.get("quality", "std")
        quality_emoji = "💎" if quality == "pro" else "⚡"

        text = f"🎯 <b>{preset.name}</b>\n\n"
        text += f"🍌 Стоимость: <code>{preset.cost}</code>🍌\n"

        if hasattr(preset, "description") and preset.description:
            text += f"\n📝 {preset.description}\n"

        text += f"\n🎬 <b>Опции видео:</b>\n"
        text += f"   ⏱ Длительность: <code>{duration} сек</code>\n"
        text += (
            f"   📐 Формат: <code>{video_options.get('aspect_ratio', '16:9')}</code>\n"
        )
        text += f"   {quality_emoji} Качество: <code>{quality.upper()}</code>\n"
        text += f"   🔊 Звук: <code>{'ВКЛ' if video_options.get('generate_audio') else 'ВЫКЛ'}</code>\n"

        if preset.requires_input and preset.input_prompt:
            text += f"\n📝 <i>{preset.input_prompt}</i>\n"

        await callback.message.edit_text(
            text,
            reply_markup=get_preset_action_keyboard(
                preset_id, preset.requires_input, preset.category
            ),
            parse_mode="HTML",
        )

    await callback.answer()


@router.callback_query(F.data.startswith("ratio_"))
async def handle_aspect_ratio_selection(
    callback: types.CallbackQuery, state: FSMContext
):
    """Обработка выбора формата видео"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        ratio = parts[2]

        data = await state.get_data()
        video_options = data.get("video_options", {})
        video_options["aspect_ratio"] = ratio
        await state.update_data(video_options=video_options)

        preset = preset_manager.get_preset(preset_id)
        if preset:
            quality = video_options.get("quality", "std")
            quality_emoji = "💎" if quality == "pro" else "⚡"

            text = f"🎯 <b>{preset.name}</b>\n\n"
            text += f"🍌 Стоимость: <code>{preset.cost}</code>🍌\n"

            if hasattr(preset, "description") and preset.description:
                text += f"\n📝 {preset.description}\n"

            text += f"\n🎬 <b>Опции видео:</b>\n"
            text += f"   ⏱ Длительность: <code>{video_options.get('duration', 5)} сек</code>\n"
            text += f"   📐 Формат: <code>{ratio}</code>\n"
            text += f"   {quality_emoji} Качество: <code>{quality.upper()}</code>\n"
            text += f"   🔊 Звук: <code>{'ВКЛ' if video_options.get('generate_audio') else 'ВЫКЛ'}</code>\n"

            if preset.requires_input and preset.input_prompt:
                text += f"\n📝 <i>{preset.input_prompt}</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()


@router.callback_query(F.data.startswith("quality_"))
async def handle_quality_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора качества видео"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        quality = parts[2]

        data = await state.get_data()
        video_options = data.get("video_options", {})
        video_options["quality"] = quality
        await state.update_data(video_options=video_options)

        preset = preset_manager.get_preset(preset_id)
        if preset:
            quality_emoji = "💎" if quality == "pro" else "⚡"

            text = f"🎯 <b>{preset.name}</b>\n\n"
            text += f"🍌 Стоимость: <code>{preset.cost}</code>🍌\n"

            if hasattr(preset, "description") and preset.description:
                text += f"\n📝 {preset.description}\n"

            text += f"\n🎬 <b>Опции видео:</b>\n"
            text += f"   ⏱ Длительность: <code>{video_options.get('duration', 5)} сек</code>\n"
            text += f"   📐 Формат: <code>{video_options.get('aspect_ratio', '16:9')}</code>\n"
            text += f"   {quality_emoji} Качество: <code>{quality.upper()}</code>\n"
            text += f"   🔊 Звук: <code>{'ВКЛ' if video_options.get('generate_audio') else 'ВЫКЛ'}</code>\n"

            if preset.requires_input and preset.input_prompt:
                text += f"\n📝 <i>{preset.input_prompt}</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()


# =============================================================================
# ОБРАБОТЧИКИ БЕЗ ПРЕСЕТА - ВЫБОР ФОРМАТА
# =============================================================================


@router.callback_query(F.data == "run_no_preset_image")
async def handle_run_no_preset_image(callback: types.CallbackQuery, state: FSMContext):
    """Запускает генерацию изображения без пресета с выбранным форматом"""
    data = await state.get_data()
    user_prompt = data.get("user_prompt", "")
    # Используем выбранный формат или 1:1 по умолчанию
    aspect_ratio = data.get("selected_aspect_ratio", "1:1")

    if not user_prompt:
        await callback.answer("Промпт не найден", show_alert=True)
        return

    await callback.answer("🚀 Запускаю...")

    # Запускаем генерацию с выбранным форматом
    await run_no_preset_image_generation(
        callback.message, state, user_prompt, aspect_ratio, callback.from_user.id
    )


@router.callback_query(F.data == "skip_face_ref")
async def skip_face_reference(callback: types.CallbackQuery, state: FSMContext):
    """Пропускает добавление референсов лиц и переходит к вводу промпта"""
    data = await state.get_data()
    ref_images = data.get("reference_images", [])

    await state.set_state(GenerationStates.waiting_for_input)

    if ref_images:
        await callback.message.edit_text(
            f"✅ <b>Готово!</b>\n"
            f"📎 Референсов лица: <code>{len(ref_images)}</code>\n\n"
            f"Теперь опишите, что нужно сделать:\n"
            f"• Изменить стиль\n"
            f"• Добавить/удалить элементы\n"
            f"• Сохранить лицо как на референсе\n"
            f"• и т.д.\n\n"
            f"<i>Введите ваш запрос:</i>",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            f"✅ <b>Продолжаем без референсов</b>\n\n"
            f"Теперь опишите, что нужно сделать:\n"
            f"• Изменить стиль\n"
            f"• Добавить/удалить элементы\n"
            f"• и т.д.\n\n"
            f"<i>Введите ваш запрос:</i>",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "run_no_preset_edit_image")
async def handle_run_no_preset_edit_image(
    callback: types.CallbackQuery, state: FSMContext
):
    """Запускает редактирование изображения без пресета с выбранным форматом"""
    data = await state.get_data()
    user_prompt = data.get("user_prompt", "")
    uploaded_image = data.get("uploaded_image")
    # Используем выбранный формат или 1:1 по умолчанию
    aspect_ratio = data.get("selected_aspect_ratio", "1:1")

    if not user_prompt:
        await callback.answer("Промпт не найден", show_alert=True)
        return

    if not uploaded_image:
        await callback.answer("Изображение не найдено", show_alert=True)
        return

    await callback.answer("🚀 Запускаю...")

    # Запускаем редактирование с выбранным форматом
    await run_no_preset_image_edit(
        callback.message, state, user_prompt, aspect_ratio, callback.from_user.id
    )


@router.callback_query(F.data.startswith("img_ratio_no_preset_edit_"))
async def handle_no_preset_edit_ratio(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора формата для редактирования без пресета - обновляет клавиатуру"""
    logger.info(f"handle_no_preset_edit_ratio called: {callback.data}")

    # Формат: img_ratio_no_preset_edit_16_9
    callback_data = callback.data
    prefix = "img_ratio_no_preset_edit_"

    if not callback_data.startswith(prefix):
        logger.warning(f"Invalid callback data: {callback_data}")
        await callback.answer("Некорректные данные", show_alert=True)
        return

    # Убираем префикс
    ratio_str = callback_data[len(prefix) :]
    # Конвертируем 16_9 в 16:9
    ratio = ratio_str.replace("_", ":")

    logger.info(f"Selected ratio for edit: {ratio}")

    # Сохраняем выбранный формат в state
    data = await state.get_data()
    await state.update_data(selected_aspect_ratio=ratio)

    # Обновляем клавиатуру с отметкой выбранного формата
    try:
        await callback.message.edit_reply_markup(
            reply_markup=get_image_aspect_ratio_no_preset_edit_keyboard(ratio)
        )
        logger.info("Keyboard updated successfully")
    except Exception as e:
        logger.error(f"Failed to edit reply markup: {e}")
        # Пробуем редактировать всё сообщение
        try:
            await callback.message.edit_text(
                callback.message.text,
                reply_markup=get_image_aspect_ratio_no_preset_edit_keyboard(ratio),
                parse_mode="HTML",
            )
            logger.info("Message text updated successfully")
        except Exception as e2:
            logger.error(f"Failed to edit text: {e2}")

    await callback.answer(f"Выбран формат: {ratio}")


@router.callback_query(F.data.startswith("img_ratio_no_preset_"))
async def handle_no_preset_ratio(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора формата для генерации без пресета - обновляет клавиатуру"""
    # Формат: img_ratio_no_preset_16_9
    callback_data = callback.data

    # Пропускаем edit callback (обрабатывается другим хэндлером)
    if callback_data.startswith("img_ratio_no_preset_edit_"):
        return

    prefix = "img_ratio_no_preset_"

    if not callback_data.startswith(prefix):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    # Убираем префикс
    ratio_str = callback_data[len(prefix) :]
    # Конвертируем 16_9 в 16:9
    ratio = ratio_str.replace("_", ":")

    # Сохраняем выбранный формат в state
    data = await state.get_data()
    await state.update_data(selected_aspect_ratio=ratio)

    # Обновляем клавиатуру с отметкой выбранного формата
    try:
        await callback.message.edit_reply_markup(
            reply_markup=get_image_aspect_ratio_no_preset_keyboard(ratio)
        )
    except Exception as e:
        logger.warning(f"Failed to edit reply markup: {e}")
        # Пробуем редактировать всё сообщение
        await callback.message.edit_text(
            callback.message.text,
            reply_markup=get_image_aspect_ratio_no_preset_keyboard(ratio),
            parse_mode="HTML",
        )

    await callback.answer(f"Выбран формат: {ratio}")


async def run_no_preset_image_generation(
    message: types.Message,
    state: FSMContext,
    prompt: str,
    aspect_ratio: str,
    user_id: int = None,
):
    """Запускает генерацию изображения без пресета с указанным форматом"""
    # Получаем предпочитаемую модель и сервис из настроек
    data = await state.get_data()
    image_service = data.get("image_service", "nanobanana")

    # Определяем пользователя (для callback message.from_user это бот)
    if user_id is None:
        user_id = message.from_user.id

    # Определяем сервис и стоимость
    if image_service == "novita":
        # FLUX.2 Pro через Novita
        from bot.services.novita_service import novita_service

        service = novita_service
        model_name = "✨ FLUX.2 Pro"
        cost = 2
    elif image_service == "seedream":
        # Seedream через Novita
        from bot.services.novita_service import novita_service

        service = novita_service
        model_name = "🎨 Seedream"
        cost = 2
    else:
        # Nano Banana (Gemini)
        from bot.services.gemini_service import gemini_service

        service = gemini_service
        model_name = "🍌 Nano Banana"
        cost = 2

    # Проверяем баланс
    if not await check_can_afford(user_id, cost):
        await message.answer(
            f"❌ Недостаточно бананов!\n" f"Нужно: {cost}🍌\n" f"Пополните баланс.",
            reply_markup=get_main_menu_keyboard(),
        )
        await state.clear()
        return

    # Списываем
    await deduct_credits(user_id, cost)

    # Генерируем изображение с выбранным сервисом
    processing = await message.answer(
        f"🎨 <b>Генерирую изображение...</b>\n\n"
        f"🤖 Модель: <code>{model_name}</code>\n"
        f"📐 Формат: <code>{aspect_ratio}</code>\n"
        f"<i>Это займёт 10-30 секунд</i>",
        parse_mode="HTML",
    )

    try:
        # Different services have different parameter names
        # gemini: aspect_ratio, novita: size (async API with task_id)
        if image_service == "novita":
            # FLUX.2 Pro через Novita - async API, returns task_id
            size = f"{aspect_ratio}_hq"
            task_response = await service.generate_image(
                prompt=prompt,
                size=size,
                webhook_url=config.novita_notification_url
                if config.WEBHOOK_HOST
                else None,
            )

            if task_response and task_response.get("task_id"):
                task_id = task_response["task_id"]

                # Сохраняем задачу в БД
                from bot.database import add_generation_task

                user = await get_or_create_user(message.from_user.id)
                await add_generation_task(user.id, task_id, "image", "no_preset")

                await processing.delete()
                await message.answer(
                    f"✅ <b>Задача создана!</b>\n\n"
                    f"🤖 Модель: <code>{model_name}</code>\n"
                    f"📐 Формат: <code>{aspect_ratio}</code>\n"
                    f"<code>{cost}</code>🍌 списано\n\n"
                    f"<i>Изображение будет готово через 10-30 секунд. Я пришлю результат автоматически.</i>",
                    parse_mode="HTML",
                    reply_markup=get_main_menu_keyboard(),
                )

                # Запускаем фоновый опрос статуса
                asyncio.create_task(
                    poll_novita_task_status(
                        task_id=task_id,
                        user_id=user_id,
                        bot=message.bot,
                        cost=cost,
                        model_name=model_name,
                    )
                )
            else:
                await processing.delete()
                await add_credits(user_id, cost)
                await message.answer(
                    "❌ Не удалось создать задачу. Бананы возвращены.",
                    reply_markup=get_main_menu_keyboard(),
                )
            await state.clear()
            return
        elif image_service == "seedream":
            # Seedream через Novita - может возвращать как task_id, так и сразу изображение
            size = "2048x2048"  # Default 2K for Seedream
            task_response = await service.generate_seedream_image(
                prompt=prompt,
                size=size,
                watermark=False,
                webhook_url=config.seedream_notification_url
                if config.WEBHOOK_HOST
                else None,
            )

            if task_response:
                # Seedream может вернуть изображение сразу в ответе
                if "images" in task_response and task_response["images"]:
                    # Изображение уже готово
                    image_url = task_response["images"][0]
                    
                    # Сохраняем задачу в БД
                    from bot.database import add_generation_task, complete_video_task

                    user = await get_or_create_user(user_id)
                    task_id = f"seedream_{uuid.uuid4().hex[:12]}"
                    await add_generation_task(user.id, task_id, "image", "no_preset")
                    await complete_video_task(task_id, image_url)

                    await processing.delete()
                    
                    # Отправляем изображение пользователю
                    try:
                        await message.answer_photo(
                            photo=image_url,
                            caption=f"✅ <b>Готово!</b>\n\n"
                                    f"🤖 Модель: <code>{model_name}</code>\n"
                                    f"📐 Размер: <code>2048x2048</code>\n"
                                    f"<code>{cost}</code>🍌 списано",
                            parse_mode="HTML",
                            reply_markup=get_multiturn_keyboard("no_preset"),
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send photo: {e}")
                        await message.answer(
                            f"✅ <b>Готово!</b>\n\n"
                            f"🤖 Модель: <code>{model_name}</code>\n"
                            f"📐 Размер: <code>2048x2048</code>\n"
                            f"<code>{cost}</code>🍌 списано\n\n"
                            f"<a href='{image_url}'>Скачать изображение</a>",
                            parse_mode="HTML",
                            reply_markup=get_multiturn_keyboard("no_preset"),
                        )
                    await state.clear()
                    return
                elif task_response.get("task_id"):
                    # Асинхронная задача
                    task_id = task_response["task_id"]

                    # Сохраняем задачу в БД
                    from bot.database import add_generation_task

                    user = await get_or_create_user(user_id)
                    await add_generation_task(user.id, task_id, "image", "no_preset")

                    await processing.delete()
                    await message.answer(
                        f"✅ <b>Задача создана!</b>\n\n"
                        f"🤖 Модель: <code>{model_name}</code>\n"
                        f"📐 Размер: <code>2048x2048</code>\n"
                        f"<code>{cost}</code>🍌 списано\n\n"
                        f"<i>Изображение будет готово через 10-30 секунд. Я пришлю результат автоматически.</i>",
                        parse_mode="HTML",
                        reply_markup=get_main_menu_keyboard(),
                    )

                    # Запускаем фоновый опрос статуса
                    asyncio.create_task(
                        poll_novita_task_status(
                            task_id=task_id,
                            user_id=user_id,
                            bot=message.bot,
                            cost=cost,
                            model_name=model_name,
                        )
                    )
                    await state.clear()
                    return

            # Ошибка
            await processing.delete()
            await add_credits(message.from_user.id, cost)
            await message.answer(
                "❌ Не удалось создать задачу. Бананы возвращены.",
                reply_markup=get_main_menu_keyboard(),
            )
            await state.clear()
            return
        else:
            # Gemini uses aspect_ratio and returns bytes directly
            result = await service.generate_image(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                image_input=None,
            )

        await processing.delete()

        if result:
            saved_url = save_uploaded_file(result, "png")

            # Сохраняем оригинальные байты и URL в состоянии
            try:
                await state.update_data(
                    last_generated_image_bytes=result,
                    last_generated_image_url=saved_url,
                )
            except Exception:
                logger.exception("Failed to update state with last_generated_image")

            if saved_url:
                from bot.database import add_generation_task, complete_video_task

                user = await get_or_create_user(message.from_user.id)
                task_id = f"img_{uuid.uuid4().hex[:12]}"
                await add_generation_task(user.id, task_id, "image", "no_preset")
                await complete_video_task(task_id, saved_url)

            photo = types.BufferedInputFile(result, filename="generated.png")
            await message.answer_photo(
                photo=photo,
                caption=f"✅ <b>Готово!</b>\n\n"
                f"📐 Формат: <code>{aspect_ratio}</code>\n"
                f"<code>{cost}</code>🍌 списано",
                parse_mode="HTML",
                reply_markup=get_multiturn_keyboard("no_preset"),
            )
            await _send_original_document(message.answer_document, result, saved_url)
            if saved_url:
                await _send_download_link(message.answer, saved_url)
        else:
            await add_credits(message.from_user.id, cost)
            await message.answer("❌ Не удалось сгенерировать. Бананы возвращены.")

    except Exception as e:
        logger.exception(f"Error: {e}")
        await add_credits(message.from_user.id, cost)
        await message.answer(f"❌ Ошибка: {str(e)[:100]}")

    await state.clear()


async def run_no_preset_image_edit(
    message: types.Message,
    state: FSMContext,
    prompt: str,
    aspect_ratio: str,
    user_id: int = None,
):
    """Запускает редактирование изображения без пресета с указанным форматом"""
    data = await state.get_data()
    uploaded_image = data.get("uploaded_image")

    if not uploaded_image:
        await message.answer("Сначала загрузите изображение")
        return

    # Определяем пользователя (для callback message.from_user это бот)
    if user_id is None:
        user_id = message.from_user.id

    # Получаем предпочитаемую модель из настроек
    preferred_model = data.get("preferred_model", "pro")

    # Определяем модель и стоимость
    if preferred_model == "flash":
        model = "gemini-2.5-flash-image"
        cost = 2
    else:
        model = "gemini-3-pro-image-preview"
        cost = 3

    # Проверяем баланс
    if not await check_can_afford(user_id, cost):
        await message.answer(
            f"❌ Недостаточно бананов!\n" f"Нужно: {cost}🍌\n" f"Пополните баланс.",
            reply_markup=get_main_menu_keyboard(),
        )
        await state.clear()
        return

    # Списываем
    await deduct_credits(user_id, cost)

    # Редактируем изображение
    model_emoji = "⚡" if preferred_model == "flash" else "💎"
    processing = await message.answer(
        f"✏️ <b>Редактирую изображение...</b>\n\n"
        f"{model_emoji} Модель: <code>{'Nano Banano' if preferred_model == 'flash' else 'Banano Pro'}</code>\n"
        f"📐 Формат: <code>{aspect_ratio}</code>\n"
        f"<i>{prompt[:50]}...</i>\n\n"
        "<i>Это займёт 10-30 секунд</i>",
        parse_mode="HTML",
    )

    try:
        from bot.services.gemini_service import gemini_service

        # Получаем референсы для сохранения лиц
        ref_images = data.get("reference_images", [])

        result = await gemini_service.generate_image(
            prompt=prompt,
            model=model,
            aspect_ratio=aspect_ratio,
            image_input=uploaded_image,
            reference_images=ref_images if ref_images else None,
            preserve_faces=True if ref_images else False,
        )

        await processing.delete()

        if result:
            saved_url = save_uploaded_file(result, "png")

            # Сохраняем оригинальные байты и URL в состоянии для кнопки скачивания
            try:
                await state.update_data(
                    last_generated_image_bytes=result,
                    last_generated_image_url=saved_url,
                )
            except Exception:
                logger.exception("Failed to update state with last_generated_image")

            if saved_url:
                from bot.database import add_generation_task, complete_video_task

                user = await get_or_create_user(message.from_user.id)
                task_id = f"img_{uuid.uuid4().hex[:12]}"
                await add_generation_task(user.id, task_id, "image", "no_preset_edit")
                await complete_video_task(task_id, saved_url)

            photo = types.BufferedInputFile(result, filename="edited.png")
            await message.answer_photo(
                photo=photo,
                caption=f"✏️ <b>Готово!</b>\n\n"
                f"📐 Формат: <code>{aspect_ratio}</code>\n"
                f"<code>{cost}</code>🍌 списано",
                parse_mode="HTML",
                reply_markup=get_multiturn_keyboard("no_preset_edit"),
            )
        else:
            await add_credits(message.from_user.id, cost)
            await message.answer("❌ Не удалось отредактировать. Бананы возвращены.")

    except Exception as e:
        logger.exception(f"Edit error: {e}")
        await add_credits(message.from_user.id, cost)
        await message.answer(f"❌ Ошибка: {str(e)[:100]}")

    await state.clear()


# =============================================================================
# ОБРАБОТЧИКИ ВИДЕО-ЭФФЕКТОВ - ЗАПУСК
# =============================================================================


@router.callback_query(F.data == "run_video_edit")
async def run_video_edit_handler(callback: types.CallbackQuery, state: FSMContext):
    """Запускает видео-эффекты (видео-в-видео)"""
    data = await state.get_data()
    user_prompt = data.get("user_prompt", "")
    uploaded_video = data.get("uploaded_video")
    video_edit_options = data.get("video_edit_options", {})

    if not uploaded_video:
        await callback.answer("Сначала загрузите видео", show_alert=True)
        return

    if not user_prompt:
        await callback.answer("Опишите эффект", show_alert=True)
        return

    # Определяем стоимость с учётом длительности
    duration = video_edit_options.get("duration", 5)
    if duration == 10:
        cost = 8
    elif duration == 15:
        cost = 10
    else:
        cost = 6

    # Проверяем баланс
    if not await check_can_afford(callback.from_user.id, cost):
        await callback.answer("Недостаточно бананов!", show_alert=True)
        return

    # Списываем
    await deduct_credits(callback.from_user.id, cost)
    await callback.answer("🚀 Запускаю...")

    # Запускаем видео-эффекты
    await execute_video_edit(
        callback.message, state, user_prompt, uploaded_video, video_edit_options, cost
    )


@router.callback_query(F.data == "run_video_edit_image")
async def run_video_edit_image_handler(
    callback: types.CallbackQuery, state: FSMContext
):
    """Запускает видео-эффекты из изображения (фото-в-видео)"""
    data = await state.get_data()
    user_prompt = data.get("user_prompt", "")
    uploaded_image = data.get("uploaded_image")
    uploaded_image_url = data.get("uploaded_image_url")
    video_edit_options = data.get("video_edit_options", {})

    if not uploaded_image:
        await callback.answer("Сначала загрузите фото", show_alert=True)
        return

    if not user_prompt:
        await callback.answer("Опишите эффект и движение", show_alert=True)
        return

    # Определяем стоимость с учётом длительности
    duration = video_edit_options.get("duration", 5)
    if duration == 10:
        cost = 8
    elif duration == 15:
        cost = 10
    else:
        cost = 6

    # Проверяем баланс
    if not await check_can_afford(callback.from_user.id, cost):
        await callback.answer("Недостаточно бананов!", show_alert=True)
        return

    # Списываем
    await deduct_credits(callback.from_user.id, cost)
    await callback.answer("🚀 Запускаю...")

    # Запускаем генерацию видео из изображения
    await execute_video_edit_image(
        callback.message,
        state,
        user_prompt,
        uploaded_image,
        uploaded_image_url,
        video_edit_options,
        cost,
    )


async def execute_video_edit(
    message: types.Message,
    state: FSMContext,
    prompt: str,
    video_bytes: bytes,
    options: dict,
    cost: int,
):
    """Выполняет видео-эффекты через Kling API"""
    quality = options.get("quality", "std")
    duration = options.get("duration", 5)
    aspect_ratio = options.get("aspect_ratio", "16:9")

    # Выбираем модель согласно kling_api.md
    model = "v3_omni_pro_r2v" if quality == "pro" else "v3_omni_std_r2v"

    # Загружаем видео на временный хостинг для Kling
    video_url = await upload_video_for_kling(video_bytes)

    if not video_url:
        await add_credits(message.from_user.id, cost)
        await message.answer(
            "❌ Не удалось загрузить видео.\n" "Бананы возвращены. Попробуйте ещё раз.",
            reply_markup=get_main_menu_keyboard(),
        )
        await state.clear()
        return

    quality_emoji = "💎" if quality == "pro" else "⚡"
    processing = await message.answer(
        f"✂️ <b>Видео-эффекты</b>\n\n"
        f"{quality_emoji} Качество: <code>{quality.upper()}</code>\n"
        f"⏱ Длительность: <code>{duration} сек</code>\n"
        f"📐 Формат: <code>{aspect_ratio}</code>\n\n"
        "<i>Это займёт 1-3 минуты</i>",
        parse_mode="HTML",
    )

    logger.info(
        f"execute_video_edit: generating video with model={model}, video_url={video_url[:80] if video_url else 'None'}..., prompt={prompt[:50]}..."
    )

    try:
        from bot.config import config
        from bot.services.kling_service import kling_service

        result = await kling_service.generate_video(
            prompt=prompt,
            model=model,
            duration=duration,
            aspect_ratio=aspect_ratio,
            webhook_url=config.kling_notification_url if config.WEBHOOK_HOST else None,
            video_url=video_url,  # Для R2V используем video_url, не image_url
        )

        if result:
            logger.info(
                f"execute_video_edit: task created successfully, task_id={result.get('task_id')}"
            )
        else:
            logger.error(f"execute_video_edit: failed to create task, result is None")

        await processing.delete()

        if result and result.get("task_id"):
            from bot.database import add_generation_task

            user = await get_or_create_user(message.from_user.id)
            await add_generation_task(user.id, result["task_id"], "video", "video_edit")

            await message.answer(
                f"✅ <b>Задача создана!</b>\n\n"
                f"ID: <code>{result['task_id']}</code>\n"
                f"<code>{cost}</code>🍌 списано\n\n"
                "🎬 Видео будет готово через 1-3 минуты.\n"
                "🔔 Я пришлю результат автоматически.",
                parse_mode="HTML",
            )
        else:
            await add_credits(message.from_user.id, cost)
            await message.answer("❌ Ошибка. Бананы возвращены.")

    except Exception as e:
        logger.exception(f"Video edit error: {e}")
        await add_credits(message.from_user.id, cost)
        await message.answer(f"❌ Ошибка: {str(e)[:100]}")

    await state.clear()


async def execute_video_edit_image(
    message: types.Message,
    state: FSMContext,
    prompt: str,
    image_bytes: bytes,
    image_url: Optional[str],
    options: dict,
    cost: int,
):
    """Выполняет создание видео из изображения через Kling API"""
    quality = options.get("quality", "std")
    duration = options.get("duration", 5)
    aspect_ratio = options.get("aspect_ratio", "16:9")

    # Выбираем модель для image-to-video
    model = "v3_omni_pro" if quality == "pro" else "v3_omni_std"

    # Если URL нет, сохраняем изображение локально
    if not image_url and image_bytes:
        image_url = save_uploaded_file(image_bytes, "png")

    if not image_url:
        await add_credits(message.from_user.id, cost)
        await message.answer(
            "❌ Не удалось сохранить изображение.\n"
            "Бананы возвращены. Попробуйте ещё раз.",
            reply_markup=get_main_menu_keyboard(),
        )
        await state.clear()
        return

    quality_emoji = "💎" if quality == "pro" else "⚡"
    processing = await message.answer(
        f"✂️ <b>Создаю видео из фото...</b>\n\n"
        f"{quality_emoji} Качество: <code>{quality.upper()}</code>\n"
        f"⏱ Длительность: <code>{duration} сек</code>\n"
        f"📐 Формат: <code>{aspect_ratio}</code>\n\n"
        f"<i>Описание:</i> {prompt[:50]}...\n\n"
        "<i>Это займёт 1-3 минуты</i>",
        parse_mode="HTML",
    )

    logger.info(
        f"execute_video_edit_image: generating video with model={model}, image_url={image_url[:80] if image_url else 'None'}..., prompt={prompt[:50]}..."
    )

    # Создаём элементы для сохранения лица/идентичности
    elements = [{"reference_image_urls": [image_url], "frontal_image_url": image_url}]

    try:
        from bot.config import config
        from bot.services.kling_service import kling_service

        # Для I2V передаём image_url и elements для сохранения лица
        result = await kling_service.generate_video(
            prompt=prompt,
            model=model,
            duration=duration,
            aspect_ratio=aspect_ratio,
            webhook_url=config.kling_notification_url if config.WEBHOOK_HOST else None,
            image_url=image_url,
            elements=elements,
        )

        if result:
            logger.info(
                f"execute_video_edit_image: task created successfully, task_id={result.get('task_id')}"
            )
        else:
            logger.error(
                f"execute_video_edit_image: failed to create task, result is None"
            )

        await processing.delete()

        if result and result.get("task_id"):
            from bot.database import add_generation_task

            user = await get_or_create_user(message.from_user.id)
            await add_generation_task(
                user.id, result["task_id"], "video", "video_edit_image"
            )

            await message.answer(
                f"✅ <b>Задача создана!</b>\n\n"
                f"ID: <code>{result['task_id']}</code>\n"
                f"<code>{cost}</code>🍌 списано\n\n"
                "🎬 Видео будет готово через 1-3 минуты.\n"
                "🔔 Я пришлю результат автоматически.",
                parse_mode="HTML",
            )
        else:
            await add_credits(message.from_user.id, cost)
            await message.answer("❌ Ошибка. Бананы возвращены.")

    except Exception as e:
        logger.exception(f"Video edit image error: {e}")
        await add_credits(message.from_user.id, cost)
        await message.answer(f"❌ Ошибка: {str(e)[:100]}")

    await state.clear()


async def upload_video_for_kling(video_bytes: bytes) -> Optional[str]:
    """Загружает видео для Kling API на временный хостинг"""
    try:
        # Пробуем загрузить на imgbb (работает и для видео)
        import aiohttp

        # Сначала пробуем сохранить локально как временный файл
        date_str = datetime.now().strftime("%Y%m%d")
        upload_dir = os.path.join("static", "uploads", "temp")
        os.makedirs(upload_dir, exist_ok=True)

        file_id = str(uuid.uuid4())[:12]
        filepath = os.path.join(upload_dir, f"{file_id}.mp4")

        with open(filepath, "wb") as f:
            f.write(video_bytes)

        # Пробуем загрузить на временный хостинг
        # Попробуем использовать imgbb API
        from bot.config import config

        if hasattr(config, "IMGBB_API_KEY") and config.IMGBB_API_KEY:
            # Загружаем на imgbb
            form = aiohttp.FormData()
            form.add_field("key", config.IMGBB_API_KEY)
            form.add_field(
                "image",
                video_bytes,
                filename=f"{file_id}.mp4",
                content_type="video/mp4",
            )

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.imgbb.com/1/upload", data=form
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("success") and data.get("data", {}).get("url"):
                            return data["data"]["url"]

        # Fallback - возвращаем локальный URL (Kling должен поддерживать)
        base_url = config.static_base_url
        return f"{base_url}/uploads/temp/{file_id}.mp4"

    except Exception as e:
        logger.exception(f"Error uploading video: {e}")
        # Пробуем вернуть локальный путь
        return None


@router.message(GenerationStates.waiting_for_video, F.video)
@router.message(GenerationStates.waiting_for_image, F.video)
async def process_uploaded_video(message: types.Message, state: FSMContext):
    """Обрабатывает загруженное видео для видео-эффектов"""
    data = await state.get_data()
    generation_type = data.get("generation_type")
    input_type = data.get("video_edit_input_type")

    # Проверяем, что это видео-эффекты (video_edit) или прямой выбор видео
    if (
        generation_type not in ["video_edit", "video_edit_image"]
        and input_type != "video"
    ):
        # Если это не видео-эффект, игнорируем
        await message.answer("Пожалуйста, загрузите изображение (фото)")
        return

    # Скачиваем видео
    video = message.video
    file = await message.bot.get_file(video.file_id)

    # Проверяем размер файла (максимум 50MB для Telegram)
    if video.file_size > 50 * 1024 * 1024:
        await message.answer("❌ Видео слишком большое. Максимум 50MB.")
        return

    # Скачиваем байты
    video_bytes = await message.bot.download_file(file.file_path)
    video_data = video_bytes.read()

    # Сохраняем в папку
    video_url = save_uploaded_file(video_data, "mp4")

    if video_url:
        await state.update_data(uploaded_video=video_data, uploaded_video_url=video_url)
    else:
        await state.update_data(uploaded_video=video_data)

    # Показываем подтверждение с опциями
    video_edit_options = data.get("video_edit_options", {})
    quality = video_edit_options.get("quality", "std")
    quality_emoji = "💎" if quality == "pro" else "⚡"

    text = f"✅ <b>Видео получено!</b>\n\n"
    text += f"📹 Размер: <code>{video.file_size // (1024*1024)} MB</code>\n\n"
    text += f"<b>Опции:</b>\n"
    text += f"   {quality_emoji} Качество: <code>{quality.upper()}</code>\n"
    text += (
        f"   ⏱ Длительность: <code>{video_edit_options.get('duration', 5)} сек</code>\n"
    )
    text += f"   📐 Формат: <code>{video_edit_options.get('aspect_ratio', '16:9')}</code>\n\n"
    text += f"<i>Теперь опишите эффект, который нужно применить</i>"

    # Устанавливаем состояние ожидания ввода
    await state.set_state(GenerationStates.waiting_for_input)

    video_edit_options = data.get("video_edit_options", {})
    quality = video_edit_options.get("quality", "std")
    duration = video_edit_options.get("duration", 5)
    aspect_ratio = video_edit_options.get("aspect_ratio", "16:9")

    await message.answer(
        text,
        reply_markup=get_video_edit_keyboard(
            input_type="video",
            quality=quality,
            duration=duration,
            aspect_ratio=aspect_ratio,
        ),
        parse_mode="HTML",
    )


# =============================================================================
# ОБРАБОТЧИКИ КНОПОК ОПЦИЙ
# =============================================================================


@router.callback_query(F.data.startswith("opt_duration_"))
async def show_duration_options(callback: types.CallbackQuery, state: FSMContext):
    """Показывает клавиатуру выбора длительности"""
    preset_id = callback.data.replace("opt_duration_", "")
    data = await state.get_data()
    current_duration = data.get("video_options", {}).get("duration", 5)

    await callback.message.edit_text(
        "⏱ <b>Выберите длительность видео:</b>",
        reply_markup=get_duration_keyboard(preset_id, current_duration),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("opt_ratio_"))
async def show_aspect_ratio_options(callback: types.CallbackQuery, state: FSMContext):
    """Показывает клавиатуру выбора формата"""
    preset_id = callback.data.replace("opt_ratio_", "")
    data = await state.get_data()
    current_ratio = data.get("video_options", {}).get("aspect_ratio", "16:9")

    await callback.message.edit_text(
        "📐 <b>Выберите формат видео:</b>",
        reply_markup=get_aspect_ratio_keyboard(preset_id, current_ratio),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("opt_audio_"))
async def toggle_audio(callback: types.CallbackQuery, state: FSMContext):
    """Переключает генерацию звука"""
    preset_id = callback.data.replace("opt_audio_", "")

    data = await state.get_data()
    video_options = data.get("video_options", {})
    video_options["generate_audio"] = not video_options.get("generate_audio", True)
    await state.update_data(video_options=video_options)

    preset = preset_manager.get_preset(preset_id)
    if preset:
        quality = video_options.get("quality", "std")
        quality_emoji = "💎" if quality == "pro" else "⚡"

        text = f"🎯 <b>{preset.name}</b>\n\n"
        text += f"🍌 Стоимость: <code>{preset.cost}</code>🍌\n"

        if hasattr(preset, "description") and preset.description:
            text += f"\n📝 {preset.description}\n"

        text += f"\n🎬 <b>Опции видео:</b>\n"
        text += (
            f"   ⏱ Длительность: <code>{video_options.get('duration', 5)} сек</code>\n"
        )
        text += (
            f"   📐 Формат: <code>{video_options.get('aspect_ratio', '16:9')}</code>\n"
        )
        text += f"   {quality_emoji} Качество: <code>{quality.upper()}</code>\n"
        text += f"   🔊 Звук: <code>{'ВКЛ' if video_options.get('generate_audio') else 'ВЫКЛ'}</code>\n"

        if preset.requires_input and preset.input_prompt:
            text += f"\n📝 <i>{preset.input_prompt}</i>\n"

        await callback.message.edit_text(
            text,
            reply_markup=get_preset_action_keyboard(
                preset_id, preset.requires_input, preset.category
            ),
            parse_mode="HTML",
        )

    await callback.answer()


# =============================================================================
# ОБРАБОТЧИКИ МНОГОХОДОВОГО РЕДАКТИРОВАНИЯ И СКАЧИВАНИЯ
# =============================================================================


@router.callback_query(F.data.startswith("multiturn_"))
async def handle_multiturn(callback: types.CallbackQuery, state: FSMContext):
    """Обработка кнопки продолжения редактирования"""
    preset_id = callback.data.replace("multiturn_", "")

    # Переходим в режим ввода для редактирования
    await state.set_state(GenerationStates.waiting_for_input)
    await state.update_data(preset_id=preset_id, input_type="multiturn_edit")

    # Проверяем, есть ли пресет
    preset = preset_manager.get_preset(preset_id)

    if preset:
        await callback.message.answer(
            f"🔄 <b>Продолжить редактирование</b>\n\n"
            f"Пресет: <b>{preset.name}</b>\n\n"
            f"Опишите, что нужно изменить в изображении:\n"
            f"• Добавить элемент\n"
            f"• Изменить стиль\n"
            f"• Улучшить детали\n"
            f"• и т.д.",
            parse_mode="HTML",
            reply_markup=get_back_keyboard(f"preset_{preset_id}"),
        )
    else:
        # Без пресета - режим редактирования
        await state.update_data(generation_type="image_edit")
        await callback.message.answer(
            "🔄 <b>Продолжить редактирование</b>\n\n"
            "Опишите, что нужно изменить в изображении:\n"
            "• Добавить элемент\n"
            "• Изменить стиль\n"
            "• Улучшить детали\n"
            "• и т.д.",
            parse_mode="HTML",
            reply_markup=get_back_keyboard("back_main"),
        )

    await callback.answer()


# =============================================================================
# ФУНКЦИЯ ГЕНЕРАЦИИ ВИДЕО ИЗ ФОТО (IMAGE TO VIDEO)
# =============================================================================


async def run_image_to_video(message: types.Message, state: FSMContext, prompt: str):
    """Запускает генерацию видео из фото"""
    data = await state.get_data()
    uploaded_image = data.get("uploaded_image")
    uploaded_image_url = data.get("uploaded_image_url")
    video_options = data.get("video_options", {})

    if not uploaded_image:
        await message.answer("❌ Ошибка: изображение не найдено. Начните заново.")
        await state.clear()
        return

    # Получаем предпочитаемую модель из настроек
    # Для Image-to-Video ОБЯЗАТЕЛЬНО нужны Omni модели!
    preferred_i2v_model = data.get("preferred_i2v_model", "v3_omni_std")

    # Проверяем что модель поддерживает I2V (только Omni)
    # v3_std/pro НЕ поддерживают Image-to-Video
    i2v_compatible_models = ["v3_omni_std", "v3_omni_pro"]
    r2v_models = ["v3_omni_pro_r2v", "v3_omni_std_r2v"]

    if preferred_i2v_model in ["v3_std", "v3_pro"]:
        # Обычные модели не поддерживают I2V, принудительно переключаем на Omni
        logger.warning(
            f"I2V called with non-I2V model {preferred_i2v_model}, switching to v3_omni_std"
        )
        preferred_i2v_model = "v3_omni_std"
    elif preferred_i2v_model in r2v_models:
        logger.warning(
            f"I2V called with R2V model {preferred_i2v_model}, falling back to v3_omni_std"
        )
        preferred_i2v_model = "v3_omni_std"

    # Определяем стоимость на основе модели
    model_costs = {
        "v3_std": 4,
        "v3_pro": 5,
        "v3_omni_std": 4,
        "v3_omni_pro": 5,
    }
    cost = model_costs.get(preferred_i2v_model, 4)

    # Проверяем баланс
    if not await check_can_afford(message.from_user.id, cost):
        await message.answer(
            f"❌ Недостаточно бананов!\n" f"Нужно: {cost}🍌\n" f"Пополните баланс.",
            reply_markup=get_main_menu_keyboard(),
        )
        await state.clear()
        return

    # Списываем
    await deduct_credits(message.from_user.id, cost)

    # Параметры видео
    duration = video_options.get("duration", 5)
    aspect_ratio = video_options.get("aspect_ratio", "16:9")

    # Определяем emoji качества
    quality_emoji = "💎" if "pro" in preferred_i2v_model else "⚡"

    processing = await message.answer(
        f"🎬 <b>Создаю видео из фото...</b>\n\n"
        f"{quality_emoji} Модель: <code>{preferred_i2v_model}</code>\n"
        f"⏱ Длительность: <code>{duration} сек</code>\n"
        f"📐 Формат: <code>{aspect_ratio}</code>\n\n"
        f"<i>Описание движения:</i> {prompt[:50]}...\n\n"
        "<i>Это займёт 1-3 минуты</i>",
        parse_mode="HTML",
    )

    try:
        from bot.config import config
        from bot.services.kling_service import kling_service

        # Используем сохранённый URL или сохраняем локально
        image_url = uploaded_image_url
        if not image_url and uploaded_image:
            image_url = save_uploaded_file(uploaded_image, "png")

        if not image_url:
            await add_credits(message.from_user.id, cost)
            await message.answer(
                "❌ Не удалось сохранить изображение.\n"
                "Бананы возвращены. Попробуйте ещё раз.",
                reply_markup=get_main_menu_keyboard(),
            )
            await state.clear()
            return

        logger.info(
            f"run_image_to_video: generating video with model={preferred_i2v_model}, image_url={image_url[:80]}..., prompt={prompt[:50]}..."
        )

        # Для Image-to-Video через Omni API:
        # - start_image_url: первый кадр видео
        # - image_urls: референсные изображения для сохранения стиля/лица
        # - elements: элементы для согласованности идентичности

        # Создаём элементы для сохранения лица/идентичности
        elements = [
            {"reference_image_urls": [image_url], "frontal_image_url": image_url}
        ]

        # Создаём задачу на генерацию видео с Omni моделью
        # Для I2V используем image_url (станет start_image_url) и elements для сохранения лица
        result = await kling_service.generate_video(
            prompt=prompt,
            model=preferred_i2v_model,
            duration=duration,
            aspect_ratio=aspect_ratio,
            webhook_url=config.kling_notification_url if config.WEBHOOK_HOST else None,
            image_url=image_url,
            elements=elements,
        )

        if result:
            logger.info(
                f"run_image_to_video: task created successfully, task_id={result.get('task_id')}"
            )
        else:
            logger.error(f"run_image_to_video: failed to create task, result is None")

        await processing.delete()

        if result and result.get("task_id"):
            from bot.database import add_generation_task

            user = await get_or_create_user(message.from_user.id)
            await add_generation_task(
                user.id, result["task_id"], "video", "image_to_video"
            )

            await message.answer(
                f"✅ <b>Задача создана!</b>\n\n"
                f"ID: <code>{result['task_id']}</code>\n"
                f"<code>{cost}</code>🍌 списано\n\n"
                "🎬 Видео будет готово через 1-3 минуты.\n"
                "🔔 Я пришлю результат автоматически.",
                parse_mode="HTML",
            )
        else:
            await add_credits(message.from_user.id, cost)
            await message.answer(
                "❌ Ошибка создания задачи.\n" "Бананы возвращены. Попробуйте позже.",
                reply_markup=get_main_menu_keyboard(),
            )

    except Exception as e:
        logger.exception(f"Image to video error: {e}")
        await add_credits(message.from_user.id, cost)
        await message.answer(
            f"❌ Ошибка генерации видео\n\n"
            f"Бананы возвращены.\n"
            f"Ошибка: {str(e)[:100]}",
            reply_markup=get_main_menu_keyboard(),
        )

    await state.clear()


# =============================================================================
# ФОНОВЫЙ ОПРОС СТАТУСА ЗАДАЧ NOVITA (FLUX/Seedream)
# =============================================================================


async def poll_novita_task_status(
    task_id: str,
    user_id: int,
    bot: Bot,
    cost: int,
    model_name: str,
    max_attempts: int = 60,
    delay: int = 5,
):
    """Фоновый опрос статуса задачи изображения от Novita"""
    from bot.database import add_credits, complete_video_task
    from bot.services.novita_service import novita_service

    logger.info(f"Starting Novita poll for task {task_id}, user {user_id}")

    result = await novita_service.wait_for_completion(
        task_id, max_attempts=max_attempts, delay=delay
    )

    if not result:
        logger.error(f"Task {task_id}: timeout or error during polling")
        await add_credits(user_id, cost)
        await bot.send_message(
            chat_id=user_id,
            text="❌ <b>Ошибка генерации изображения</b>\n\nТаймаут ожидания результата.\n🍌 Бананы возвращены на счёт.",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    # Проверяем статус
    task_info = result.get("task", {})
    status = task_info.get("status")

    if status == "TASK_STATUS_SUCCEED":
        # Получаем изображения
        images = result.get("images", [])
        if images and len(images) > 0:
            image_url = images[0].get("image_url")
            if image_url:
                # Обновляем в БД
                await complete_video_task(task_id, image_url)

                # Отправляем пользователю
                try:
                    await bot.send_photo(
                        chat_id=user_id,
                        photo=image_url,
                        caption=f"✅ <b>Готово!</b>\n\n🤖 Модель: <code>{model_name}</code>\n<code>{cost}</code>🍌 списано",
                        parse_mode="HTML",
                        reply_markup=get_multiturn_keyboard("no_preset"),
                    )
                    logger.info(f"Task {task_id}: image sent to user {user_id}")
                except Exception as e:
                    # Если не удалось отправить фото по URL, отправляем ссылкой
                    logger.warning(f"Failed to send photo: {e}")
                    await bot.send_message(
                        chat_id=user_id,
                        text=f"✅ <b>Готово!</b>\n\n🤖 Модель: <code>{model_name}</code>\n<code>{cost}</code>🍌 списано\n\n<a href='{image_url}'>Скачать изображение</a>",
                        parse_mode="HTML",
                        reply_markup=get_multiturn_keyboard("no_preset"),
                    )
                return

        logger.error(f"Task {task_id}: completed but no image URL")
        await add_credits(user_id, cost)
        await bot.send_message(
            chat_id=user_id,
            text="❌ Изображение сгенерировано, но не удалось получить ссылку.\n🍌 Бананы возвращены на счёт.",
            reply_markup=get_main_menu_keyboard(),
        )

    elif status == "TASK_STATUS_FAILED":
        # Задача упала
        reason = task_info.get("reason", "Unknown error")
        logger.error(f"Task {task_id}: failed with reason: {reason}")

        # Возвращаем кредиты
        await add_credits(user_id, cost)
        await bot.send_message(
            chat_id=user_id,
            text=f"❌ <b>Ошибка генерации изображения</b>\n\n{reason}\n\n🍌 Бананы возвращены на счёт.",
            reply_markup=get_main_menu_keyboard(),
        )
    else:
        # Таймаут или другой статус
        logger.warning(f"Task {task_id}: unexpected status {status}")
        await add_credits(user_id, cost)
        await bot.send_message(
            chat_id=user_id,
            text="❌ <b>Ошибка генерации изображения</b>\n\n🍌 Бананы возвращены на счёт.",
            reply_markup=get_main_menu_keyboard(),
        )


# =============================================================================
# ФОНОВЫЙ ОПРОС СТАТУСА ВИДЕО ЗАДАЧ
# =============================================================================


async def poll_video_task_status(
    task_id: str, user_id: int, bot: Bot, max_attempts: int = 60, delay: int = 10
):
    """Фоновый опрос статуса задачи видео от Freepik/Kling"""
    from bot.services.kling_service import kling_service

    logger.info(f"Starting poll for task {task_id}, user {user_id}")

    for attempt in range(max_attempts):
        try:
            # Проверяем статус задачи
            status_data = await kling_service.get_task_status(task_id)

            if not status_data:
                logger.warning(f"Task {task_id}: no status data, attempt {attempt + 1}")
                await asyncio.sleep(delay)
                continue

            task_data = status_data.get("data", {})
            status = task_data.get("status")

            logger.info(f"Task {task_id}: status = {status}, attempt {attempt + 1}")

            if status == "COMPLETED":
                # Задача завершена — получаем URL видео
                generated = task_data.get("generated", [])
                if generated and len(generated) > 0:
                    video_url = generated[0].get("url")
                    if video_url:
                        # Обновляем в БД
                        await complete_video_task(task_id, video_url)

                        # Отправляем пользователю
                        try:
                            from bot.keyboards import get_video_result_keyboard

                            await bot.send_video(
                                chat_id=user_id,
                                video=video_url,
                                caption="🎬 <b>Ваше видео готово!</b>",
                                parse_mode="HTML",
                                reply_markup=get_video_result_keyboard(video_url),
                            )
                            logger.info(f"Task {task_id}: video sent to user {user_id}")
                        except Exception as e:
                            # Если не удалось отправить видео по URL, отправляем ссылкой
                            logger.warning(f"Failed to send video: {e}")
                            from bot.keyboards import get_video_result_keyboard

                            await bot.send_message(
                                chat_id=user_id,
                                text=f"🎬 <b>Ваше видео готово!</b>\n\n<a href='{video_url}'>Скачать видео</a>",
                                parse_mode="HTML",
                                reply_markup=get_video_result_keyboard(video_url),
                            )
                        return

                logger.error(f"Task {task_id}: completed but no video URL")
                await bot.send_message(
                    chat_id=user_id,
                    text="❌ Видео сгенерировано, но не удалось получить ссылку.\nПожалуйста, обратитесь в поддержку.",
                    reply_markup=get_main_menu_keyboard(),
                )
                return

            elif status == "FAILED":
                # Задача упала
                error_msg = task_data.get("error", "Unknown error")
                logger.error(f"Task {task_id}: failed with error: {error_msg}")

                # Возвращаем кредиты
                task = await get_task_by_id(task_id)
                if task:
                    # Определяем стоимость по пресету
                    preset = preset_manager.get_preset(task.preset_id)
                    if preset:
                        await add_credits(user_id, preset.cost)
                        await bot.send_message(
                            chat_id=user_id,
                            text=f"❌ <b>Ошибка генерации видео</b>\n\n{error_msg}\n\n🍌 Бананы возвращены на счёт.",
                            reply_markup=get_main_menu_keyboard(),
                        )
                        return

                await bot.send_message(
                    chat_id=user_id,
                    text=f"❌ <b>Ошибка генерации видео</b>\n\n{error_msg}",
                    reply_markup=get_main_menu_keyboard(),
                )
                return

            elif status in ("PENDING", "PROCESSING", "CREATED"):
                # Задача ещё в процессе — ждём
                await asyncio.sleep(delay)
                continue
            else:
                # Неизвестный статус
                logger.warning(f"Task {task_id}: unknown status '{status}'")
                await asyncio.sleep(delay)
                continue

        except Exception as e:
            logger.exception(f"Task {task_id}: error during polling: {e}")
            await asyncio.sleep(delay)

    # Таймаут
    logger.warning(f"Task {task_id}: polling timeout after {max_attempts} attempts")
    await bot.send_message(
        chat_id=user_id,
        text="⏱ <b>Генерация видео занимает слишком долго</b>\n\nЯ продолжу проверять статус в фоне.\nЕсли видео будет готово — я пришлю его автоматически.",
        reply_markup=get_main_menu_keyboard(),
    )


# =============================================================================
# ОБРАБОТЧИКИ ОПЦИЙ ВИДЕО БЕЗ ПРЕСЕТА
# =============================================================================


@router.callback_query(F.data.startswith("no_preset_duration_"))
async def set_no_preset_duration(callback: types.CallbackQuery, state: FSMContext):
    """Устанавливает длительность видео без пресета"""
    duration = int(callback.data.replace("no_preset_duration_", ""))

    data = await state.get_data()
    video_options = data.get("video_options", {})
    video_options["duration"] = duration
    await state.update_data(video_options=video_options)

    user_prompt = data.get("user_prompt", "")

    # Обновляем клавиатуру с новыми значениями
    current_ratio = video_options.get("aspect_ratio", "16:9")
    current_audio = video_options.get("generate_audio", True)

    await callback.message.edit_text(
        f"🎬 <b>Настройка видео</b>\n\n"
        f"Промпт: <code>{user_prompt[:100]}{'...' if len(user_prompt) > 100 else ''}</code>\n\n"
        f"Выберите параметры и нажмите ▶️ Запустить:",
        reply_markup=get_video_options_no_preset_keyboard(
            duration, current_ratio, current_audio
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("no_preset_ratio_"))
async def set_no_preset_ratio(callback: types.CallbackQuery, state: FSMContext):
    """Устанавливает формат видео без пресета"""
    ratio = callback.data.replace("no_preset_ratio_", "").replace("_", ":")

    data = await state.get_data()
    video_options = data.get("video_options", {})
    video_options["aspect_ratio"] = ratio
    await state.update_data(video_options=video_options)

    user_prompt = data.get("user_prompt", "")

    # Обновляем клавиатуру с новыми значениями
    current_duration = video_options.get("duration", 5)
    current_audio = video_options.get("generate_audio", True)

    await callback.message.edit_text(
        f"🎬 <b>Настройка видео</b>\n\n"
        f"Промпт: <code>{user_prompt[:100]}{'...' if len(user_prompt) > 100 else ''}</code>\n\n"
        f"Выберите параметры и нажмите ▶️ Запустить:",
        reply_markup=get_video_options_no_preset_keyboard(
            current_duration, ratio, current_audio
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("no_preset_audio_"))
async def set_no_preset_audio(callback: types.CallbackQuery, state: FSMContext):
    """Устанавливает генерацию звука без пресета"""
    audio = callback.data.replace("no_preset_audio_", "") == "on"

    data = await state.get_data()
    video_options = data.get("video_options", {})
    video_options["generate_audio"] = audio
    await state.update_data(video_options=video_options)

    user_prompt = data.get("user_prompt", "")

    # Обновляем клавиатуру с новыми значениями
    current_duration = video_options.get("duration", 5)
    current_ratio = video_options.get("aspect_ratio", "16:9")

    await callback.message.edit_text(
        f"🎬 <b>Настройка видео</b>\n\n"
        f"Промпт: <code>{user_prompt[:100]}{'...' if len(user_prompt) > 100 else ''}</code>\n\n"
        f"Выберите параметры и нажмите ▶️ Запустить:",
        reply_markup=get_video_options_no_preset_keyboard(
            current_duration, current_ratio, audio
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "run_no_preset_video")
async def run_no_preset_video(callback: types.CallbackQuery, state: FSMContext):
    """Запускает генерацию видео без пресета"""
    data = await state.get_data()
    user_prompt = data.get("user_prompt", "")

    await callback.message.edit_text(
        f"🎬 <b>Запускаю генерацию видео...</b>\n\n" f"<i>Это займёт 1-3 минуты</i>",
        parse_mode="HTML",
    )

    # Запускаем генерацию напрямую через callback
    await start_no_preset_video_generation(callback, state, user_prompt)
    await callback.answer()


async def start_no_preset_video_generation(
    callback: types.CallbackQuery, state: FSMContext, prompt: str
):
    """Запускает генерацию видео без пресета (выделено для совместимости с callback)"""
    cost = 4

    # Проверяем баланс
    if not await check_can_afford(callback.from_user.id, cost):
        await callback.message.answer(
            f"❌ Недостаточно бананов!\n" f"Нужно: {cost}🍌\n" f"Пополните баланс.",
            reply_markup=get_main_menu_keyboard(),
        )
        await state.clear()
        return

    # Списываем
    await deduct_credits(callback.from_user.id, cost)

    data = await state.get_data()
    video_options = data.get("video_options", {})
    duration = video_options.get("duration", 5)
    aspect_ratio = video_options.get("aspect_ratio", "16:9")
    generate_audio = video_options.get("generate_audio", True)

    processing = await callback.message.answer(
        "🎬 <b>Генерирую видео...</b>\n\n"
        f"⏱ Длительность: {duration} сек\n"
        f"📐 Формат: {aspect_ratio}\n"
        f"🔊 Звук: {'Да' if generate_audio else 'Нет'}\n\n"
        f"<i>Это займёт 1-3 минуты</i>",
        parse_mode="HTML",
    )

    try:
        from bot.config import config
        from bot.services.kling_service import kling_service

        # Генерируем с webhook для асинхронной обработки
        result = await kling_service.generate_video(
            prompt=prompt,
            model="v3_std"
            if video_options.get("quality", "std") == "std"
            else "v3_pro",
            duration=duration,
            aspect_ratio=aspect_ratio,
            webhook_url=config.kling_notification_url,
        )

        if result and result.get("task_id"):
            task_id = result["task_id"]

            # Сохраняем задачу в БД для обработки webhook'ом
            from bot.database import add_generation_task

            user = await get_or_create_user(callback.from_user.id)
            await add_generation_task(user.id, task_id, "video", "no_preset")

            # Клавиатура с кнопкой главного меню
            from aiogram.utils.keyboard import InlineKeyboardBuilder

            menu_builder = InlineKeyboardBuilder()
            menu_builder.button(text="🏠 Главное меню", callback_data="back_main")

            await processing.edit_text(
                f"🎬 <b>Видео в процессе генерации...</b>\n\n"
                f"⏱ Длительность: {duration} сек\n"
                f"📐 Формат: {aspect_ratio}\n"
                f"🔊 Звук: {'Да' if generate_audio else 'Нет'}\n\n"
                f"<i>Задача: <code>{task_id}</code></i>\n"
                f"Видео будет отправлено автоматически когда будет готово.",
                reply_markup=menu_builder.as_markup(),
                parse_mode="HTML",
            )
        else:
            await processing.delete()
            await add_credits(callback.from_user.id, cost)
            await callback.message.answer(
                "❌ Не удалось создать задачу на генерацию видео. Бананы возвращены.",
                reply_markup=get_main_menu_keyboard(),
            )

    except Exception as e:
        logger.exception(f"Video generation error: {e}")
        await processing.delete()
        await add_credits(callback.from_user.id, cost)
        await callback.message.answer(
            f"❌ Ошибка генерации: {str(e)[:100]}", reply_markup=get_main_menu_keyboard()
        )

    await state.clear()
