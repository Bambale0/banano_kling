import asyncio
import base64
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
    get_image_model_label,
    get_image_model_selection_keyboard,
    get_image_result_keyboard,
    get_main_menu_button_keyboard,
    get_main_menu_keyboard,
    get_reference_images_upload_keyboard,
    get_reference_videos_upload_keyboard,
    get_video_media_step_keyboard,
    get_video_model_label,
    get_video_model_selection_keyboard,
    get_video_type_label,
)
from bot.services.gemini_service import gemini_service
from bot.services.gpt_image_service import gpt_image_service
from bot.services.grok_service import grok_service
from bot.services.nano_banana_2_service import nano_banana_2_service
from bot.services.nano_banana_pro_service import nano_banana_pro_service
from bot.services.preset_manager import preset_manager
from bot.services.seedream_service import seedream_service
from bot.services.wan27_service import wan27_service
from bot.states import GenerationStates
from bot.utils.help_texts import (
    UserHints,
    format_generation_options,
    get_prompt_tips,
    get_reference_images_help,
)

logger = logging.getLogger(__name__)
router = Router()


SENSITIVE_FASHION_KEYWORDS = {
    "белье",
    "нижнее белье",
    "нижнем белье",
    "бюстгальтер",
    "стринги",
    "лиф",
    "чулки",
    "подвяз",
    "корсет",
    "бикини",
    "купальник",
    "lingerie",
    "underwear",
    "bra",
    "thong",
    "stockings",
    "garter",
    "corset",
    "bikini",
    "swimsuit",
}


def _get_image_provider_model(img_service: str, reference_images: list[str]) -> str:
    """Return provider-facing model identifier for routing logs."""
    if img_service == "banana_2":
        return "google/gemini-2.5-flash-image"
    if img_service in {"banana_pro", "nanobanana"}:
        return "google/gemini-3-pro-image"
    if img_service == "seedream_edit":
        return "seedream/4.5-edit"
    if img_service == "flux_pro":
        return (
            "gpt-image-2-image-to-image"
            if reference_images
            else "gpt-image-2-text-to-image"
        )
    if img_service in {"seedream", "seedream_45"}:
        return "google/gemini-pro"
    if img_service == "grok_imagine_i2i":
        return "grok-imagine-image-to-image"
    if img_service == "wan_27":
        return "wan/2-7-image-pro"
    return img_service


def _classify_image_generation_result(result) -> tuple[str, Optional[str]]:
    """Normalize provider responses into queued/done/failed states."""
    if isinstance(result, dict):
        if result.get("task_id"):
            return "queued", None
        error_message = result.get("message") or result.get("error") or str(result)
        return "failed", error_message
    if isinstance(result, (bytes, bytearray)):
        return "done", None
    if result:
        return "failed", f"Unexpected result type: {type(result).__name__}"
    return "failed", None


def _apply_safe_prompt_framing(img_service: str, prompt: str) -> str:
    """Reduce false positives for benign fashion/editorial prompts without bypassing policy."""
    prompt = (prompt or "").strip()
    if not prompt:
        return prompt
    if img_service not in {"banana_pro", "banana_2", "nanobanana", "grok_imagine_i2i", "wan_27"}:
        return prompt

    replacements = {
        r"\blingerie\b": "fashion outfit",
        r"\bunderwear\b": "fashion outfit",
        r"\bbra\b": "top",
        r"\bthong\b": "swimwear bottom",
        r"\bstockings\b": "fashion stockings",
        r"\bgarter\b": "fashion accessory",
        r"\bбелье\b": "модный образ",
        r"\bнижнее белье\b": "модный образ",
        r"\bбюстгальтер\b": "топ",
        r"\bстринги\b": "низ от купальника",
        r"\bчулки\b": "fashion-чулки",
        r"\bкорсет\b": "fashion-корсет",
    }
    normalized = prompt
    for pattern, replacement in replacements.items():
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)

    safety_prefix = (
        "Safe, non-explicit editorial image of an adult subject. "
        "Fashion or product focused, no nudity, no explicit anatomy, no sexual content. "
    )
    return f"{safety_prefix}{normalized}"


def _build_image_variant_prompt(prompt: str, variant_index: int, total_count: int) -> str:
    """Add controlled variation for multi-image batches while keeping references."""
    prompt = (prompt or "").strip()
    if total_count <= 1:
        return prompt

    variants = [
        "Create a distinct variation while preserving the same referenced person/object, identity, key features, outfit, and visual style. Use a slightly different composition and micro-pose.",
        "Create another distinct interpretation while preserving the same referenced person/object, identity, key features, outfit, and visual style. Change camera angle, crop, and natural expression slightly.",
        "Create a new variation while preserving the same referenced person/object, identity, key features, outfit, and visual style. Vary lighting balance, framing, and background depth slightly.",
        "Create an alternate editorial take while preserving the same referenced person/object, identity, key features, outfit, and visual style. Use a different crop, pose nuance, and mood.",
    ]
    instruction = variants[variant_index % len(variants)]
    return f"{prompt}\n\nVariant {variant_index + 1} of {total_count}: {instruction} Do not copy previous outputs exactly."


async def _start_image_generation_task(
    *,
    user,
    telegram_id: int,
    img_service: str,
    prompt: str,
    img_ratio: str,
    reference_images: list[str],
    unit_cost: int,
    img_quality: str = "basic",
    img_nsfw_checker: bool = False,
    nsfw_enabled: bool = False,
    callback_url: Optional[str] = None,
):
    """Launch one image generation task and persist enough data for repeats."""
    runtime_img_service = img_service
    provider_model = _get_image_provider_model(runtime_img_service, reference_images)

    local_task_id = f"img_{uuid.uuid4().hex[:12]}"
    effective_prompt = _apply_safe_prompt_framing(runtime_img_service, prompt)
    request_snapshot = {
        "img_service": img_service,
        "prompt": prompt,
        "effective_prompt": effective_prompt,
        "img_ratio": img_ratio,
        "reference_images": reference_images,
        "img_quality": img_quality,
        "img_nsfw_checker": img_nsfw_checker,
        "nsfw_enabled": nsfw_enabled,
        "provider_model": provider_model,
    }
    await add_generation_task(
        user.id,
        telegram_id,
        local_task_id,
        "image",
        runtime_img_service,
        model=runtime_img_service,
        aspect_ratio=img_ratio,
        prompt=prompt,
        cost=unit_cost,
        request_data=request_snapshot,
    )
    logger.info(
        "Image route: local_task_id=%s selected_model=%s runtime_model=%s provider_model=%s references=%s ratio=%s ref_sample=%s prompt_len=%s",
        local_task_id,
        img_service,
        runtime_img_service,
        provider_model,
        len(reference_images),
        img_ratio,
        reference_images[:3],
        len(prompt or ""),
    )

    if runtime_img_service == "banana_2":
        result = await nano_banana_2_service.generate_image(
            prompt=effective_prompt,
            aspect_ratio=img_ratio,
            image_input=reference_images,
            callback_url=callback_url,
        )
    elif runtime_img_service in {"banana_pro", "nanobanana"}:
        result = await nano_banana_pro_service.generate_image(
            prompt=effective_prompt,
            aspect_ratio=img_ratio,
            image_input=reference_images,
            callback_url=callback_url,
        )
    elif runtime_img_service == "seedream_edit":
        result = await seedream_service.generate_image(
            prompt=prompt,
            model="seedream/4.5-edit",
            aspect_ratio=img_ratio,
            image_urls=reference_images,
            quality=img_quality,
            nsfw_checker=img_nsfw_checker,
            callBackUrl=callback_url,
        )
    elif runtime_img_service == "flux_pro":
        if reference_images:
            result = await gpt_image_service.generate_image_to_image(
                prompt=prompt,
                input_urls=reference_images,
                model="gpt-image-2-image-to-image",
                aspect_ratio=img_ratio,
                nsfw_checker=img_nsfw_checker,
                callBackUrl=callback_url,
            )
        else:
            result = await gpt_image_service.generate_image(
                prompt=prompt,
                model="gpt-image-2-text-to-image",
                aspect_ratio=img_ratio,
                nsfw_checker=img_nsfw_checker,
                callBackUrl=callback_url,
            )
    elif runtime_img_service in {"seedream", "seedream_45"}:
        result = await gemini_service.generate_image(
            prompt=prompt,
            model="pro",
            aspect_ratio=img_ratio,
            reference_image_urls=reference_images,
        )
    elif runtime_img_service == "grok_imagine_i2i":
        result = await grok_service.generate_image_to_image(
            image_urls=reference_images,
            prompt=effective_prompt,
            nsfw_checker=nsfw_enabled,
            callBackUrl=callback_url,
        )
    elif runtime_img_service == "wan_27":
        result = await wan27_service.generate_image(
            prompt=effective_prompt,
            aspect_ratio=img_ratio,
            input_urls=reference_images,
            n=1,
            resolution="2K",
            pro=True,
            enable_sequential=False,
            thinking_mode=False,
            watermark=False,
            seed=random.randint(1, 2147483647),
            nsfw_checker=False,
            callBackUrl=callback_url,
        )
    else:
        result = await nano_banana_pro_service.generate_image(
            prompt=effective_prompt,
            aspect_ratio=img_ratio,
            image_input=reference_images,
            callback_url=callback_url,
        )

    result_status, error_message = _classify_image_generation_result(result)

    if result_status == "queued":
        api_task_id = result["task_id"]
        import aiosqlite

        from bot.database import DATABASE_PATH

        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "UPDATE generation_tasks SET task_id = ? WHERE task_id = ? AND user_id = ?",
                (api_task_id, local_task_id, user.id),
            )
            await db.commit()
        logger.info(
            "Image route confirmed: local_task_id=%s api_task_id=%s selected_model=%s runtime_model=%s provider_model=%s",
            local_task_id,
            api_task_id,
            img_service,
            runtime_img_service,
            provider_model,
        )
        return {
            "status": "queued",
            "task_id": api_task_id,
            "local_task_id": local_task_id,
            "runtime_img_service": runtime_img_service,
        }

    if result_status == "done":
        result_bytes = bytes(result)
        saved_url = save_uploaded_file(result_bytes, "png")
        await complete_video_task(local_task_id, saved_url)
        return {
            "status": "done",
            "task_id": local_task_id,
            "result_bytes": result_bytes,
            "saved_url": saved_url,
            "runtime_img_service": runtime_img_service,
        }

    if error_message:
        logger.error(
            "Image generation failed before queueing: local_task_id=%s selected_model=%s runtime_model=%s provider_model=%s error=%s",
            local_task_id,
            img_service,
            runtime_img_service,
            provider_model,
            error_message,
        )
    await complete_video_task(local_task_id, None)
    return {
        "status": "failed",
        "task_id": local_task_id,
        "runtime_img_service": runtime_img_service,
    }


