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
from bot.database import (
    add_credits,
    add_generation_history,
    add_generation_task,
    check_can_afford,
    deduct_credits,
    get_or_create_user,
    get_user_credits,
)
from bot.config import config
from bot.keyboards import (
    get_back_keyboard,
    get_category_keyboard,
    get_main_menu_keyboard,
    get_preset_action_keyboard,
    get_model_selection_keyboard,
    get_resolution_keyboard,
    get_image_aspect_ratio_keyboard,
    get_search_grounding_keyboard,
    get_reference_images_keyboard,
    get_advanced_options_keyboard,
    get_multiturn_keyboard,
    get_prompt_tips_keyboard,
    get_image_editing_options_keyboard,
    get_duration_keyboard,
    get_aspect_ratio_keyboard,
)
from bot.services.preset_manager import preset_manager
from bot.services.gemini_service import gemini_service
from bot.states import GenerationStates
from bot.utils.help_texts import (
    get_model_selection_help,
    get_resolution_help,
    get_aspect_ratio_help,
    get_reference_images_help,
    get_search_grounding_help,
    get_prompt_tips,
    get_editing_help,
    get_multiturn_help,
    get_success_message,
    get_error_handling,
    format_generation_options,
    UserHints,
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


# =============================================================================
# ОСНОВНЫЕ ОБРАБОТЧИКИ
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
            "quality": getattr(preset, 'quality', 'std'),
            "generate_audio": True
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
            cost=preset.cost,
            credits=user_credits
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

    if hasattr(preset, 'description') and preset.description:
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

    if preset.aspect_ratio and preset.category not in ["video_generation", "video_editing"]:
        text += f"📐 Формат: <code>{preset.aspect_ratio}</code>\n"
    if preset.duration and preset.category not in ["video_generation", "video_editing"]:
        text += f"⏱ Длительность: <code>{preset.duration} сек</code>\n"

    if preset.requires_upload:
        text += "\n📎 <i>Требуется загрузить медиафайл</i>\n"
    if preset.requires_input and preset.input_prompt:
        text += f"\n📝 <i>{preset.input_prompt}</i>\n"

    # Добавляем подсказку
    hint = UserHints.get_hint_for_stage("preset")
    text += f"\n<i>{hint}</i>"

    # Выбираем клавиатуру в зависимости от категории
    if preset.category in ["image_generation", "image_editing"]:
        reply_markup = get_preset_action_keyboard(preset_id, preset.requires_input, preset.category)
    else:
        reply_markup = get_preset_action_keyboard(preset_id, preset.requires_input, preset.category)

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
        
        model = "gemini-2.5-flash-image" if model_type == "flash" else "gemini-3-pro-image-preview"
        
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
                reply_markup=get_preset_action_keyboard(preset_id, preset.requires_input, preset.category),
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
                "4K": "Максимальное качество, 4096px"
            }
            text += f"<i>{resolutions.get(resolution, '')}</i>\n"
            
            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(preset_id, preset.requires_input, preset.category),
                parse_mode="HTML",
            )
    
    await callback.answer()


