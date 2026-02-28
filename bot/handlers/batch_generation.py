import asyncio
import logging
from typing import Optional

from aiogram import Bot, F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.database import add_credits, check_can_afford, deduct_credits, get_user_credits
from bot.keyboards import get_main_menu_keyboard
from bot.services.batch_service import BatchStatus, batch_service
from bot.services.preset_manager import preset_manager
from bot.states import GenerationStates

logger = logging.getLogger(__name__)
router = Router()


# Клавиатуры для пакетного редактирования


def get_batch_upload_keyboard():
    """Клавиатура для загрузки фото"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Готово, ввести промпт", callback_data="batch_done_upload")
    builder.button(text="❌ Отмена", callback_data="cancel_batch")
    builder.adjust(1)
    return builder.as_markup()


def get_batch_confirmation_keyboard(job_id: str, cost: int):
    """Подтверждение пакетной генерации"""
    builder = InlineKeyboardBuilder()

    builder.button(text=f"▶️ Запустить за {cost}🍌", callback_data=f"batchrun_{job_id}")
    builder.button(text="🔙 Отмена", callback_data="cancel_batch")

    return builder.as_markup()


def get_batch_aspect_ratio_keyboard():
    """Клавиатура выбора соотношения сторон"""
    builder = InlineKeyboardBuilder()
    builder.button(text="1:1 Квадрат", callback_data="batch_aspect_1:1")
    builder.button(text="16:9 Широкий", callback_data="batch_aspect_16:9")
    builder.button(text="9:16 Вертикальный", callback_data="batch_aspect_9:16")
    builder.button(text="4:3 Классический", callback_data="batch_aspect_4:3")
    builder.button(text="3:4 Портрет", callback_data="batch_aspect_3:4")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_results_gallery_keyboard(job_id: str, count: int, has_failed: bool = False):
    """Навигация по результатам - только скачать и продолжить редактирование"""
    builder = InlineKeyboardBuilder()

    # Только скачать все и продолжить редактирование
    builder.button(text="📥 Скачать все", callback_data=f"batchdownload_{job_id}")
    builder.button(text="✏️ Продолжить редактирование", callback_data="menu_batch_edit")

    if has_failed:
        builder.button(
            text="🔄 Повторить неудачные", callback_data=f"batchretry_{job_id}"
        )

    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 1)

    return builder.as_markup()


def get_upscale_options_keyboard(job_id: str, item_index: int):
    """Опции апскейла"""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="📐 2K (5🍌)", callback_data=f"upscale_{job_id}_{item_index}_2K_5"
    )
    builder.button(
        text="🖼 4K (10🍌)", callback_data=f"upscale_{job_id}_{item_index}_4K_10"
    )
    builder.button(text="🔙 Назад к результатам", callback_data=f"batchback_{job_id}")

    return builder.as_markup()


# Хранилище для загружаемых фото (в памяти)
_batch_uploads: dict[int, list[bytes]] = {}
_batch_upload_urls: dict[int, list[str]] = {}


def _save_uploaded_file(file_bytes: bytes, file_ext: str = "png") -> Optional[str]:
    """Сохраняет загруженный файл в папку static/uploads и возвращает публичный URL."""
    try:
        import os
        import uuid
        from datetime import datetime

        from bot.config import config

        date_str = datetime.now().strftime("%Y%m%d")
        upload_dir = os.path.join("static", "uploads", date_str)
        os.makedirs(upload_dir, exist_ok=True)

        file_id = str(uuid.uuid4())[:8]
        filename = f"{file_id}.{file_ext}"
        filepath = os.path.join(upload_dir, filename)

        with open(filepath, "wb") as f:
            f.write(file_bytes)

        base_url = config.static_base_url
        public_url = f"{base_url}/uploads/{date_str}/{filename}"

        logger.info(f"Saved batch upload: {public_url}")
        return public_url

    except Exception as e:
        logger.exception(f"Error saving batch upload file: {e}")
        return None


# Обработчики


@router.callback_query(F.data == "menu_batch_edit")
async def show_batch_edit_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало редактирования по референсам - загрузка главного фото"""

    user_credits = await get_user_credits(callback.from_user.id)

    # Очищаем предыдущие загрузки пользователя
    _batch_uploads[callback.from_user.id] = []
    _batch_upload_urls[callback.from_user.id] = []

    # Сохраняем состояние: ожидаем главное фото
    await state.update_data(batch_mode="reference_edit", main_image=None, reference_images=[])

    text = (
        f"🎨 <b>Редактирование по референсам</b>\n\n"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n\n"
        f"<b>Как это работает:</b>\n"
        f"1. Загрузите <b>главное фото</b> для редактирования\n"
        f"2. Добавьте до <b>14 референсных изображений</b> (стиль, персонажи, объекты)\n"
        f"3. Введите промпт\n"
        f"4. Получите результат с учётом всех референсов!\n\n"
        f"<b>💡 Для сохранения лиц (важно!):</b>\n"
        f"• Первые <b>4 фото</b> — это референсы лиц/персонажей\n"
        f"• Загружайте чёткие фото лица крупным планом\n"
        f"• Остальные фото (5-14) — стиль, объекты, фон\n"
        f"• В промпте укажите: «Сохрани лицо как на референсе»\n\n"
        f"<b>Возможности:</b>\n"
        f"• До 10 объектов с высокой точностью\n"
        f"• До 4 персонажей для консистентности\n"
        f"• Перенос стиля, композиции, цветов\n\n"
        f"💰 Стоимость: <b>4🍌</b> (Pro модель, 4K, сохранение лиц)\n\n"
        f"<i>📸 Отправьте главное фото для редактирования:</i>"
    )

    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_batch_upload_keyboard(),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=get_batch_upload_keyboard(),
            parse_mode="HTML",
        )
    await state.set_state(GenerationStates.waiting_for_batch_image)


