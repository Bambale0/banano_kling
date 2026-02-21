import asyncio
import logging

from aiogram import Bot, F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.database import add_credits, check_can_afford, deduct_credits, get_user_credits
from bot.config import config
from bot.keyboards import get_main_menu_keyboard
from bot.services.batch_service import BatchStatus, batch_service
from bot.services.preset_manager import preset_manager

logger = logging.getLogger(__name__)
router = Router()


# Клавиатуры для пакетной генерации


def get_batch_modes_keyboard():
    """Выбор режима пакетной генерации"""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎨 Сетка 2×2 (4 варианта, −20%)", callback_data="batchmode_grid_2x2"
    )
    builder.button(
        text="⚡ Пакет ×6 (6 вариантов, −15%)", callback_data="batchmode_batch_6"
    )
    builder.button(
        text="🎭 3 стиля (3 вариации, −10%)", callback_data="batchmode_variations_3"
    )
    builder.button(text="🔙 Назад", callback_data="back_main")

    builder.adjust(1)
    return builder.as_markup()


def get_batch_confirmation_keyboard(job_id: str, cost: int):
    """Подтверждение пакетной генерации"""
    builder = InlineKeyboardBuilder()

    builder.button(
        text=f"▶️ Запустить за {cost}🍌", callback_data=f"batchrun_{job_id}"
    )
    builder.button(text="🔙 Отмена", callback_data="cancel_batch")

    return builder.as_markup()


def get_results_gallery_keyboard(job_id: str, count: int, has_failed: bool = False):
    """Навигация по результатам"""
    builder = InlineKeyboardBuilder()

    # Кнопки выбора изображения
    row = []
    for i in range(count):
        row.append(
            InlineKeyboardButton(
                text=str(i + 1), callback_data=f"batchview_{job_id}_{i}"
            )
        )
        if len(row) == 5:  # Максимум 5 в ряд
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)

    # Дополнительные действия
    builder.button(text="🔍 Апскейл выбранного", callback_data=f"batchupscale_{job_id}")
    builder.button(text="📥 Скачать все", callback_data=f"batchdownload_{job_id}")

    if has_failed:
        builder.button(
            text="🔄 Повторить неудачные", callback_data=f"batchretry_{job_id}"
        )

    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(5, 1, 1, 1)

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


# Обработчики


@router.callback_query(F.data == "menu_batch_pro")
async def show_batch_modes(callback: types.CallbackQuery, state: FSMContext):
    """Показывает режимы пакетной генерации"""

    user_credits = await get_user_credits(callback.from_user.id)

    await callback.message.edit_text(
        f"⚡ <b>Пакетная генерация PRO</b>\n\n"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n\n"
        f"<b>Доступные режимы:</b>\n\n"
        f"🎨 <b>Сетка 2×2</b> — 4 варианта в одном изображении\n"
        f"   Экономия: 20% | Стоимость: ~3.2× от базовой\n\n"
        f"⚡ <b>Пакет ×6</b> — 6 отдельных вариантов параллельно\n"
        f"   Экономия: 15% | Стоимость: ~5.1× от базовой\n\n"
        f"🎭 <b>3 стиля</b> — три стилистических варианта\n"
        f"   Экономия: 10% | Стоимость: ~2.7× от базовой\n\n"
        f"<i>Выберите режим для начала. Сначала выберите пресет в обычном меню генерации.</i>",
        reply_markup=get_batch_modes_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("batchmode_"))
