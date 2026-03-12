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
    get_multiturn_keyboard,
    get_prompt_tips_keyboard,
    get_reference_images_confirmation_keyboard,
    get_reference_images_keyboard,
    get_reference_images_upload_keyboard,
    get_resolution_keyboard,
    get_search_grounding_keyboard,
    get_video_edit_confirm_keyboard,
    get_video_edit_input_type_keyboard,
    get_video_edit_keyboard,
    get_video_options_no_preset_keyboard,
)
from bot.services.gemini_service import gemini_service
from bot.services.preset_manager import preset_manager
from bot.services.seedream_service import seedream_service
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
        v_model="v26_pro",  # модель видео
        v_duration=5,
        v_ratio="16:9",
        reference_images=[],  # Для референсов (до 14)
        v_image_url=None,  # Для imgtxt режима - стартовое изображение
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
    await callback.message.edit_text(
        f"🖼 <b>Создание фото</b>\n\n"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n\n"
        f"<b>Шаг 1: Загрузка референсов (опционально)</b>\n\n"
        f"Загрузите изображения для:\n"
        f"• Точного сходства с объектом\n"
        f"• Сохранения стиля\n"
        f"• Персонажей (до 14 фото)\n\n"
        f"После загрузки нажмите 'Продолжить' или 'Пропустить'",
        reply_markup=get_reference_images_upload_keyboard(0, 14, "new"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_images)


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
    current_model = data.get("v_model", "v26_pro")
    current_duration = data.get("v_duration", 5)
    current_ratio = data.get("v_ratio", "16:9")
    reference_images = data.get("reference_images", [])
    user_prompt = data.get("user_prompt", "")
    v_image_url = data.get("v_image_url")
    v_video_url = data.get("v_video_url")

    # Формируем текст о референсах
    ref_text = ""
    if reference_images:
        ref_text = f"📎 Референсов: <code>{len(reference_images)}</code>\n"

    # Формируем статус медиа в зависимости от типа
    media_status = ""
    if current_v_type == "imgtxt":
        if v_image_url:
            media_status = "✅ <b>Стартовое изображение загружено!</b>\n"
        else:
            media_status = "📷 <b>Загрузите стартовое изображение</b>\n"
    elif current_v_type == "video":
        if v_video_url:
            media_status = "✅ <b>Референсное видео загружено!</b>\n"
        else:
            media_status = "📹 <b>Загрузите референсное видео</b>\n"

    # Формируем текст о промпте
    prompt_text = ""
    if user_prompt:
        prompt_text = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:100]}{'...' if len(user_prompt) > 100 else ''}</code>\n"

    # Тип в настройках
    type_text = (
        "Текст → Видео"
        if current_v_type == "text"
        else "Фото + Текст → Видео"
        if current_v_type == "imgtxt"
        else "Видео + Текст → Видео"
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
    elif current_v_type == "video" and not v_video_url:
        text += f"\n\n<i>📹 Загрузите видео-референс (3-10 сек) для стиля/движения</i>"

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
            reply_markup=get_create_image_keyboard(current_service, current_ratio),
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
            reply_markup=get_create_image_keyboard(current_service, current_ratio),
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
    await state.set_state(GenerationStates.waiting_for_video_prompt)



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
    """Выбор типа генерации: видео+текст - запрашиваем видео на том же экране"""
    data = await state.get_data()
    current_model = data.get("v_model", "v26_pro")
    current_duration = data.get("v_duration", 5)
    current_ratio = data.get("v_ratio", "16:9")
    v_video_url = data.get("v_video_url")

    await state.update_data(v_type="video")

    # Показываем сообщение с просьбой загрузить видео на ТОМ ЖЕ экране
    video_status = ""
    if v_video_url:
        video_status = "\n✅ <b>Референсное видео загружено!</b>\n"

    text = (
        f"🎬 <b>Создание видео</b>\n\n"
        f"⚙️ <b>Текущие настройки:</b>\n"
        f"   📝 Тип: <code>Видео + Текст → Видео</code>\n"
        f"   🤖 Модель: <code>{current_model}</code>\n"
        f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
        f"   📐 Формат: <code>{current_ratio}</code>\n"
        f"{video_status}\n"
        f"<b>📹 Загрузите референсное видео</b>\n\n"
        f"Отправьте видео (3-10 сек), которое станет референсом для стиля/движения.\n"
        f"После загрузки введите промпт для генерации.\n\n"
        f"<i>Пример: 'преобразовать в футуристический стиль с неоновым свечением'</i>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_create_video_keyboard(
            current_v_type="video",
            current_model=current_model,
            current_duration=current_duration,
            current_ratio=current_ratio,
        ),
        parse_mode="HTML",
    )
    if v_video_url:
        await state.set_state(GenerationStates.waiting_for_video_prompt)
    else:
        await state.set_state(GenerationStates.waiting_for_reference_video)
    await callback.answer()