@router.message(GenerationStates.waiting_for_batch_image)
async def process_batch_image(message: types.Message, state: FSMContext):
    """Обрабатывает загрузку главного фото и референсов"""

    photo = message.photo[-1] if message.photo else None
    if not photo:
        await message.answer("❌ Пожалуйста, отправьте изображение.")
        return

    try:
        file = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()
    except Exception as e:
        logger.exception(f"Failed to download image: {e}")
        await message.answer("❌ Ошибка загрузки изображения. Попробуйте снова.")
        return

    user_id = message.from_user.id
    data = await state.get_data()
    main_image = data.get("main_image")
    ref_images = data.get("reference_images", [])

    # Если главное фото ещё не загружено — сохраняем как главное
    if not main_image:
        await state.update_data(main_image=image_data)

        await message.answer(
            f"✅ <b>Главное фото загружено!</b>\n\n"
            f"Теперь вы можете:\n"
            f"• Добавить до <b>14 референсных изображений</b> (стиль, персонажи, объекты)\n"
            f"• Или нажать «Готово» чтобы продолжить без референсов\n\n"
            f"📎 Референсов добавлено: <code>0/14</code>",
            reply_markup=get_batch_upload_keyboard(),
            parse_mode="HTML",
        )
    else:
        # Добавляем как референс
        if len(ref_images) >= 14:
            await message.answer(
                f"⚠️ <b>Достигнут лимит референсов (14)</b>\n\n"
                f"Нажмите «Готово» чтобы продолжить.",
                reply_markup=get_batch_upload_keyboard(),
                parse_mode="HTML",
            )
            return

        ref_images.append(image_data)
        await state.update_data(reference_images=ref_images)

        await message.answer(
            f"✅ <b>Референс добавлен!</b>\n"
            f"📎 Референсов: <code>{len(ref_images)}/14</code>\n\n"
            f"Можете загрузить ещё референсы или нажмите «Готово»",
            reply_markup=get_batch_upload_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "batch_done_upload")
async def batch_done_upload(callback: types.CallbackQuery, state: FSMContext):
    """Пользователь завершил загрузку фото и референсов"""

    data = await state.get_data()
    main_image = data.get("main_image")
    ref_images = data.get("reference_images", [])

    if not main_image:
        await callback.answer("Сначала загрузите главное фото для редактирования!", show_alert=True)
        return

    cost = 4  # Фиксированная стоимость за сессию с референсами

    # Переходим к вводу промпта
    await state.set_state(GenerationStates.waiting_for_batch_prompt)

    ref_count = len(ref_images)

    await callback.message.edit_text(
        f"✏️ <b>Введите промпт</b>\n\n"
        f"🎨 <b>Режим:</b> Редактирование по референсам\n"
        f"💰 Стоимость: <code>{cost}</code>🍌 (Pro модель, до 14 референсов)\n\n"
        f"📸 Главное фото: ✅ Загружено\n"
        f"📎 Референсов: <code>{ref_count}/14</code>\n\n"
        f"Опишите, <b>что нужно сделать</b> с главным фото:\n"
        f"• Перенеси стиль с референсов\n"
        f"• Добавь объектов/персонажей из референсов\n"
        f"• Измени фон/композицию\n"
        f"• Что-то другое\n\n"
        f"<i>Например: «Примени стиль как на референсах, добавь персонажа»</i>",
        parse_mode="HTML",
    )


