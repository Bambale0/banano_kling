import asyncio
import base64
import html
import io
import json
import logging
import os
import random
import re
import time
import uuid
from datetime import datetime
from typing import Optional

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.database import (
    add_credits,
    add_credits_once,
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
from bot.image_models import (
    IMAGE_OPTION_LABELS,
    get_image_model_config,
    get_image_option_label,
    normalize_image_options,
    resolve_image_model,
)
from bot.keyboards import (
    get_back_keyboard,
    get_create_image_keyboard,
    get_create_video_keyboard,
    get_animate_photo_keyboard,
    get_image_result_keyboard,
    get_main_menu_keyboard,
    get_reference_images_upload_keyboard,
    get_reference_videos_upload_keyboard,
)
from bot.services.aleph_service import aleph_service
from bot.services.gemini_service import gemini_service
from bot.services.generation_guard import generation_lock_guard
from bot.services.storage_policy import choose_upload_category, public_upload_url, upload_path
from bot.services.gpt_image_service import gpt_image_service
from bot.services.grok_service import grok_service
from bot.services.hailuo_service import hailuo_service
from bot.services.happyhorse_service import happyhorse_service
from bot.services.ideogram_service import ideogram_service
from bot.services.nano_banana_2_service import nano_banana_2_service
from bot.services.nano_banana_pro_service import nano_banana_pro_service
from bot.services.preset_manager import preset_manager
from bot.services.seedream_service import seedream_lite_service as seedream_service
from bot.services.veo_service import veo_service
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
from bot.video_models import (
    VIDEO_OPTION_LABELS,
    get_video_model_config,
    get_video_option_label,
    normalize_video_options,
)

logger = logging.getLogger(__name__)
router = Router()

MIX_PHOTO_MODELS = ("banana_2", "seedream_edit", "grok_i2i")

ANIMATE_PHOTO_PROMPTS = {
    "smile": "The person gently smiles, subtle natural facial motion, soft cinematic camera movement, realistic motion, keep identity and photo style.",
    "blink": "The person naturally blinks once or twice, tiny head movement, realistic facial animation, keep identity and original photo style.",
    "zoom": "Slow smooth camera push-in toward the subject, cinematic depth, natural parallax, keep the subject still and recognizable.",
    "wind": "A light breeze moves the hair and clothes naturally, subtle cinematic camera movement, realistic motion, keep identity and original photo style.",
    "walk": "The subject starts walking forward naturally toward the camera, smooth body movement, realistic animation, keep identity and outfit.",
    "talk": "The person starts speaking naturally with subtle lips and facial movement, gentle head motion, realistic portrait animation.",
    "dance": "The subject makes a short stylish dance move, smooth body motion, upbeat cinematic energy, keep identity and original styling.",
}


def _get_default_animate_model(preferred_model: str | None) -> str:
    if preferred_model in _MODELS_IMGTXT:
        return preferred_model
    return "v3_std"


def _get_image_state(data: dict) -> tuple[str, dict, list]:
    current_service = resolve_image_model(data.get("img_service", "banana_pro"))
    reference_images = data.get("reference_images", [])
    current_options = normalize_image_options(
        current_service,
        {
            "aspect_ratio": data.get("img_ratio"),
            **data.get("img_options", {}),
        },
    )
    return current_service, current_options, reference_images


async def _sync_image_state(
    state: FSMContext,
    model_id: str | None = None,
    option_updates: dict | None = None,
) -> tuple[str, dict, list]:
    data = await state.get_data()
    current_service, current_options, reference_images = _get_image_state(data)

    if model_id:
        current_service = resolve_image_model(model_id)
        current_options = normalize_image_options(current_service, current_options)

    if option_updates:
        current_options = normalize_image_options(
            current_service, {**current_options, **option_updates}
        )

    await state.update_data(
        img_service=current_service,
        img_ratio=current_options["aspect_ratio"],
        img_options=current_options,
    )
    return current_service, current_options, reference_images


def _format_image_settings(model_id: str, options: dict) -> str:
    model_config = get_image_model_config(model_id)
    lines = []
    for option_name in model_config["options"]:
        label = IMAGE_OPTION_LABELS.get(option_name, option_name)
        value = get_image_option_label(option_name, options[option_name])
        lines.append(f"• {label}: <code>{value}</code>")
    return "\n".join(lines)


def _build_image_creation_text(
    model_id: str,
    options: dict,
    reference_images: list,
    img_count: int = 1,
) -> str:
    ref_text = (
        f"📎 Референсов: <code>{len(reference_images)}</code>\n"
        if reference_images
        else ""
    )
    model_config = get_image_model_config(model_id)
    unit_cost = preset_manager.get_generation_cost(model_config["cost_key"])
    total_cost = unit_cost * max(1, int(img_count or 1))
    cost_text = (
        f"💰 Стоимость: <code>{total_cost}</code>🍌 "
        f"(<code>{img_count}</code>×<code>{unit_cost}</code>🍌)\n"
        if img_count and img_count > 1
        else f"💰 Стоимость: <code>{unit_cost}</code>🍌\n"
    )
    return (
        "🖼 <b>Создание фото</b>\n"
        f"{ref_text}"
        f"🤖 Модель: <code>{model_config['label']}</code>\n"
        f"{cost_text}"
        "⚙️ <b>Параметры:</b>\n"
        f"{_format_image_settings(model_id, options)}\n"
        "\n<b>Введите промпт для генерации:</b>\n"
        "Опишите сцену, стиль и детали результата."
    )


def _build_mix_photo_prompt_text(ref_count: int) -> str:
    ref_line = (
        f"Загружено фото: <code>{ref_count}</code>\n\n" if ref_count else ""
    )
    return (
        "🧬 <b>Микс фото</b>\n\n"
        f"{ref_line}"
        "Один промпт уйдёт сразу в 3 нейросети: Banana 2, Seedream 4.5 и Grok.\n\n"
        "Напишите, какой результат нужен.\n"
        "Например: «сделай кинематографичный постер, реализм, мягкий свет»."
    )


def _build_image_waiting_text(*, mix_mode: bool, count: int) -> str:
    if mix_mode:
        return (
            "🧬 <b>Микс запущен</b>\n\n"
            "Отправляю запрос сразу в 3 нейросети.\n"
            "Сейчас каждая готовит свой вариант, результаты придут сюда по мере готовности.\n\n"
            "<i>Обычно это занимает 1-3 минуты.</i>"
        )
    if count > 1:
        return (
            "🖼 <b>Генерация запущена</b>\n\n"
            f"Запускаю <code>{count}</code> вариантов параллельно.\n"
            "Я на месте: как только модель отдаст результат, сразу пришлю его сюда.\n\n"
            "<i>Обычно это занимает 1-3 минуты.</i>"
        )
    return (
        "🖼 <b>Генерация запущена</b>\n\n"
        "Модель уже получила задачу и собирает картинку.\n"
        "Как только будет готово, пришлю результат сюда.\n\n"
        "<i>Обычно это занимает 1-3 минуты.</i>"
    )


def _build_image_task_started_text(
    *,
    prefix: str,
    model_label: str,
    task_id: str,
) -> str:
    return (
        f"🚀 {prefix}<b>{model_label}</b> приняла задачу\n\n"
        f"Код: <code>{html.escape(str(task_id))}</code>\n"
        "Работа идёт, результат придёт сюда автоматически.\n\n"
        "<i>Можно закрыть чат и вернуться позже.</i>"
    )


def _build_video_waiting_text(
    *,
    model: str,
    duration: int,
    ratio: str,
    cost: int,
) -> str:
    return (
        "🎬 <b>Видео запущено в работу</b>\n\n"
        f"🤖 Модель: <code>{html.escape(str(model))}</code>\n"
        f"⏱ Длительность: <code>{duration}s</code>\n"
        f"📐 Формат: <code>{html.escape(str(ratio))}</code>\n"
        f"💰 Стоимость: <code>{cost}</code>🍌\n\n"
        "Сейчас модель собирает кадры и движение. "
        "Результат придёт сюда автоматически.\n\n"
        "<i>Обычно это занимает 1-5 минут.</i>"
    )


def _build_video_task_started_text(
    *,
    task_id: str,
    model: str,
    duration: int,
    ratio: str,
    cost: int,
    is_admin: bool,
) -> str:
    price_text = "(админ бесплатно)" if is_admin else "списано"
    ratio_text = (
        "формат по стартовому фото" if model == "wan_27_i2v" else str(ratio)
    )
    return (
        "✅ <b>Видео задача принята</b>\n\n"
        f"Код: <code>{html.escape(str(task_id))}</code>\n"
        f"🎯 <code>{html.escape(str(model))}</code> | {duration}s | {html.escape(ratio_text)}\n"
        f"💰 <code>{cost}</code>🍌 {price_text}\n\n"
        "Работа идёт, результат появится в этом чате автоматически."
    )


def _progress_bar(percent: int) -> str:
    percent = max(0, min(100, percent))
    filled = max(1, round(percent / 10)) if percent else 0
    return "🟩" * filled + "⬜" * (10 - filled)


def _build_progress_text(
    *,
    title: str,
    percent: int,
    status: str,
    task_id: str | None = None,
    eta: str | None = None,
) -> str:
    code_line = f"\nКод: <code>{html.escape(str(task_id))}</code>" if task_id else ""
    eta_line = f"\n\n<i>{html.escape(eta)}</i>" if eta else ""
    return (
        f"{title}\n\n"
        f"{_progress_bar(percent)} <code>{percent}%</code>\n"
        f"{html.escape(status)}"
        f"{code_line}"
        f"{eta_line}"
    )


async def _simulate_generation_progress(
    message: types.Message,
    task_id: str,
    *,
    title: str,
    eta: str,
    steps: tuple[tuple[int, str], ...],
    interval: int = 12,
) -> None:
    for percent, status in steps:
        await asyncio.sleep(interval)
        try:
            task = await get_task_by_id(task_id)
            if task and task.status == "completed":
                final_status = (
                    "Готово. Отправляю результат в чат."
                    if task.result_url
                    else "Задача завершилась. Отправляю статус в чат."
                )
                await message.edit_text(
                    _build_progress_text(
                        title=title,
                        percent=100,
                        status=final_status,
                        task_id=task_id,
                    ),
                    parse_mode="HTML",
                )
                return

            await message.edit_text(
                _build_progress_text(
                    title=title,
                    percent=percent,
                    status=status,
                    task_id=task_id,
                    eta=eta,
                ),
                parse_mode="HTML",
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                continue
            return
        except Exception:
            logger.debug("Progress update failed for task %s", task_id, exc_info=True)
            return


_MODELS_TEXT = {
    "v3_std",
    "v3_pro",
    "runway",
    "veo3_fast",
    "veo3",
    "veo3_lite",
    "hailuo_pro",
    "hailuo_std",
    "happyhorse_t2v",
    "wan_27_t2v",
}
_MODELS_IMGTXT = {
    "v3_std",
    "v3_pro",
    "seedance2",
    "runway",
    "grok_imagine",
    "veo3_fast",  # only veo3_fast supports image reference; veo3/veo3_lite are text-only
    "hailuo_23_pro",
    "hailuo_23_std",
    "hailuo_i2v_pro",
    "hailuo_i2v_std",
    "happyhorse_i2v",
    "happyhorse_ref2v",
    "wan_27_i2v",
}
_MODELS_VIDEO = {
    "aleph",
    "glow",
    "happyhorse_edit",
}


def _clamp_model_for_type(model: str, v_type: str) -> str:
    if v_type == "text" and model not in _MODELS_TEXT:
        return "v3_std"
    if v_type == "imgtxt" and model not in _MODELS_IMGTXT:
        return "v3_std"
    if v_type == "video" and model not in _MODELS_VIDEO:
        return "aleph"
    return model


def _get_video_ui_state(data: dict) -> dict:
    model = data.get("v_model", "v3_std")
    return {
        "current_v_type": data.get("v_type", "text"),
        "current_model": model,
        "current_duration": data.get("v_duration", 5),
        "current_ratio": data.get("v_ratio", "16:9"),
        "current_mode": data.get("v_mode", "720p"),
        "current_orientation": data.get("v_orientation", "video"),
        "current_grok_mode": data.get("grok_mode", "normal"),
        "current_hailuo_resolution": data.get("hailuo_resolution", "768P"),
        "current_video_options": normalize_video_options(
            model, data.get("video_options", {})
        ),
    }


def _format_video_settings(data: dict) -> str:
    ui = _get_video_ui_state(data)
    type_text = {
        "text": "Текст → Видео",
        "imgtxt": "Фото + Текст → Видео",
        "video": "Видео + Текст → Видео",
    }.get(ui["current_v_type"], ui["current_v_type"])

    lines = [
        "⚙️ <b>Текущие настройки:</b>",
        f"• Тип: <code>{type_text}</code>",
        f"• Модель: <code>{ui['current_model']}</code>",
        f"• Длительность: <code>{ui['current_duration']} сек</code>",
    ]

    model_config = get_video_model_config(ui["current_model"])
    if model_config.get("aspect_ratios"):
        lines.append(f"• Формат: <code>{ui['current_ratio']}</code>")
    elif ui["current_model"] == "wan_27_i2v":
        lines.append("• Формат: <code>по стартовому фото</code>")

    for option_name in model_config.get("options", {}):
        value = ui["current_video_options"].get(option_name)
        label = VIDEO_OPTION_LABELS.get(option_name, option_name)
        lines.append(
            f"• {label}: <code>{get_video_option_label(option_name, value)}</code>"
        )

    return "\n".join(lines)


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
    user_credits = await get_user_credits(callback.from_user.id)

    # Инициализируем опции по умолчанию
    default_options = normalize_image_options("banana_pro")
    await state.update_data(
        generation_type="image",
        img_service="banana_pro",
        img_ratio=default_options["aspect_ratio"],
        img_options=default_options,
        reference_images=[],  # Инициализируем пустой список референсов
        preset_id="new",  # Для нового UX - указываем, что это "new" режим
    )

    # Показываем экран загрузки референсов (ШАГ 1)
    text = (
        "🖼 <b>Создание фото</b>\n\n"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n\n"
        "<b>Шаг 1: загрузка референсов</b>\n"
        "Это необязательно, но полезно для:\n"
        "• сходства с объектом\n"
        "• сохранения стиля\n"
        "• консистентных персонажей\n\n"
        "Можно загрузить до 14 изображений.\n"
        "После этого нажмите «Продолжить» или «Пропустить»."
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


@router.callback_query(F.data == "quick_animate_photo")
async def quick_animate_photo(callback: types.CallbackQuery, state: FSMContext):
    """Shortcut: photo to video via Grok Imagine."""
    default_options = normalize_video_options("grok_imagine")
    await state.update_data(
        generation_type="video",
        v_type="imgtxt",
        v_model="grok_imagine",
        v_duration=6,
        v_ratio="16:9",
        video_options=default_options,
        grok_mode="normal",
        reference_images=[],
        v_reference_videos=[],
        user_prompt="",
        v_image_url=None,
    )
    await callback.message.edit_text(
        "📸 <b>Оживить фото</b>\n\n"
        "Отправьте фото, которое нужно превратить в короткое видео.\n"
        "После фото напишите движение: например, «улыбается и медленно смотрит в камеру».",
        reply_markup=get_create_video_keyboard(
            current_v_type="imgtxt",
            current_model="grok_imagine",
            current_duration=6,
            current_ratio="16:9",
            current_video_options=default_options,
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data.startswith("animate_img_"))
async def open_animate_generated_photo(callback: types.CallbackQuery, state: FSMContext):
    """Open a separate animate-photo menu for a generated image result."""
    task_id = callback.data.replace("animate_img_", "", 1)
    task = await get_task_by_id(task_id)
    if not task or not task.result_url:
        await callback.answer("Не нашёл готовое фото для оживления", show_alert=True)
        return
    if task.telegram_id != callback.from_user.id:
        await callback.answer("Это фото из другой сессии", show_alert=True)
        return

    settings = await get_user_settings(callback.from_user.id)
    v_model = _get_default_animate_model(settings.get("preferred_i2v_model"))
    video_options = normalize_video_options(v_model)
    model_config = get_video_model_config(v_model)
    durations = model_config.get("durations") or [5]
    ratios = model_config.get("aspect_ratios") or ["16:9"]

    await state.update_data(
        generation_type="video",
        v_type="imgtxt",
        v_model=v_model,
        v_duration=5 if 5 in durations else durations[0],
        v_ratio="16:9" if "16:9" in ratios else ratios[0],
        video_options=video_options,
        reference_images=[],
        v_reference_videos=[],
        user_prompt="",
        v_image_url=task.result_url,
        animate_source_task_id=task_id,
    )

    await callback.message.answer(
        "📸 <b>Оживить фото</b>\n\n"
        "Выберите движение из меню или нажмите «Свой вариант» и напишите, как оживить фото.\n"
        "Фото уже сохранено как стартовый кадр для видео.",
        reply_markup=get_animate_photo_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data.startswith("animate_preset_"))
async def handle_animate_photo_preset(callback: types.CallbackQuery, state: FSMContext):
    """Run image-to-video from the saved generated photo and selected motion preset."""
    preset = callback.data.replace("animate_preset_", "", 1)
    data = await state.get_data()
    if not data.get("v_image_url"):
        await callback.answer("Сначала выберите готовое фото", show_alert=True)
        return

    if preset == "custom":
        await callback.message.answer(
            "🎬 Напишите одним сообщением, как именно оживить фото.\n"
            "Например: <code>улыбается, камера медленно приближается, ветер в волосах</code>",
            parse_mode="HTML",
        )
        await callback.answer()
        await state.set_state(GenerationStates.waiting_for_video_prompt)
        return

    prompt = ANIMATE_PHOTO_PROMPTS.get(preset)
    if not prompt:
        await callback.answer("Неизвестный вариант", show_alert=True)
        return

    await callback.answer("Запускаю оживление...")
    await run_no_preset_video_from_message(callback, state, prompt)


@router.callback_query(F.data == "animate_settings")
async def open_animate_photo_settings(callback: types.CallbackQuery, state: FSMContext):
    """Open the full video settings screen while keeping the generated photo reference."""
    data = await state.get_data()
    if not data.get("v_image_url"):
        await callback.answer("Сначала выберите готовое фото", show_alert=True)
        return
    await _show_video_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "quick_mix_photo")
async def quick_mix_photo(callback: types.CallbackQuery, state: FSMContext):
    """Shortcut: upload references and mix them into a new image."""
    data = await state.get_data()
    existing_refs = data.get("reference_images", [])
    options = normalize_image_options("banana_2")
    await state.update_data(
        generation_type="image",
        img_service="banana_2",
        img_ratio=options["aspect_ratio"],
        img_options=options,
        img_count=1,
        reference_images=existing_refs,
        mix_mode=True,
        preset_id="new",
    )

    if existing_refs:
        await callback.message.edit_text(
            _build_mix_photo_prompt_text(len(existing_refs)),
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
        await callback.answer()
        await state.set_state(GenerationStates.waiting_for_input)
        return

    await callback.message.edit_text(
        "🧬 <b>Микс фото</b>\n\n"
        "Загрузите хотя бы 1 фото-референс и нажмите «Продолжить».\n"
        "После промпта бот отправит один запрос в 3 нейросети: Banana 2, Seedream 4.5 и Grok.",
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
        "🎯 <b>Kling 2.6 Motion Control</b>\n\n"
        f"🍌 Баланс: <code>{user_credits}</code>\n\n"
        "<b>Шаг 1: Reference Image</b>\n"
        "Загрузите чёткое фото субъекта:\n"
        "• голова, плечи, торс\n"
        "• формат JPEG или PNG\n"
        "• размер до 10 MB\n\n"
        "<i>Это фото станет персонажем, который повторит движение из видео.</i>"
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
    user_credits = await get_user_credits(callback.from_user.id)
    default_options = normalize_image_options("banana_pro")

    await state.update_data(
        generation_type="image",
        img_service="banana_pro",
        img_ratio=default_options["aspect_ratio"],
        img_options=default_options,
    )

    await callback.message.edit_text(
        _build_image_creation_text("banana_pro", default_options, [], 1),
        reply_markup=get_create_image_keyboard(
            current_service="banana_pro",
            current_ratio=default_options["aspect_ratio"],
            num_refs=0,
            current_options=default_options,
        ),
        parse_mode="HTML",
    )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "img_ref_upload_new")
async def handle_img_ref_upload_new(callback: types.CallbackQuery, state: FSMContext):
    """Показывает меню загрузки референсных изображений для нового UX"""
    data = await state.get_data()
    # Показываем клавиатуру загрузки референсов
    await callback.message.edit_text(
        "📎 <b>Загрузка референсов</b>\n\n"
        "Загрузите до 14 изображений.\n"
        "После загрузки нажмите «Продолжить» или «Пропустить».",
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
    ui = _get_video_ui_state(data)
    current_v_type = ui["current_v_type"]
    current_model = ui["current_model"]
    current_duration = ui["current_duration"]
    current_ratio = ui["current_ratio"]
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
            media_status = f"✅ <b>{len(v_reference_videos)} реф. видео загружено!</b>\n"
        else:
            media_status = "📹 <b>Загрузите референсные видео (до 5)</b>\n"

    prompt_text = ""
    if user_prompt:
        prompt_text = (
            "\n📝 <b>Промпт:</b>\n"
            f"<code>{user_prompt[:100]}{'...' if len(user_prompt) > 100 else ''}</code>\n"
        )

    text = (
        "🎬 <b>Создание видео</b>\n\n"
        f"{ref_text}"
        f"{_format_video_settings(data)}\n"
        f"{media_status}"
        f"{prompt_text}"
        "\n<b>Введите промпт для генерации:</b>\n"
        "• что происходит в сцене\n"
        "• как движется камера\n"
        "• какой нужен стиль и настрой"
    )

    # Напоминание о загрузке медиа
    if current_v_type == "imgtxt" and not v_image_url:
        text += "\n\n<i>📷 Загрузите фото, которое станет первым кадром видео.</i>"
    elif current_v_type == "video" and not v_reference_videos:
        text += "\n\n<i>📹 Загрузите референсные видео: до 5 файлов, длительность 3-10 сек.</i>"
    elif current_v_type == "video" and current_model == "happyhorse_edit":
        text += "\n\n<i>🖼 Для HappyHorse Edit можно добавить фото-референсы через режим «Фото + Текст», затем вернуться к редактированию видео.</i>"

    keyboard = get_create_video_keyboard(
        current_v_type=current_v_type,
        current_model=current_model,
        current_duration=current_duration,
        current_ratio=current_ratio,
        current_mode=ui["current_mode"],
        current_orientation=ui["current_orientation"],
        current_grok_mode=ui["current_grok_mode"],
        current_hailuo_resolution=ui["current_hailuo_resolution"],
        current_video_options=ui["current_video_options"],
    )
    # Используем edit для callback, send для message
    try:
        await message_or_callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        target = (
            message_or_callback.message
            if hasattr(message_or_callback, "message")
            else message_or_callback
        )
        await target.answer(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        target = (
            message_or_callback.message
            if hasattr(message_or_callback, "message")
            else message_or_callback
        )
        await target.answer(text, reply_markup=keyboard, parse_mode="HTML")

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

    if data.get("mix_mode"):
        await callback.answer(
            "Для микса загрузите хотя бы 1 фото-референс.",
            show_alert=True,
        )
        return

    # Очищаем референсы
    await state.update_data(reference_images=[])

    if generation_type == "video":
        # Для видео - показываем параметры видео и промпт
        await _show_video_creation_screen(callback.message, state)
        await callback.answer()
    else:
        # Для фото - показываем параметры фото
        current_service, current_options, _ = await _sync_image_state(state)

        await callback.message.edit_text(
            _build_image_creation_text(
                current_service,
                current_options,
                [],
                data.get("img_count", 1),
            ),
            reply_markup=get_create_image_keyboard(
                current_service=current_service,
                current_ratio=current_options["aspect_ratio"],
                num_refs=0,
                current_options=current_options,
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

    if data.get("mix_mode"):
        current_refs = data.get("reference_images", [])
        if not current_refs:
            await callback.answer(
                "Для микса загрузите хотя бы 1 фото-референс.",
                show_alert=True,
            )
            return

        options = normalize_image_options(
            "banana_2",
            {"aspect_ratio": data.get("img_ratio"), **data.get("img_options", {})},
        )
        await state.update_data(
            generation_type="image",
            img_service="banana_2",
            img_ratio=options["aspect_ratio"],
            img_options=options,
            img_count=1,
        )
        await callback.message.edit_text(
            _build_mix_photo_prompt_text(len(current_refs)),
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
        await callback.answer()
        await state.set_state(GenerationStates.waiting_for_input)
        return

    if generation_type == "video":
        # Сразу показываем единый экран с параметрами и промптом (без подтверждения)
        await _show_video_creation_screen(callback.message, state)
        await callback.answer()
        return
    else:
        # Для фото - показываем параметры фото
        current_service, current_options, current_refs = await _sync_image_state(state)

        await callback.message.edit_text(
            _build_image_creation_text(
                current_service,
                current_options,
                current_refs,
                data.get("img_count", 1),
            ),
            reply_markup=get_create_image_keyboard(
                current_service=current_service,
                current_ratio=current_options["aspect_ratio"],
                num_refs=len(current_refs),
                current_options=current_options,
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
        "📎 <b>Перезагрузка референсов</b>\n\n"
        "Загружено: <code>0/14</code>\n"
        "Отправьте новые изображения для загрузки.",
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

    current_service, current_options, current_refs = await _sync_image_state(state)

    await callback.message.edit_text(
        _build_image_creation_text(
            current_service,
            current_options,
            current_refs,
            data.get("img_count", 1),
        ),
        reply_markup=get_create_image_keyboard(
            current_service=current_service,
            current_ratio=current_options["aspect_ratio"],
            num_refs=len(current_refs),
            current_options=current_options,
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


# Обработчики для меню создания видео
@router.callback_query(F.data == "v_type_text")
async def handle_v_type_text(callback: types.CallbackQuery, state: FSMContext):
    """Выбор типа генерации: текст"""
    data = await state.get_data()
    ui = _get_video_ui_state(data)
    clamped_model = _clamp_model_for_type(ui["current_model"], "text")
    await state.update_data(v_type="text", v_model=clamped_model)

    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type="text",
            current_model=clamped_model,
            current_duration=ui["current_duration"],
            current_ratio=ui["current_ratio"],
            current_mode=ui["current_mode"],
            current_orientation=ui["current_orientation"],
            current_grok_mode=ui["current_grok_mode"],
            current_hailuo_resolution=ui["current_hailuo_resolution"],
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "v_type_imgtxt")
async def handle_v_type_imgtxt(callback: types.CallbackQuery, state: FSMContext):
    """Выбор типа генерации: фото+текст - запрашиваем изображение на том же экране"""
    data = await state.get_data()
    ui = _get_video_ui_state(data)
    v_image_url = data.get("v_image_url")
    clamped_model = _clamp_model_for_type(ui["current_model"], "imgtxt")
    await state.update_data(v_type="imgtxt", v_model=clamped_model)

    # Показываем сообщение с просьбой загрузить изображение на ТОМ ЖЕ экране
    image_status = ""
    if v_image_url:
        image_status = "\n✅ <b>Изображение загружено!</b>\n"

    preview_data = {**data, "v_type": "imgtxt", "v_model": clamped_model}
    text = (
        "🎬 <b>Создание видео</b>\n\n"
        f"{_format_video_settings(preview_data)}\n"
        f"{image_status}\n"
        "<b>Загрузите стартовое изображение</b>\n"
        "Отправьте фото, которое станет первым кадром видео,\n"
        "а затем введите промпт для генерации.\n"
        "<i>Пример: птица летит в небе, волны накатывают на берег.</i>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_create_video_keyboard(
            current_v_type="imgtxt",
            current_model=clamped_model,
            current_duration=ui["current_duration"],
            current_ratio=ui["current_ratio"],
            current_mode=ui["current_mode"],
            current_orientation=ui["current_orientation"],
            current_grok_mode=ui["current_grok_mode"],
            current_hailuo_resolution=ui["current_hailuo_resolution"],
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

    data = await state.get_data()
    ui = _get_video_ui_state(data)
    clamped_model = _clamp_model_for_type(ui["current_model"], "video")
    await state.update_data(v_type="video", v_model=clamped_model)

    text = (
        "🎬 <b>Видео + Текст → Видео</b>\n\n"
        f"🍌 Баланс: <code>{user_credits}</code>\n\n"
        "<b>Шаг 1: загрузка видео-референсов</b>\n"
        + (
            "Для HappyHorse Edit нужно загрузить минимум одно видео.\n\n"
            if clamped_model == "happyhorse_edit"
            else "Это опционально, можно добавить до 5 коротких видео.\n\n"
        )
        + "Они помогут передать:\n"
        + "• стиль движения\n"
        + "• характер камеры\n"
        + "• атмосферу сцены\n\n"
        + "После загрузки нажмите «Продолжить» или «Пропустить»."
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
    data = await state.get_data()
    video_options = data.get("video_options", {})
    video_options["mode"] = mode
    await state.update_data(grok_mode=mode, video_options=video_options)
    await _show_video_creation_screen(callback, state)
    await callback.answer(f"Режим Grok: {mode.title()}")


@router.callback_query(F.data.startswith("hailuo_res_"))
async def handle_hailuo_resolution(callback: types.CallbackQuery, state: FSMContext):
    """Handler for Hailuo resolution selection (768P / 1080P)"""
    res_map = {"hailuo_res_768p": "768P", "hailuo_res_1080p": "1080P"}
    resolution = res_map.get(callback.data, "768P")
    data = await state.get_data()
    video_options = data.get("video_options", {})
    video_options["resolution"] = resolution
    await state.update_data(hailuo_resolution=resolution, video_options=video_options)
    await _show_video_creation_screen(callback, state)
    await callback.answer(f"Разрешение: {resolution}")


@router.callback_query(F.data.startswith("vopt_"))
async def handle_video_option(callback: types.CallbackQuery, state: FSMContext):
    """Generic video model option selection."""
    data = await state.get_data()
    model = data.get("v_model", "v3_std")
    config = get_video_model_config(model)
    raw_option = callback.data.replace("vopt_", "", 1)
    option_name = None
    raw_value = None
    for candidate in config.get("options", {}):
        prefix = f"{candidate}_"
        if raw_option.startswith(prefix):
            option_name = candidate
            raw_value = raw_option[len(prefix) :]
            break
    if not option_name:
        await callback.answer("Некорректная опция", show_alert=True)
        return
    allowed_values = config.get("options", {}).get(option_name)
    if not allowed_values:
        await callback.answer("Опция недоступна для этой модели", show_alert=True)
        return

    value = None
    for candidate in allowed_values:
        if str(candidate).lower() == raw_value:
            value = candidate
            break
    if value is None:
        await callback.answer("Некорректное значение", show_alert=True)
        return

    video_options = data.get("video_options", {})
    video_options[option_name] = value
    updates = {"video_options": normalize_video_options(model, video_options)}
    if option_name == "mode":
        updates["grok_mode"] = value
    if option_name == "resolution" and model.startswith("hailuo"):
        updates["hailuo_resolution"] = value
    if option_name == "motion_quality":
        updates["v_mode"] = value
    if option_name == "character_orientation":
        updates["v_orientation"] = value
    await state.update_data(**updates)
    await _show_video_creation_screen(callback, state)
    await callback.answer()


async def _apply_video_model_selection(
    callback: types.CallbackQuery, state: FSMContext, model: str
):
    """Apply video model selection across all keyboard variants."""
    data = await state.get_data()
    ui = _get_video_ui_state(data)
    current_v_type = ui["current_v_type"]
    current_duration = ui["current_duration"]
    current_ratio = ui["current_ratio"]

    # Set default grok_mode for grok_imagine
    if model == "grok_imagine":
        await state.update_data(grok_mode="normal")

    # WanX LoRA is text-to-video only, so we force the UI into text mode
    # to expose aspect ratio and duration controls immediately.
    if model.startswith("wanx"):
        current_v_type = "text"

    video_options = normalize_video_options(model, data.get("video_options", {}))
    model_config = get_video_model_config(model)
    durations = model_config.get("durations") or []
    ratios = model_config.get("aspect_ratios")
    if durations and current_duration not in durations:
        current_duration = durations[0]
    if ratios and current_ratio not in ratios:
        current_ratio = ratios[0]

    await state.update_data(
        v_model=model,
        v_type=current_v_type,
        v_duration=current_duration,
        v_ratio=current_ratio,
        video_options=video_options,
    )
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
                current_mode=ui["current_mode"],
                current_orientation=ui["current_orientation"],
                current_grok_mode=data.get("grok_mode", "normal"),
                current_hailuo_resolution=data.get("hailuo_resolution", "768P"),
            ),
            parse_mode="HTML",
        )
    else:
        await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data.startswith("vratio_"))
async def handle_dynamic_video_ratio(callback: types.CallbackQuery, state: FSMContext):
    ratio = callback.data.replace("vratio_", "", 1).replace("_", ":")
    await state.update_data(v_ratio=ratio)
    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data.startswith("vdur_"))
async def handle_dynamic_video_duration(
    callback: types.CallbackQuery, state: FSMContext
):
    duration = int(callback.data.replace("vdur_", "", 1))
    await state.update_data(v_duration=duration)
    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


# =============================================================================
# НОВЫЙ UX: МЕНЮ СОЗДАНИЯ ФОТО (get_create_image_keyboard)
# =============================================================================


async def _refresh_image_creation_screen(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    data = await state.get_data()
    img_count = data.get("img_count", 1)
    current_service, current_options, reference_images = await _sync_image_state(state)
    await callback.message.edit_text(
        _build_image_creation_text(
            current_service,
            current_options,
            reference_images,
            img_count,
        ),
        reply_markup=get_create_image_keyboard(
            current_service=current_service,
            current_ratio=current_options["aspect_ratio"],
            num_refs=len(reference_images),
            current_options=current_options,
            img_count=img_count,
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "img_count_info")
async def handle_img_count_info(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer(
        "Выберите количество одновременных генераций (1-6)", show_alert=False
    )


@router.callback_query(F.data.startswith("img_count_"))
async def handle_img_count(callback: types.CallbackQuery, state: FSMContext):
    """Устанавливает количество одновременных генераций"""
    try:
        count = int(callback.data.replace("img_count_", ""))
        if count < 1 or count > 6:
            await callback.answer("❌ Допустимо от 1 до 6", show_alert=True)
            return
    except ValueError:
        await callback.answer("❌ Неверное значение", show_alert=True)
        return
    await state.update_data(img_count=count)
    await _refresh_image_creation_screen(callback, state)
    await callback.answer(f"✅ Будет запущено {count} генераций")
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("img_model_"))
async def handle_dynamic_image_model(callback: types.CallbackQuery, state: FSMContext):
    model_id = callback.data.replace("img_model_", "", 1)
    await _sync_image_state(state, model_id=model_id)
    await _refresh_image_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("imgopt_"))
async def handle_dynamic_image_option(callback: types.CallbackQuery, state: FSMContext):
    payload = callback.data.replace("imgopt_", "", 1)
    prefix_map = {
        "aspect_ratio": "aspect_ratio_",
        "output_format": "output_format_",
        "resolution": "resolution_",
        "quality": "quality_",
        "nsfw_checker": "nsfw_checker_",
        "enable_pro": "enable_pro_",
        "rendering_speed": "rendering_speed_",
        "style": "style_",
        "expand_prompt": "expand_prompt_",
    }

    option_name = None
    raw_value = None
    for candidate, prefix in prefix_map.items():
        if payload.startswith(prefix):
            option_name = candidate
            raw_value = payload[len(prefix) :]
            break

    if option_name is None:
        await callback.answer("Неизвестная опция", show_alert=True)
        return

    if option_name in {"nsfw_checker", "expand_prompt", "enable_pro"}:
        value = raw_value == "on"
    elif option_name == "aspect_ratio":
        value = raw_value.replace("_", ":").upper().replace("AUTO", "auto")
    elif option_name == "output_format":
        value = raw_value.lower()
    elif option_name == "quality":
        value = raw_value.lower()
    elif option_name in {"rendering_speed", "style"}:
        value = raw_value.upper()
    else:
        value = raw_value.upper()

    await _sync_image_state(state, option_updates={option_name: value})
    await _refresh_image_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_nanobanana")
async def handle_model_nanobanana(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Nano Banana"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")
    reference_images = data.get("reference_images", [])
    ref_text = (
        f"📎 Референсов: <code>{len(reference_images)}</code>"
        if reference_images
        else ""
    )

    await state.update_data(img_service="nanobanana")

    text = (
        f"🖼 <b>Создание фото</b>"
        f"{ref_text}"
        f"✨ Модель: <code>nanobanana</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>"
        f"<b>Введите промпт для генерации:</b>"
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
        f"📎 Референсов: <code>{len(reference_images)}</code>"
        if reference_images
        else ""
    )

    await state.update_data(img_service="banana_pro")

    text = (
        f"🖼 <b>Создание фото</b>"
        f"{ref_text}"
        f"✨ Модель: <code>banana_pro</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>"
        f"<b>Введите промпт для генерации:</b>"
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
        f"📎 Референсов: <code>{len(reference_images)}</code>"
        if reference_images
        else ""
    )

    await state.update_data(img_service="seedream")

    text = (
        f"🖼 <b>Создание фото</b>"
        f"{ref_text}"
        f"✨ Модель: <code>seedream</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>"
        f"<b>Введите промпт для генерации:</b>"
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
        f"📎 Референсов: <code>{len(reference_images)}</code>"
        if reference_images
        else ""
    )

    await state.update_data(img_service="seedream_45")

    text = (
        f"🖼 <b>Создание фото</b>"
        f"{ref_text}"
        f"✨ Модель: <code>seedream_45</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>"
        f"<b>Введите промпт для генерации:</b>"
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
        f"📎 Референсов: <code>{len(reference_images)}</code>"
        if reference_images
        else ""
    )

    await state.update_data(img_service="z_image_turbo_lora")

    text = (
        f"🖼 <b>Создание фото</b>"
        f"{ref_text}"
        f"✨ Модель: <code>z_image_turbo_lora</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>"
        f"<b>Введите промпт для генерации:</b>"
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
    current_service = data.get("img_service", "banana_pro")

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
    current_service = data.get("img_service", "banana_pro")

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
    current_service = data.get("img_service", "banana_pro")

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
    current_service = data.get("img_service", "banana_pro")

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
    current_service = data.get("img_service", "banana_pro")

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


def save_uploaded_file(file_bytes: bytes, file_ext: str = "png", *, is_reference: bool = False, category: str | None = None) -> Optional[str]:
    """
    Сохраняет загруженный файл в папку static/uploads и возвращает публичный URL.
    """
    try:
        # Создаём поддиректорию по policy: uploads/<category>/<date>/file
        date_str = datetime.now().strftime("%Y%m%d")
        category = category or choose_upload_category(file_ext, is_reference=is_reference)

        # Генерируем уникальное имя файла
        file_id = str(uuid.uuid4())[:8]
        filename = f"{file_id}.{file_ext}"
        filepath = upload_path(os.path.join("static", "uploads"), category, date_str, filename)
        os.makedirs(filepath.parent, exist_ok=True)

        # Сохраняем файл
        with open(filepath, "wb") as f:
            f.write(file_bytes)

        # Формируем публичный URL
        # nginx настроен на /uploads/ -> static/uploads/
        base_url = config.static_base_url
        public_url = public_upload_url(base_url, category, date_str, filename)

        logger.info(f"Saved uploaded file: {public_url}")
        return public_url

    except Exception as e:
        logger.exception(f"Error saving uploaded file: {e}")
        return None


def _serialize_reference_images(reference_images: list) -> Optional[str]:
    refs = [str(url) for url in (reference_images or []) if url]
    return json.dumps(refs, ensure_ascii=False) if refs else None


def _deserialize_reference_images(raw_refs: Optional[str]) -> list:
    if not raw_refs:
        return []
    try:
        refs = json.loads(raw_refs)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(refs, list):
        return []
    return [str(url) for url in refs if url]


def _extract_reference_images_from_message(message: Optional[types.Message]) -> list:
    if not message:
        return []

    candidates = []
    try:
        candidates.append(message.html_text)
    except Exception:
        pass
    try:
        candidates.append(message.html_caption)
    except Exception:
        pass
    candidates.extend(
        [getattr(message, "caption", None), getattr(message, "text", None)]
    )

    for text in candidates:
        if not text or "Исходники" not in text:
            continue
        block = text.split("Исходники", 1)[1]
        block = block.split("🔗", 1)[0]
        refs = re.findall(r"<a\s+href=['\"]([^'\"]+)['\"]", block)
        if not refs:
            refs = re.findall(r"https?://[^\s<>'\"]+", block)
        if refs:
            return refs[:14]
    return []


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
    image_service = resolve_image_model(settings.get("image_service", "banana_pro"))
    image_options = normalize_image_options(image_service)

    # Инициализируем опции
    await state.set_state(GenerationStates.waiting_for_image)
    await state.update_data(
        generation_type="image",
        image_service=image_service,
        reference_images=[],
        generation_options={
            "model": image_service,
            "aspect_ratio": image_options["aspect_ratio"],
            "quality": "pro",
        },
        img_service=image_service,
        img_ratio=image_options["aspect_ratio"],
        img_options=image_options,
    )

    model_config = get_image_model_config(image_service)
    model_name = model_config["label"]
    model_cost = str(preset_manager.get_generation_cost(model_config["cost_key"]))

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
        f"✂️ <b>Видео-эффекты</b>"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: {model_name} ({model_cost}🍌)"
        f"<b>Kling 3 Omni</b>\n"
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
        f"🖼 <b>Фото в видео</b>"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n"
        f"🤖 Модель: {model_name} ({model_cost}🍌)"
        f"<b>Kling 3 - Image to Video</b>\n"
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
        f"<b>Kling 3 Omni</b>\n"
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
            data = await state.get_data()
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
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
                current_service = data.get("img_service", "banana_pro")
                current_ratio = data.get("img_ratio", "1:1")
                await callback.message.edit_text(
                    f"✨ <b>Создание фото</b>"
                    f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                    f"✨ Модель: <code>{current_service}</code>\n"
                    f"📐 Формат: <code>{current_ratio}</code>"
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
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
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

    # Если требуется загрузка файла
    if preset.requires_upload:
        await state.set_state(GenerationStates.waiting_for_image)

        hint = UserHints.get_hint_for_stage("input")
        await callback.message.edit_text(
            (
                "📎 <b>Загрузите изображение</b>\n\n"
                f"Пресет: <b>{preset.name}</b>\n"
                f"После загрузки изображения {preset.input_prompt or 'введите описание'}\n\n"
                f"<i>{hint}</i>"
            ),
            reply_markup=get_back_keyboard(f"preset_{preset_id}"),
            parse_mode="HTML",
        )
    else:
        await state.set_state(GenerationStates.waiting_for_input)

        hint = UserHints.get_hint_for_stage("input")
        await callback.message.edit_text(
            (
                "✏️ <b>Введите ваш вариант</b>\n\n"
                f"{preset.input_prompt or 'Опишите, что хотите создать'}\n\n"
                "Примеры для вдохновения:\n"
                "• Стиль: минимализм, винтаж, футуризм\n"
                "• Цветовая схема: яркий, пастельный, тёмный\n"
                "• Эмоция: радостное, удивлённое, задумчивое\n\n"
                f"<i>{hint}</i>"
            ),
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
        (
            "▶️ <b>Подтвердите генерацию</b>\n\n"
            f"Пресет: <b>{preset.name}</b>\n"
            f"Стоимость: <code>{preset.cost}</code>🍌\n\n"
            "<b>Промпт:</b>\n"
            f"<code>{final_prompt[:300]}{'...' if len(final_prompt) > 300 else ''}</code>"
            f"{format_generation_options(generation_options)}"
        ),
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
    v_model = data.get("v_model")
    if v_type == "video" and v_model == "happyhorse_edit":
        reference_images = data.get("reference_images", [])
        if len(reference_images) >= 5:
            await message.answer(
                "❌ Для HappyHorse Edit можно добавить до 5 фото-референсов. Введите промпт."
            )
            return
    elif v_type != "imgtxt":
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

    image_url = save_uploaded_file(image_data, "png", is_reference=True)
    if not image_url:
        await message.answer("❌ Не удалось сохранить фото.")
        return

    v_image_url = data.get("v_image_url")
    reference_images = data.get("reference_images", [])

    if v_type == "video" and v_model == "happyhorse_edit":
        reference_images.append(image_url)
        await state.update_data(reference_images=reference_images)
        await message.answer(
            f"✅ Фото-референс для HappyHorse Edit добавлен: <code>{len(reference_images)}/5</code>\n\n"
            "Отправьте ещё фото или введите промпт.",
            reply_markup=get_create_video_keyboard(
                current_v_type="video",
                current_model="happyhorse_edit",
                current_duration=data.get("v_duration", 5),
                current_ratio=data.get("v_ratio", "16:9"),
            ),
            parse_mode="HTML",
        )
        return

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
        video_url = save_uploaded_file(video_data, "mp4", is_reference=True)
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
    max_refs = 14 if data.get("mix_mode") else 9 if v_type == "imgtxt" else 14

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

    # Validate image size (minimum 300x300)
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
    image_url = save_uploaded_file(image_data, file_ext, is_reference=True)

    if image_url:
        reference_images.append(image_url)
        await state.update_data(reference_images=reference_images)

        preset_id = data.get("preset_id", "new")
        current_count = len(reference_images)

        title = (
            "🧬 <b>Фото для микса</b>"
            if data.get("mix_mode")
            else "📎 <b>Загрузка референсов</b>"
        )
        text = (
            f"{title}\n\n"
            f"Загружено: <code>{current_count}/{max_refs}</code>\n"
            "✅ Фото добавлено!\n\n"
            "Отправьте следующее или нажмите кнопку ниже:"
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

    if data.get("mix_mode"):
        reference_images = data.get("reference_images", [])
        if not reference_images:
            await message.answer(
                "🧬 Для микса загрузите хотя бы 1 фото-референс и нажмите «Продолжить».",
                reply_markup=get_reference_images_upload_keyboard(
                    0, 14, data.get("preset_id", "new")
                ),
                parse_mode="HTML",
            )
            await state.set_state(GenerationStates.uploading_reference_images)
            return

        mix_options = normalize_image_options(
            "banana_2",
            {"aspect_ratio": data.get("img_ratio"), **data.get("img_options", {})},
        )
        await state.update_data(
            img_service="banana_2",
            img_ratio=mix_options["aspect_ratio"],
            img_options=mix_options,
            img_count=1,
        )
        data = {
            **data,
            "img_service": "banana_2",
            "img_options": mix_options,
            "img_count": 1,
        }

    img_service, img_options, reference_images = _get_image_state(data)
    mix_mode = bool(data.get("mix_mode"))

    if mix_mode:
        generation_jobs = []
        for model_id in MIX_PHOTO_MODELS:
            model_options = normalize_image_options(
                model_id,
                {
                    "aspect_ratio": img_options.get("aspect_ratio"),
                    **data.get("img_options", {}),
                },
            )
            generation_jobs.append(
                {
                    "model": model_id,
                    "options": model_options,
                    "cost": preset_manager.get_generation_cost(model_id),
                }
            )
    else:
        img_count = data.get("img_count", 1)
        cost = preset_manager.get_generation_cost(img_service)
        generation_jobs = [
            {"model": img_service, "options": img_options, "cost": cost}
            for _ in range(img_count)
        ]

    user = await get_or_create_user(message.from_user.id)
    total_cost = sum(job["cost"] for job in generation_jobs)
    img_count = len(generation_jobs)

    if user.credits < total_cost:
        if mix_mode:
            models_text = ", ".join(
                get_image_model_config(job["model"])["label"] for job in generation_jobs
            )
            cost_text = f"Нужно: <code>{total_cost}</code>🍌 за 3 нейросети ({models_text})"
        else:
            cost = generation_jobs[0]["cost"]
            cost_text = f"Нужно: <code>{total_cost}</code>🍌 ({img_count}×{cost}🍌)"
        await message.answer(
            f"❌ Недостаточно бананов! {cost_text}",
            reply_markup=get_main_menu_keyboard(user.credits),
            parse_mode="HTML",
        )
        return

    generation_lock = await generation_lock_guard.acquire(message.from_user.id)
    if not generation_lock:
        await message.answer("⏳ Предыдущая генерация ещё запускается. Подождите несколько секунд и попробуйте снова.")
        return

    processing_msg = None
    try:
        charged = await deduct_credits(
            message.from_user.id,
            total_cost,
            reason="image_generation_charge",
            external_id=f"image_submit:{message.from_user.id}:{message.message_id}",
            metadata={
                "model": "mix_photo" if mix_mode else img_service,
                "models": [job["model"] for job in generation_jobs],
                "count": img_count,
            },
        )
        if not charged:
            await generation_lock_guard.release(generation_lock)
            await state.clear()
            await message.answer("❌ Не удалось списать бананы. Генерация не запущена.")
            return

        if mix_mode:
            processing_msg = await message.answer(
                _build_progress_text(
                    title="🧬 <b>Микс фото запускается</b>",
                    percent=8,
                    status="Готовлю референсы и отправляю запросы в 3 нейросети.",
                    eta="Сейчас появятся отдельные прогресс-бары по каждой модели.",
                ),
                parse_mode="HTML",
            )
        elif img_count == 1:
            processing_msg = await message.answer(
                _build_progress_text(
                    title="🖼 <b>Фото запускается</b>",
                    percent=10,
                    status="Проверяю параметры и передаю задачу модели.",
                    eta="Обычно это занимает 1-3 минуты.",
                ),
                parse_mode="HTML",
            )
        else:
            processing_msg = await message.answer(
                _build_progress_text(
                    title="🖼 <b>Параллельная генерация запускается</b>",
                    percent=8,
                    status=f"Готовлю {img_count} вариантов и отправляю их моделям.",
                    eta="Сейчас появятся отдельные прогресс-бары по задачам.",
                ),
                parse_mode="HTML",
            )
    except Exception:
        logger.exception("Image generation setup failed")
        if not config.is_admin(message.from_user.id):
            await add_credits_once(
                message.from_user.id,
                total_cost,
                reason="generation_refund",
                external_id=f"image_setup:{message.from_user.id}:{message.message_id}",
                metadata={"handler": "image_setup"},
            )
        await generation_lock_guard.release(generation_lock)
        await state.clear()
        await message.answer("❌ Ошибка запуска генерации. Бананы возвращены.")
        return

    async def _run_single(idx: int, job: dict) -> None:
        job_model = job["model"]
        job_options = job["options"]
        job_cost = job["cost"]
        local_tid = f"img_{uuid.uuid4().hex[:12]}"
        await add_generation_task(
            user.id,
            message.from_user.id,
            local_tid,
            "image",
            job_model,
            model=job_model,
            aspect_ratio=job_options["aspect_ratio"],
            prompt=prompt,
            cost=job_cost,
            reference_images=_serialize_reference_images(reference_images),
        )
        try:
            callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None
            if job_model == "banana_2":
                result = await nano_banana_2_service.generate_image(
                    prompt=prompt,
                    aspect_ratio=job_options["aspect_ratio"],
                    resolution=job_options["resolution"],
                    output_format=job_options["output_format"],
                    image_input=reference_images,
                    callback_url=callback_url,
                )
            elif job_model == "banana_pro":
                result = await nano_banana_pro_service.generate_image(
                    prompt=prompt,
                    aspect_ratio=job_options["aspect_ratio"],
                    resolution=job_options["resolution"],
                    output_format=job_options["output_format"],
                    image_input=reference_images,
                    callback_url=callback_url,
                )
            elif job_model in ["seedream_edit", "seedream_5_lite"]:
                model_config = get_image_model_config(job_model)
                result = await seedream_service.generate_image(
                    prompt=prompt,
                    model=model_config["api_model"],
                    aspect_ratio=job_options["aspect_ratio"],
                    quality=job_options.get("quality", "basic"),
                    nsfw_checker=job_options.get("nsfw_checker", False),
                    image_urls=reference_images,
                    callback_url=callback_url,
                )
            elif job_model == "gpt_image_2":
                result = await gpt_image_service.generate_image(
                    prompt=prompt,
                    image_urls=reference_images,
                    aspect_ratio=job_options["aspect_ratio"],
                    nsfw_checker=job_options.get("nsfw_checker", False),
                    callback_url=callback_url,
                )
            elif job_model == "grok_t2i":
                result = await grok_service.generate_text_to_image(
                    prompt=prompt,
                    aspect_ratio=job_options["aspect_ratio"],
                    enable_pro=job_options.get("enable_pro", False),
                    nsfw_checker=job_options.get("nsfw_checker", False),
                    callback_url=callback_url,
                )
            elif job_model == "grok_i2i":
                if reference_images:
                    result = await grok_service.generate_image_to_image(
                        image_url=reference_images[0],
                        prompt=prompt,
                        nsfw_checker=job_options.get("nsfw_checker", False),
                        callback_url=callback_url,
                    )
                else:
                    result = await grok_service.generate_text_to_image(
                        prompt=prompt,
                        aspect_ratio=job_options["aspect_ratio"],
                        nsfw_checker=job_options.get("nsfw_checker", False),
                        callback_url=callback_url,
                    )
            elif job_model == "ideogram_character":
                if not reference_images:
                    result = None
                else:
                    result = await ideogram_service.generate_character(
                        prompt=prompt,
                        reference_image_urls=reference_images,
                        aspect_ratio=job_options["aspect_ratio"],
                        rendering_speed=job_options.get(
                            "rendering_speed", "BALANCED"
                        ),
                        style=job_options.get("style", "AUTO"),
                        expand_prompt=job_options.get("expand_prompt", True),
                        num_images=job_options.get("num_images", "1"),
                        nsfw_checker=job_options.get("nsfw_checker", False),
                        callback_url=callback_url,
                    )
            else:
                result = await nano_banana_pro_service.generate_image(
                    prompt=prompt,
                    aspect_ratio=job_options["aspect_ratio"],
                    image_input=reference_images,
                    callback_url=callback_url,
                )

            model_label = get_image_model_config(job_model)["label"]
            prefix = f"[{idx}/{img_count}] " if img_count > 1 else ""

            if isinstance(result, dict) and "task_id" in result:
                api_task_id = result["task_id"]
                import aiosqlite

                from bot.database import DATABASE_PATH

                async with aiosqlite.connect(DATABASE_PATH) as db:
                    await db.execute(
                        "UPDATE generation_tasks SET task_id = ? WHERE task_id = ? AND user_id = ?",
                        (api_task_id, local_tid, user.id),
                    )
                    await db.commit()
                progress_msg = await message.answer(
                    _build_progress_text(
                        title=f"🚀 <b>{html.escape(prefix + model_label)}</b>",
                        percent=20,
                        status="Модель приняла задачу. Работа идёт.",
                        task_id=api_task_id,
                        eta="Результат придёт сюда автоматически.",
                    ),
                    parse_mode="HTML",
                )
                asyncio.create_task(
                    _simulate_generation_progress(
                        progress_msg,
                        api_task_id,
                        title=f"🚀 <b>{html.escape(prefix + model_label)}</b>",
                        eta="Результат придёт сюда автоматически.",
                        steps=(
                            (35, "Модель разбирает промпт и референсы."),
                            (55, "Собирает композицию и детали."),
                            (75, "Доводит изображение до финального вида."),
                            (90, "Почти готово, ждём файл от сервиса."),
                        ),
                        interval=12,
                    )
                )
            elif result:
                saved_url = save_uploaded_file(result, "png")
                retry_kb = get_image_result_keyboard(local_tid, saved_url)
                await message.answer_photo(
                    photo=types.BufferedInputFile(result, filename="generated.png"),
                    caption=f"✅ {prefix}{model_label}: готово!\n💰 <code>{job_cost}</code>🍌",
                    parse_mode="HTML",
                    reply_markup=retry_kb,
                )
                await _send_original_document(
                    message.answer_document, result, saved_url
                )
                await complete_video_task(local_tid, saved_url)
            else:
                if not config.is_admin(message.from_user.id):
                    await add_credits_once(message.from_user.id, job_cost, reason="generation_refund", external_id=local_tid)
                await complete_video_task(local_tid, None)
                await message.answer(f"❌ {prefix}{model_label}: ошибка генерации. Бананы возвращены.")

        except Exception as e:
            logger.exception(f"Image generation error (idx={idx}): {e}")
            if not config.is_admin(message.from_user.id):
                await add_credits_once(message.from_user.id, job_cost, reason="generation_refund", external_id=local_tid)
            await complete_video_task(local_tid, None)
            await message.answer(f"❌ Ошибка генерации #{idx}.")

    try:
        await asyncio.gather(
            *[_run_single(i + 1, job) for i, job in enumerate(generation_jobs)]
        )
    finally:
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await generation_lock_guard.release(generation_lock)

    await state.clear()


@router.callback_query(F.data.startswith("retry_img_"))
async def handle_retry_image(callback: types.CallbackQuery, state: FSMContext):
    """Повторяет генерацию фото с теми же параметрами."""
    task_id = callback.data.replace("retry_img_", "")
    task = await get_task_by_id(task_id)

    if not task or not task.prompt:
        await callback.answer("❌ Нет данных для повтора", show_alert=True)
        return

    img_service = task.model or "banana_pro"
    aspect_ratio = task.aspect_ratio or "1:1"
    cost = task.cost or preset_manager.get_generation_cost(img_service)
    img_options = normalize_image_options(img_service, {"aspect_ratio": aspect_ratio})
    prompt = task.prompt
    reference_images = _deserialize_reference_images(task.reference_images)
    if not reference_images:
        reference_images = _extract_reference_images_from_message(callback.message)

    model_config = get_image_model_config(img_service)
    if model_config.get("requires_refs") and not reference_images:
        await callback.answer("❌ Не нашёл исходники для повтора", show_alert=True)
        return

    user = await get_or_create_user(callback.from_user.id)
    if user.credits < cost:
        await callback.answer(f"❌ Нужно {cost}🍌", show_alert=True)
        return

    generation_lock = await generation_lock_guard.acquire(callback.from_user.id)
    if not generation_lock:
        await callback.answer("⏳ Предыдущая генерация ещё запускается", show_alert=True)
        return

    local_task_id = f"img_{uuid.uuid4().hex[:12]}"
    processing_msg = None
    try:
        await callback.answer("🔄 Запускаю повтор...")
        charged = await deduct_credits(
            callback.from_user.id,
            cost,
            reason="image_retry_charge",
            external_id=f"retry:{task_id}:{callback.id}",
            metadata={"model": img_service, "source_task_id": task_id},
        )
        if not charged:
            await generation_lock_guard.release(generation_lock)
            await callback.message.answer("❌ Не удалось списать бананы. Повтор не запущен.")
            return

        await add_generation_task(
            user.id,
            callback.from_user.id,
            local_task_id,
            "image",
            img_service,
            model=img_service,
            aspect_ratio=aspect_ratio,
            prompt=prompt,
            cost=cost,
            reference_images=_serialize_reference_images(reference_images),
        )

        processing_msg = await callback.message.answer("🔄 Повторяю генерацию...")
    except Exception:
        logger.exception("Retry image setup failed")
        if not config.is_admin(callback.from_user.id):
            await add_credits_once(
                callback.from_user.id,
                cost,
                reason="generation_refund",
                external_id=local_task_id,
                metadata={"handler": "retry_image_setup"},
            )
        await generation_lock_guard.release(generation_lock)
        await callback.message.answer("❌ Ошибка запуска повтора. Бананы возвращены.")
        return

    try:
        callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None

        if img_service == "banana_2":
            result = await nano_banana_2_service.generate_image(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                resolution=img_options.get("resolution", "4K"),
                output_format=img_options.get("output_format", "png"),
                image_input=reference_images,
                callback_url=callback_url,
            )
        elif img_service == "banana_pro":
            result = await nano_banana_pro_service.generate_image(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                resolution=img_options.get("resolution", "4K"),
                output_format=img_options.get("output_format", "png"),
                image_input=reference_images,
                callback_url=callback_url,
            )
        elif img_service in ("seedream_edit", "seedream_5_lite"):
            result = await seedream_service.generate_image(
                prompt=prompt,
                model=model_config["api_model"],
                aspect_ratio=aspect_ratio,
                quality=img_options.get("quality", "basic"),
                nsfw_checker=img_options.get("nsfw_checker", False),
                image_urls=reference_images,
                callback_url=callback_url,
            )
        elif img_service == "gpt_image_2":
            result = await gpt_image_service.generate_image(
                prompt=prompt,
                image_urls=reference_images,
                aspect_ratio=aspect_ratio,
                nsfw_checker=img_options.get("nsfw_checker", False),
                callback_url=callback_url,
            )
        elif img_service in ("grok_t2i", "grok_i2i"):
            if img_service == "grok_i2i" and reference_images:
                result = await grok_service.generate_image_to_image(
                    image_url=reference_images[0],
                    prompt=prompt,
                    nsfw_checker=img_options.get("nsfw_checker", False),
                    callback_url=callback_url,
                )
            else:
                result = await grok_service.generate_text_to_image(
                    prompt=prompt,
                    aspect_ratio=aspect_ratio,
                    nsfw_checker=img_options.get("nsfw_checker", False),
                    callback_url=callback_url,
                )
        else:
            result = await nano_banana_pro_service.generate_image(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                image_input=reference_images,
                callback_url=callback_url,
            )

        await processing_msg.delete()

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
            await callback.message.answer(
                f"🚀 Повтор запущен!\n🆔 <code>{api_task_id}</code>\n"
                f"💰 <code>{cost}</code>🍌 списано\nОжидайте результат (1-3 мин).",
                parse_mode="HTML",
            )
        elif result:  # bytes
            saved_url = save_uploaded_file(result, "png")
            retry_kb = get_image_result_keyboard(local_task_id, saved_url)
            await callback.message.answer_photo(
                photo=types.BufferedInputFile(result, filename="generated.png"),
                caption=f"✅ Готово!\n💰 <code>{cost}</code>🍌 списано",
                parse_mode="HTML",
                reply_markup=retry_kb,
            )
            await _send_original_document(
                callback.message.answer_document, result, saved_url
            )
            await complete_video_task(local_task_id, saved_url)
        else:
            if not config.is_admin(callback.from_user.id):
                await add_credits_once(callback.from_user.id, cost, reason="generation_refund", external_id=local_task_id if "local_task_id" in locals() else f"retry:{task_id}")
            await complete_video_task(local_task_id, None)
            await callback.message.answer("❌ Ошибка повтора. Бананы возвращены.")

    except Exception as e:
        logger.exception(f"Retry image error: {e}")
        if not config.is_admin(callback.from_user.id):
            await add_credits_once(
                callback.from_user.id,
                cost,
                reason="generation_refund",
                external_id=local_task_id,
                metadata={"handler": "retry_image"},
            )
        await complete_video_task(local_task_id, None)
        await callback.message.answer("❌ Ошибка повтора.")
    finally:
        await generation_lock_guard.release(generation_lock)


@router.message(GenerationStates.waiting_for_reference_video)
async def invalid_reference_video_input(message: types.Message, state: FSMContext):
    """
    Обрабатывает невалидный ввод в состоянии waiting_for_reference_video.
    """
    await message.answer(
        "⚠️ Пожалуйста, отправьте видео файл (макс 50MB)."
        "Это видео будет использовано как референс для стиля/движения."
    )


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
    message: types.Message | types.CallbackQuery, state: FSMContext, prompt: str
):
    """Запускает видео генерацию без пресета (новый UX с v_type, v_model и т.д.)"""
    target_message = message.message if isinstance(message, types.CallbackQuery) else message
    telegram_id = message.from_user.id
    submit_message_id = getattr(target_message, "message_id", 0)
    data = await state.get_data()
    v_type = data.get("v_type", "text")
    v_model = data.get("v_model", "v3_std")
    video_urls = data.get("v_reference_videos", [])
    if video_urls and v_model not in {"happyhorse_edit", "glow"}:
        v_model = "aleph"
    if v_type == "video" and v_model not in _MODELS_VIDEO:
        v_model = "aleph"
    v_duration = int(data.get("v_duration", 5))
    video_options = normalize_video_options(v_model, data.get("video_options", {}))
    # Cap duration for imgtxt except for models with their own duration logic
    _no_cap_models = (
        "grok_imagine",
        "seedance2",
        "veo3_fast",
        "veo3",
        "veo3_lite",
        "hailuo_23_pro",
        "hailuo_23_std",
        "hailuo_pro",
        "hailuo_std",
        "hailuo_i2v_pro",
        "hailuo_i2v_std",
        "happyhorse_t2v",
        "happyhorse_i2v",
        "happyhorse_ref2v",
        "happyhorse_edit",
        "wan_27_t2v",
        "wan_27_i2v",
    )
    if v_type == "imgtxt" and v_model not in _no_cap_models:
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

    user = await get_or_create_user(telegram_id)
    is_admin = config.is_admin(telegram_id)

    generation_lock = None

    # Admin free access
    if is_admin:
        logger.info(
            f"Admin {telegram_id} - free access (skipped {cost} credits)"
        )
    else:
        if not await check_can_afford(telegram_id, cost):
            await target_message.answer(
                f"❌ Недостаточно бананов!\nНужно: <code>{cost}</code>🍌\nПополните баланс.",
                reply_markup=get_main_menu_keyboard(
                    await get_user_credits(telegram_id)
                ),
                parse_mode="HTML",
            )
            await state.clear()
            return
        generation_lock = await generation_lock_guard.acquire(telegram_id)
        if not generation_lock:
            await target_message.answer("⏳ Предыдущая генерация ещё запускается. Подождите несколько секунд и попробуйте снова.")
            await state.clear()
            return
        charged = await deduct_credits(
            telegram_id,
            cost,
            reason="video_generation_charge",
            external_id=f"video_submit:{telegram_id}:{submit_message_id}",
            metadata={"model": v_model, "duration": v_duration, "ratio": v_ratio},
        )
        if not charged:
            await generation_lock_guard.release(generation_lock)
            await state.clear()
            await target_message.answer("❌ Не удалось списать бананы. Генерация не запущена.")
            return

    refund_external_id = f"video:{telegram_id}:{submit_message_id}"
    processing_msg = None
    try:
        processing_msg = await target_message.answer(
            _build_progress_text(
                title="🎬 <b>Видео запускается</b>",
                percent=10,
                status=(
                    f"Передаю задачу модели {v_model}: "
                    f"{v_duration}s, "
                    f"{'формат по фото' if v_model == 'wan_27_i2v' else v_ratio}, "
                    f"{cost}🍌."
                ),
                eta="Обычно видео занимает 1-5 минут.",
            ),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Video generation setup failed")
        if not is_admin:
            await add_credits_once(
                telegram_id,
                cost,
                reason="generation_refund",
                external_id=refund_external_id,
                metadata={"handler": "video_setup"},
            )
        await generation_lock_guard.release(generation_lock)
        await state.clear()
        await target_message.answer("❌ Ошибка запуска генерации. Бананы возвращены.")
        return

    try:
        from bot.services.kling_service import kling_service

        if v_model == "grok_imagine":
            if not image_url:
                await target_message.answer(
                    "❌ Grok Imagine требует стартовое изображение (фото+текст режим)."
                )
                if not is_admin:
                    await add_credits_once(telegram_id, cost, reason="generation_refund", external_id=refund_external_id)
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
                await state.clear()
                return

            # Pass start image + references (max 7 total for Grok)
            grok_image_urls = [image_url] + image_refs[:6]
            grok_duration = v_duration  # Supports 6,20,30 sec
            grok_mode = video_options.get("mode", data.get("grok_mode", "normal"))
            result = await grok_service.generate_image_to_video(
                image_urls=grok_image_urls,
                prompt=prompt,
                mode=grok_mode,
                duration=grok_duration,
                resolution=video_options.get("resolution", "720p"),
                aspect_ratio=v_ratio,
                nsfw_checker=video_options.get("nsfw_checker", False),
                callBackUrl=(
                    config.kling_notification_url if config.WEBHOOK_HOST else None
                ),
            )
        elif v_model == "aleph":
            if not video_urls:
                await target_message.answer(
                    "❌ Aleph Video требует референсное видео (видео+текст режим)."
                )
                if not is_admin:
                    await add_credits_once(telegram_id, cost, reason="generation_refund", external_id=refund_external_id)
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
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
                await target_message.answer(
                    "❌ Runway не поддерживает видео референсы. Используйте текст или фото+текст."
                )
                if not is_admin:
                    await add_credits_once(telegram_id, cost, reason="generation_refund", external_id=refund_external_id)
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
                await state.clear()
                return
            callback_url = (
                config.kling_notification_url if config.WEBHOOK_HOST else None
            )
            result = await runway_service.generate_video(
                prompt=prompt,
                image_url=image_url,
                duration=v_duration,
                quality=video_options.get("quality", "720p"),
                aspect_ratio=v_ratio,
                callback_url=callback_url,
            )
        elif v_model in ("veo3_fast", "veo3", "veo3_lite"):
            veo_image_urls = []
            if image_url:
                veo_image_urls = [image_url] + image_refs[:1]
            result = await veo_service.generate_video(
                prompt=prompt,
                model=v_model,
                aspect_ratio=v_ratio,
                resolution=video_options.get("resolution", "1080p"),
                enable_translation=video_options.get("enable_translation", True),
                image_urls=veo_image_urls or None,
                callback_url=(
                    config.veo_notification_url if config.WEBHOOK_HOST else None
                ),
            )
        elif v_model in (
            "hailuo_23_pro",
            "hailuo_23_std",
            "hailuo_pro",
            "hailuo_std",
            "hailuo_i2v_pro",
            "hailuo_i2v_std",
        ):
            from bot.services.hailuo_service import HAILUO_IMAGE_REQUIRED

            if v_model in HAILUO_IMAGE_REQUIRED and not image_url:
                await target_message.answer(
                    f"❌ {v_model} требует стартовое изображение (фото+текст режим)."
                )
                if not is_admin:
                    await add_credits_once(telegram_id, cost, reason="generation_refund", external_id=refund_external_id)
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
                await state.clear()
                return
            result = await hailuo_service.generate_video(
                model_key=v_model,
                prompt=prompt,
                image_url=image_url,
                duration=v_duration,
                resolution=video_options.get(
                    "resolution", data.get("hailuo_resolution", "768P")
                ),
                nsfw_checker=video_options.get("nsfw_checker", False),
                prompt_optimizer=video_options.get("prompt_optimizer", False),
                callback_url=(
                    config.kie_notification_url if config.WEBHOOK_HOST else None
                ),
            )
        elif v_model in (
            "happyhorse_t2v",
            "happyhorse_i2v",
            "happyhorse_ref2v",
            "happyhorse_edit",
        ):
            from bot.services.happyhorse_service import (
                HAPPYHORSE_IMAGE_REQUIRED,
                HAPPYHORSE_VIDEO_REQUIRED,
            )

            happyhorse_images = []
            if image_url:
                happyhorse_images.append(image_url)
            happyhorse_images.extend(image_refs)

            if v_model in HAPPYHORSE_IMAGE_REQUIRED and not happyhorse_images:
                await target_message.answer(
                    f"❌ {v_model} требует минимум одно изображение (фото+текст режим)."
                )
                if not is_admin:
                    await add_credits_once(telegram_id, cost, reason="generation_refund", external_id=refund_external_id)
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
                await state.clear()
                return
            if v_model in HAPPYHORSE_VIDEO_REQUIRED and not video_urls:
                await target_message.answer(
                    "❌ HappyHorse Edit требует видео-референс (режим видео+текст)."
                )
                if not is_admin:
                    await add_credits_once(telegram_id, cost, reason="generation_refund", external_id=refund_external_id)
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
                await state.clear()
                return

            result = await happyhorse_service.generate_video(
                model_key=v_model,
                prompt=prompt,
                image_urls=happyhorse_images,
                video_url=video_urls[0] if video_urls else None,
                duration=v_duration,
                aspect_ratio=v_ratio,
                resolution=video_options.get("resolution", "1080p"),
                audio_setting=video_options.get("audio_setting", "auto"),
                seed=video_options.get("seed"),
                callback_url=(
                    config.kie_notification_url if config.WEBHOOK_HOST else None
                ),
            )
        elif v_model in {"wan_27_t2v", "wan_27_i2v"}:
            if v_model == "wan_27_i2v" and not image_url:
                await target_message.answer(
                    "❌ Wan 2.7 I2V требует стартовое изображение (фото+текст режим)."
                )
                if not is_admin:
                    await add_credits_once(telegram_id, cost, reason="generation_refund", external_id=refund_external_id)
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
                await state.clear()
                return
            result = await kling_service.generate_video(
                prompt=prompt,
                model=v_model,
                duration=v_duration,
                aspect_ratio=v_ratio,
                image_url=image_url,
                seedance_resolution=video_options.get("resolution", "1080p"),
                wan_resolution=video_options.get("resolution", "1080p"),
                wan_prompt_extend=video_options.get("prompt_extend", True),
                wan_watermark=video_options.get("watermark", False),
                webhook_url=(
                    config.kie_notification_url if config.WEBHOOK_HOST else None
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
                generate_audio=video_options.get("sound", True),
                seedance_resolution=video_options.get("resolution"),
                seedance_nsfw_checker=video_options.get("nsfw_checker", False),
                seedance_web_search=video_options.get("web_search", False),
                motion_mode=video_options.get(
                    "motion_quality", data.get("v_mode", "720p")
                ),
                motion_orientation=video_options.get(
                    "character_orientation", data.get("v_orientation", "video")
                ),
                keep_original_sound=video_options.get("keep_original_sound", True),
                webhook_url=(
                    config.kling_notification_url if config.WEBHOOK_HOST else None
                ),
            )

        await processing_msg.delete()

        if result and "task_id" in result:
            await add_generation_task(
                user.id,
                telegram_id,
                result["task_id"],
                "video",
                "no_preset_video",
                model=v_model,
                duration=v_duration,
                aspect_ratio=v_ratio,
                prompt=prompt,
                cost=cost,
            )
            await target_message.answer(
                _build_video_task_started_text(
                    task_id=result["task_id"],
                    model=v_model,
                    duration=v_duration,
                    ratio=v_ratio,
                    cost=cost,
                    is_admin=is_admin,
                ),
                parse_mode="HTML",
            )
            progress_msg = await target_message.answer(
                _build_progress_text(
                    title="🎬 <b>Прогресс видео</b>",
                    percent=20,
                    status="Модель приняла задачу. Работа идёт.",
                    task_id=result["task_id"],
                    eta="Результат придёт сюда автоматически.",
                ),
                parse_mode="HTML",
            )
            asyncio.create_task(
                _simulate_generation_progress(
                    progress_msg,
                    result["task_id"],
                    title="🎬 <b>Прогресс видео</b>",
                    eta="Результат придёт сюда автоматически.",
                    steps=(
                        (30, "Модель строит сцену и движение."),
                        (45, "Генерируются ключевые кадры."),
                        (65, "Склеивается плавное видео."),
                        (82, "Финальная обработка и качество."),
                        (94, "Почти готово, ждём файл от сервиса."),
                    ),
                    interval=18,
                )
            )
        else:
            if not is_admin:
                await add_credits_once(telegram_id, cost, reason="generation_refund", external_id=refund_external_id)
            await target_message.answer("❌ Не удалось создать задачу. Бананы возвращены.")
    except Exception as e:
        logger.exception(f"Video generation error: {e}")
        if not is_admin:
            await add_credits_once(telegram_id, cost, reason="generation_refund", external_id=refund_external_id)
        await target_message.answer("❌ Ошибка генерации. Бананы возвращены.")

    await generation_lock_guard.release(generation_lock)
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
            data = await state.get_data()
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
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
                current_service = data.get("img_service", "banana_pro")
                current_ratio = data.get("img_ratio", "1:1")
                await callback.message.edit_text(
                    f"✨ <b>Создание фото</b>"
                    f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                    f"✨ Модель: <code>{current_service}</code>\n"
                    f"📐 Формат: <code>{current_ratio}</code>"
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
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
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
        video_url = save_uploaded_file(video_data, "mp4", is_reference=True)

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
            f"🎬 <b>Создание видео</b>"
            f"{video_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Видео + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>"
            f"Опишите желаемый эффект/стиль:\n"
            f"• Стиль видео\n"
            f"• Дополнительные эффекты\n"
            f"• Атмосфера"
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
        "⚠️ Пожалуйста, отправьте видеофайл до 50 MB.\n\n"
        "Это видео будет использовано как референс для стиля и движения."
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
            data = await state.get_data()
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
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
                current_service = data.get("img_service", "banana_pro")
                current_ratio = data.get("img_ratio", "1:1")
                await callback.message.edit_text(
                    f"✨ <b>Создание фото</b>"
                    f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                    f"✨ Модель: <code>{current_service}</code>\n"
                    f"📐 Формат: <code>{current_ratio}</code>"
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
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
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

        # Validate image dimensions for video generation API
        try:
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(image_data))
            width, height = img.size
            if width < 300 or height < 300:
                await message.answer(
                    f"❌ <b>Изображение слишком маленькое!</b>\\n\\n"
                    f"Размер: {width}×{height} px\\n\\n"
                    "Минимальный размер изображения: 300×300 px.\\n"
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
        image_url = save_uploaded_file(image_data, "png", is_reference=True)

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
            f"🎬 <b>Создание видео</b>"
            f"{image_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Фото + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>"
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
        video_url = save_uploaded_file(video_data, "mp4", is_reference=True)

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
            f"🎬 <b>Создание видео</b>"
            f"{video_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Видео + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>"
            f"Опишите желаемый эффект/стиль:\n"
            f"• Стиль видео\n"
            f"• Дополнительные эффекты\n"
            f"• Атмосфера"
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
        "⚠️ Пожалуйста, отправьте видео файл (макс 50MB)."
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
            data = await state.get_data()
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
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
                current_service = data.get("img_service", "banana_pro")
                current_ratio = data.get("img_ratio", "1:1")
                await callback.message.edit_text(
                    f"✨ <b>Создание фото</b>"
                    f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                    f"✨ Модель: <code>{current_service}</code>\n"
                    f"📐 Формат: <code>{current_ratio}</code>"
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
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
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
        video_url = save_uploaded_file(video_data, "mp4", is_reference=True)

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
            f"🎬 <b>Создание видео</b>"
            f"{video_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Видео + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>"
            f"Опишите желаемый эффект/стиль:\n"
            f"• Стиль видео\n"
            f"• Дополнительные эффекты\n"
            f"• Атмосфера"
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
        "⚠️ Пожалуйста, отправьте видео файл (макс 50MB)."
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
            data = await state.get_data()
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
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
                current_service = data.get("img_service", "banana_pro")
                current_ratio = data.get("img_ratio", "1:1")
                await callback.message.edit_text(
                    f"✨ <b>Создание фото</b>"
                    f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                    f"✨ Модель: <code>{current_service}</code>\n"
                    f"📐 Формат: <code>{current_ratio}</code>"
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
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
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
        video_url = save_uploaded_file(video_data, "mp4", is_reference=True)

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
            f"🎬 <b>Создание видео</b>"
            f"{video_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Видео + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>"
            f"Опишите желаемый эффект/стиль:\n"
            f"• Стиль видео\n"
            f"• Дополнительные эффекты\n"
            f"• Атмосфера"
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