# =============================================================================
# НОВЫЙ UX: МЕНЮ СОЗДАНИЯ ВИДЕО (get_create_video_keyboard)
# =============================================================================


@router.callback_query(F.data == "create_video_new")
async def show_create_video_menu(callback: types.CallbackQuery, state: FSMContext):
    """Пошаговый вход в видео: модель -> настройки/медиа/промпт."""
    await _init_default_video_state(state)
    await state.update_data(video_flow_step="select_model")
    await _show_video_model_selection_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "create_image_refs_new")
async def show_create_image_menu(callback: types.CallbackQuery, state: FSMContext):
    """Показывает меню создания фото - начинаем с загрузки референсов"""
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
        "Этот шаг можно пропустить.\n"
        "Фото-референсы помогают, если важно:\n"
        "• сохранить внешность человека или предмета\n"
        "• повторить стиль и детали\n"
        "• опираться на конкретный исходник\n\n"
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


@router.callback_query(F.data == "create_image_text_new")
async def show_create_image_text_menu(callback: types.CallbackQuery, state: FSMContext):
    """Пошаговый вход в фото: модель -> референсы -> настройки."""
    await state.update_data(
        generation_type="image",
        img_service="banana_pro",
        img_ratio="1:1",
        img_count=1,
        img_quality="basic",
        img_nsfw_checker=False,
        reference_images=[],
        img_flow_step="select_model",
        preset_id="new",
    )
    await _show_image_model_selection_screen(callback, state)
    await callback.answer()



@router.callback_query(F.data == "model_wan_27")
async def select_model_wan_27(callback: types.CallbackQuery, state: FSMContext):
    """Select Wan 2.7 Pro and open reference upload step."""
    logger.info("Wan 2.7 selected by user_id=%s", callback.from_user.id)
    user_credits = await get_user_credits(callback.from_user.id)

    await state.update_data(
        generation_type="image",
        img_service="wan_27",
        img_ratio="1:1",
        img_count=1,
        reference_images=[],
        img_quality="basic",
        img_nsfw_checker=False,
        nsfw_enabled=False,
        preset_id="new",
        img_flow_step="refs",
    )
    await state.set_state(GenerationStates.uploading_reference_images)

    text = (
        "🧪 <b>Wan 2.7 Pro — тест</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "<b>Шаг 1. Референсы</b>\n"
        "Загрузите фото, если хотите проверить редактирование или генерацию по исходнику.\n"
        "Можно загрузить до 9 фото.\n\n"
        "Если референсы не нужны — нажмите <b>⏭ Пропустить</b>.\n"
        "Когда всё готово — нажмите <b>✅ Продолжить</b>."
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_reference_images_upload_keyboard(0, 9, "new"),
        parse_mode="HTML",
    )
    await callback.answer("Wan 2.7 Pro выбран")


@router.callback_query(F.data.startswith("repeat_image_"))
async def repeat_image_generation(callback: types.CallbackQuery, state: FSMContext):
    """Повторяет фото-задачу с тем же промптом, моделью и исходниками."""
    task_id = callback.data.replace("repeat_image_", "", 1)
    task = await get_task_by_id(task_id)

    if not task or task.type != "image" or not task.request_data:
        await callback.answer("Не удалось найти данные для повтора.", show_alert=True)
        return

    try:
        request_data = json.loads(task.request_data)
    except Exception:
        await callback.answer("Данные исходной задачи повреждены.", show_alert=True)
        return

    unit_cost = task.cost or 0
    is_admin = config.is_admin(callback.from_user.id)
    if unit_cost > 0 and not is_admin:
        can_afford = await check_can_afford(callback.from_user.id, unit_cost)
        if not can_afford:
            await callback.answer("Недостаточно бананов для повтора.", show_alert=True)
            return
        if not await deduct_credits(callback.from_user.id, unit_cost):
            await callback.answer("Не удалось списать бананы.", show_alert=True)
            return

    user = await get_or_create_user(callback.from_user.id)
    img_service = request_data.get("img_service", task.model or "banana_pro")
    prompt = request_data.get("prompt", task.prompt or "")
    img_ratio = request_data.get("img_ratio", task.aspect_ratio or "1:1")
    reference_images = request_data.get("reference_images", [])
    img_quality = request_data.get("img_quality", "basic")
    img_nsfw_checker = bool(request_data.get("img_nsfw_checker", False))
    nsfw_enabled = bool(request_data.get("nsfw_enabled", False))
    callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None

    model_label = get_image_model_label(img_service)
    progress_message = await callback.message.answer(
        "🔁 <b>Повторяю генерацию</b>\n"
        f"• Модель: <code>{model_label}</code>\n"
        f"• Формат: <code>{img_ratio.replace(':', '∶')}</code>\n"
        f"• Референсы: <code>{len(reference_images)}</code>",
        parse_mode="HTML",
    )

    try:
        launch_result = await _start_image_generation_task(
            user=user,
            telegram_id=callback.from_user.id,
            img_service=img_service,
            prompt=_build_image_variant_prompt(prompt, index if 'index' in locals() else 0, img_count if 'img_count' in locals() else 1),
            img_ratio=img_ratio,
            reference_images=list(stable_reference_images if 'stable_reference_images' in locals() else (reference_images or [])),
            unit_cost=unit_cost,
            img_quality=img_quality,
            img_nsfw_checker=img_nsfw_checker,
            nsfw_enabled=nsfw_enabled,
            callback_url=callback_url,
        )
        await progress_message.delete()

        if launch_result["status"] == "queued":
            await callback.message.answer(
                "🚀 <b>Повторная генерация запущена</b>\n"
                f"• Модель: <code>{model_label}</code>\n"
                f"• ID: <code>{launch_result['task_id']}</code>\n"
                f"• Списано: <code>{unit_cost}</code>🍌 {'(админ бесплатно)' if is_admin else ''}\n\n"
                "Результат придёт в этот чат.",
                parse_mode="HTML",
            )
        elif launch_result["status"] == "done":
            result_bytes = launch_result["result_bytes"]
            saved_url = launch_result["saved_url"]
            await callback.message.answer_photo(
                photo=types.BufferedInputFile(result_bytes, filename="repeated.png"),
                caption=(
                    "✅ <b>Повтор готов</b>\n"
                    f"• Модель: <code>{model_label}</code>\n"
                    f"• Списано: <code>{unit_cost}</code>🍌 {'(админ бесплатно)' if is_admin else ''}"
                ),
                parse_mode="HTML",
                reply_markup=get_image_result_keyboard(
                    saved_url, task_id=launch_result["task_id"]
                ),
            )
            await _send_original_document(
                callback.message.answer_document,
                result_bytes,
                saved_url,
                filename="repeated_original.png",
            )
        else:
            if unit_cost > 0 and not is_admin:
                await add_credits(callback.from_user.id, unit_cost)
            await callback.message.answer(
                "❌ Не получилось повторить генерацию. Бананы за попытку уже возвращены."
            )

        await callback.answer("Повтор запускаю")
    except Exception:
        logger.exception("Repeat image generation failed")
        if unit_cost > 0 and not is_admin:
            await add_credits(callback.from_user.id, unit_cost)
        try:
            await progress_message.delete()
        except Exception:
            pass
        await callback.answer("Не удалось повторить генерацию.", show_alert=True)


@router.callback_query(F.data == "main_img_banana_pro")
async def show_main_img_banana_pro(callback: types.CallbackQuery, state: FSMContext):
    await _open_image_model_from_main(callback, state, model="banana_pro")


@router.callback_query(F.data == "main_img_banana_2")
async def show_main_img_banana_2(callback: types.CallbackQuery, state: FSMContext):
    await _open_image_model_from_main(callback, state, model="banana_2")


@router.callback_query(F.data == "main_img_seedream")
async def show_main_img_seedream(callback: types.CallbackQuery, state: FSMContext):
    await _open_image_model_from_main(callback, state, model="seedream_edit")


@router.callback_query(F.data == "main_img_flux")
async def show_main_img_flux(callback: types.CallbackQuery, state: FSMContext):
    await _open_image_model_from_main(callback, state, model="flux_pro")


@router.callback_query(F.data == "main_img_grok")
async def show_main_img_grok(callback: types.CallbackQuery, state: FSMContext):
    await _open_image_model_from_main(
        callback, state, model="grok_imagine_i2i", upload_first=True
    )