@router.callback_query(F.data.startswith("v_model_"))
async def handle_v_model(callback: types.CallbackQuery, state: FSMContext):
    """Generic handler for all video model selections"""
    model = callback.data.replace("v_model_", "")
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    current_duration = data.get("v_duration", 5)
    current_ratio = data.get("v_ratio", "16:9")

    await state.update_data(v_model=model)

    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type=current_v_type,
            current_model=model,
            current_duration=current_duration,
            current_ratio=current_ratio,
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


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
    await state.set_state(GenerationStates.waiting_for_input)


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
    await state.set_state(GenerationStates.waiting_for_input)


# =============================================================================
# НОВЫЙ UX: МЕНЮ СОЗДАНИЯ ФОТО (get_create_image_keyboard)
# =============================================================================


@router.callback_query(F.data == "model_flux_pro")
async def handle_model_flux_pro(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели FLUX.2 Pro"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")

    await state.update_data(img_service="flux_pro")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service="flux_pro",
            current_ratio=current_ratio,
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_nanobanana")
async def handle_model_nanobanana(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Nano Banana"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")

    await state.update_data(img_service="nanobanana")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service="nanobanana",
            current_ratio=current_ratio,
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_banana_pro")
async def handle_model_banana_pro(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Banana Pro"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")

    await state.update_data(img_service="banana_pro")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service="banana_pro",
            current_ratio=current_ratio,
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_seedream")
async def handle_model_seedream(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Seedream 5.0 (Novita)"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")

    await state.update_data(img_service="seedream")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service="seedream",
            current_ratio=current_ratio,
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_seedream_45")
async def handle_model_seedream_45(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Seedream 4.5 (Novita)"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")

    await state.update_data(img_service="seedream_45")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service="seedream_45",
            current_ratio=current_ratio,
        )
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

    await state.update_data(img_service="z_image_turbo_lora")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service="z_image_turbo_lora",
            current_ratio=current_ratio,
        )
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
        model_name = "🍌 Nano Banana"
        model_cost = str(preset_manager.get_generation_cost("gemini-2.5-flash"))

    # Шаг 1: Загрузка референсов
    await callback.message.edit_text(
        f"🖼 <b>Генерация фото</b>\n\n"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: {model_name} ({model_cost}🍌)\n\n"
        f"<b>Шаг 1: Референсы (опционально)</b>\n\n"
        f"Загрузите референсные изображения для:\n"
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
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: 💎 Banano Pro ({edit_cost}🍌, 4K, сохранение лиц)\n\n"
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
        f"🔊 Звук: {'Да' if video_options.get('generate_audio', True) else 'Нет'}</i>",
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
                reply_markup=get_create_image_keyboard(current_service, current_ratio),
                parse_mode="HTML",
            )
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


@router.message(GenerationStates.waiting_for_reference_video, F.video | (F.document & F.document.mime_type.startswith("video/")))
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

        # Проверяем размер (макс 50MB)
        file_size = getattr(video_obj, 'file_size', 0)
        if file_size > 50 * 1024 * 1024:
            await message.answer("❌ Видео слишком большое (макс 50MB).")
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



@router.message(GenerationStates.waiting_for_video_prompt, F.video | (F.document & F.document.mime_type.startswith("video/")))
async def process_video_for_video_prompt_state(
    message: types.Message, state: FSMContext
):
    """
    Обрабатывает загруженное видео когда пользователь в состоянии waiting_for_video_prompt.
    Это для режима video (видео+текст → видео). Поддерживает video и document.
    """
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    if generation_type == "video" and v_type == "video":
        # Определяем источник файла
        if message.video:
            video_obj = message.video
        elif message.document and message.document.mime_type.startswith("video/"):
            video_obj = message.document
        else:
            await message.answer("❌ Неверный тип файла. Отправьте видео.")
            return

        file = await message.bot.get_file(video_obj.file_id)

        # Проверяем размер (макс 50MB)
        file_size = getattr(video_obj, 'file_size', 0)
        if file_size > 50 * 1024 * 1024:
            await message.answer("❌ Видео слишком большое (макс 50MB).")
            return

        video_bytes = await message.bot.download_file(file.file_path)
        video_data = video_bytes.read()

        # Сохраняем видео и получаем URL
        video_url = save_uploaded_file(video_data, "mp4")

        if video_url:
            await state.update_data(v_video_url=video_url)
            logger.info(f"Saved reference video for video mode (prompt state): {video_url}")
        else:
            await message.answer("❌ Не удалось сохранить видео. Попробуйте ещё раз.")
            return