@router.message(GenerationStates.waiting_for_batch_prompt)
async def process_batch_prompt(message: types.Message, state: FSMContext):
    """Обрабатывает введённый пользователем промпт"""

    user_prompt = message.text.strip()
    if not user_prompt:
        await message.answer("❌ Пожалуйста, введите описание того, что хотите сделать.")
        return

    user_id = message.from_user.id
    images = _batch_uploads.get(user_id, [])

    if not images:
        await message.answer("❌ Ошибка: фото не найдены. Начните заново.")
        await state.clear()
        return

    # Сохраняем промпт и переходим к выбору aspect ratio
    await state.update_data(batch_prompt=user_prompt)
    await state.set_state(GenerationStates.waiting_for_batch_aspect_ratio)

    await message.answer(
        f"✏️ <b>Выберите формат изображения</b>\n\n"
        f"📝 Промпт: <code>{user_prompt[:60]}{'...' if len(user_prompt) > 60 else ''}</code>\n\n"
        f"Выберите соотношение сторон:",
        reply_markup=get_batch_aspect_ratio_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("batch_aspect_"))
async def process_batch_aspect_ratio(callback: types.CallbackQuery, state: FSMContext):
    """Обрабатывает выбор aspect ratio для редактирования с референсами"""

    aspect_ratio = callback.data.replace("batch_aspect_", "")
    data = await state.get_data()
    user_prompt = data.get("batch_prompt", "")
    main_image = data.get("main_image")
    ref_images = data.get("reference_images", [])
    user_id = callback.from_user.id

    if not main_image or not user_prompt:
        await callback.answer(
            "Ошибка: данные не найдены. Начните заново.", show_alert=True
        )
        await state.clear()
        return

    cost = 4  # Фиксированная стоимость

    # Проверяем баланс
    is_admin = config.is_admin(user_id)
    user_credits = await get_user_credits(user_id)

    if not is_admin and user_credits < cost:
        await callback.message.edit_text(
            f"❌ <b>Недостаточно бананов!</b>\n\n"
            f"Требуется: <code>{cost}</code>🍌\n"
            f"Доступно: <code>{user_credits}</code>🍌\n\n"
            f"💳 Пополните баланс.",
            reply_markup=get_main_menu_keyboard(),
        )
        await state.clear()
        return

    # Сохраняем в состояние
    await state.update_data(batch_aspect_ratio=aspect_ratio, batch_cost=cost)

    ref_count = len(ref_images)

    await callback.message.edit_text(
        f"✏️ <b>Подтверждение редактирования по референсам</b>\n\n"
        f"📝 <b>Промпт:</b>\n<code>{user_prompt[:80]}{'...' if len(user_prompt) > 80 else ''}</code>\n\n"
        f"🎨 Режим: Редактирование с референсами\n"
        f"📸 Главное фото: ✅\n"
        f"📎 Референсов: <code>{ref_count}/14</code>\n"
        f"📐 Формат: <code>{aspect_ratio}</code>\n"
        f"🤖 Модель: <code>Gemini 3 Pro</code> (4K)\n"
        f"💰 Стоимость: <code>{cost}</code>🍌\n\n"
        f"<i>Нажмите кнопку ниже для запуска:</i>",
        reply_markup=get_batch_confirmation_keyboard("ref_edit", cost),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("batchrun_"))
