import asyncio
import logging
from typing import Any as Message
from typing import List, Optional

from vkbottle import BotBlueprint as Blueprint

try:
    from vkbottle.filter import F
except Exception:
    pass  # F imported from vkbottle.filter


try:
    from vkbottle.types import Callback
except Exception:
    try:
        from vkbottle_types.codegen.objects import Callback
    except Exception:

        class Callback:
            pass


from bot.config import config
from bot.database import add_credits, check_can_afford, deduct_credits, get_user_credits
from bot.keyboards import get_main_menu_keyboard
from bot.services.batch_service import BatchStatus, batch_service
from bot.states import GenerationStates
from bot.vk_rules import PayloadEq, PayloadStartsWith

logger = logging.getLogger(__name__)
batch_bp = Blueprint("batch_generation")


# Клавиатуры для пакетного редактирования
from bot.keyboards import InlineKeyboardBuilder


def get_batch_upload_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готово, ввести промпт", payload="batch_done_upload")
    kb.button(text="❌ Отмена", payload="cancel_batch")
    kb.adjust(1)
    return kb.build()


def get_batch_confirmation_keyboard(job_id: str, cost: int):
    kb = InlineKeyboardBuilder()
    kb.button(text=f"▶️ Запустить за {cost}🍌", payload=f"batchrun_{job_id}")
    kb.button(text="🔙 Отмена", payload="cancel_batch")
    kb.adjust(1)
    return kb.build()


def get_batch_aspect_ratio_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="1:1 Квадрат", payload="batch_aspect_1:1")
    kb.button(text="16:9 Широкий", payload="batch_aspect_16:9")
    kb.button(text="9:16 Вертикальный", payload="batch_aspect_9:16")
    kb.button(text="4:3 Классический", payload="batch_aspect_4:3")
    kb.button(text="3:4 Портрет", payload="batch_aspect_3:4")
    kb.adjust(2, 2, 1)
    return kb.build()


def get_results_gallery_keyboard(job_id: str, count: int, has_failed: bool = False):
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Скачать все", payload=f"batchdownload_{job_id}")
    kb.button(text="✏️ Продолжить редактирование", payload="menu_batch_edit")
    if has_failed:
        kb.button(text="🔄 Повторить неудачные", payload=f"batchretry_{job_id}")
    kb.button(text="🏠 Главное меню", payload="back_main")
    kb.adjust(1, 1, 1)
    return kb.build()


def get_upscale_options_keyboard(job_id: str, item_index: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="📐 2K (5🍌)", payload=f"upscale_{job_id}_{item_index}_2K_5")
    kb.button(text="🖼 4K (10🍌)", payload=f"upscale_{job_id}_{item_index}_4K_10")
    kb.button(text="🔙 Назад к результатам", payload=f"batchback_{job_id}")
    kb.adjust(1)
    return kb.build()


# Хранилище для загружаемых фото (в памяти)
_batch_uploads: dict[int, list[bytes]] = {}
_batch_upload_urls: dict[int, list[str]] = {}


from bot.utils.file_utils import save_uploaded_file