async def start_no_preset_generation(
    message: types.Message, state: FSMContext, gen_type: str, prompt: str
):
    """Запускает генерацию без пресета"""
    # Используем preset_manager для получения стоимости
    if gen_type == "image":
        cost = preset_manager.get_generation_cost("gemini-2.5-flash")
    else:
        cost = preset_manager.get_video_cost("v3_std", 5)

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
                photo = types.BufferedInputFile(image_bytes, filename="generated.png")
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
                webhook_url=(
                    config.kling_notification_url if config.WEBHOOK_HOST else None
                ),
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
        "motion_control",
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
        elif generation_type == "motion_control":
            # Motion Control: после загрузки изображения персонажа,
            # запрашиваем видео-референс для движения
            await state.set_state(GenerationStates.waiting_for_video)
            await message.answer(
                f"✅ <b>Изображение персонажа получено!</b>\n\n"
                f"Теперь загрузите видео-референс с движением:\n"
                f"• Видео с человеком\n"
                f"• Видео с нужным движением\n"
                f"• Любое видео для переноса движения\n\n"
                f"<i>Это видео определит, как будет двигаться персонаж</i>",
                parse_mode="HTML",
                reply_markup=get_back_keyboard("back_main"),
            )
            return
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




@router.message(GenerationStates.waiting_for_input, F.text)
async def handle_generation_prompt(message: types.Message, state: FSMContext):
    """Обрабатывает текстовые промпты для нового UX генерации изображений."""
    prompt = message.text.strip()
    if not prompt:
        await message.answer("⚠️ Введите описание перед генерацией.")
        return

    data = await state.get_data()
    generation_type = data.get("generation_type")

    if generation_type != "image":
        return

    await state.update_data(user_prompt=prompt)
    aspect_ratio = data.get("img_ratio", "1:1")
    await run_no_preset_image_generation(
        message, state, prompt, aspect_ratio, message.from_user.id
    )
# =============================================================================
# ЗАПУСК ГЕНЕРАЦИИ
# =============================================================================


@router.callback_query(
    F.data.startswith("run_")
    & ~F.data.startswith("run_no_preset")
    & ~F.data.in_(["run_generate", "run_image_generate"])
)
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
            photo = types.BufferedInputFile(image_bytes, filename="generated.png")

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

    # Используем preset_manager для получения стоимости
    cost = preset_manager.get_generation_cost("gemini-3-pro-image-preview")

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

    # Используем preset_manager для получения стоимости
    cost = preset_manager.get_generation_cost("gemini-3-pro-image-preview")

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
    await state.set_state(GenerationStates.waiting_for_input)


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
    await state.set_state(GenerationStates.waiting_for_input)


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
    await state.set_state(GenerationStates.waiting_for_input)


# =============================================================================
# ОБРАБОТЧИКИ БЕЗ ПРЕСЕТА - ВЫБОР ФОРМАТА
# =============================================================================