async def execute_batch(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    """Запускает редактирование с референсами через Gemini Pro"""

    data = await state.get_data()
    cost = data.get("batch_cost", 4)
    user_id = callback.from_user.id
    main_image = data.get("main_image")
    ref_images = data.get("reference_images", [])
    user_prompt = data.get("batch_prompt", "")
    aspect_ratio = data.get("batch_aspect_ratio", "1:1")

    if not main_image:
        await callback.answer("Ошибка: главное фото не найдено", show_alert=True)
        return

    # Списываем кредиты
    success = await deduct_credits(user_id, cost)
    if not success:
        await callback.answer("Ошибка списания кредитов", show_alert=True)
        return

    await callback.answer("🚀 Запускаю редактирование с референсами...")

    # Сообщение с прогрессом
    progress_msg = await callback.message.answer(
        f"⏳ <b>Редактирование с референсами</b>\n\n"
        f"🤖 Модель: <code>Gemini 3 Pro</code>\n"
        f"📎 Референсов: <code>{len(ref_images)}</code>\n"
        f"📐 Формат: <code>{aspect_ratio}</code>\n"
        f"⏱ Это займёт 15-30 секунд...\n\n"
        f"<i>Используйте /cancel для отмены</i>",
        parse_mode="HTML",
    )

    try:
        from bot.services.gemini_service import gemini_service

        # Генерируем с учётом референсов
        result = await gemini_service.generate_image(
            prompt=user_prompt,
            model="gemini-3-pro-image-preview",
            aspect_ratio=aspect_ratio,
            image_input=main_image,
            reference_images=ref_images,
            resolution="4K",
            preserve_faces=True,  # Важно: сохраняем лица с референсов
        )

        # Удаляем сообщение прогресса
        try:
            await progress_msg.delete()
        except:
            pass

        if result:
            # Сохраняем результат
            from bot.handlers.generation import save_uploaded_file
            saved_url = save_uploaded_file(result, "png")

            # Отправляем результат
            await callback.message.answer_photo(
                photo=types.BufferedInputFile(result, "edited.png"),
                caption=(
                    f"✅ <b>Редактирование завершено!</b>\n\n"
                    f"🎨 Режим: Редактирование с референсами\n"
                    f"📎 Референсов использовано: <code>{len(ref_images)}</code>\n"
                    f"📐 Формат: <code>{aspect_ratio}</code>\n"
                    f"💰 Стоимость: <code>{cost}</code>🍌\n\n"
                    f"<i>Сохраните изображение, если нужно</i>"
                ),
                reply_markup=get_main_menu_keyboard(await get_user_credits(user_id)),
                parse_mode="HTML",
            )
        else:
            # Возвращаем кредиты при неудаче
            await add_credits(user_id, cost)
            await callback.message.answer(
                "❌ <b>Не удалось отредактировать изображение</b>\n"
                "Попробуйте другой промпт или референсы.\n"
                "Кредиты возвращены.",
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML",
            )

    except Exception as e:
        logger.exception(f"Reference editing failed: {e}")
        # Возвращаем кредиты при ошибке
        await add_credits(user_id, cost)
        await callback.message.answer(
            "❌ <b>Ошибка редактирования</b>\n"
            f"<code>{str(e)[:100]}</code>\n"
            "Кредиты возвращены.",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )


async def show_batch_results(
    callback: types.CallbackQuery, job, state: FSMContext, bot: Bot
):
    """Показывает результаты пакетного редактирования"""

    successful = [i for i in job.items if i.result]
    failed = [i for i in job.items if i.status == BatchStatus.FAILED]

    if not successful:
        # Полный возврат
        await add_credits(callback.from_user.id, job.total_cost)
        await callback.message.answer(
            "❌ <b>Все редактирования не удались</b>\n" "Кредиты полностью возвращены.",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    # Создаём превью-галерею
    gallery_bytes = await batch_service.create_gallery_preview(job)

    # Статистика
    duration = job.completed_at - job.created_at if job.completed_at else 0

    caption = (
        f"✅ <b>Пакетное редактирование завершено!</b>\n\n"
        f"📊 Успешно: <code>{len(successful)}/{len(job.items)}</code>\n"
        f"⏱ Время: <code>{duration:.1f}</code> сек\n"
        f"🍌 Стоимость: <code>{job.total_cost}</code>🍌\n\n"
        f"<i>Нажмите номер для просмотра в полном размере</i>"
    )

    if gallery_bytes:
        await callback.message.answer_photo(
            photo=types.BufferedInputFile(gallery_bytes, "gallery.jpg"),
            caption=caption,
            reply_markup=get_results_gallery_keyboard(
                job.id, len(successful), has_failed=len(failed) > 0
            ),
            parse_mode="HTML",
        )
    else:
        # Если превью не создалось, показываем списком
        await callback.message.answer(
            caption,
            reply_markup=get_results_gallery_keyboard(
                job.id, len(successful), has_failed=len(failed) > 0
            ),
            parse_mode="HTML",
        )

    await state.update_data(current_job_id=job.id)


@router.callback_query(F.data.startswith("batchview_"))
async def view_single_result(callback: types.CallbackQuery, state: FSMContext):
    """Показывает один результат в полном размере с публичным URL"""

    parts = callback.data.split("_")
    job_id = parts[1]
    item_index = int(parts[2])

    job = batch_service.get_job(job_id)
    if not job or item_index >= len(job.items):
        await callback.answer("Результат не найден")
        return

    item = job.items[item_index]
    if not item.result_url:
        await callback.answer("Этот вариант не был сгенерирован или URL недоступен")
        return

    # Показываем изображение с информацией
    info_text = (
        f"🖼 <b>Вариант {item.index + 1}</b>\n\n"
        f"⏱ Генерация: <code>{item.duration:.1f}</code> сек\n"
        f"📝 Промпт:\n<code>{item.prompt[:100]}...</code>"
    )

    # Клавиатура для этого изображения
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 Апскейл", callback_data=f"upscalemenu_{job_id}_{item_index}")
    builder.button(text="📥 Скачать", callback_data=f"download_{job_id}_{item_index}")
    builder.button(text="🔙 К галерее", callback_data=f"batchback_{job_id}")

    await callback.message.answer_photo(
        photo=item.result_url,
        caption=info_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("upscalemenu_"))
async def show_upscale_options(callback: types.CallbackQuery):
    """Показывает опции апскейла"""

    parts = callback.data.split("_")
    job_id = parts[1]
    item_index = int(parts[2])

    user_credits = await get_user_credits(callback.from_user.id)

    await callback.message.edit_caption(
        caption=f"🔍 <b>Апскейл варианта {item_index + 1}</b>\n\n"
        f"🍌 Доступно: <code>{user_credits}</code>🍌\n\n"
        f"Выберите качество:",
        reply_markup=get_upscale_options_keyboard(job_id, item_index),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("upscale_"))
async def execute_upscale(callback: types.CallbackQuery):
    """Выполняет апскейл выбранного изображения"""

    parts = callback.data.split("_")
    job_id = parts[1]
    item_index = int(parts[2])
    resolution = parts[3]
    cost = int(parts[4])

    # Проверяем возможность оплаты (админы могут бесплатно)
    if not await check_can_afford(callback.from_user.id, cost):
        await callback.answer(f"Нужно {cost} кредитов", show_alert=True)
        return

    # Списываем (админам - бесплатно)
    success = await deduct_credits(callback.from_user.id, cost)
    if not success:
        await callback.answer("Ошибка списания")
        return

    await callback.answer(f"🔍 Апскейл до {resolution}...")

    # Запускаем апскейл
    try:
        result = await batch_service.upscale_selected(job_id, item_index, resolution)

        if result:
            await callback.message.answer_photo(
                photo=types.BufferedInputFile(result, f"upscaled_{resolution}.png"),
                caption=f"✅ <b>Апскейл завершён!</b>\n\n"
                f"🖼 Разрешение: <code>{resolution}</code>\n"
                f"🍌 Стоимость: <code>{cost}</code>🍌",
                parse_mode="HTML",
            )
        else:
            await add_credits(callback.from_user.id, cost)
            await callback.message.answer("❌ Ошибка апскейла. Бананы возвращены.")

    except Exception as e:
        logger.exception(f"Upscale failed: {e}")
        await add_credits(callback.from_user.id, cost)
        await callback.message.answer("❌ Ошибка. Кредиты возвращены.")


@router.callback_query(F.data.startswith("batchdownload_"))
async def download_all_results(callback: types.CallbackQuery, bot: Bot):
    """Отправляет все результаты как альбом с публичными ссылками"""

    job_id = callback.data.replace("batchdownload_", "")
    job = batch_service.get_job(job_id)

    if not job:
        await callback.answer("Задача не найдена")
        return

    successful = [i for i in job.items if i.result_url]
    if not successful:
        await callback.answer("Нет результатов для скачивания")
        return

    # Формируем медиа-группу из публичных URL (максимум 10)
    media_group = []
    for i, item in enumerate(successful[:10]):
        media = types.InputMediaPhoto(
            media=item.result_url,
            caption=f"Вариант {i+1}" if i == 0 else None,
        )
        media_group.append(media)

    await callback.message.answer_media_group(media=media_group)
    await callback.answer("✅ Отправлено!")


@router.callback_query(F.data == "cancel_batch")
async def cancel_batch(callback: types.CallbackQuery, state: FSMContext):
    """Отмена пакетной генерации"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Пакетная генерация отменена.", reply_markup=get_main_menu_keyboard()
    )


@router.callback_query(F.data.startswith("batchback_"))
async def back_to_results(callback: types.CallbackQuery):
    """Возврат к галерее результатов"""
    job_id = callback.data.replace("batchback_", "")
    job = batch_service.get_job(job_id)

    if not job:
        await callback.answer("Задача не найдена")
        return

    successful = [i for i in job.items if i.result]

    await callback.message.edit_text(
        f"✅ <b>Результаты пакетной генерации</b>\n\n"
        f"📊 Вариантов: <code>{len(successful)}</code>\n"
        f"ID: <code>{job.id}</code>",
        reply_markup=get_results_gallery_keyboard(
            job.id,
            len(successful),
            has_failed=any(i.status == BatchStatus.FAILED for i in job.items),
        ),
        parse_mode="HTML",
    )