@batch_bp.on.message(PayloadEq("menu_batch_edit"))
async def show_batch_edit_start(c: Callback, state):
    """Начало редактирования по референсам - сначала референсы"""

    user_credits = await get_user_credits(c.from_id)

    # Очищаем предыдущие загрузки пользователя
    _batch_uploads[c.from_id] = []
    _batch_upload_urls[c.from_id] = []

    # Сохраняем состояние: ожидаем референсы
    await state.update_data(
        batch_mode="reference_edit", main_image=None, reference_images=[]
    )

    text = (
        f"🎨 <b>Редактирование по референсам (image-to-image)</b>\n\n"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n\n"
        f"📎 <b>Отправьте одно или несколько фото-референсов для image-to-image.</b>\n\n"
        f"После загрузки нажмите '✅ Продолжить' или '⏭️ Пропустить'.\n\n"
        f"<b>Как это работает:</b>\n"
        f"1. Загрузите <b>референсные изображения</b> (стиль, персонажи, объекты)\n"
        f"2. Загрузите <b>главное фото</b> для редактирования\n"
        f"3. Введите промпт\n"
        f"4. Получите результат!\n\n"
        f"<b>💡 Для сохранения лиц:</b>\n"
        f"• До <b>4 фото лица</b> крупным планом\n"
        f"• Остальные — стиль/объекты\n"
        f"• В промпте: «Сохрани лицо как на референсе»\n\n"
        f"💰 Стоимость: <b>5🍌</b>"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Продолжить", payload="batch_done_refs")
    kb.button(text="⏭️ Пропустить", payload="batch_skip_refs")
    kb.button(text="❌ Отмена", payload="cancel_batch")
    kb.adjust(1)

    try:
        await c.message.edit_text(
            text,
            keyboard=kb.build(),
            parse_mode="HTML",
        )
    except Exception:
        await c.message.answer(
            text,
            keyboard=kb.build(),
            parse_mode="HTML",
        )
    await state.set_state(GenerationStates.waiting_for_refs)


@batch_bp.on.message(state=GenerationStates.waiting_for_refs)
async def process_refs(m: Message, state):
    """Обрабатывает загрузку референсов (несколько фото)"""

    data = await state.get_data()
    ref_images: List[str] = data.get("reference_images", [])
    added = 0
    max_refs = 14

    for att in m.attachments:
        if att.type == "photo":
            try:
                image_bytes = await download_media_bytes(att)
                from bot.utils.file_utils import save_uploaded_file

                url = save_uploaded_file(image_bytes, "jpg")
                if url and len(ref_images) < max_refs:
                    ref_images.append(url)
                    added += 1
            except Exception as e:
                logger.exception(f"Failed to download ref: {e}")

    await state.update_data(reference_images=ref_images)

    ref_count = len(ref_images)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Продолжить", payload="batch_done_refs")
    kb.button(text="⏭️ Пропустить", payload="batch_skip_refs")
    kb.button(text="❌ Отмена", payload="cancel_batch")
    kb.adjust(1)

    if added > 0:
        await m.answer(
            f"✅ <b>{added} референс(ов) добавлено!</b>\n"
            f"📎 Всего: <code>{ref_count}/{max_refs}</code>\n\n"
            f"Можете отправить ещё или продолжить.",
            keyboard=kb.build(),
            parse_mode="HTML",
        )
    else:
        await m.answer(
            f"⚠️ <b>Не удалось добавить референсы</b>\n\n"
            f"📎 Всего: <code>{ref_count}/{max_refs}</code>",
            keyboard=kb.build(),
            parse_mode="HTML",
        )


@batch_bp.on.message(state=GenerationStates.waiting_for_batch_image)
async def process_main_image(m: Message, state):
    """Обрабатывает главное фото"""

    if m.attachments and m.attachments[0].type == "photo":
        photo = m.attachments[0]
        try:
            image_bytes = await download_media_bytes(photo)
            await state.update_data(main_image=image_bytes)

            data = await state.get_data()
            ref_count = len(data.get("reference_images", []))

            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Готово, ввести промпт", payload="batch_done_upload")
            kb.button(text="❌ Отмена", payload="cancel_batch")
            kb.adjust(1)

            await m.answer(
                f"✅ <b>Главное фото загружено!</b>\n\n"
                f"📎 Референсов: <code>{ref_count}</code>\n\n"
                f"Нажмите «Готово» для ввода промпта.",
                keyboard=kb.build(),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.exception(f"Failed to download main image: {e}")
            await m.answer("❌ Ошибка загрузки изображения. Попробуйте снова.")
    else:
        await m.answer("❌ Пожалуйста, отправьте главное фото.")


@batch_bp.on.message(PayloadEq("batch_skip_refs"))
async def batch_skip_refs(c: Callback, state):
    """Пропускает референсы, переходит к главному фото"""
    await state.update_data(reference_images=[])
    text = (
        f"⏭️ <b>Референсы пропущены</b>\n\n"
        f"<i>📸 Теперь отправьте главное фото для редактирования:</i>"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готово", payload="batch_done_upload")
    kb.button(text="❌ Отмена", payload="cancel_batch")
    kb.adjust(1)
    await c.message.edit_text(text, keyboard=kb.build(), parse_mode="HTML")
    await state.set_state(GenerationStates.waiting_for_batch_image)


@batch_bp.on.message(PayloadEq("batch_done_refs"))
async def batch_done_refs(c: Callback, state):
    """Завершил референсы, переходит к главному фото"""
    data = await state.get_data()
    ref_count = len(data.get("reference_images", []))
    text = (
        f"✅ <b>Референсы готовы ({ref_count}/14)</b>\n\n"
        f"<i>📸 Отправьте главное фото для редактирования:</i>"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готово", payload="batch_done_upload")
    kb.button(text="❌ Отмена", payload="cancel_batch")
    kb.adjust(1)
    await c.message.edit_text(text, keyboard=kb.build(), parse_mode="HTML")
    await state.set_state(GenerationStates.waiting_for_batch_image)


@batch_bp.on.message(PayloadEq("batch_done_upload"))
async def batch_done_upload(c: Callback, state):
    """Пользователь завершил загрузку фото и референсов"""

    data = await state.get_data()
    main_image = data.get("main_image")
    ref_images = data.get("reference_images", [])

    if not main_image:
        try:
            await c.answer(
                "Сначала загрузите главное фото для редактирования!", show_alert=True
            )
        except:
            pass
        return

    cost = 5  # Фиксированная стоимость за сессию с референсами

    # Переходим к вводу промпта
    await state.set_state(GenerationStates.waiting_for_batch_prompt)

    ref_count = len(ref_images)

    await c.message.edit_text(
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


@batch_bp.on.message(state=GenerationStates.waiting_for_batch_prompt)
async def process_batch_prompt(m: Message, state):
    """Обрабатывает введённый пользователем промпт"""

    user_prompt = m.text.strip()
    if not user_prompt:
        await m.answer("❌ Пожалуйста, введите описание того, что хотите сделать.")
        return

    # Получаем изображения из состояния (FSM state), а не из глобального словаря
    data = await state.get_data()
    main_image = data.get("main_image")
    ref_images = data.get("reference_images", [])

    if not main_image:
        await m.answer("❌ Ошибка: фото не найдены. Начните заново.")
        await state.clear()
        return

    # Сохраняем промпт и переходим к выбору aspect ratio
    await state.update_data(batch_prompt=user_prompt)
    await state.set_state(GenerationStates.waiting_for_batch_aspect_ratio)

    await m.answer(
        f"✏️ <b>Выберите формат изображения</b>\n\n"
        f"📝 Промпт: <code>{user_prompt[:60]}{'...' if len(user_prompt) > 60 else ''}</code>\n\n"
        f"Выберите соотношение сторон:",
        keyboard=get_batch_aspect_ratio_keyboard(),
        parse_mode="HTML",
    )


@batch_bp.on.message(PayloadStartsWith("batch_aspect_"))
async def process_batch_aspect_ratio(c: Callback, state):
    """Обрабатывает выбор aspect ratio для редактирования с референсами"""

    aspect_ratio = c.payload.replace("batch_aspect_", "")
    data = await state.get_data()
    user_prompt = data.get("batch_prompt", "")
    main_image = data.get("main_image")
    ref_images = data.get("reference_images", [])
    user_id = c.from_id

    if not main_image or not user_prompt:
        try:
            await c.answer(
                "Ошибка: данные не найдены. Начните заново.", show_alert=True
            )
        except:
            pass
        await state.clear()
        return

    cost = 5  # Фиксированная стоимость

    # Проверяем баланс
    is_admin = config.is_admin(user_id)
    user_credits = await get_user_credits(user_id)

    if not is_admin and user_credits < cost:
        await c.message.edit_text(
            f"❌ <b>Недостаточно бананов!</b>\n\n"
            f"Требуется: <code>{cost}</code>🍌\n"
            f"Доступно: <code>{user_credits}</code>🍌\n\n"
            f"💳 Пополните баланс.",
            keyboard=get_main_menu_keyboard().build(),
        )
        await state.clear()
        return

    # Сохраняем в состояние
    await state.update_data(batch_aspect_ratio=aspect_ratio, batch_cost=cost)

    ref_count = len(ref_images)

    await c.message.edit_text(
        f"✏️ <b>Подтверждение редактирования по референсам</b>\n\n"
        f"📝 <b>Промпт:</b>\n<code>{user_prompt[:80]}{'...' if len(user_prompt) > 80 else ''}</code>\n\n"
        f"🎨 Режим: Редактирование с референсами\n"
        f"📸 Главное фото: ✅\n"
        f"📎 Референсов: <code>{ref_count}/14</code>\n"
        f"📐 Формат: <code>{aspect_ratio}</code>\n"
        f"🤖 Модель: <code>Gemini 3 Pro</code> (4K)\n"
        f"💰 Стоимость: <code>{cost}</code>🍌\n\n"
        f"<i>Нажмите кнопку ниже для запуска:</i>",
        keyboard=get_batch_confirmation_keyboard("ref_edit", cost),
        parse_mode="HTML",
    )


@batch_bp.on.message(PayloadStartsWith("batchrun_"))
async def execute_batch(c: Callback, state):
    """Запускает редактирование с референсами через Gemini Pro"""

    data = await state.get_data()
    cost = data.get("batch_cost", 5)
    user_id = c.from_id
    main_image = data.get("main_image")
    ref_images = data.get("reference_images", [])
    user_prompt = data.get("batch_prompt", "")
    aspect_ratio = data.get("batch_aspect_ratio", "1:1")

    if not main_image:
        try:
            await c.answer("Ошибка: главное фото не найдено", show_alert=True)
        except:
            pass
        return

    # Списываем кредиты
    success = await deduct_credits(user_id, cost)
    if not success:
        try:
            await c.answer("Ошибка списания кредитов", show_alert=True)
        except:
            pass
        return

    try:
        await c.answer("🚀 Запускаю редактирование с референсами...")
    except:
        pass

    # Сообщение с прогрессом
    progress_msg = await c.message.answer(
        f"⏳ <b>Редактирование с референсами</b>\n\n"
        f"🤖 Модель: <code>Nano Banana Pro</code>\n"
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
            model="google/nano-banana-pro",
            aspect_ratio=aspect_ratio,
            image_input=main_image,
            reference_images=ref_images,
            resolution="4K",
            preserve_faces=True,  # Важно: сохраняем лица с референсов
            user_id=user_id,
        )

        # Удаляем сообщение прогресса
        try:
            await progress_msg.delete()
        except:
            pass

        if result:
            await c.message.answer_photo(
                photo=result,
                message=(
                    f"✅ <b>Редактирование завершено!</b>\n\n"
                    f"🎨 Режим: Редактирование с референсами\n"
                    f"📎 Референсов использовано: <code>{len(ref_images)}</code>\n"
                    f"📐 Формат: <code>{aspect_ratio}</code>\n"
                    f"💰 Стоимость: <code>{cost}</code>🍌\n\n"
                    f"<i>Сохраните изображение, если нужно</i>"
                ),
                keyboard=get_main_menu_keyboard(
                    await get_user_credits(user_id)
                ).build(),
                parse_mode="HTML",
            )
        else:
            # Возвращаем кредиты при неудаче
            await add_credits(user_id, cost)
            await c.message.answer(
                "❌ <b>Не удалось отредактировать изображение</b>\n"
                "Попробуйте другой промпт или референсы.\n"
                "Кредиты возвращены.",
                keyboard=get_main_menu_keyboard().build(),
                parse_mode="HTML",
            )

    except Exception as e:
        logger.exception(f"Reference editing failed: {e}")
        # Возвращаем кредиты при ошибке
        await add_credits(user_id, cost)
        await c.message.answer(
            "❌ <b>Ошибка редактирования</b>\n"
            f"<code>{str(e)[:100]}</code>\n"
            "Кредиты возвращены.",
            keyboard=get_main_menu_keyboard().build(),
            parse_mode="HTML",
        )


async def show_batch_results(c: Callback, job, state, api):
    """Показывает результаты пакетного редактирования"""

    successful = [i for i in job.items if i.result]
    failed = [i for i in job.items if i.status == BatchStatus.FAILED]

    if not successful:
        # Полный возврат
        await add_credits(c.from_id, job.total_cost)
        await c.message.answer(
            "❌ <b>Все редактирования не удались</b>\n" "Кредиты полностью возвращены.",
            keyboard=get_main_menu_keyboard().build(),
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
        await c.message.answer_photo(
            photo=gallery_bytes,
            message=caption,
            keyboard=get_results_gallery_keyboard(
                job.id, len(successful), has_failed=len(failed) > 0
            ).build(),
            parse_mode="HTML",
        )
    else:
        # Если превью не создалось, показываем списком
        await c.message.answer(
            caption,
            keyboard=get_results_gallery_keyboard(
                job.id, len(successful), has_failed=len(failed) > 0
            ).build(),
            parse_mode="HTML",
        )

    await state.update_data(current_job_id=job.id)


@batch_bp.on.message(PayloadStartsWith("batchview_"))
async def view_single_result(c: Callback, state):
    """Показывает один результат в полном размере с публичным URL"""

    parts = c.payload.split("_")
    job_id = parts[1]
    item_index = int(parts[2])

    job = batch_service.get_job(job_id)
    if not job or item_index >= len(job.items):
        await c.answer("Результат не найден")
        return

    item = job.items[item_index]
    if not item.result_url:
        await c.answer("Этот вариант не был сгенерирован или URL недоступен")
        return

    # Показываем изображение с информацией
    info_text = (
        f"🖼 <b>Вариант {item.index + 1}</b>\n\n"
        f"⏱ Генерация: <code>{item.duration:.1f}</code> сек\n"
        f"📝 Промпт:\n<code>{item.prompt[:100]}...</code>"
    )

    # Клавиатура для этого изображения
    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 Апскейл", payload=f"upscalemenu_{job_id}_{item_index}")
    kb.button(text="📥 Скачать", payload=f"download_{job_id}_{item_index}")
    kb.button(text="🔙 К галерее", payload=f"batchback_{job_id}")

    await c.message.answer_photo(
        photo=item.result_url,
        message=info_text,
        keyboard=kb.build(),
        parse_mode="HTML",
    )


@batch_bp.on.message(PayloadStartsWith("upscalemenu_"))
async def show_upscale_options(c: Callback):
    """Показывает опции апскейла"""

    parts = c.payload.split("_")
    job_id = parts[1]
    item_index = int(parts[2])

    user_credits = await get_user_credits(c.from_id)

    await c.message.edit_caption(
        caption=f"🔍 <b>Апскейл варианта {item_index + 1}</b>\n\n"
        f"🍌 Доступно: <code>{user_credits}</code>🍌\n\n"
        f"Выберите качество:",
        keyboard=get_upscale_options_keyboard(job_id, item_index),
        parse_mode="HTML",
    )


@batch_bp.on.message(PayloadStartsWith("upscale_"))
async def execute_upscale(c: Callback):
    """Выполняет апскейл выбранного изображения"""

    parts = c.payload.split("_")
    job_id = parts[1]
    item_index = int(parts[2])
    resolution = parts[3]
    cost = int(parts[4])

    # Проверяем возможность оплаты (админы могут бесплатно)
    if not await check_can_afford(c.from_id, cost):
        await c.answer(f"Нужно {cost} кредитов", show_alert=True)
        return

    # Списываем (админам - бесплатно)
    success = await deduct_credits(c.from_id, cost)
    if not success:
        await c.answer("Ошибка списания")
        return

    try:
        await c.answer(f"🔍 Апскейл до {resolution}...")
    except:
        pass

    # Запускаем апскейл
    try:
        result = await batch_service.upscale_selected(job_id, item_index, resolution)

        if result:
            await c.message.answer_photo(
                photo=result,
                message=f"✅ <b>Апскейл завершён!</b>\n\n"
                f"🖼 Разрешение: <code>{resolution}</code>\n"
                f"🍌 Стоимость: <code>{cost}</code>🍌",
                parse_mode="HTML",
            )
        else:
            await add_credits(c.from_id, cost)
            await c.message.answer("❌ Ошибка апскейла. Бананы возвращены.")

    except Exception as e:
        logger.exception(f"Upscale failed: {e}")
        await add_credits(c.from_id, cost)
        await c.message.answer("❌ Ошибка. Кредиты возвращены.")


@batch_bp.on.message(PayloadStartsWith("batchdownload_"))
async def download_all_results(c: Callback):
    """Отправляет все результаты как альбом с публичными ссылками"""

    job_id = c.payload.replace("batchdownload_", "")
    job = batch_service.get_job(job_id)

    if not job:
        await c.answer("Задача не найдена")
        return

    successful = [i for i in job.items if i.result_url]
    if not successful:
        await c.answer("Нет результатов для скачивания")
        return

    # Формируем медиа-группу из публичных URL (максимум 10)
    media_group = []
    for i, item in enumerate(successful[:10]):
        media = {"photo": item.result_url}
        if i == 0:
            media["caption"] = f"Вариант {i+1}"
        media_group.append(media)

    # VK doesn't have media_group like Telegram, send sequentially
    for media in media_group:
        await c.message.answer_photo(
            photo=media["photo"], message=media.get("caption", "")
        )

    await c.answer("✅ Отправлено!")


@batch_bp.on.message(PayloadEq("cancel_batch"))
async def cancel_batch(c: Callback, state):
    """Отмена пакетной генерации"""
    await state.clear()
    await c.message.edit_text(
        "❌ Пакетная генерация отменена.", keyboard=get_main_menu_keyboard().build()
    )


@batch_bp.on.message(PayloadStartsWith("batchback_"))
async def back_to_results(c: Callback):
    """Возврат к галерее результатов"""
    job_id = c.payload.replace("batchback_", "")
    job = batch_service.get_job(job_id)

    if not job:
        await c.answer("Задача не найдена")
        return

    successful = [i for i in job.items if i.result]

    await c.message.edit_text(
        f"✅ <b>Результаты пакетной генерации</b>\n\n"
        f"📊 Вариантов: <code>{len(successful)}</code>\n"
        f"ID: <code>{job.id}</code>",
        keyboard=get_results_gallery_keyboard(
            job.id,
            len(successful),
            has_failed=any(i.status == BatchStatus.FAILED for i in job.items),
        ).build(),
        parse_mode="HTML",
    )


from bot.utils.media_utils import download_media_bytes