@router.callback_query(F.data == "run_no_preset_image")
async def handle_run_no_preset_image(callback: types.CallbackQuery, state: FSMContext):
    """Запускает генерацию изображения без пресета с выбранным форматом"""
    data = await state.get_data()
    user_prompt = data.get("user_prompt", "")
    # Используем выбранный формат или 1:1 по умолчанию
    data = await state.get_data()
    aspect_ratio = data.get("img_ratio", "1:1")

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
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "generate_image_confirm_refs")
async def confirm_image_references(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждает референсы и переходит к вводу промпта для генерации изображений"""
    data = await state.get_data()
    ref_images = data.get("reference_images", [])
    generation_options = data.get("generation_options", {})

    # Сохраняем референсы в generation_options
    generation_options["reference_images"] = ref_images
    await state.update_data(generation_options=generation_options)

    # Переходим к вводу промпта
    await state.set_state(GenerationStates.waiting_for_input)

    ref_text = f"\n📎 Референсов: <code>{len(ref_images)}</code>\n" if ref_images else ""

    await callback.message.edit_text(
        f"🖼 <b>Генерация фото</b>\n\n"
        f"{ref_text}"
        f"<b>Шаг 2: Опишите изображение</b>\n\n"
        f"Что хотите создать:\n"
        f"• Что должно быть на изображении\n"
        f"• Стиль (фотореализм, аниме, живопись...)\n"
        f"• Цветовая гамма\n"
        f"• и т.д.\n\n"
        f"<i>Чем подробнее описание — тем лучше результат!</i>",
        reply_markup=get_back_keyboard("back_main"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "generate_image_skip_refs")
async def skip_image_references(callback: types.CallbackQuery, state: FSMContext):
    """Пропускает загрузку референсов и переходит к вводу промпта"""
    data = await state.get_data()
    generation_options = data.get("generation_options", {})

    # Очищаем референсы
    generation_options["reference_images"] = []
    await state.update_data(generation_options=generation_options)

    # Переходим к вводу промпта
    await state.set_state(GenerationStates.waiting_for_input)

    await callback.message.edit_text(
        f"🖼 <b>Генерация фото</b>\n\n"
        f"<b>Шаг 2: Опишите изображение</b>\n\n"
        f"Что хотите создать:\n"
        f"• Что должно быть на изображении\n"
        f"• Стиль (фотореализм, аниме, живопись...)\n"
        f"• Цветовая гамма\n"
        f"• и т.д.\n\n"
        f"<i>Чем подробнее описание — тем лучше результат!</i>",
        reply_markup=get_back_keyboard("back_main"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "run_no_preset_edit_image")
async def handle_run_no_preset_edit_image(
    callback: types.CallbackQuery, state: FSMContext
):
    """Запускает редактирование изображения без пресета с выбранным форматом"""
    data = await state.get_data()
    user_prompt = data.get("user_prompt", "")
    uploaded_image = data.get("uploaded_image")
    # Используем выбранный формат или 1:1 по умолчанию
    data = await state.get_data()
    aspect_ratio = data.get("img_ratio", "1:1")

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
    await state.update_data(img_ratio=ratio)

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
    await state.update_data(img_ratio=ratio)

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
    image_service = data.get("img_service", "nanobanana")
    # Получаем загруженные референсные изображения
    raw_reference_images = data.get("reference_images", [])

    # Определяем пользователя (для callback message.from_user это бот)
    if user_id is None:
        user_id = message.from_user.id

    # Определяем сервис и стоимость через preset_manager
    model_override = None
    if image_service in ("novita", "flux_pro"):
        from bot.services.novita_service import novita_service

        service = novita_service
        model_name = "✨ FLUX.2 Pro"
        cost = preset_manager.get_generation_cost("z_image_turbo")
    elif image_service == "seedream":
        from bot.services.novita_service import novita_service

        service = novita_service
        model_name = "🎨 Seedream"
        cost = preset_manager.get_generation_cost("seedream")
    elif image_service == "seedream_45":
        service = seedream_service
        model_name = "🌟 Seedream 4.5"
        cost = preset_manager.get_generation_cost("seedream")
    elif image_service == "z_image_turbo":
        from bot.services.novita_service import novita_service

        service = novita_service
        model_name = "🚀 Z-Image Turbo LoRA"
        cost = preset_manager.get_generation_cost("z_image_turbo")
    elif image_service == "banana_2":
        from bot.services.gemini_service import gemini_service

        service = gemini_service
        model_name = "⚡ Banana 2"
        cost = preset_manager.get_generation_cost("gemini-3.1-flash-image-preview")
        model_override = "google/gemini-3.1-flash-image-preview"
    else:
        from bot.services.gemini_service import gemini_service

        service = gemini_service
        model_name = "🍌 Nano Banana"
        cost = preset_manager.get_generation_cost("gemini-2.5-flash-image")

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
        if image_service == "novita" or image_service == "flux_pro":
            # FLUX.2 Pro через Novita - async API, returns task_id
            size = f"{aspect_ratio}_hq"
            # Конвертируем байты референсов в URL для Novita
            reference_images = []
            for img_data in raw_reference_images:
                if isinstance(img_data, bytes):
                    img_url = save_uploaded_file(img_data, "png")
                    if img_url:
                        reference_images.append(img_url)
                elif isinstance(img_data, str):
                    reference_images.append(img_data)
            task_response = await service.generate_image(
                prompt=prompt,
                model="flux-pro",  # or appropriate model
                size=size,
                webhook_url=config.novita_notification_url if config.WEBHOOK_HOST else None,
                reference_images=reference_images,
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

                await state.clear()
                return
            return
        elif image_service == "seedream":
            # Seedream через Novita - может возвращать как task_id, так и сразу изображение
            size = "2048x2048"  # Default 2K for Seedream
            # Конвертируем байты референсов в URL для Novita
            reference_images = []
            for img_data in raw_reference_images:
                if isinstance(img_data, bytes):
                    img_url = save_uploaded_file(img_data, "png")
                    if img_url:
                        reference_images.append(img_url)
                elif isinstance(img_data, str):
                    reference_images.append(img_data)

            task_response = await service.generate_seedream_image(
                prompt=prompt,
                size=size,
                watermark=False,
                webhook_url=(
                    config.seedream_notification_url if config.WEBHOOK_HOST else None
                ),
                image=reference_images,
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
            return
        elif image_service == "z_image_turbo":
            # Z-Image Turbo LoRA через Novita
            size = f"{aspect_ratio}_hq"
            task_response = await service.generate_image_turbo_lora(
                prompt=prompt,
                size=size,
                webhook_url=(
                    config.novita_notification_url if config.WEBHOOK_HOST else None
                ),
                reference_images=reference_images,
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

        elif image_service == "seedream_45":
            service = seedream_service
            model_name = "🌟 Seedream 4.5"
            cost = preset_manager.get_generation_cost("seedream")

            aspect_to_size = {
                "1:1": "2048x2048",
                "16:9": "2560x1440",
                "9:16": "1440x2560",
                "4:3": "2560x1920",
                "3:4": "1920x2560",
                "3:2": "2560x1707",
                "2:3": "1707x2560",
            }
            size = aspect_to_size.get(aspect_ratio, "2048x2048")

            # Convert reference images to URLs (API expects URLs, not base64)
            reference_images = []
            for img_data in raw_reference_images:
                if isinstance(img_data, bytes):
                    img_url = save_uploaded_file(img_data, "png")
                    if img_url:
                        reference_images.append(img_url)
                elif isinstance(img_data, str):
                    reference_images.append(img_data)

            result = await service.generate_image(
                prompt=prompt,
                size=size,
                images=reference_images,
                watermark=False,  # Match successful Seedream 5.0 config
            )
            await processing.delete()
            if result:
                # Seedream returns List[bytes], take first image
                image_bytes = result[0] if isinstance(result, list) else result
                saved_url = save_uploaded_file(image_bytes, "png")

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

                    user = await get_or_create_user(user_id)
                    task_id = f"seedream_45_{uuid.uuid4().hex[:12]}"
                    await add_generation_task(user.id, task_id, "image", "no_preset")
                    await complete_video_task(task_id, saved_url)

                photo = types.BufferedInputFile(image_bytes, filename="generated.png")
                await message.answer_photo(
                    photo=photo,
                    caption=f"✅ <b>Готово!</b>\n\n"
                    f"🤖 Модель: <code>{model_name}</code>\n"
                    f"📐 Размер: <code>{size}</code>\n"
                    f"<code>{cost}</code>🍌 списано",
                    parse_mode="HTML",
                    reply_markup=get_multiturn_keyboard("no_preset"),
                )

                await _send_original_document(
                    message.answer_document, result, saved_url
                )
                if saved_url:
                    await _send_download_link(message.answer, saved_url)
            else:
                await add_credits(user_id, cost)
                await message.answer("❌ Не удалось сгенерировать. Бананы возвращены.")

            await state.clear()
            return
        else:
            # Nano Banana / Gemini
            # Map service to correct model
            if image_service == "nanobanana":
                model_to_use = "gemini-2.5-flash-image"
            elif image_service == "banana_pro":
                model_to_use = "gemini-3-pro-image-preview"
            elif image_service == "banana_2":
                model_to_use = "gemini-3.1-flash-image-preview"
            else:
                model_to_use = "gemini-2.5-flash-image"

            # Calculate cost for Gemini models
            cost = preset_manager.get_generation_cost(model_to_use)

            # Prepare reference images for Gemini: separate bytes and URLs
            reference_images_bytes = []
            reference_image_urls = []
            for ref in raw_reference_images:
                if isinstance(ref, bytes):
                    reference_images_bytes.append(ref)
                elif isinstance(ref, str):
                    reference_image_urls.append(ref)

            result = await service.generate_image(
                prompt=prompt,
                model=model_to_use,
                aspect_ratio=aspect_ratio,
                image_input=None,
                reference_images=reference_images_bytes
                if reference_images_bytes
                else None,
                reference_image_urls=reference_image_urls
                if reference_image_urls
                else None,
                preserve_faces=True
                if (reference_images_bytes or reference_image_urls)
                else False,
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

    # Определяем модель и стоимость через preset_manager
    if preferred_model == "flash":
        model = "gemini-2.5-flash-image"
        cost = preset_manager.get_generation_cost("gemini-2.5-flash")
    else:
        model = "gemini-3-pro-image-preview"
        cost = preset_manager.get_generation_cost("gemini-3-pro-image-preview")

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

    # Используем preset_manager для получения стоимости с учётом длительности
    # Модель определяется по качеству: std = v3_omni_std_r2v, pro = v3_omni_pro_r2v
    quality = video_edit_options.get("quality", "std")
    video_model = "v3_omni_pro_r2v" if quality == "pro" else "v3_omni_std_r2v"
    duration = video_edit_options.get("duration", 5)
    cost = preset_manager.get_video_cost(video_model, duration)

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

    # Используем preset_manager для получения стоимости с учётом длительности
    # Модель определяется по качеству: std = v3_omni_std, pro = v3_omni_pro
    quality = video_edit_options.get("quality", "std")
    video_model = "v3_omni_pro" if quality == "pro" else "v3_omni_std"
    duration = video_edit_options.get("duration", 5)
    cost = preset_manager.get_video_cost(video_model, duration)

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
    """Обрабатывает загруженное видео для видео-эффектов и motion control"""
    data = await state.get_data()
    generation_type = data.get("generation_type")
    input_type = data.get("video_edit_input_type")

    # Проверяем, что это видео-эффекты (video_edit), видео-изображение (video_edit_image) или motion_control
    if (
        generation_type not in ["video_edit", "video_edit_image", "motion_control"]
        and input_type != "video"
    ):
        # Если это не видео-эффект/motion_control, игнорируем
        await message.answer("Пожалуйста, загрузите изображение (фото)")
        return

    # Обрабатываем motion_control - после загрузки видео-референса запрашиваем промпт
    if generation_type == "motion_control":
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

        # Сохраняем видео-референс
        video_url = save_uploaded_file(video_data, "mp4")

        if video_url:
            await state.update_data(motion_video_url=video_url)
            logger.info(f"Saved motion control video reference: {video_url}")
        else:
            await state.update_data(motion_video_url_data=video_data)

        # Запрашиваем промпт для описания движения
        await state.set_state(GenerationStates.waiting_for_video_prompt)
        await message.answer(
            f"✅ <b>Видео-референс получен!</b>\n\n"
            f"Теперь опишите желаемое движение:\n"
            f"• Как должен двигаться персонаж\n"
            f"• Стиль и атмосфера\n"
            f"• Особые эффекты\n\n"
            f"<i>Например: 'Плавное движение вправо, естественная ходьба'</i>",
            parse_mode="HTML",
            reply_markup=get_back_keyboard("back_main"),
        )
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
    await state.set_state(GenerationStates.waiting_for_input)


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
    await state.set_state(GenerationStates.waiting_for_input)


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
    await state.set_state(GenerationStates.waiting_for_input)


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
    await state.set_state(GenerationStates.waiting_for_input)


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

    # Используем preset_manager для получения стоимости с учётом длительности
    duration = video_options.get("duration", 5)
    cost = preset_manager.get_video_cost(preferred_i2v_model, duration)

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
# ФУНКЦИЯ MOTION CONTROL
# =============================================================================


async def run_motion_control(message: types.Message, state: FSMContext, prompt: str):
    """Запускает генерацию Motion Control - перенос движения с видео на изображение"""
    data = await state.get_data()
    uploaded_image = data.get("uploaded_image")
    uploaded_image_url = data.get("uploaded_image_url")
    motion_video_url = data.get("motion_video_url")
    motion_video_url_data = data.get("motion_video_url_data")
    video_options = data.get("video_options", {})

    if not uploaded_image:
        await message.answer(
            "❌ Ошибка: изображение персонажа не найдено. Начните заново."
        )
        await state.clear()
        return

    if not motion_video_url and not motion_video_url_data:
        await message.answer(
            "❌ Ошибка: видео-референс движения не найден. Начните заново."
        )
        await state.clear()
        return

    # Для Motion Control используем модель v26_motion_pro
    motion_model = "v26_motion_pro"

    # Используем preset_manager для получения стоимости с учётом длительности
    duration = video_options.get("duration", 5)
    cost = preset_manager.get_video_cost(motion_model, duration)

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

    processing = await message.answer(
        f"🎯 <b>Motion Control</b>\n\n"
        f"⏱ Длительность: <code>{duration} сек</code>\n"
        f"📐 Формат: <code>{aspect_ratio}</code>\n\n"
        f"<i>Описание:</i> {prompt[:50]}...\n\n"
        "<i>Это займёт 1-3 минуты</i>",
        parse_mode="HTML",
    )

    try:
        from bot.config import config
        from bot.services.kling_service import kling_service

        # Сохраняем изображение персонажа если нет URL
        image_url = uploaded_image_url
        if not image_url and uploaded_image:
            image_url = save_uploaded_file(uploaded_image, "png")

        # Сохраняем видео-референс если нет URL
        video_ref_url = motion_video_url
        if not video_ref_url and motion_video_url_data:
            video_ref_url = save_uploaded_file(motion_video_url_data, "mp4")

        if not image_url:
            await add_credits(message.from_user.id, cost)
            await message.answer(
                "❌ Не удалось сохранить изображение персонажа.\n"
                "Бананы возвращены. Попробуйте ещё раз.",
                reply_markup=get_main_menu_keyboard(),
            )
            await state.clear()
            return

        if not video_ref_url:
            await add_credits(message.from_user.id, cost)
            await message.answer(
                "❌ Не удалось сохранить видео-референс.\n"
                "Бананы возвращены. Попробуйте ещё раз.",
                reply_markup=get_main_menu_keyboard(),
            )
            await state.clear()
            return

        logger.info(
            f"run_motion_control: generating with model={motion_model}, image_url={image_url[:80] if image_url else 'None'}..., video_ref_url={video_ref_url[:80] if video_ref_url else 'None'}..., prompt={prompt[:50]}..."
        )

        # Для Motion Control используем video_url параметр
        result = await kling_service.generate_video(
            prompt=prompt,
            model=motion_model,
            duration=duration,
            aspect_ratio=aspect_ratio,
            webhook_url=config.kling_notification_url if config.WEBHOOK_HOST else None,
            image_url=image_url,
            video_url=video_ref_url,
        )

        if result:
            logger.info(
                f"run_motion_control: task created successfully, task_id={result.get('task_id')}"
            )
        else:
            logger.error(f"run_motion_control: failed to create task, result is None")

        await processing.delete()

        if result and result.get("task_id"):
            from bot.database import add_generation_task

            user = await get_or_create_user(message.from_user.id)
            await add_generation_task(
                user.id, result["task_id"], "video", "motion_control"
            )

            await message.answer(
                f"✅ <b>Задача создана!</b>\n\n"
                f"ID: <code>{result['task_id']}</code>\n"
                f"🎯 Тип: <code>Motion Control</code>\n"
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
        logger.exception(f"Motion control error: {e}")
        await add_credits(message.from_user.id, cost)
        await message.answer(
            f"❌ Ошибка генерации Motion Control\n\n"
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
    await state.set_state(GenerationStates.waiting_for_input)


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
    await state.set_state(GenerationStates.waiting_for_input)


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
    await state.set_state(GenerationStates.waiting_for_input)


async def run_no_preset_image_from_message(
    message: types.Message, state: FSMContext, user_prompt: str
):
    """Запускает генерацию изображения без пресета из сообщения (новый UX)"""
    # Используем формат по умолчанию 1:1
    # Позже можно добавить выбор формата перед генерацией
    data = await state.get_data()
    aspect_ratio = data.get("img_ratio", "1:1")

    # Запускаем генерацию с выбранным форматом
    await run_no_preset_image_generation(
        message, state, user_prompt, aspect_ratio, message.from_user.id
    )


@router.callback_query(F.data == "run_no_preset_video")
async def run_no_preset_video_from_message(
    message: types.Message, state: FSMContext, user_prompt: str
):
    """Запускает генерацию видео без пресета из сообщения (новый UX)"""
    data = await state.get_data()

    await message.answer(
        f"🎬 <b>Запускаю генерацию видео...</b>\n\n<i>Это займёт 1-3 минуты</i>",
        parse_mode="HTML",
    )

    # Запускаем генерацию
    await start_no_preset_video_from_message(message, state, user_prompt)


async def start_no_preset_video_from_message(
    message: types.Message, state: FSMContext, prompt: str
):
    """Запускает генерацию видео без пресета из сообщения"""
    from bot.database import add_credits, add_generation_task, get_or_create_user

    data = await state.get_data()

    # Получаем параметры из state (новый UX) или video_options (старый UX)
    v_model = data.get("v_model", "v26_pro")
    v_duration = data.get("v_duration", 5)
    v_ratio = data.get("v_ratio", "16:9")
    v_type = data.get("v_type", "text")
    reference_images = data.get("reference_images", [])
    v_image_url = data.get("v_image_url")

    # Fallback для старого формата
    video_options = data.get("video_options", {})
    if not v_model or v_model == "v26_pro":
        v_model = video_options.get("model", "v3_std")
    if not v_duration:
        v_duration = video_options.get("duration", 5)
    if not v_ratio:
        v_ratio = video_options.get("aspect_ratio", "16:9")

    # Используем preset_manager для получения стоимости
    cost = preset_manager.get_video_cost(v_model, v_duration)

    # Проверяем баланс
    if not await check_can_afford(message.from_user.id, cost):
        await message.answer(
            f"❌ Недостаточно бананов!\nНужно: {cost}🍌\nПополните баланс.",
            reply_markup=get_main_menu_keyboard(),
        )
        await state.clear()
        return

    # Списываем
    await deduct_credits(message.from_user.id, cost)

    # Формируем информацию о референсах
    ref_text = ""
    if reference_images:
        ref_text = f"📎 Референсов: <code>{len(reference_images)}</code>\n"

    model_names = {
        "v26_pro": "Kling 2.6 Pro",
        "v3_std": "Kling 3 Standard",
        "v3_pro": "Kling 3 Pro",
        "v3_omni_std": "Kling 3 Omni Std",
        "v3_omni_pro": "Kling 3 Omni Pro",
        "v26_motion_pro": "Kling 2.6 Motion Pro",
    }
    model_name = model_names.get(v_model, v_model)

    processing = await message.answer(
        f"🎬 <b>Генерирую видео...</b>\n\n"
        f"{ref_text}"
        f"🤖 Модель: <code>{model_name}</code>\n"
        f"⏱ Длительность: <code>{v_duration} сек</code>\n"
        f"📐 Формат: <code>{v_ratio}</code>\n"
        f"📝 Тип: <code>{'Фото → Видео' if v_type == 'imgtxt' else 'Текст → Видео'}</code>\n\n"
        f"<i>Это займёт 1-3 минуты</i>",
        parse_mode="HTML",
    )

    try:
        from bot.config import config
        from bot.services.kling_service import kling_service

        # Подготавливаем параметры
        image_url = None
        elements = None

        # Для imgtxt используем загруженное изображение как стартовый кадр
        if v_type == "imgtxt" and v_image_url:
            image_url = v_image_url

        # Конвертируем референсы в URLs (если они в bytes)
        ref_urls = []
        for ref in reference_images:
            if isinstance(ref, bytes):
                ref_url = save_uploaded_file(ref, "png")
                if ref_url:
                    ref_urls.append(ref_url)
            elif isinstance(ref, str):
                ref_urls.append(ref)

        # Формируем elements для сохранения персонажей/стиля
        # Kling поддерживает elements для консистентности
        if ref_urls:
            elements = []
            for ref_url in ref_urls[:4]:  # Максимум 4 персонажа
                elements.append(
                    {"reference_image_urls": [ref_url], "frontal_image_url": ref_url}
                )

        # Если imgtxt + есть референсы, объединяем
        if v_type == "imgtxt" and image_url and elements:
            # Добавляем стартовое изображение как основной референс
            elements.insert(
                0, {"reference_image_urls": [image_url], "frontal_image_url": image_url}
            )
        elif v_type == "imgtxt" and image_url and not elements:
            # Только стартовое изображение
            elements = [
                {"reference_image_urls": [image_url], "frontal_image_url": image_url}
            ]

        # DEBUG: Add logging for image_url and elements
        logger.info(
            f"DEBUG v_type={v_type}, v_image_url={v_image_url}, image_url={image_url}, elements={elements}"
        )

        # Генерируем с webhook для асинхронной обработки
        # ВАЖНО: Для Kling 3 нужно передавать и image_url (основное изображение), и elements (референсы для консистентности)
        result = await kling_service.generate_video(
            prompt=prompt,
            model=v_model,
            duration=v_duration,
            aspect_ratio=v_ratio,
            webhook_url=config.kling_notification_url if config.WEBHOOK_HOST else None,
            image_url=image_url,  # Всегда передаем основное изображение
            elements=elements,  # Всегда передаем elements (могут быть None)
        )

        if result and result.get("task_id"):
            task_id = result["task_id"]

            # Сохраняем задачу в БД для обработки webhook
            user = await get_or_create_user(message.from_user.id)
            await add_generation_task(user.id, task_id, "video", "no_preset")

            # Клавиатура с кнопкой главного меню
            await processing.delete()
            await message.answer(
                f"✅ <b>Задача создана!</b>\n\n"
                f"🤖 Модель: <code>{model_name}</code>\n"
                f"⏱ Длительность: <code>{v_duration} сек</code>\n"
                f"📐 Формат: <code>{v_ratio}</code>\n"
                f"<code>{cost}</code>🍌 списано\n\n"
                f"<i>Видео будет готово через 1-3 минуты.</i>",
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML",
            )
        else:
            await processing.edit_text(
                "❌ Ошибка при запуске генерации. Попробуйте ещё раз."
            )
    except Exception as e:
        logger.exception("Video generation error")
        # Возвращаем кредиты
        await add_credits(message.from_user.id, cost)
        await processing.edit_text(f"❌ Ошибка генерации: {str(e)[:200]}")
    await state.clear()


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
    await state.set_state(GenerationStates.waiting_for_input)


async def start_no_preset_video_generation(
    callback: types.CallbackQuery, state: FSMContext, prompt: str
):
    """Запускает генерацию видео без пресета (выделено для совместимости с callback)"""
    data = await state.get_data()
    video_options = data.get("video_options", {})
    duration = video_options.get("duration", 5)

    # Используем preset_manager для получения стоимости
    cost = preset_manager.get_video_cost("v3_std", duration)

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

        # DEBUG: Add logging for image_url and elements
        logger.info(
            f"DEBUG v_type={v_type}, v_image_url={v_image_url}, image_url={image_url}, elements={elements}"
        )

        # Генерируем с webhook для асинхронной обработки
        result = await kling_service.generate_video(
            prompt=prompt,
            model=(
                "v3_std" if video_options.get("quality", "std") == "std" else "v3_pro"
            ),
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
            f"❌ Ошибка генерации: {str(e)[:100]}",
            reply_markup=get_main_menu_keyboard(),
        )

    await state.clear()


# =============================================================================
# НОВЫЕ ОБРАБОТЧИКИ ДЛЯ UNIFIED UX (run_generate и run_image_generate)
# =============================================================================


@router.callback_query(F.data == "run_generate")
async def handle_run_generate(callback: types.CallbackQuery, state: FSMContext):
    """Обрабатывает нажатие кнопки 'Создать видео' в новом UX"""
    data = await state.get_data()
    user_prompt = data.get("user_prompt", "")
    video_options = data.get("video_options", {})

    if not user_prompt:
        await callback.answer("Введите описание видео", show_alert=True)
        return

    await callback.answer("🚀 Запускаю генерацию видео...")

    # Запускаем генерацию видео
    await run_no_preset_video_from_message(callback.message, state, user_prompt)


@router.callback_query(F.data == "run_image_generate")
async def handle_run_image_generate(callback: types.CallbackQuery, state: FSMContext):
    """Обрабатывает нажатие кнопки 'Создать фото' в новом UX"""
    data = await state.get_data()
    user_prompt = data.get("user_prompt", "")
    data = await state.get_data()
    aspect_ratio = data.get("img_ratio", "1:1")
    image_service = data.get("img_service", "flux_pro")

    if not user_prompt:
        await callback.answer("Введите описание изображения", show_alert=True)
        return

    await callback.answer("🚀 Запускаю генерацию изображения...")

    # Запускаем генерацию изображения
    await run_no_preset_image_generation(
        callback.message, state, user_prompt, aspect_ratio, callback.from_user.id
    )