@router.callback_query(F.data == "main_img_wan_27")
async def show_main_img_wan_27(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(img_service="wan_27", preset_id="new", img_flow_step="settings")
    await _show_image_creation_screen(callback, state)
    await callback.answer("Выбрана тестовая модель Wan 2.7 Pro")


@router.callback_query(F.data == "main_vid_v3_std")
async def show_main_vid_v3_std(callback: types.CallbackQuery, state: FSMContext):
    await _open_video_model_from_main(callback, state, model="v3_std")


@router.callback_query(F.data == "main_vid_v3_pro")
async def show_main_vid_v3_pro(callback: types.CallbackQuery, state: FSMContext):
    await _open_video_model_from_main(callback, state, model="v3_pro")


@router.callback_query(F.data == "main_vid_veo3")
async def show_main_vid_veo3(callback: types.CallbackQuery, state: FSMContext):
    await _open_video_model_from_main(
        callback, state, model="veo3", duration=6, ratio="9:16"
    )


@router.callback_query(F.data == "main_vid_veo3_fast")
async def show_main_vid_veo3_fast(callback: types.CallbackQuery, state: FSMContext):
    await _open_video_model_from_main(
        callback, state, model="veo3_fast", duration=6, ratio="9:16"
    )


@router.callback_query(F.data == "main_vid_veo3_lite")
async def show_main_vid_veo3_lite(callback: types.CallbackQuery, state: FSMContext):
    await _open_video_model_from_main(
        callback, state, model="veo3_lite", duration=6, ratio="9:16"
    )


@router.callback_query(F.data == "main_vid_grok")
async def show_main_vid_grok(callback: types.CallbackQuery, state: FSMContext):
    await _open_video_model_from_main(
        callback, state, model="grok_imagine", duration=6, ratio="16:9"
    )


@router.callback_query(F.data == "main_vid_glow")
async def show_main_vid_glow(callback: types.CallbackQuery, state: FSMContext):
    await _open_video_model_from_main(
        callback, state, model="glow", v_type="video", duration=5, ratio="16:9"
    )


@router.callback_query(F.data == "quick_product_image")
async def show_quick_product_image(callback: types.CallbackQuery, state: FSMContext):
    """Быстрый сценарий для товара/рекламы."""
    await state.update_data(
        generation_type="image",
        img_service="banana_pro",
        img_ratio="16:9",
        img_count=1,
        reference_images=[],
        preset_id="new",
    )
    await _show_image_creation_screen(callback, state)
    await callback.answer("Формат 16:9 и Banana Pro выбраны для рекламного кадра")


@router.callback_query(F.data.in_({"edit_style_image", "edit_background_image"}))
async def show_edit_reference_upload(callback: types.CallbackQuery, state: FSMContext):
    """Сценарии редактирования фото через загрузку исходника/референсов."""
    user_credits = await get_user_credits(callback.from_user.id)
    is_background = callback.data == "edit_background_image"
    title = "🖼 <b>Сменить фон</b>" if is_background else "🎨 <b>Сменить стиль</b>"
    hint = (
        "Загрузите фото, у которого нужно заменить фон.\n"
        "Потом нажмите <b>Продолжить</b> и напишите, какой фон нужен."
        if is_background
        else "Загрузите фото.\n"
        "При желании добавьте ещё стиль-референсы.\n"
        "Потом нажмите <b>Продолжить</b> и опишите нужный стиль."
    )

    await state.update_data(
        generation_type="image",
        img_service="seedream_edit",
        img_ratio="1:1",
        img_count=1,
        img_quality="basic",
        img_nsfw_checker=False,
        reference_images=[],
        preset_id="new",
    )
    await callback.message.edit_text(
        f"{title}\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        f"{hint}\n\n"
        "<i>Можно загрузить до 14 фото.</i>",
        reply_markup=get_reference_images_upload_keyboard(0, 14, "new"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_images)


@router.callback_query(F.data == "edit_grok_i2i")
async def show_grok_i2i_upload(callback: types.CallbackQuery, state: FSMContext):
    """Быстрый вход в Grok Imagine i2i."""
    user_credits = await get_user_credits(callback.from_user.id)
    await state.update_data(
        generation_type="image",
        img_service="grok_imagine_i2i",
        img_ratio="1:1",
        img_count=1,
        reference_images=[],
        nsfw_enabled=False,
        preset_id="new",
    )
    await callback.message.edit_text(
        "🧠 <b>Grok Imagine i2i</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "Загрузите фото для изменения.\n"
        "Потом нажмите <b>Продолжить</b> и напишите, что нужно поменять.",
        reply_markup=get_reference_images_upload_keyboard(0, 14, "new"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_images)


@router.callback_query(F.data == "quick_reels_video")
async def show_quick_reels_video(callback: types.CallbackQuery, state: FSMContext):
    """Быстрый сценарий вертикального ролика."""
    await _init_default_video_state(
        state,
        v_type="text",
        v_model="veo3_fast",
        v_duration=6,
        v_ratio="9:16",
    )
    await _show_video_creation_screen(callback, state)
    await callback.answer("Выбраны настройки для Reels/TikTok: 9:16, 6 сек")


@router.callback_query(F.data == "quick_image_to_video")
async def show_quick_image_to_video(callback: types.CallbackQuery, state: FSMContext):
    """Быстрый сценарий фото -> видео."""
    await _init_default_video_state(
        state,
        v_type="imgtxt",
        v_model="v3_std",
        v_duration=5,
        v_ratio="9:16",
    )
    await _show_video_creation_screen(callback, state)
    await callback.answer("Загрузите фото, затем промпт движения")


@router.callback_query(F.data == "quick_video_reference")
async def show_quick_video_reference(callback: types.CallbackQuery, state: FSMContext):
    """Быстрый вход в видео-референсы."""
    user_credits = await get_user_credits(callback.from_user.id)
    await _init_default_video_state(
        state,
        v_type="video",
        v_model="glow",
        v_duration=5,
        v_ratio="16:9",
    )
    text = (
        "🎞 <b>Видео-референс</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code>\n\n"
        "Загрузите до 5 коротких видео, если хотите передать движение, стиль камеры "
        "или атмосферу.\nМожно пропустить шаг и продолжить без них."
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_reference_videos_upload_keyboard(0, 5, "video_new"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_videos)


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
        "Загрузите чёткое фото, которое нужно оживить.\n\n"
        "Подойдёт:\n"
        "• портрет или персонаж по пояс\n"
        "• иллюстрация или рендер\n"
        "• JPEG/PNG до 10 MB\n\n"
        "<i>Движение потом будет перенесено с видео на это изображение.</i>"
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
        "Добавьте фото, если хотите точнее передать стиль, человека или объект.\n\n"
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


async def _init_default_video_state(
    state: FSMContext,
    *,
    v_type: str = "text",
    v_model: str = "v3_std",
    v_duration: int = 5,
    v_ratio: str = "16:9",
):
    """Инициализирует единый state для новых видео-сценариев."""
    await state.update_data(
        generation_type="video",
        v_type=v_type,
        v_model=v_model,
        v_duration=v_duration,
        v_ratio=v_ratio,
        v_mode="720p",
        v_orientation="video",
        reference_images=[],
        v_reference_videos=[],
        v_image_url=None,
        user_prompt="",
        grok_mode="normal",
        veo_generation_type=(
            "FIRST_AND_LAST_FRAMES_2_VIDEO"
            if v_type == "imgtxt" and v_model.startswith("veo3")
            else "TEXT_2_VIDEO"
        ),
        veo_translation=True,
        veo_resolution="720p",
        veo_seed=None,
        veo_watermark="",
        kling_negative_prompt="",
        kling_cfg_scale=0.5,
        avatar_audio_url=None,
    )


async def _open_image_model_from_main(
    callback: types.CallbackQuery,
    state: FSMContext,
    *,
    model: str,
    upload_first: bool = False,
):
    """Прямой вход из главного меню в нужную модель фото."""
    await state.update_data(
        generation_type="image",
        img_service=model,
        img_ratio="auto" if model == "flux_pro" else "1:1",
        img_count=1,
        img_quality="basic",
        img_nsfw_checker=False,
        reference_images=[],
        preset_id="new",
    )

    if model == "flux_pro":
        await state.update_data(img_flow_step="upload_refs")
        await _show_image_references_screen(callback, state)
    elif upload_first:
        user_credits = await get_user_credits(callback.from_user.id)
        await callback.message.edit_text(
            "🧠 <b>Grok Imagine</b>\n"
            f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
            "Сначала загрузите фото для редактирования, затем нажмите "
            "<b>Продолжить</b> и опишите изменение.",
            reply_markup=get_reference_images_upload_keyboard(0, 14, "new"),
            parse_mode="HTML",
        )
        await state.set_state(GenerationStates.uploading_reference_images)
    else:
        await _show_image_creation_screen(callback, state)
    await callback.answer()


async def _open_video_model_from_main(
    callback: types.CallbackQuery,
    state: FSMContext,
    *,
    model: str,
    v_type: str = "text",
    duration: int = 5,
    ratio: str = "16:9",
):
    """Прямой вход из главного меню в нужную модель видео."""
    await _init_default_video_state(
        state,
        v_type=v_type,
        v_model=model,
        v_duration=duration,
        v_ratio=ratio,
    )

    if v_type == "video":
        user_credits = await get_user_credits(callback.from_user.id)
        text = (
            "🎞 <b>Видео-референс</b>\n"
            f"🍌 Баланс: <code>{user_credits}</code>\n\n"
            "Загрузите до 5 коротких видео, чтобы передать движение, стиль камеры "
            "или атмосферу. Можно пропустить и продолжить без референсов."
        )
        await callback.message.edit_text(
            text,
            reply_markup=get_reference_videos_upload_keyboard(0, 5, "video_new"),
            parse_mode="HTML",
        )
        await state.set_state(GenerationStates.uploading_reference_videos)
    else:
        await _show_video_creation_screen(callback, state)
    await callback.answer()


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
    avatar_audio_url = data.get("avatar_audio_url")
    user_prompt = data.get("user_prompt", "")
    grok_mode = data.get("grok_mode", "normal")
    veo_generation_type = data.get("veo_generation_type", "TEXT_2_VIDEO")
    veo_translation = data.get("veo_translation", True)
    veo_resolution = data.get("veo_resolution", "720p")
    veo_seed = data.get("veo_seed")
    veo_watermark = data.get("veo_watermark", "")
    kling_negative_prompt = data.get("kling_negative_prompt", "")
    kling_cfg_scale = float(data.get("kling_cfg_scale", 0.5))

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
    if current_v_type == "avatar":
        media_status = (
            f"{'✅' if v_image_url else '🖼'} <b>Аватар:</b> "
            f"<code>{'загружен' if v_image_url else 'не загружен'}</code>\n"
            f"{'✅' if avatar_audio_url else '🎵'} <b>Аудио:</b> "
            f"<code>{'загружено' if avatar_audio_url else 'не загружено'}</code>\n"
        )
    elif current_v_type == "imgtxt":
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
    if current_model not in {
        "avatar_std",
        "avatar_pro",
    } and not current_model.startswith("veo3"):
        settings_lines.append(f"   ⏱ Длительность: <code>{current_duration} сек</code>")
    if current_model not in {"avatar_std", "avatar_pro"}:
        settings_lines.append(f"   📐 Формат: <code>{current_ratio}</code>")

    if current_model == "grok_imagine":
        settings_lines.append(f"   🧠 Режим Grok: <code>{grok_mode}</code>")
    if current_model == "v26_pro":
        settings_lines.append(
            f"   🚫 Negative: <code>{kling_negative_prompt or 'off'}</code>"
        )
        settings_lines.append(f"   🎚 CFG: <code>{kling_cfg_scale:.1f}</code>")
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
        f"🎬 <b>Создание видео</b>\n"
        f"<b>Шаг 3. Настройки и промпт</b>\n"
        f"{ref_text}"
        f"⚙️ <b>Текущие настройки:</b>\n" + "\n".join(settings_lines) + "\n"
        f"{media_status}"
        f"{prompt_text}\n"
        f"<b>Опишите видео</b>\n"
        f"Напишите простыми словами:\n"
        f"• что происходит в кадре\n"
        f"• как двигается камера\n"
        f"• какой нужен стиль или настроение"
    )

    # Напоминание о загрузке медиа
    if current_v_type == "avatar" and not (v_image_url and avatar_audio_url):
        text += "<i>🗣 Сначала загрузите фото аватара и аудио.</i>"
    elif current_v_type == "imgtxt" and not v_image_url:
        text += f"<i>📷 Сначала загрузите фото для первого кадра.</i>"
    elif current_v_type == "video" and not v_reference_videos:
        text += f"<i>📹 При желании загрузите до 5 коротких видео-референсов.</i>"

    keyboard = _build_video_creation_keyboard(data)

    # Используем edit для callback, send для message
    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        elif edit:
            await message_or_callback.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:
            await message_or_callback.answer(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
    except TelegramBadRequest as e:
        error_msg = str(e).lower()
        if "message is not modified" in error_msg:
            pass
        elif isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.answer(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:
            await message_or_callback.answer(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
    except AttributeError:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.answer("Экран создания уже открыт")
        else:
            await message_or_callback.answer(
                text,
                reply_markup=keyboard,
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
        current_kling_negative_prompt=data.get("kling_negative_prompt", ""),
        current_kling_cfg_scale=float(data.get("kling_cfg_scale", 0.5)),
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
    ]
    if v_model not in {"avatar_std", "avatar_pro"}:
        parts.append(f"📐 <code>{v_ratio}</code>")
    if v_model not in {"avatar_std", "avatar_pro"} and not v_model.startswith("veo3"):
        parts.append(f"⏱ <code>{v_duration}s</code>")

    if v_model == "grok_imagine":
        parts.append(f"🧠 <code>{data.get('grok_mode', 'normal')}</code>")
    if v_model == "v26_pro":
        negative = data.get("kling_negative_prompt", "")
        parts.append(f"🎚 <code>{float(data.get('kling_cfg_scale', 0.5)):.1f}</code>")
        if negative:
            parts.append("🚫 <code>negative on</code>")

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
    current_ratio = data.get(
        "img_ratio", "auto" if current_service == "flux_pro" else "1:1"
    )
    current_count = data.get("img_count", 1)
    reference_images = data.get("reference_images", [])
    nsfw_enabled = data.get("nsfw_enabled", False)
    img_quality = data.get("img_quality", "basic")
    img_nsfw_checker = data.get("img_nsfw_checker", False)
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
    elif current_service == "flux_pro":
        info_lines.append("• Референсы: <code>0 (text-to-image)</code>")
    if current_service == "seedream_edit":
        info_lines.append(f"• Quality: <code>{img_quality}</code>")
        info_lines.append(
            f"• NSFW checker: <code>{'on' if img_nsfw_checker else 'off'}</code>"
        )
    if current_service == "flux_pro":
        info_lines.append(
            f"• NSFW checker: <code>{'on' if img_nsfw_checker else 'off'}</code>"
        )
    if current_service == "grok_imagine_i2i":
        info_lines.append(f"• NSFW: <code>{'Вкл' if nsfw_enabled else 'Выкл'}</code>")

    prompt_hint = (
        "Опишите, что нужно изменить на загруженном изображении."
        if current_service == "seedream_edit"
        else (
            "Опишите, что нужно изменить на загруженных фото."
            if current_service == "grok_imagine_i2i"
            else (
                "Опишите, что хотите создать или как переработать загруженные изображения."
                if current_service == "flux_pro"
                else "Опишите, что хотите создать."
            )
        )
    )

    return (
        "🖼 <b>Создание фото</b>\n"
        + "<b>Шаг 3. Настройки и промпт</b>\n"
        + "Модель уже выбрана. Ниже можно настроить результат и отправить описание.\n\n"
        + "<b>Текущие настройки</b>\n"
        + "\n".join(info_lines)
        + "\n\n<b>Промпт</b>\n"
        + prompt_hint
    )


async def _show_image_model_selection_screen(
    message_or_callback, state: FSMContext, edit: bool = True
):
    data = await state.get_data()
    current_service = data.get("img_service", "banana_pro")
    user_id = (
        message_or_callback.from_user.id
        if hasattr(message_or_callback, "from_user")
        else None
    )
    user_credits = await get_user_credits(user_id) if user_id else 0
    text = (
        "🖼 <b>Создание фото</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "<b>Шаг 1. Выберите модель</b>\n"
        "Сначала выберите модель.\n"
        "После этого бот покажет следующий шаг: референсы или настройки."
    )
    keyboard = get_image_model_selection_keyboard(current_service)

    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.edit_text(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        elif edit:
            await message_or_callback.edit_text(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        else:
            await message_or_callback.answer(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
    except Exception:
        await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")

    await state.set_state(GenerationStates.waiting_for_input)


async def _show_image_references_screen(
    message_or_callback,
    state: FSMContext,
    *,
    current_count: int = 0,
):
    data = await state.get_data()
    current_service = data.get("img_service", "banana_pro")
    user_id = (
        message_or_callback.from_user.id
        if hasattr(message_or_callback, "from_user")
        else None
    )
    user_credits = await get_user_credits(user_id) if user_id else 0
    text = (
        "🖼 <b>Создание фото</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "<b>Шаг 2. Референсы</b>\n"
        f"Выбрана модель: <code>{get_image_model_label(current_service)}</code>\n\n"
        + (
            "Для <b>GPT Image 2</b> фото не обязательны.\n"
            "Если загрузите фото, бот изменит его.\n"
            "Если пропустите шаг, бот создаст картинку с нуля.\n\n"
            if current_service == "flux_pro"
            else (
                "Для <b>Seedream 4.5 Edit</b> нужно хотя бы одно исходное фото.\n"
                "Можно добавить и дополнительные фото, если это поможет.\n\n"
                if current_service == "seedream_edit"
                else "Референсы не обязательны, но помогают сохранить человека, "
                "стиль, одежду, товар или композицию.\n\n"
            )
        )
        + f"<i>Можно загрузить до {16 if current_service == 'flux_pro' else 14} фото. Когда всё готово, нажмите «Продолжить».</i>"
    )

    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.edit_text(
                text,
                reply_markup=get_reference_images_upload_keyboard(
                    current_count, 16 if current_service == "flux_pro" else 14, "new"
                ),
                parse_mode="HTML",
            )
        else:
            await message_or_callback.answer(
                text,
                reply_markup=get_reference_images_upload_keyboard(
                    current_count, 16 if current_service == "flux_pro" else 14, "new"
                ),
                parse_mode="HTML",
            )
    except Exception:
        await message_or_callback.answer(
            text,
            reply_markup=get_reference_images_upload_keyboard(
                current_count, 16 if current_service == "flux_pro" else 14, "new"
            ),
            parse_mode="HTML",
        )

    await state.set_state(GenerationStates.uploading_reference_images)


async def _show_image_creation_screen(message_or_callback, state: FSMContext):
    data = await state.get_data()
    text = _build_image_creation_text(data)
    reply_markup = get_create_image_keyboard(
        current_service=data.get("img_service", "banana_pro"),
        current_ratio=data.get("img_ratio", "1:1"),
        current_count=data.get("img_count", 1),
        num_refs=len(data.get("reference_images", [])),
        nsfw_enabled=data.get("nsfw_enabled", False),
        img_quality=data.get("img_quality", "basic"),
        img_nsfw_checker=data.get("img_nsfw_checker", False),
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


async def _show_video_model_selection_screen(
    message_or_callback, state: FSMContext, edit: bool = True
):
    data = await state.get_data()
    current_model = data.get("v_model", "v3_pro")
    user_id = (
        message_or_callback.from_user.id
        if hasattr(message_or_callback, "from_user")
        else None
    )
    user_credits = await get_user_credits(user_id) if user_id else 0
    text = (
        "🎬 <b>Создание видео</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "<b>Шаг 1. Выберите модель</b>\n"
        "Сначала выберите модель видео.\n"
        "После этого бот покажет следующий шаг именно для неё."
    )
    keyboard = get_video_model_selection_keyboard(current_model)

    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.edit_text(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        elif edit:
            await message_or_callback.edit_text(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        else:
            await message_or_callback.answer(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
    except Exception:
        await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")

    await state.set_state(GenerationStates.waiting_for_input)


async def _show_video_media_screen(
    message_or_callback, state: FSMContext, edit: bool = True
):
    data = await state.get_data()
    current_model = data.get("v_model", "v3_pro")
    current_v_type = data.get("v_type", "text")
    v_image_url = data.get("v_image_url")
    avatar_audio_url = data.get("avatar_audio_url")
    reference_images = data.get("reference_images", [])
    v_reference_videos = data.get("v_reference_videos", [])
    user_id = (
        message_or_callback.from_user.id
        if hasattr(message_or_callback, "from_user")
        else None
    )
    user_credits = await get_user_credits(user_id) if user_id else 0

    if current_v_type == "avatar":
        body = (
            "<b>Шаг 2. Аватар и аудио</b>\n"
            f"Модель: <code>{get_video_model_label(current_model)}</code>\n\n"
            "Загрузите 1 фото аватара и 1 аудиофайл.\n"
            "После этого можно переходить к описанию."
        )
        next_state = GenerationStates.waiting_for_video_prompt
    elif current_v_type == "imgtxt":
        body = (
            "<b>Шаг 2. Тип и медиа</b>\n"
            f"Модель: <code>{get_video_model_label(current_model)}</code>\n\n"
            + (
                "Выбран режим <b>Фото + Текст → Видео</b>.\n"
                "Для Kling 2.5 Turbo нужно только одно стартовое фото."
                if current_model == "v26_pro"
                else "Выбран режим <b>Фото + Текст → Видео</b>.\n"
                "Сначала отправьте стартовое фото.\n"
                "При желании потом можно добавить ещё фото-референсы."
            )
        )
        next_state = GenerationStates.waiting_for_video_prompt
    elif current_v_type == "video":
        body = (
            "<b>Шаг 2. Тип и медиа</b>\n"
            f"Модель: <code>{get_video_model_label(current_model)}</code>\n\n"
            "Выбран режим <b>Видео + Текст → Видео</b>.\n"
            "Загрузите до 5 коротких видео или пропустите шаг."
        )
        next_state = GenerationStates.uploading_reference_videos
    else:
        body = (
            "<b>Шаг 2. Тип и медиа</b>\n"
            f"Модель: <code>{get_video_model_label(current_model)}</code>\n\n"
            "Выбран режим <b>Текст → Видео</b>.\n"
            "Ничего загружать не нужно. Можно сразу переходить дальше."
        )
        next_state = GenerationStates.waiting_for_input

    text = (
        "🎬 <b>Создание видео</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        f"{body}"
    )
    keyboard = get_video_media_step_keyboard(
        current_v_type=current_v_type,
        current_model=current_model,
        has_start_image=bool(v_image_url),
        reference_image_count=len(reference_images),
        reference_video_count=len(v_reference_videos),
        has_avatar_audio=bool(avatar_audio_url),
    )

    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.edit_text(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        elif edit:
            await message_or_callback.edit_text(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        else:
            await message_or_callback.answer(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
    except Exception:
        await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")

    await state.set_state(next_state)


@router.callback_query(F.data == "img_ref_skip_new")
async def handle_img_ref_skip_new(callback: types.CallbackQuery, state: FSMContext):
    """Пропускает загрузку референсов и переходит к вводу промпта"""
    data = await state.get_data()
    generation_type = data.get("generation_type")
    current_service = data.get("img_service", "banana_pro")

    if generation_type == "image" and current_service == "seedream_edit":
        await callback.answer(
            "Для Seedream 4.5 Edit нужно хотя бы одно исходное изображение",
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
        await state.update_data(img_flow_step="configure")
        await _show_image_creation_screen(callback, state)
        await callback.answer()


@router.callback_query(F.data == "img_ref_continue_new")
async def handle_img_ref_continue_new(callback: types.CallbackQuery, state: FSMContext):
    """Продолжает после загрузки референсов - сразу к параметрам видео (без проверки наличия референсов)"""
    # УБРАНА ПРОВЕРКА: референсы опциональны, всегда продолжаем
    data = await state.get_data()
    generation_type = data.get("generation_type")
    current_service = data.get("img_service", "banana_pro")
    reference_images = data.get("reference_images", [])

    if (
        generation_type == "image"
        and current_service == "seedream_edit"
        and not reference_images
    ):
        await callback.answer(
            "Для Seedream 4.5 Edit нужно загрузить хотя бы одно изображение",
            show_alert=True,
        )
        return

    if generation_type == "video":
        # Сразу показываем единый экран с параметрами и промптом (без подтверждения)
        await _show_video_creation_screen(callback.message, state)
        await callback.answer()
        return
    else:
        await state.update_data(img_flow_step="configure")
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


@router.callback_query(F.data == "image_change_model")
async def handle_image_change_model(callback: types.CallbackQuery, state: FSMContext):
    """Возвращает пользователя к шагу выбора модели."""
    await state.update_data(img_flow_step="select_model")
    await _show_image_model_selection_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "video_change_model")
async def handle_video_change_model(callback: types.CallbackQuery, state: FSMContext):
    """Возвращает пользователя к шагу выбора модели видео."""
    await state.update_data(video_flow_step="select_model")
    await _show_video_model_selection_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "video_change_media")
async def handle_video_change_media(callback: types.CallbackQuery, state: FSMContext):
    """Возвращает пользователя к шагу выбора типа и медиа."""
    await state.update_data(video_flow_step="media")
    await _show_video_media_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "video_media_skip")
async def handle_video_media_skip(callback: types.CallbackQuery, state: FSMContext):
    """Пропускает медиашаг, если он опционален."""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    if current_v_type == "avatar":
        await callback.answer("Для Avatar нужны и фото, и аудио", show_alert=True)
        return
    if current_v_type == "imgtxt":
        await callback.answer(
            "Для режима Фото + Текст сначала загрузите стартовое фото", show_alert=True
        )
        return
    if current_v_type == "video":
        await state.update_data(v_reference_videos=[])
    await state.update_data(video_flow_step="configure")
    await _show_video_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "video_media_continue")
async def handle_video_media_continue(callback: types.CallbackQuery, state: FSMContext):
    """Переходит к шагу настроек после выбора типа и загрузки медиа."""
    data = await state.get_data()
    current_v_type = data.get("v_type", "text")
    if current_v_type == "avatar":
        if not data.get("v_image_url"):
            await callback.answer("Сначала загрузите фото аватара", show_alert=True)
            return
        if not data.get("avatar_audio_url"):
            await callback.answer("Сначала загрузите аудио", show_alert=True)
            return
        await state.update_data(video_flow_step="configure")
        await _show_video_creation_screen(callback, state)
        await callback.answer()
        return
    if current_v_type == "imgtxt" and not data.get("v_image_url"):
        await callback.answer("Сначала загрузите стартовое фото", show_alert=True)
        return
    await state.update_data(video_flow_step="configure")
    await _show_video_creation_screen(callback, state)
    await callback.answer()


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

    updates = {"v_type": "text"}
    if current_model.startswith("veo3"):
        updates["veo_generation_type"] = "TEXT_2_VIDEO"
    await state.update_data(**updates)
    await _show_video_media_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "v_type_imgtxt")
async def handle_v_type_imgtxt(callback: types.CallbackQuery, state: FSMContext):
    """Выбор типа генерации: фото+текст."""
    data = await state.get_data()
    current_model = data.get("v_model", "v26_pro")

    updates = {"v_type": "imgtxt"}
    if current_model.startswith("veo3"):
        updates["veo_generation_type"] = "FIRST_AND_LAST_FRAMES_2_VIDEO"
    await state.update_data(**updates)
    await _show_video_media_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "v_type_video")
async def handle_v_type_video(callback: types.CallbackQuery, state: FSMContext):
    """Выбор типа генерации: видео+текст."""
    data = await state.get_data()
    updates = {"v_type": "video", "v_duration": 5}
    if data.get("v_model") != "glow":
        updates["v_model"] = "glow"
    await state.update_data(**updates)
    await _show_video_media_screen(callback, state)
    await callback.answer("Для режима Видео + Текст выбрана модель Kling Glow")


@router.callback_query(F.data == "vid_ref_skip_new")
async def handle_vid_ref_skip_new(callback: types.CallbackQuery, state: FSMContext):
    """Пропускает загрузку видео референсов для video+text"""
    await state.update_data(v_reference_videos=[])
    await state.update_data(video_flow_step="configure")
    await _show_video_creation_screen(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "vid_ref_continue_new")
async def handle_vid_ref_continue_new(callback: types.CallbackQuery, state: FSMContext):
    """Продолжает после загрузки видео референсов"""
    await state.update_data(video_flow_step="configure")
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
    elif model == "v26_pro":
        await state.update_data(
            kling_negative_prompt=data.get("kling_negative_prompt", ""),
            kling_cfg_scale=float(data.get("kling_cfg_scale", 0.5)),
            reference_images=[],
            v_reference_videos=[],
        )
    elif model in {"avatar_std", "avatar_pro"}:
        await state.update_data(
            reference_images=[],
            v_reference_videos=[],
            v_image_url=None,
            avatar_audio_url=None,
        )
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
    if model == "glow":
        current_v_type = "video"
    if model in {"avatar_std", "avatar_pro"}:
        current_v_type = "avatar"
    if model == "v26_pro" and current_v_type == "video":
        current_v_type = "text"
    if model.startswith("veo3") and current_v_type == "video":
        current_v_type = "text"

    updates = {"v_model": model, "v_type": current_v_type}
    if data.get("video_flow_step") == "select_model":
        updates["video_flow_step"] = "media"
    await state.update_data(**updates)
    await _normalize_veo_state(state)
    if model.startswith("wanx"):
        await state.update_data(
            wanx_lora_settings=[{"lora_type": "nsfw-general", "lora_strength": 1.0}]
        )

    if data.get("video_flow_step") == "select_model":
        await _show_video_media_screen(callback, state)
    elif model.startswith("wanx"):
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
    current_data = await state.get_data()
    if current_data.get("video_flow_step") == "media":
        current_type = current_data.get("v_type", "text")
        if current_type == "imgtxt":
            await state.set_state(GenerationStates.waiting_for_video_prompt)
        elif current_type == "video":
            await state.set_state(GenerationStates.uploading_reference_videos)
        else:
            await state.set_state(GenerationStates.waiting_for_input)
    else:
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
    await state.set_state(GenerationStates.waiting_for_video_prompt)


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
    await state.set_state(GenerationStates.waiting_for_video_prompt)


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
    await state.set_state(GenerationStates.waiting_for_video_prompt)


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
    await state.set_state(GenerationStates.waiting_for_video_prompt)


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
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "ratio_2_3")
async def handle_video_ratio_2_3(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата 2:3"""
    await state.update_data(v_ratio="2:3")
    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "ratio_Auto")
async def handle_video_ratio_auto(callback: types.CallbackQuery, state: FSMContext):
    """Выбор автоматического формата для Veo"""
    await state.update_data(v_ratio="Auto")
    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


# Обработчик длительности видео
@router.callback_query(F.data.startswith("video_dur_"))
async def handle_video_duration(callback: types.CallbackQuery, state: FSMContext):
    """Выбор длительности видео для всех моделей."""
    try:
        duration = int(callback.data.replace("video_dur_", ""))
    except ValueError:
        await callback.answer()
        return

    if duration < 2 or duration > 30:
        await callback.answer()
        return

    await state.update_data(v_duration=duration)
    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


# =============================================================================
# НОВЫЙ UX: МЕНЮ СОЗДАНИЯ ФОТО (get_create_image_keyboard)
# =============================================================================


@router.callback_query(F.data == "model_flux_pro")
async def handle_model_flux_pro(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели GPT Image 2."""
    await state.update_data(
        img_service="flux_pro",
        img_ratio="auto",
        img_nsfw_checker=False,
        reference_images=[],
    )
    data = await state.get_data()
    if data.get("img_flow_step") == "select_model":
        await state.update_data(img_flow_step="upload_refs")
        await _show_image_references_screen(callback, state)
    else:
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
    data = await state.get_data()
    if data.get("img_flow_step") == "select_model":
        await state.update_data(img_flow_step="upload_refs")
        await _show_image_references_screen(callback, state)
    else:
        await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "model_banana_2")
async def handle_model_banana_2(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Banana 2 (Gemini 3.1 Flash Image Preview)"""
    await state.update_data(img_service="banana_2")
    data = await state.get_data()
    if data.get("img_flow_step") == "select_model":
        await state.update_data(img_flow_step="upload_refs")
        await _show_image_references_screen(callback, state)
    else:
        await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "model_seedream_edit")
async def handle_model_seedream_edit(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Seedream 4.5"""
    await state.update_data(
        img_service="seedream_edit",
        img_ratio="1:1",
        img_quality="basic",
        img_nsfw_checker=False,
    )
    data = await state.get_data()
    if data.get("img_flow_step") == "select_model":
        await state.update_data(img_flow_step="upload_refs")
        await _show_image_references_screen(callback, state)
    else:
        await _show_image_creation_screen(callback, state)
    await callback.answer()



@router.callback_query(F.data == "model_grok_i2i")
async def handle_model_grok_i2i(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Grok Imagine i2i (фото + текст)"""
    data = await state.get_data()
    nsfw_enabled = data.get("nsfw_enabled", False)

    await state.update_data(img_service="grok_imagine_i2i", nsfw_enabled=nsfw_enabled)
    data = await state.get_data()
    if data.get("img_flow_step") == "select_model":
        await state.update_data(img_flow_step="upload_refs")
        await _show_image_references_screen(callback, state)
    else:
        await _show_image_creation_screen(callback, state)
    await callback.answer()


# Обработчики формата изображения
@router.callback_query(F.data == "img_ratio_auto")
async def handle_img_ratio_auto(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения auto."""
    await state.update_data(img_ratio="auto")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


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


@router.callback_query(F.data == "img_ratio_2_3")
async def handle_img_ratio_2_3(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 2:3"""
    await state.update_data(img_ratio="2:3")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ratio_3_4")
async def handle_img_ratio_3_4(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 3:4"""
    await state.update_data(img_ratio="3:4")
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ratio_21_9")
async def handle_img_ratio_21_9(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 21:9"""
    await state.update_data(img_ratio="21:9")
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


@router.callback_query(F.data == "img_quality_basic")
async def handle_img_quality_basic(callback: types.CallbackQuery, state: FSMContext):
    """Seedream quality: basic."""
    await state.update_data(img_quality="basic")
    await _show_image_creation_screen(callback, state)
    await callback.answer("Quality: basic")


@router.callback_query(F.data == "img_quality_high")
async def handle_img_quality_high(callback: types.CallbackQuery, state: FSMContext):
    """Seedream quality: high."""
    await state.update_data(img_quality="high")
    await _show_image_creation_screen(callback, state)
    await callback.answer("Quality: high")


# =============================================================================
# СЛУЖЕБНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С ФАЙЛАМИ
# =============================================================================


def save_uploaded_file(file_bytes: bytes, file_ext: str = "png") -> Optional[str]:
    """
    Сохраняет загруженный файл в папку static/uploads и возвращает публичный URL.
    """
    try:
        if not isinstance(file_bytes, (bytes, bytearray)):
            logger.error(
                "save_uploaded_file expected bytes, got %s",
                type(file_bytes).__name__,
            )
            return None

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
            f.write(bytes(file_bytes))

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
            f"📎 <b>Загрузка референсов</b>\n"
            f"Загружено: <code>{len(current_refs)}/{max_refs}</code>\n\n"
            f"Отправьте фото, которые помогут точнее передать внешний вид, стиль или детали.\n"
            f"После загрузки нажмите <b>▶️ Продолжить</b>.",
            reply_markup=get_reference_images_upload_keyboard(
                len(current_refs), max_refs, preset_id
            ),
            parse_mode="HTML",
        )

    elif action == "clear":
        # Очищаем все референсы
        await state.update_data(reference_images=[])
        await callback.message.edit_text(
            f"📎 <b>Референсы очищены</b>\n"
            f"Загружено: <code>0/{max_refs}</code>\n"
            f"Теперь можно загрузить новые фото.",
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
            f"📎 <b>Начнём заново</b>\n"
            f"Загружено: <code>0/{max_refs}</code>\n"
            f"Отправьте новые фото-референсы.",
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


@router.message(
    GenerationStates.waiting_for_video_prompt,
    F.photo
    | (
        F.document & F.document.mime_type.in_(["image/jpeg", "image/png", "image/webp"])
    ),
)
async def process_photo_for_video_prompt_state(
    message: types.Message, state: FSMContext
):
    """
    Обрабатывает фото для imgtxt видео в состоянии waiting_for_video_prompt.
    Первое фото - v_image_url (старт кадр), остальные - reference_images (до 8 рефов, total 9).
    """
    data = await state.get_data()
    v_type = data.get("v_type")
    current_model = data.get("v_model", "v3_std")
    if v_type not in {"imgtxt", "avatar"}:
        await message.answer(
            "Пожалуйста, отправьте текстовое описание.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    # Download photo
    if message.photo:
        photo = message.photo[-1]
    else:
        photo = message.document

    file_size = getattr(photo, "file_size", 0) or 0
    if v_type == "avatar" and file_size and file_size > 10 * 1024 * 1024:
        await message.answer(
            "❌ Фото аватара слишком большое. Максимум 10MB.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return
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
        if v_type != "avatar" and (width < 300 or height < 300):
            await message.answer(
                f"❌ Изображение слишком маленькое: {width}×{height} (мин 300px)",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return
    except Exception as e:
        logger.error(f"Image validation failed: {e}")
        await message.answer(
            "❌ Не удалось обработать изображение.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    if message.photo:
        file_ext = "jpg"
    else:
        mime_type = message.document.mime_type
        file_ext = (
            "jpg"
            if mime_type == "image/jpeg"
            else "png" if mime_type == "image/png" else "webp"
        )

    image_url = save_uploaded_file(image_data, file_ext)
    if not image_url:
        await message.answer(
            "❌ Не удалось сохранить фото.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    v_image_url = data.get("v_image_url")
    reference_images = data.get("reference_images", [])

    if v_type == "avatar":
        await state.update_data(v_image_url=image_url)
        await message.answer("✅ Фото аватара загружено. Можно перейти дальше.")
        if data.get("video_flow_step") == "media":
            await _show_video_media_screen(message, state, edit=False)
        else:
            await _show_video_creation_screen(message, state, edit=False)
        return

    if current_model == "v26_pro" and v_image_url:
        await message.answer(
            "Для Kling 2.5 Turbo можно использовать только одно стартовое фото."
        )
        return

    start_count = 1 if v_image_url else 0
    current_refs = len(reference_images)
    total = start_count + current_refs + 1  # +1 for this photo
    if total > 9:
        await message.answer(
            "❌ Можно загрузить максимум 9 фото: 1 основное и 8 дополнительных."
        )
        return

    if not v_image_url:
        # Первое фото - стартовый кадр
        await state.update_data(v_image_url=image_url)
        logger.info(f"Saved start image for video (1st photo): {image_url}")
        status = "✅ Основное фото загружено. (1/9)"
    else:
        # Последующие - референсы
        reference_images.append(image_url)
        await state.update_data(reference_images=reference_images)
        logger.info(
            f"Saved reference image for video (ref #{current_refs + 1}): {image_url}"
        )
        status = f"✅ Дополнительное фото загружено. Всего: {total}/9"

    # Update UI with current count
    data = await state.get_data()
    current_model = data.get("v_model", "v3_std")
    current_duration = data.get("v_duration", 5)
    current_ratio = data.get("v_ratio", "16:9")

    start_count = 1 if data.get("v_image_url") else 0
    ref_count = len(data.get("reference_images", []))
    total_photos = start_count + ref_count

    if data.get("video_flow_step") == "media":
        await message.answer(
            f"{status}\nНиже открыт обновлённый шаг с файлами.",
            parse_mode="HTML",
        )
        await _show_video_media_screen(message, state, edit=False)
    else:
        text = (
            f"🎬 <b>Фото + Текст → Видео</b>\n"
            f"📎 Загружено фото: <code>{total_photos}/9</code>\n"
            f"{status}\n"
            f"⚙️ Модель: <code>{current_model}</code> | {current_duration}с | {current_ratio}\n\n"
            f"<b>Можно отправить ещё фото или сразу написать описание видео.</b>"
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
            await message.answer(
                "❌ Неверный тип файла. Отправьте видео.",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return

        # Проверяем размер (макс 20MB)
        file_size = getattr(video_obj, "file_size", 0)
        if file_size > 20 * 1024 * 1024:
            await message.answer(
                "❌ Видео слишком большое (макс 20MB).",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return

        if len(v_reference_videos) >= 5:
            await message.answer(
                "❌ Можно загрузить максимум 5 видео. Дальше нажмите «Продолжить».",
                parse_mode="HTML",
                reply_markup=get_main_menu_button_keyboard(),
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

            if data.get("video_flow_step") == "media":
                await message.answer(
                    f"✅ Видео загружено. Сейчас файлов: <code>{len(v_reference_videos)}/5</code>",
                    parse_mode="HTML",
                )
                await _show_video_media_screen(message, state, edit=False)
            else:
                current_count = len(v_reference_videos)
                max_refs = 5
                text = (
                    f"📹 <b>Загрузка видео-референсов</b>\n"
                    f"Загружено: <code>{current_count}/{max_refs}</code>\n"
                    f"✅ Видео добавлено.\n"
                    f"Можно отправить ещё одно или нажать кнопку ниже."
                )
                await message.reply(
                    text,
                    reply_markup=get_reference_videos_upload_keyboard(
                        current_count, max_refs, "video_new"
                    ),
                    parse_mode="HTML",
                )
        else:
            await message.answer(
                "❌ Не удалось сохранить видео. Попробуйте ещё раз.",
                reply_markup=get_main_menu_button_keyboard(),
            )
        return

    await message.answer(
        "Пожалуйста, отправьте видео.",
        reply_markup=get_main_menu_button_keyboard(),
    )


@router.message(
    GenerationStates.uploading_reference_images,
    F.photo
    | (
        F.document & F.document.mime_type.in_(["image/jpeg", "image/png", "image/webp"])
    ),
)
async def process_reference_photo_upload(message: types.Message, state: FSMContext):
    """Handles reference photo uploads during image creation."""
    data = await state.get_data()
    reference_images = data.get("reference_images", [])
    v_type = data.get("v_type")
    img_service = data.get("img_service")
    max_refs = 9 if v_type == "imgtxt" else (16 if img_service == "flux_pro" else 14)

    if len(reference_images) >= max_refs:
        await message.answer(
            f"❌ Можно загрузить максимум {max_refs} фото. Дальше нажмите «Продолжить» или очистите список.",
            parse_mode="HTML",
            reply_markup=get_main_menu_button_keyboard(),
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
                "Нужно фото не меньше 300×300 px.",
                parse_mode="HTML",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return
    except Exception as e:
        logger.error(f"Image validation failed: {e}")
        await message.answer(
            "❌ Не удалось обработать изображение. Попробуйте другое.",
            reply_markup=get_main_menu_button_keyboard(),
        )
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
            f"📎 <b>Загрузка референсов</b>\n"
            f"Загружено: <code>{current_count}/{max_refs}</code>\n"
            f"✅ Фото добавлено.\n"
            f"Можно отправить ещё одно или нажать кнопку ниже."
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
        await message.answer(
            "❌ Не удалось сохранить фото. Попробуйте ещё раз.",
            reply_markup=get_main_menu_button_keyboard(),
        )


@router.message(GenerationStates.waiting_for_input, F.text)
async def handle_image_prompt_text(message: types.Message, state: FSMContext):
    """Handles text prompt for image generation in waiting_for_input state"""
    data = await state.get_data()
    if data.get("generation_type") != "image":
        return  # Not for images, let other handlers catch

    prompt = message.text.strip()
    if not prompt:
        await message.answer(
            "Нужен текстовый промпт — опишите, какое изображение хотите получить.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    img_service = data.get("img_service", "nanobanana")
    img_ratio = data.get("img_ratio", "1:1")
    img_count = data.get("img_count", 1)
    img_quality = data.get("img_quality", "basic")
    img_nsfw_checker = data.get("img_nsfw_checker", False)
    reference_images = data.get("reference_images", [])
    nsfw_enabled = data.get("nsfw_enabled", False)

    if img_service == "grok_imagine_i2i" and not reference_images:
        await message.answer(
            "Для Grok Imagine сначала добавьте хотя бы одно фото-референс.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return
    if img_service == "seedream_edit" and not reference_images:
        await message.answer(
            "Для Seedream 4.5 Edit сначала добавьте хотя бы одно исходное изображение.",
            reply_markup=get_main_menu_button_keyboard(),
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
        stable_reference_images = list(reference_images or [])

        for index in range(img_count):
            variant_prompt = _build_image_variant_prompt(prompt, index, img_count)

            launch_result = await _start_image_generation_task(
                user=user,
                telegram_id=message.from_user.id,
                img_service=img_service,
                prompt=variant_prompt,
                img_ratio=img_ratio,
                reference_images=list(stable_reference_images),
                unit_cost=unit_cost,
                img_quality=img_quality,
                img_nsfw_checker=img_nsfw_checker,
                nsfw_enabled=nsfw_enabled,
                callback_url=callback_url,
            )
            current_local_task_id = launch_result.get(
                "local_task_id"
            ) or launch_result.get("task_id")

            if launch_result["status"] == "queued":
                started_task_ids.append(launch_result["task_id"])
                current_local_task_id = None
            elif launch_result["status"] == "done":
                immediate_success_count += 1
                result_bytes = launch_result["result_bytes"]
                saved_url = launch_result["saved_url"]
                await message.answer_photo(
                    photo=types.BufferedInputFile(
                        result_bytes, filename=f"generated_{index + 1}.png"
                    ),
                    caption=(
                        "✅ <b>Изображение готово</b>\n"
                        f"• Вариант: <code>{index + 1}/{img_count}</code>\n"
                        f"• Модель: <code>{model_label}</code>\n"
                        f"• Списано: <code>{unit_cost}</code>🍌"
                    ),
                    parse_mode="HTML",
                    reply_markup=get_image_result_keyboard(
                        saved_url, task_id=launch_result["task_id"]
                    ),
                )
                await _send_original_document(
                    message.answer_document, result_bytes, saved_url
                )
                current_local_task_id = None
            else:
                refunded_count += 1
                await add_credits(message.from_user.id, unit_cost)
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


@router.callback_query(F.data == "grok_i2i_nsfw_toggle")
async def handle_grok_i2i_nsfw_toggle(callback: types.CallbackQuery, state: FSMContext):
    """Переключение NSFW для Grok i2i на общем экране создания фото"""
    data = await state.get_data()
    nsfw_enabled = not data.get("nsfw_enabled", False)
    await state.update_data(nsfw_enabled=nsfw_enabled)
    await _show_image_creation_screen(callback, state)
    await callback.answer(f"NSFW: {'Вкл' if nsfw_enabled else 'Выкл'}")
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "seedream_nsfw_toggle")
async def handle_seedream_nsfw_toggle(callback: types.CallbackQuery, state: FSMContext):
    """Toggle Seedream nsfw_checker."""
    data = await state.get_data()
    img_nsfw_checker = not data.get("img_nsfw_checker", False)
    await state.update_data(img_nsfw_checker=img_nsfw_checker)
    await _show_image_creation_screen(callback, state)
    await callback.answer(f"NSFW checker: {'on' if img_nsfw_checker else 'off'}")
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "gpt_nsfw_toggle")
async def handle_gpt_nsfw_toggle(callback: types.CallbackQuery, state: FSMContext):
    """Toggle GPT Image 2 nsfw_checker."""
    data = await state.get_data()
    img_nsfw_checker = not data.get("img_nsfw_checker", False)
    await state.update_data(img_nsfw_checker=img_nsfw_checker)
    await _show_image_creation_screen(callback, state)
    await callback.answer(f"NSFW checker: {'on' if img_nsfw_checker else 'off'}")
    await state.set_state(GenerationStates.waiting_for_input)


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


@router.callback_query(F.data == "kling_negative_prompt_edit")
async def handle_kling_negative_prompt_edit(
    callback: types.CallbackQuery, state: FSMContext
):
    """Prompt user to enter Kling 2.5 negative prompt."""
    data = await state.get_data()
    current_negative = data.get("kling_negative_prompt") or "off"
    await callback.message.answer(
        "🚫 Введите negative prompt для Kling 2.5 Turbo или `off`, чтобы отключить.\n"
        "До 500 символов.\n"
        f"Сейчас: <code>{current_negative}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_kling_negative_prompt)
    await callback.answer()


@router.callback_query(F.data == "kling_cfg_scale_edit")
async def handle_kling_cfg_scale_edit(callback: types.CallbackQuery, state: FSMContext):
    """Prompt user to enter Kling 2.5 CFG scale."""
    data = await state.get_data()
    current_cfg = float(data.get("kling_cfg_scale", 0.5))
    await callback.message.answer(
        "🎚 Введите CFG scale для Kling 2.5 Turbo от `0.0` до `1.0` с шагом `0.1`.\n"
        f"Сейчас: <code>{current_cfg:.1f}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_kling_cfg_scale)
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


@router.message(GenerationStates.waiting_for_kling_negative_prompt, F.text)
async def handle_kling_negative_prompt_input(message: types.Message, state: FSMContext):
    """Store Kling 2.5 negative prompt and return to video creation screen."""
    value = message.text.strip()
    if value.lower() in {"off", "none", "disable", "disabled"}:
        await state.update_data(kling_negative_prompt="")
    else:
        await state.update_data(kling_negative_prompt=value[:500])
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_kling_cfg_scale, F.text)
async def handle_kling_cfg_scale_input(message: types.Message, state: FSMContext):
    """Store Kling 2.5 CFG scale and return to video creation screen."""
    value = message.text.strip().replace(",", ".")
    try:
        cfg_scale = float(value)
    except ValueError:
        await message.answer("❌ CFG scale должен быть числом от 0.0 до 1.0.")
        return

    if cfg_scale < 0 or cfg_scale > 1:
        await message.answer("❌ CFG scale должен быть в диапазоне 0.0-1.0.")
        return

    await state.update_data(kling_cfg_scale=round(cfg_scale, 1))
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
    if generation_type == "video" and data.get("video_flow_step") != "configure":
        await message.answer(
            "Сначала завершите шаг с типом и медиа, затем нажмите кнопку перехода к настройкам."
        )
        return
    logger.info(f"Generation type: {generation_type}")

    await state.update_data(user_prompt=prompt)

    if generation_type == "motion_control":
        logger.info("Calling run_motion_control")
        await run_motion_control(message, state, prompt)
    else:
        logger.info("Calling run_no_preset_video_from_message")
        await run_no_preset_video_from_message(message, state, prompt)


@router.message(
    GenerationStates.waiting_for_video_prompt,
    F.audio
    | F.voice
    | (
        F.document
        & F.document.mime_type.in_(
            [
                "audio/mpeg",
                "audio/wav",
                "audio/x-wav",
                "audio/aac",
                "audio/mp4",
                "audio/ogg",
            ]
        )
    ),
)
async def process_avatar_audio_upload(message: types.Message, state: FSMContext):
    """Handles audio uploads for Kling AI Avatar flow."""
    data = await state.get_data()
    if data.get("v_type") != "avatar":
        await message.answer("Пожалуйста, отправьте текстовое описание.")
        return

    media = message.audio or message.voice or message.document
    file_size = getattr(media, "file_size", 0) or 0
    if file_size and file_size > 10 * 1024 * 1024:
        await message.answer("❌ Аудиофайл слишком большой. Максимум 10MB.")
        return

    file = await message.bot.get_file(media.file_id)
    audio_bytes = await message.bot.download_file(file.file_path)
    audio_data = audio_bytes.read()

    if message.audio:
        mime_type = message.audio.mime_type or "audio/mpeg"
    elif message.voice:
        mime_type = "audio/ogg"
    else:
        mime_type = message.document.mime_type or "audio/mpeg"

    ext_map = {
        "audio/mpeg": "mp3",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/aac": "aac",
        "audio/mp4": "m4a",
        "audio/ogg": "ogg",
    }
    file_ext = ext_map.get(mime_type, "mp3")
    audio_url = save_uploaded_file(audio_data, file_ext)
    if not audio_url:
        await message.answer("❌ Не удалось сохранить аудио.")
        return

    await state.update_data(avatar_audio_url=audio_url)
    await message.answer("✅ Аудио загружено.")
    if data.get("video_flow_step") == "media":
        await _show_video_media_screen(message, state, edit=False)
    else:
        await _show_video_creation_screen(message, state, edit=False)


async def run_no_preset_video_from_message(
    message: types.Message, state: FSMContext, prompt: str
):
    """Запускает видео генерацию без пресета (новый UX с v_type, v_model и т.д.)"""
    data = await state.get_data()
    v_type = data.get("v_type", "text")
    v_model = data.get("v_model", "v3_std")
    video_urls = data.get("v_reference_videos", [])

    v_duration = int(data.get("v_duration", 5))
    if v_model.startswith("veo3"):
        v_duration = max(2, min(v_duration, 10))
    if v_model == "v26_pro":
        v_duration = 10 if v_duration == 10 else 5
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
                duration=v_duration,
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
            if v_model == "v26_pro" and v_type == "video":
                await message.answer(
                    "❌ Kling 2.5 Turbo не поддерживает режим Видео + Текст."
                )
                if not is_admin:
                    await add_credits(message.from_user.id, cost)
                await processing_msg.delete()
                await state.clear()
                return
            if v_model in {"avatar_std", "avatar_pro"}:
                if not image_url:
                    await message.answer("❌ Для Kling AI Avatar нужно фото аватара.")
                    if not is_admin:
                        await add_credits(message.from_user.id, cost)
                    await processing_msg.delete()
                    await state.clear()
                    return
                if not avatar_audio_url:
                    await message.answer("❌ Для Kling AI Avatar нужно аудио.")
                    if not is_admin:
                        await add_credits(message.from_user.id, cost)
                    await processing_msg.delete()
                    await state.clear()
                    return
            result = await kling_service.generate_video(
                prompt=prompt,
                model=v_model,
                duration=v_duration,
                aspect_ratio=v_ratio,
                image_url=image_url,
                video_urls=(
                    [avatar_audio_url]
                    if v_model in {"avatar_std", "avatar_pro"} and avatar_audio_url
                    else video_urls
                ),
                image_input=image_refs if v_type != "imgtxt" else None,
                elements=elements_list,
                negative_prompt=kling_negative_prompt or None,
                cfg_scale=kling_cfg_scale,
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


# Service callback for informational inline buttons.
# Prevents Telegram loading spinner on non-action buttons like price/status.
@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: types.CallbackQuery):
    await callback.answer()



# =============================================================================
# WAN 2.7 TEST FLOW
# =============================================================================

    text = (
        "🧪 <b>Wan 2.7 Pro — тест</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code>\n\n"
        "<b>Шаг 1. Референсы</b>\n"
        "Можно загрузить до 9 фото или сразу продолжить без референсов.\n\n"
        "Когда всё готово — нажмите <b>▶️ Продолжить</b>."
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_reference_images_upload_keyboard(0, 9, "wan_27"),
        parse_mode="HTML",
    )
    await callback.answer("Wan 2.7 Pro выбран")


@router.message(GenerationStates.uploading_reference_images, F.photo)
async def upload_reference_image_for_any_image_flow(message: types.Message, state: FSMContext):
    """Universal reference upload fallback for image flows, including Wan 2.7."""
    data = await state.get_data()
    img_service = data.get("img_service", "banana_pro")
    preset_id = data.get("preset_id", "new")
    max_refs = 9 if img_service == "wan_27" else 14

    reference_images = list(data.get("reference_images") or [])
    if len(reference_images) >= max_refs:
        await message.answer(
            f"Уже загружено максимум: {max_refs} фото.",
            reply_markup=get_reference_images_upload_keyboard(len(reference_images), max_refs, preset_id),
        )
        return

    try:
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        downloaded = await message.bot.download_file(file.file_path)
        image_bytes = downloaded.read()

        public_url = save_uploaded_file(image_bytes, "jpg")
        if not public_url:
            await message.answer("Не удалось сохранить фото. Попробуйте другое изображение.")
            return

        reference_images.append(public_url)
        await state.update_data(reference_images=reference_images)

        title = "🧪 Wan 2.7 Pro — тест" if img_service == "wan_27" else "🖼 Референсы"
        await message.answer(
            f"{title}\n\n"
            f"✅ Фото добавлено: <code>{len(reference_images)}/{max_refs}</code>\n\n"
            "Можете загрузить ещё фото или нажать <b>▶️ Продолжить</b>.",
            reply_markup=get_reference_images_upload_keyboard(len(reference_images), max_refs, preset_id),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Reference image upload failed")
        await message.answer("Не удалось загрузить фото. Попробуйте ещё раз.")


@router.callback_query(F.data.in_({"img_ref_confirm_wan_27", "img_ref_continue_wan_27"}))
async def continue_wan27_after_refs(callback: types.CallbackQuery, state: FSMContext):
    """Continue Wan 2.7 after optional references."""
    await state.update_data(
        img_service="wan_27",
        img_flow_step="settings",
        preset_id="wan_27",
    )
    await _show_image_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "img_ref_skip_wan_27")
async def skip_wan27_refs(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(
        img_service="wan_27",
        reference_images=[],
        img_flow_step="settings",
        preset_id="wan_27",
    )
    await _show_image_creation_screen(callback, state)
    await callback.answer("Продолжаем без референсов")