@router.callback_query(F.data.startswith("img_ratio_"))
async def handle_image_ratio_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора формата изображения"""
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
                "21:9": "Панорамный (Кино)"
            }
            text += f"<i>{ratios_desc.get(ratio, '')}</i>\n"
            
            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(preset_id, preset.requires_input, preset.category),
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
        generation_options["enable_search"] = not generation_options.get("enable_search", False)
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
                reply_markup=get_preset_action_keyboard(preset_id, preset.requires_input, preset.category),
                parse_mode="HTML",
            )
    
    await callback.answer()


@router.callback_query(F.data.startswith("ref_"))
async def handle_reference_images(callback: types.CallbackQuery, state: FSMContext):
    """Обработка работы с референсными изображениями"""
    parts = callback.data.split("_")
    if len(parts) >= 2:
        preset_id = parts[1]
        
        # Показываем справку о референсах
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
            f"<b>Примеры для вдохновения:</b>\n"
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


@router.message(GenerationStates.waiting_for_image, F.photo)
async def process_uploaded_image(message: types.Message, state: FSMContext):
    """Обрабатывает загруженное изображение"""
    data = await state.get_data()
    preset_id = data.get("preset_id")

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
        await state.update_data(
            uploaded_image=image_data,
            uploaded_image_url=image_url
        )
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
# ЗАПУСК ГЕНЕРАЦИИ
# =============================================================================

@router.callback_query(F.data.startswith("run_"))
async def execute_generation(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    """Запускает процесс генерации"""
    preset_id = callback.data.replace("run_", "")
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
        await generate_image(callback, preset, final_prompt, uploaded_image, bot, state, generation_options)
    else:
        await generate_video(callback, preset, final_prompt, uploaded_image, bot, state)

    # Сохраняем в историю
    user = await get_or_create_user(callback.from_user.id)
    await add_generation_history(user.id, preset_id, final_prompt, preset.cost)

    await state.clear()


async def generate_image(callback, preset, prompt, image_bytes, bot: Bot, state: FSMContext, options: dict):
    """Генерация изображения через Gemini с расширенными опциями"""
    
    # UX: Показываем мотивирующее сообщение
    encouragements = UserHints.get_encouragement()
    random.shuffle(encouragements)
    
    processing_msg = await callback.message.answer(
        f"{encouragements[0]}\n\n"
        f"🎨 <b>Генерирую изображение...</b>\n\n"
        f"⏱ Это займёт 10-30 секунд\n\n"
        f"<i>Модель: {options.get('model', 'gemini-2.5-flash-image')}</i>",
        parse_mode="HTML",
    )

    try:
        from bot.services.gemini_service import gemini_service

        result = await gemini_service.generate_image(
            prompt=prompt,
            model=options.get("model", preset.model),
            aspect_ratio=options.get("aspect_ratio", preset.aspect_ratio),
            image_input=image_bytes,
            resolution=options.get("resolution", "1K"),
            enable_search=options.get("enable_search", False),
            reference_images=options.get("reference_images", []),
        )

        if result:
            # Отправляем результат с опциями многоходового редактирования
            photo = types.BufferedInputFile(result, filename="generated.png")
            
            success_text = get_success_message(preset.name, preset.cost)
            
            await callback.message.answer_photo(
                photo=photo,
                caption=success_text,
                reply_markup=get_multiturn_keyboard(preset.id),
                parse_mode="HTML",
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
    
    duration = video_options.get("duration", preset.duration or 5)
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
        image_url = await upload_temp_image(image_bytes)

    model_map = {
        ("video_generation", "pro"): "v3_pro",
        ("video_generation", "std"): "v3_std",
        ("video_editing", "pro"): "v3_omni_pro_r2v",
        ("video_editing", "std"): "v3_omni_std_r2v",
    }
    model = model_map.get((preset.category, quality), "v3_std")

    try:
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


async def upload_temp_image(image_bytes: bytes) -> str:
    """Загружает изображение на временный хостинг"""
    logger.warning("upload_temp_image called but not implemented")
    return "https://example.com/temp/image.jpg"


# =============================================================================
# ОБРАБОТЧИКИ ВИДЕО-ОПЦИЙ
# =============================================================================

@router.callback_query(F.data.startswith("duration_"))
async def handle_duration_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора длительности видео"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        duration = int(parts[2])
        
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
            
            if hasattr(preset, 'description') and preset.description:
                text += f"\n📝 {preset.description}\n"
            
            text += f"\n🎬 <b>Опции видео:</b>\n"
            text += f"   ⏱ Длительность: <code>{duration} сек</code>\n"
            text += f"   📐 Формат: <code>{video_options.get('aspect_ratio', '16:9')}</code>\n"
            text += f"   {quality_emoji} Качество: <code>{quality.upper()}</code>\n"
            text += f"   🔊 Звук: <code>{'ВКЛ' if video_options.get('generate_audio') else 'ВЫКЛ'}</code>\n"
            
            if preset.requires_input and preset.input_prompt:
                text += f"\n📝 <i>{preset.input_prompt}</i>\n"
            
            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(preset_id, preset.requires_input, preset.category),
                parse_mode="HTML",
            )
    
    await callback.answer()


@router.callback_query(F.data.startswith("ratio_"))
async def handle_aspect_ratio_selection(callback: types.CallbackQuery, state: FSMContext):
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
            
            if hasattr(preset, 'description') and preset.description:
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
                reply_markup=get_preset_action_keyboard(preset_id, preset.requires_input, preset.category),
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
            
            if hasattr(preset, 'description') and preset.description:
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
                reply_markup=get_preset_action_keyboard(preset_id, preset.requires_input, preset.category),
                parse_mode="HTML",
            )
    
    await callback.answer()


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
        parse_mode="HTML"
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
        parse_mode="HTML"
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
        
        if hasattr(preset, 'description') and preset.description:
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
            reply_markup=get_preset_action_keyboard(preset_id, preset.requires_input, preset.category),
            parse_mode="HTML",
        )
    
    await callback.answer()
