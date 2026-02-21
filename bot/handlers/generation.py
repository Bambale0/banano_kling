import io
import logging

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
)
from bot.services.preset_manager import preset_manager
from bot.states import GenerationStates

logger = logging.getLogger(__name__)
router = Router()


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

    await callback.message.edit_text(
        f"📂 <b>{categories[category]['name']}</b>\n"
        f"📝 {categories[category].get('description', '')}\n\n"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n\n"
        f"Выберите пресет:",
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

    # Сохраняем в состояние
    await state.update_data(preset_id=preset_id)

    user_credits = await get_user_credits(callback.from_user.id)
    is_admin = config.is_admin(callback.from_user.id)

    # Админы могут использовать бесплатно
    if not is_admin and user_credits < preset.cost:
        await callback.message.edit_text(
            f"❌ <b>Недостаточно бананов!</b>\n\n"
            f"Пресет: <b>{preset.name}</b>\n"
            f"Стоимость: <code>{preset.cost}</code>🍌\n"
            f"Ваш баланс: <code>{user_credits}</code>🍌\n\n"
            f"💳 Пополните баланс, чтобы продолжить.",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
        return

    text = f"🎯 <b>{preset.name}</b>\n\n"
    text += f"🍌 Стоимость: <code>{preset.cost}</code>🍌\n"
    text += f"🤖 Модель: <code>{preset.model}</code>\n"

    if preset.aspect_ratio:
        text += f"📐 Формат: <code>{preset.aspect_ratio}</code>\n"
    if preset.duration:
        text += f"⏱ Длительность: <code>{preset.duration} сек</code>\n"

    if preset.requires_upload:
        text += "\n📎 <i>Требуется загрузить медиафайл</i>\n"
    if preset.requires_input and preset.input_prompt:
        text += f"\n📝 <i>{preset.input_prompt}</i>\n"

    # Показываем кнопки действий
    await callback.message.edit_text(
        text,
        reply_markup=get_preset_action_keyboard(preset_id, preset.requires_input),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("custom_"))
async def request_custom_input(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает пользовательский ввод для пресета"""
    preset_id = callback.data.replace("custom_", "")
    preset = preset_manager.get_preset(preset_id)

    if not preset:
        await callback.answer("Пресет не найден")
        return

    await state.update_data(preset_id=preset_id, input_type="custom")

    # Если требуется загрузка файла
    if preset.requires_upload:
        await state.set_state(GenerationStates.waiting_for_image)
        await callback.message.edit_text(
            f"📎 <b>Загрузите изображение</b>\n\n"
            f"Для пресета: {preset.name}\n\n"
            f"После загрузки изображения, {preset.input_prompt or 'введите описание'}",
            reply_markup=get_back_keyboard(f"preset_{preset_id}"),
            parse_mode="HTML",
        )
    else:
        await state.set_state(GenerationStates.waiting_for_input)
        await callback.message.edit_text(
            f"✏️ <b>Введите ваш вариант</b>\n\n"
            f"{preset.input_prompt or 'Опишите, что хотите создать'}\n\n"
            f"<i>Примеры значений для плейсхолдеров:</i>\n"
            f"• Стиль: минимализм, винтаж, футуризм\n"
            f"• Цветовая схема: яркий, пастельный, тёмный\n"
            f"• Эмоция: радостное, удивлённое, задумчивое",
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

    await callback.message.edit_text(
        f"▶️ <b>Подтвердите генерацию</b>\n\n"
        f"Пресет: <b>{preset.name}</b>\n"
        f"Стоимость: <code>{preset.cost}</code>🍌\n\n"
        f"Промпт:\n<code>{final_prompt[:300]}{'...' if len(final_prompt) > 300 else ''}</code>",
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
        # Используем введённый текст для первого плейсхолдера
        placeholder_values[preset.placeholders[0]] = message.text

        # Заполняем остальные значениями по умолчанию
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

    # Подтверждение
    await message.answer(
        f"▶️ <b>Подтвердите генерацию</b>\n\n"
        f"Пресет: <b>{preset.name}</b>\n"
        f"Стоимость: <code>{preset.cost}</code>🍌\n\n"
        f"Промпт:\n<code>{final_prompt[:300]}{'...' if len(final_prompt) > 300 else ''}</code>",
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
    photo = message.photo[-1]  # Берём максимальное качество
    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)

    # Сохраняем в состояние
    await state.update_data(uploaded_image=image_bytes.read())

    if preset.requires_input:
        # Нужно ввести описание
        await state.set_state(GenerationStates.waiting_for_input)
        await message.answer(
            f"✅ Изображение получено!\n\n"
            f"{preset.input_prompt or 'Введите описание того, что нужно сделать с изображением:'}",
            reply_markup=get_back_keyboard(f"preset_{preset_id}"),
        )
    else:
        # Можно запускать генерацию
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

    # Получаем финальный промпт
    final_prompt = data.get("final_prompt", preset.prompt)
    uploaded_image = data.get("uploaded_image")  # bytes если загружали

    # Определяем тип генерации
    if preset.category in ["image_generation", "image_editing"]:
        await generate_image(callback, preset, final_prompt, uploaded_image, bot)
    else:
        await generate_video(callback, preset, final_prompt, uploaded_image, bot, state)

    # Сохраняем в историю
    user = await get_or_create_user(callback.from_user.id)
    await add_generation_history(user.id, preset_id, final_prompt, preset.cost)

    await state.clear()


async def generate_image(callback, preset, prompt, image_bytes, bot: Bot):
    """Генерация изображения через Gemini"""
    processing_msg = await callback.message.answer(
        "🎨 <b>Генерирую изображение...</b>\n\n" "⏱ Это займёт 10-30 секунд",
        parse_mode="HTML",
    )

    try:
        from bot.services.gemini_service import gemini_service

        result = await gemini_service.generate_image(
            prompt=prompt,
            model=preset.model,
            aspect_ratio=preset.aspect_ratio,
            image_input=image_bytes,
        )

        if result:
            # Отправляем результат
            photo = types.BufferedInputFile(result, filename="generated.png")
            await callback.message.answer_photo(
                photo=photo,
                caption=f"✅ <b>Готово!</b>\n\n"
                f"🍌 Списано: <code>{preset.cost}</code>🍌\n"
                f"🎯 Пресет: {preset.name}",
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML",
            )
        else:
            # Возвращаем кредиты при ошибке
            await add_credits(callback.from_user.id, preset.cost)
            await callback.message.answer(
                "❌ <b>Ошибка генерации</b>\n\n"
                "Бананы возвращены. Попробуйте позже или обратитесь в поддержку.",
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML",
            )

    except Exception as e:
        logger.exception(f"Image generation error: {e}")
        await add_credits(callback.from_user.id, preset.cost)
        await callback.message.answer(
            f"❌ <b>Ошибка генерации</b>\n\n"
            f"Бананы возвращены.\n"
            f"Ошибка: {str(e)[:100]}",
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

    processing_msg = await callback.message.answer(
        "🎬 <b>Видео готовится</b>\n\n"
        "⏱ Это может занять 1-3 минуты\n"
        "🔔 Я пришлю результат, когда будет готово",
        parse_mode="HTML",
    )

    # Если есть изображение, нужно его загрузить куда-то
    image_url = None
    if image_bytes:
        # В реальности нужно загрузить на хостинг и получить публичный URL
        # Заглушка - в production нужна реальная реализация
        image_url = await upload_temp_image(image_bytes)

    try:
        # Создаём задачу
        result = await kling_service.generate_video(
            prompt=prompt,
            model=preset.model.replace("kling-", "").replace("-", "_"),
            duration=preset.duration or 5,
            aspect_ratio=preset.aspect_ratio or "16:9",
            webhook_url=config.kling_notification_url if config.WEBHOOK_HOST else None,
            image_url=image_url,
        )

        if result and result.get("task_id"):
            # Сохраняем в БД для отслеживания
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
                f"Я пришлю видео автоматически, когда оно будет готово.",
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML",
            )
        else:
            # Возвращаем кредиты
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
    """
    Загружает изображение на временный хостинг и возвращает URL
    В production нужна реальная реализация (S3, imgur, etc)
    """
    # Заглушка - в реальности нужно реализовать загрузку
    logger.warning(
        "upload_temp_image called but not implemented - returning placeholder URL"
    )
    return "https://example.com/temp/image.jpg"