async def configure_batch(callback: types.CallbackQuery, state: FSMContext):
    """Настройка пакетной генерации"""

    mode = callback.data.replace("batchmode_", "")
    data = await state.get_data()
    preset_id = data.get("preset_id")

    if not preset_id:
        await callback.answer(
            "Сначала выберите пресет в обычном режиме", show_alert=True
        )
        return

    preset = preset_manager.get_preset(preset_id)
    if not preset:
        await callback.answer("Пресет не найден", show_alert=True)
        return

    # Получаем или запрашиваем базовый промпт
    base_prompt = data.get("final_prompt") or preset.prompt

    # Создаём задачу
    job = await batch_service.create_batch_job(
        user_id=callback.from_user.id,
        mode=mode,
        preset_id=preset_id,
        base_prompt=base_prompt,
        custom_params=data.get("custom_params"),
    )

    if not job:
        await callback.message.edit_text(
            "❌ Ошибка создания задачи. Попробуйте позже.",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    # Проверяем баланс (админы могут бесплатно)
    is_admin = config.is_admin(callback.from_user.id)
    user_credits = await get_user_credits(callback.from_user.id)
    
    if not is_admin and user_credits < job.total_cost:
        await callback.message.edit_text(
            f"❌ <b>Недостаточно бананов!</b>\n\n"
            f"Требуется: <code>{job.total_cost}</code>🍌\n"
            f"Доступно: <code>{user_credits}</code>🍌\n\n"
            f"💳 Пополните баланс для пакетной генерации.",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    # Сохраняем в состояние
    await state.update_data(batch_job_id=job.id, batch_cost=job.total_cost)

    # Показываем подтверждение
    batch_config = batch_service._get_batch_config(mode)

    await callback.message.edit_text(
        f"⚡ <b>Подтверждение пакетной генерации</b>\n\n"
        f"🎯 Режим: <b>{batch_config['name']}</b>\n"
        f"📊 Количество: <code>{batch_config['count']}</code> вариантов\n"
        f"🤖 Модель: <code>{batch_config['gemini_model']}</code>\n"
        f"🍌 Стоимость: <code>{job.total_cost}</code>🍌 "
        f"(экономия {batch_config['discount_percent']}%)\n\n"
        f"📝 <b>Базовый промпт:</b>\n"
        f"<code>{base_prompt[:150]}...</code>\n\n"
        f"<i>Генерация займёт 30-120 секунд. Вы получите уведомление о прогрессе.</i>",
        reply_markup=get_batch_confirmation_keyboard(job.id, job.total_cost),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("batchrun_"))
async def execute_batch(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    """Запускает пакетную генерацию"""

    job_id = callback.data.replace("batchrun_", "")
    data = await state.get_data()
    cost = data.get("batch_cost", 0)

    # Списываем кредиты
    success = await deduct_credits(callback.from_user.id, cost)
    if not success:
        await callback.answer("Ошибка списания кредитов", show_alert=True)
        return

    job = batch_service.get_job(job_id)
    if not job:
        # Возвращаем кредиты
        await add_credits(callback.from_user.id, cost)
        await callback.message.edit_text(
            "❌ Задача не найдена. Кредиты возвращены.",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    await callback.answer("🚀 Запускаю пакетную генерацию...")

    # Сообщение с прогрессом
    progress_msg = await callback.message.answer(
        f"⏳ <b>Пакетная генерация запущена</b>\n\n"
        f"ID: <code>{job_id}</code>\n"
        f"Вариантов: <code>{len(job.items)}</code>\n"
        f"Прогресс: <code>0%</code>\n\n"
        f"<i>Обновление каждые 5 секунд...</i>",
        parse_mode="HTML",
    )

    # Callback для обновления прогресса
    last_update = [0]  # Для rate limiting

    async def update_progress(job):
        now = asyncio.get_event_loop().time()
        if now - last_update[0] < 5:  # Минимум 5 секунд между обновлениями
            return

        last_update[0] = now

        # Создаём визуальный прогресс-бар
        percent = job.progress_percent
        filled = percent // 10
        bar = "█" * filled + "░" * (10 - filled)

        try:
            await progress_msg.edit_text(
                f"⏳ <b>Пакетная генерация</b>\n\n"
                f"ID: <code>{job.id}</code>\n"
                f"Прогресс: <code>{percent}%</code> [{bar}]\n"
                f"Готово: <code>{sum(1 for i in job.items if i.status == BatchStatus.COMPLETED)}/{len(job.items)}</code>\n\n"
                f"<i>Пожалуйста, подождите...</i>",
                parse_mode="HTML",
            )
        except Exception:
            pass  # Игнорируем ошибки редактирования

    # Запускаем генерацию
    try:
        completed_job = await batch_service.execute_batch(job, update_progress)

        # Удаляем сообщение прогресса
        try:
            await progress_msg.delete()
        except:
            pass

        # Показываем результаты
        await show_batch_results(callback, completed_job, state, bot)

    except Exception as e:
        logger.exception(f"Batch execution failed: {e}")
        # Возвращаем кредиты при критической ошибке
        await add_credits(callback.from_user.id, cost)
        await callback.message.answer(
            "❌ <b>Ошибка пакетной генерации</b>\n"
            "Кредиты возвращены. Попробуйте позже.",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )


async def show_batch_results(
    callback: types.CallbackQuery, job, state: FSMContext, bot: Bot
):
    """Показывает результаты пакетной генерации"""

    successful = [i for i in job.items if i.result]
    failed = [i for i in job.items if i.status == BatchStatus.FAILED]

    if not successful:
        # Полный возврат
        await add_credits(callback.from_user.id, job.total_cost)
        await callback.message.answer(
            "❌ <b>Все генерации не удались</b>\n" "Кредиты полностью возвращены.",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    # Создаём превью-галерею
    gallery_bytes = await batch_service.create_gallery_preview(job)

    # Статистика
    duration = job.completed_at - job.created_at if job.completed_at else 0

    caption = (
        f"✅ <b>Пакетная генерация завершена!</b>\n\n"
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
    """Показывает один результат в полном размере"""

    parts = callback.data.split("_")
    job_id = parts[1]
    item_index = int(parts[2])

    job = batch_service.get_job(job_id)
    if not job or item_index >= len(job.items):
        await callback.answer("Результат не найден")
        return

    item = job.items[item_index]
    if not item.result:
        await callback.answer("Этот вариант не был сгенерирован")
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
        photo=types.BufferedInputFile(item.result, f"variant_{item.index}.png"),
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
    """Отправляет все результаты как альбом"""

    job_id = callback.data.replace("batchdownload_", "")
    job = batch_service.get_job(job_id)

    if not job:
        await callback.answer("Задача не найдена")
        return

    successful = [i for i in job.items if i.result]
    if not successful:
        await callback.answer("Нет результатов для скачивания")
        return

    # Формируем медиа-группу (максимум 10)
    media_group = []
    for i, item in enumerate(successful[:10]):
        media = types.InputMediaPhoto(
            media=types.BufferedInputFile(item.result, f"result_{i}.png"),
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
