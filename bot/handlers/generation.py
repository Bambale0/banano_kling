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
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from PIL import Image

from bot.config import config
from bot.database import (
    add_credits,
    add_generation_history,
    add_generation_task,
    check_can_afford,
    complete_video_task,
    deduct_credits,
    delete_saved_reference,
    get_or_create_user,
    get_task_by_id,
    get_user_credits,
    get_user_settings,
    list_saved_references,
)
from bot.keyboards import (
    get_back_keyboard,
    get_create_image_keyboard,
    get_create_video_keyboard,
    get_gemini_omni_result_keyboard,
    get_image_model_label,
    get_image_model_selection_keyboard,
    get_image_result_keyboard,
    get_main_menu_button_keyboard,
    get_main_menu_keyboard,
    get_reference_images_upload_keyboard,
    get_reference_videos_upload_keyboard,
    get_saved_reference_picker_keyboard,
    get_video_media_step_keyboard,
    get_video_model_label,
    get_video_model_selection_keyboard,
    get_video_type_label,
)
from bot.services.gemini_service import gemini_service
from bot.services.gemini_omni_service import gemini_omni_service
from bot.services.gpt_image_service import gpt_image_service
from bot.services.grok_service import grok_service
from bot.services.nano_banana_2_service import nano_banana_2_service
from bot.services.nano_banana_pro_service import nano_banana_pro_service
from bot.services.preset_manager import preset_manager
from bot.services.seedream_service import seedream_service
from bot.services.reference_storage_service import save_reference_file
from bot.services.veo_service import veo_service
from bot.services.wan27_service import wan27_service
from bot.states import GenerationStates
from bot.utils.help_texts import (
    UserHints,
    format_generation_options,
    get_prompt_tips,
    get_reference_images_help,
)
from bot.utils.user_facing_errors import make_user_friendly_generation_error
from bot.utils.validators import detect_explicit_prompt_policy_violation
from bot.video_reference_policy import (
    choose_video_reference_model,
    get_max_video_image_references,
    get_max_video_references,
    normalize_reference_urls,
    video_model_supports_reference_videos,
)

logger = logging.getLogger(__name__)
router = Router()
_reference_upload_locks: dict[int, asyncio.Lock] = {}

def _parse_omni_ids(raw: str, *, max_count: int) -> list[str]:
    """Parse comma/space separated Gemini Omni reusable asset ids."""
    value = (raw or "").strip()
    if value.lower() in {"off", "none", "нет", "clear", "очистить", "-"}:
        return []
    tokens = re.split(r"[\s,;]+", value)
    parsed: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        item = token.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        parsed.append(item)
        if len(parsed) >= max_count:
            break
    return parsed


def _derive_omni_name(text: str, fallback: str) -> str:
    value = re.sub(r"\s+", " ", (text or "").strip())
    value = re.sub(r"[^\w\s.-]", "", value, flags=re.UNICODE).strip()
    return (value[:20] or fallback)[:20]


def _get_reference_upload_lock(user_id: int) -> asyncio.Lock:
    lock = _reference_upload_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _reference_upload_locks[user_id] = lock
    return lock


async def _persist_reusable_image_reference(
    telegram_id: int,
    image_data: bytes,
    file_ext: str,
    *,
    original_filename: str | None = None,
    content_type: str | None = None,
) -> Optional[str]:
    return await _persist_reusable_media_reference(
        telegram_id,
        image_data,
        file_ext,
        kind="image",
        original_filename=original_filename,
        content_type=content_type,
    )


async def _persist_reusable_media_reference(
    telegram_id: int,
    file_data: bytes,
    file_ext: str,
    *,
    kind: str,
    original_filename: str | None = None,
    content_type: str | None = None,
) -> Optional[str]:
    public_url, _saved_reference = await save_reference_file(
        telegram_id,
        file_data,
        file_ext=file_ext,
        kind=kind,
        original_filename=original_filename,
        content_type=content_type,
        source="telegram_bot",
    )
    if public_url:
        return public_url
    return save_uploaded_file(file_data, file_ext)


@router.message(CommandStart(), StateFilter("*"))
async def cmd_start_interrupt(message: types.Message, state: FSMContext):
    """/start interrupts any active FSM state and redirects to main menu handler"""
    from bot.handlers.common import cmd_start as _cmd_start

    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
    await _cmd_start(message, state)


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
        return "nano-banana-2"
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


def _get_max_image_references(img_service: str | None) -> int:
    # Product rule: users may attach up to 8 reference images before generation.
    # Saved-reference library is limited separately in storage.
    return 8


def _classify_image_generation_result(result) -> tuple[str, Optional[str]]:
    """Normalize provider responses into queued/done/failed states."""
    if isinstance(result, dict):
        if result.get("task_id"):
            return "queued", None
        error_message = result.get("message") or result.get("error") or str(result)
        return "failed", make_user_friendly_generation_error(error_message)
    if isinstance(result, (bytes, bytearray)):
        return "done", None
    if result:
        return "failed", make_user_friendly_generation_error(
            f"Unexpected result type: {type(result).__name__}"
        )
    return "failed", None


def _enforce_generation_prompt_policy(prompt: str, *, medium: str) -> Optional[str]:
    """Local prompt moderation is disabled; let the upstream provider decide."""
    return None


def _enforce_image_prompt_policy(prompt: str) -> Optional[str]:
    return _enforce_generation_prompt_policy(prompt, medium="image")


def _enforce_video_prompt_policy(prompt: str) -> Optional[str]:
    return _enforce_generation_prompt_policy(prompt, medium="video")


def _apply_safe_prompt_framing(img_service: str, prompt: str) -> str:
    """Reduce false positives for benign fashion/editorial prompts without bypassing policy."""
    prompt = (prompt or "").strip()
    if not prompt:
        return prompt
    if img_service not in {
        "banana_pro",
        "banana_2",
        "nanobanana",
        "grok_imagine_i2i",
        "wan_27",
    }:
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


def _apply_reference_detail_preservation(
    img_service: str, prompt: str, reference_images: list[str]
) -> str:
    """For reference-based generation, strongly lock identity and outfit details."""
    prompt = (prompt or "").strip()
    if not reference_images or img_service not in {
        "banana_pro",
        "banana_2",
        "nanobanana",
        "grok_imagine_i2i",
        "seedream_edit",
        "wan_27",
        "flux_pro",
    }:
        return prompt
    instruction = """
STRICT IDENTITY AND DETAIL PRESERVATION. HIGHEST PRIORITY.

Treat the reference image(s) as the exact source of truth.
Recreate the same person or people with no identity drift and no redesign.

Preserve exactly and do not alter unless the user explicitly requests it:
- face identity
- head shape, facial proportions, bone structure
- eyes, eyelids, iris color, eyebrows, eyelashes
- nose, lips, teeth, smile line, ears
- skin tone, undertone, texture, freckles, moles, scars, wrinkles, pores
- age appearance and body proportions
- hairstyle, hairline, hair density, hair texture, hair color
- makeup style and intensity
- outfit, fabric, folds, fit, seams, logos, prints, labels
- accessories, jewelry, piercings, tattoos, glasses, headwear
- pose, hand shape, fingers, nails, silhouette
- colors, materials, textures, lighting logic, camera perspective

STRICT FACE LOCK - ABSOLUTE PRIORITY:
The face must match the reference exactly. Preserve every facial detail with no simplification and no beautification:
- exact face oval, skull shape, forehead, cheekbones, jawline, chin
- exact eye shape, eyelids, eye spacing, iris color, gaze character, eyelashes, eyebrows
- exact nose bridge, nostrils, tip, width, length, profile
- exact lips, mouth shape, cupid's bow, lip fullness, teeth, smile lines
- exact ears, temples, hairline, sideburns
- exact skin tone, undertone, pores, texture, freckles, moles, scars, wrinkles, nasolabial folds, dimples
- exact facial asymmetry, age signs, expression style, makeup placement

OUTFIT LOCK - ABSOLUTE PRIORITY:
Keep the exact same clothing and wearable details from the reference unless the user explicitly asks to change them:
- same garments, layers, sleeves, neckline, length, fit, silhouette
- same fabric type, texture, folds, seams, stitching, buttons, zippers
- same colors, color blocking, patterns, logos, prints, labels, trims
- same shoes, bags, jewelry, glasses, hats, belts, gloves, watches and other accessories

Do not make the face prettier, younger, older, smoother, slimmer, wider, more symmetrical, more generic, or more model-like. Do not replace the face with a similar-looking person. If the requested edit conflicts with face preservation, keep the face from the reference and apply the edit only outside the face.

APPEARANCE LOCK:
The person's appearance is locked to the reference images. Every generated output must keep the same recognizable person with the same facial geometry, age, skin, hair, body proportions, outfit, accessories, makeup, tattoos, marks, and all visible distinctive details. Treat these visual details as immutable unless the user explicitly names a change.

For batch or multiple-output requests, produce multiple camera/composition variants of the exact same referenced person/object. Do not create different people, alternate identities, redesigned faces, changed hairstyles, changed clothing, changed accessories, changed body shape, or generic lookalikes across the variants.

Do not beautify, stylize, reinterpret, average out, morph, or substitute the person.
Do not generate a similar person. Generate the exact same person from the reference.
Do not change ethnicity, gender presentation, age, weight, body shape, facial expression style, or facial asymmetry.
Do not add distortions, warping, extra fingers, altered eyes, altered teeth, blurred skin, or fabric redesign.
If something is not explicitly requested, keep it identical to the reference.
Apply only the minimum necessary change requested by the user while preserving everything else exactly.
The uploaded images are visual references, not text content. Never render file names, URLs, labels, counters, prompt text, or the words "reference"/"variant" inside the image unless the user explicitly asks for visible typography.
""".strip()
    return f"{instruction}\n\nUser request: {prompt}" if prompt else instruction


def _build_image_variant_prompt(
    prompt: str, variant_index: int, total_count: int
) -> str:
    """Add controlled variation for multi-image batches while keeping references."""
    prompt = (prompt or "").strip()
    if total_count <= 1:
        return prompt

    variants = [
        "Use a slightly different composition and camera crop only. Keep the referenced face exactly identical: same facial geometry, eyes, nose, lips, skin texture, asymmetry, age signs, hairline, and all distinctive facial details.",
        "Use a slightly different camera angle and framing only. Keep the referenced face exactly identical: same facial geometry, eyes, nose, lips, skin texture, asymmetry, age signs, hairline, and all distinctive facial details.",
        "Use a subtle lighting/framing variation only. Keep the referenced face exactly identical: same facial geometry, eyes, nose, lips, skin texture, asymmetry, age signs, hairline, and all distinctive facial details.",
        "Use a different crop and background depth only. Keep the referenced face exactly identical: same facial geometry, eyes, nose, lips, skin texture, asymmetry, age signs, hairline, and all distinctive facial details.",
    ]
    instruction = variants[variant_index % len(variants)]
    return (
        f"{prompt}\n\n"
        f"For this single output: {instruction} "
        "Do not render batch numbers, labels, prompt text, file names, URLs, or UI text in the image."
    )


def _snapshot_reference_images(reference_images: list[str] | None) -> list[str]:
    """Freeze the exact reference set for every launched image task."""
    if not reference_images:
        return []
    seen: set[str] = set()
    normalized: list[str] = []
    for image in reference_images:
        value = str(image).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _prepare_banana_reference_images(
    img_service: str, reference_images: list[str] | None
) -> list[str]:
    normalized = _snapshot_reference_images(reference_images)
    if img_service not in {"banana_pro", "banana_2", "nanobanana"}:
        return normalized
    if len(normalized) <= 1:
        return normalized
    # For identity-sensitive Banana edits, extra refs often cause identity blending.
    # Keep the first user-selected reference as the source-of-truth person image.
    return normalized[:8]


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
    policy_error = _enforce_image_prompt_policy(prompt)
    if policy_error:
        logger.warning(
            "Blocked image prompt by policy: user_id=%s telegram_id=%s model=%s prompt_prefix=%s",
            getattr(user, "id", None),
            telegram_id,
            runtime_img_service,
            (prompt or "")[:200],
        )
        return {
            "status": "failed",
            "task_id": None,
            "runtime_img_service": runtime_img_service,
            "error": policy_error,
        }
    reference_images = _prepare_banana_reference_images(
        runtime_img_service, reference_images
    )
    provider_model = _get_image_provider_model(runtime_img_service, reference_images)

    local_task_id = f"img_{uuid.uuid4().hex[:12]}"
    effective_prompt = _apply_safe_prompt_framing(
        runtime_img_service,
        _apply_reference_detail_preservation(
            runtime_img_service, prompt, reference_images
        ),
    )
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
            resolution=img_quality.upper(),
            image_input=reference_images,
            callback_url=callback_url,
        )
    elif runtime_img_service in {"banana_pro", "nanobanana"}:
        result = await nano_banana_pro_service.generate_image(
            prompt=effective_prompt,
            aspect_ratio=img_ratio,
            resolution=img_quality.upper(),
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
            nsfw_checker=False,
            callBackUrl=callback_url,
        )
    elif runtime_img_service == "flux_pro":
        if reference_images:
            result = await gpt_image_service.generate_image_to_image(
                prompt=prompt,
                input_urls=reference_images,
                model="gpt-image-2-image-to-image",
                aspect_ratio=img_ratio,
                nsfw_checker=False,
                callBackUrl=callback_url,
            )
        else:
            result = await gpt_image_service.generate_image(
                prompt=prompt,
                model="gpt-image-2-text-to-image",
                aspect_ratio=img_ratio,
                nsfw_checker=False,
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
            nsfw_checker=False,
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
            resolution=img_quality.upper(),
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
        "<i>Можно загрузить до 9 фото.</i>\n"
        "Когда всё готово, нажмите <b>▶️ Продолжить</b>.\n"
        "Если референсы не нужны — выберите <b>⏭ Пропустить</b>."
    )
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_reference_images_upload_keyboard(0, _get_max_image_references("banana_pro"), "new"),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=get_reference_images_upload_keyboard(0, _get_max_image_references("banana_pro"), "new"),
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
        img_quality="2K",
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
        img_quality="2K",
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
        reply_markup=get_reference_images_upload_keyboard(0, _get_max_image_references("wan_27"), "new"),
        parse_mode="HTML",
    )
    await callback.answer("Wan 2.7 Pro выбран")


async def _restore_image_task_to_state(task, state: FSMContext) -> tuple[bool, str | None]:
    if not task or task.type != "image" or not task.request_data:
        return False, "Не удалось найти данные задачи."

    try:
        request_data = json.loads(task.request_data)
    except Exception:
        return False, "Данные исходной задачи повреждены."

    img_service = request_data.get("img_service", task.model or "banana_pro")
    img_ratio = request_data.get("img_ratio", task.aspect_ratio or "1:1")
    reference_images = _snapshot_reference_images(
        request_data.get("reference_images", [])
    )
    img_quality = request_data.get("img_quality", "2K")
    img_nsfw_checker = bool(request_data.get("img_nsfw_checker", False))
    nsfw_enabled = bool(request_data.get("nsfw_enabled", False))

    await state.clear()
    await state.update_data(
        generation_type="image",
        img_service=img_service,
        img_ratio=img_ratio,
        img_count=1,
        reference_images=reference_images,
        img_quality=img_quality,
        img_nsfw_checker=img_nsfw_checker,
        nsfw_enabled=nsfw_enabled,
        preset_id="new",
        img_flow_step="configure",
    )
    await state.set_state(GenerationStates.waiting_for_input)
    return True, None


@router.callback_query(F.data.startswith("retry_prompt_image_"))
async def retry_image_with_new_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Открывает тот же image flow с теми же референсами и настройками, но ждёт новый промпт."""
    task_id = callback.data.replace("retry_prompt_image_", "", 1)
    task = await get_task_by_id(task_id)

    restored, error_message = await _restore_image_task_to_state(task, state)
    if not restored:
        await callback.answer(error_message or "Не удалось открыть повтор.", show_alert=True)
        return

    await _show_image_creation_screen(callback, state)
    await callback.answer("Отправь новый промпт — рефы и настройки сохранены")


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
    reference_images = _snapshot_reference_images(
        request_data.get("reference_images", [])
    )
    img_quality = request_data.get("img_quality", "2K")
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
            prompt=_build_image_variant_prompt(prompt, 0, 1),
            img_ratio=img_ratio,
            reference_images=reference_images,
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
    await state.update_data(
        img_service="wan_27", preset_id="new", img_flow_step="settings"
    )
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
        img_quality="2K",
        img_nsfw_checker=False,
        reference_images=[],
        preset_id="new",
    )
    await callback.message.edit_text(
        f"{title}\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        f"{hint}\n\n"
        f"<i>Можно загрузить до {_get_max_image_references('seedream_edit')} фото.</i>",
        reply_markup=get_reference_images_upload_keyboard(0, _get_max_image_references("seedream_edit"), "new"),
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
        reply_markup=get_reference_images_upload_keyboard(0, _get_max_image_references("grok_imagine_i2i"), "new"),
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
    default_model = "seedance_2"
    max_video_refs = get_max_video_references(default_model)
    await _init_default_video_state(
        state,
        v_type="video",
        v_model=default_model,
        v_duration=5,
        v_ratio="16:9",
    )
    text = (
        "🎞 <b>Видео-референс</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code>\n\n"
        f"Загрузите до {max_video_refs} коротких видео, если хотите передать движение, стиль камеры "
        "или атмосферу.\nЭтот режим работает через Seedance 2.0."
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_reference_videos_upload_keyboard(
            0, max_video_refs, "video_new"
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_videos)


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
    current_refs = len(data.get("reference_images", []))
    max_refs = _get_max_image_references(current_service)

    # Показываем клавиатуру загрузки референсов
    await callback.message.edit_text(
        "📎 <b>Загрузка референсов</b>\n"
        "Добавьте фото, если хотите точнее передать стиль, человека или объект.\n\n"
        "<i>Можно загрузить до 9 фото.</i>\n"
        "Когда всё готово, нажмите <b>Продолжить</b> или <b>Пропустить</b>.",
        reply_markup=get_reference_images_upload_keyboard(
            current_refs, max_refs, "new"
        ),
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
        omni_resolution="720p",
        omni_seed=None,
        omni_audio_ids=[],
        omni_character_ids=[],
        omni_base_voice="achernar",
        omni_voice_name="",
        omni_voice_description="",
        omni_example_dialogue="",
        omni_character_name="",
        omni_character_audio_ids=[],
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
        img_quality="2K",
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
            reply_markup=get_reference_images_upload_keyboard(0, 9, "new"),
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
    if v_type == "video":
        model = choose_video_reference_model(model)

    await _init_default_video_state(
        state,
        v_type=v_type,
        v_model=model,
        v_duration=duration,
        v_ratio=ratio,
    )

    if v_type == "video":
        user_credits = await get_user_credits(callback.from_user.id)
        max_video_refs = get_max_video_references(model)
        text = (
            "🎞 <b>Видео-референс</b>\n"
            f"🍌 Баланс: <code>{user_credits}</code>\n\n"
            f"Загрузите до {max_video_refs} коротких видео, чтобы передать движение, стиль камеры "
            "или атмосферу. Можно пропустить и продолжить без референсов."
        )
        await callback.message.edit_text(
            text,
            reply_markup=get_reference_videos_upload_keyboard(
                0, max_video_refs, "video_new"
            ),
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
    max_video_refs = get_max_video_references(current_model)
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
    omni_resolution = data.get("omni_resolution", "720p")
    omni_seed = data.get("omni_seed")
    omni_audio_ids = data.get("omni_audio_ids", [])
    omni_character_ids = data.get("omni_character_ids", [])
    omni_base_voice = data.get("omni_base_voice", "achernar")
    omni_voice_name = data.get("omni_voice_name", "")
    omni_voice_description = data.get("omni_voice_description", "")
    omni_example_dialogue = data.get("omni_example_dialogue", "")
    omni_character_name = data.get("omni_character_name", "")
    omni_character_audio_ids = data.get("omni_character_audio_ids", [])

    await _normalize_veo_state(state)
    await _normalize_video_duration_state(state)
    data = await state.get_data()
    current_v_type = data.get("v_type", current_v_type)
    current_model = data.get("v_model", current_model)
    current_duration = data.get("v_duration", current_duration)
    current_ratio = data.get("v_ratio", current_ratio)
    grok_mode = data.get("grok_mode", grok_mode)
    veo_generation_type = data.get("veo_generation_type", veo_generation_type)
    veo_translation = data.get("veo_translation", veo_translation)
    veo_resolution = data.get("veo_resolution", veo_resolution)
    veo_seed = data.get("veo_seed", veo_seed)
    veo_watermark = data.get("veo_watermark", veo_watermark)
    omni_resolution = data.get("omni_resolution", omni_resolution)
    omni_seed = data.get("omni_seed", omni_seed)
    omni_audio_ids = data.get("omni_audio_ids", omni_audio_ids)
    omni_character_ids = data.get("omni_character_ids", omni_character_ids)
    omni_base_voice = data.get("omni_base_voice", omni_base_voice)
    omni_voice_name = data.get("omni_voice_name", omni_voice_name)
    omni_voice_description = data.get("omni_voice_description", omni_voice_description)
    omni_example_dialogue = data.get("omni_example_dialogue", omni_example_dialogue)
    omni_character_name = data.get("omni_character_name", omni_character_name)
    omni_character_audio_ids = data.get(
        "omni_character_audio_ids",
        omni_character_audio_ids,
    )

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
            max_image_refs = get_max_video_image_references(current_model)
            media_status = (
                f"✅ <b>Фото загружено: {total}/{max_image_refs}</b> (старт + рефы)\n"
            )
        else:
            media_status = "📷 <b>Загрузите стартовое изображение</b>\n"
    elif current_v_type == "video":
        if v_reference_videos:
            media_status = (
                f"✅ <b>{len(v_reference_videos)} реф. видео загружено!</b>\n"
            )
        else:
            media_status = (
                f"📹 <b>Загрузите референсные видео (до {max_video_refs})</b>\n"
            )
    elif current_v_type == "character":
        media_status = (
            f"{'✅' if v_image_url else '🖼'} <b>Character image:</b> "
            f"<code>{'загружено' if v_image_url else 'не загружено'}</code>\n"
        )

    # Формируем текст о промпте
    prompt_text = ""
    if user_prompt:
        prompt_text = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:100]}{'...' if len(user_prompt) > 100 else ''}</code>\n"

    settings_lines = [
        f"   📝 Тип: <code>{get_video_type_label(current_v_type)}</code>",
        f"   🤖 Модель: <code>{get_video_model_label(current_model)}</code>",
    ]
    if current_model not in {"avatar_std", "avatar_pro", "gemini_omni_audio", "gemini_omni_character"}:
        settings_lines.append(f"   ⏱ Длительность: <code>{current_duration} сек</code>")
    if current_model not in {"avatar_std", "avatar_pro", "gemini_omni_audio", "gemini_omni_character"}:
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
        settings_lines.append(f"   🖥 Качество: <code>{veo_resolution}</code>")
        if veo_seed is not None:
            settings_lines.append(f"   🎲 Seed: <code>{veo_seed}</code>")
        if veo_watermark:
            settings_lines.append(f"   🏷 Метка: <code>{veo_watermark}</code>")
    if current_model == "gemini_omni_video":
        settings_lines.append(f"   🖥 Качество: <code>{omni_resolution}</code>")
        if omni_seed is not None:
            settings_lines.append(f"   🎲 Seed: <code>{omni_seed}</code>")
        if omni_audio_ids:
            settings_lines.append(f"   🎧 Audio ID: <code>{len(omni_audio_ids)}</code>")
        if omni_character_ids:
            settings_lines.append(
                f"   🧍 Character ID: <code>{len(omni_character_ids)}</code>"
            )
    if current_model == "gemini_omni_audio":
        settings_lines.append(f"   🎙 Базовый голос: <code>{omni_base_voice}</code>")
        settings_lines.append(
            f"   🏷 Имя: <code>{omni_voice_name or 'авто из промпта'}</code>"
        )
        if omni_voice_description:
            settings_lines.append("   🗣 Описание: <code>заполнено</code>")
        if omni_example_dialogue:
            settings_lines.append("   💬 Пример фразы: <code>заполнено</code>")
    if current_model == "gemini_omni_character":
        settings_lines.append(
            f"   🏷 Персонаж: <code>{omni_character_name or 'авто из промпта'}</code>"
        )
        if omni_character_audio_ids:
            settings_lines.append(
                f"   🎧 Audio ID: <code>{len(omni_character_audio_ids)}</code>"
            )

    if current_model == "gemini_omni_audio":
        prompt_title = "Опишите голос"
        prompt_guidance = (
            "Напишите простыми словами:\n"
            "• тембр и возраст звучания\n"
            "• темп, эмоцию и акцент\n"
            "• для каких роликов нужен голос"
        )
    elif current_model == "gemini_omni_character":
        prompt_title = "Опишите персонажа"
        prompt_guidance = (
            "Напишите простыми словами:\n"
            "• внешность и одежду\n"
            "• характер и настроение\n"
            "• какую роль персонаж будет играть в видео"
        )
    else:
        prompt_title = "Опишите видео"
        prompt_guidance = (
            "Напишите простыми словами:\n"
            "• что происходит в кадре\n"
            "• как двигается камера\n"
            "• какой нужен стиль или настроение"
        )

    text = (
        f"🎬 <b>Создание видео</b>\n"
        f"<b>Шаг 3. Настройки и промпт</b>\n"
        f"{ref_text}"
        f"⚙️ <b>Текущие настройки:</b>\n" + "\n".join(settings_lines) + "\n"
        f"{media_status}"
        f"{prompt_text}\n"
        f"<b>{prompt_title}</b>\n"
        f"{prompt_guidance}"
    )

    # Напоминание о загрузке медиа
    if current_v_type == "avatar" and not (v_image_url and avatar_audio_url):
        text += "<i>🗣 Сначала загрузите фото аватара и аудио.</i>"
    elif current_v_type == "character" and not v_image_url:
        text += "<i>🖼 Сначала загрузите изображение персонажа.</i>"
    elif current_v_type == "imgtxt" and not v_image_url:
        text += f"<i>📷 Сначала загрузите фото для первого кадра.</i>"
    elif current_v_type == "video" and not v_reference_videos:
        text += (
            f"<i>📹 При желании загрузите до {max_video_refs} коротких "
            "видео-референсов.</i>"
        )

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
        current_omni_resolution=data.get("omni_resolution", "720p"),
        current_omni_seed=data.get("omni_seed"),
        current_omni_audio_ids=data.get("omni_audio_ids", []),
        current_omni_character_ids=data.get("omni_character_ids", []),
        current_omni_base_voice=data.get("omni_base_voice", "achernar"),
        current_omni_voice_name=data.get("omni_voice_name", ""),
        current_omni_character_name=data.get("omni_character_name", ""),
        current_omni_character_audio_ids=data.get("omni_character_audio_ids", []),
    )


def _get_supported_video_durations(model: str) -> list[int]:
    """Return supported durations for the Telegram video flow."""
    if model.startswith("veo3"):
        return [2, 4, 6, 8, 10]
    if model in {"gemini_omni", "gemini_omni_video"}:
        return [4, 6, 8, 10]
    if model in {"gemini_omni_audio", "gemini_omni_character"}:
        return [6]
    if model in {"avatar_std", "avatar_pro", "motion_control_v26", "motion_control_v30"}:
        return [5]

    model_config = (
        preset_manager._price_config.get("costs_reference", {})
        .get("video_models", {})
        .get(model, {})
    )
    duration_costs = model_config.get("duration_costs", {})
    if duration_costs:
        return sorted(int(value) for value in duration_costs.keys())
    return [5, 10, 15]


def _normalize_video_duration_value(model: str, duration: int) -> int:
    """Snap duration to the closest supported value for the selected model."""
    if model in {"motion_control_v26", "motion_control_v30"}:
        # Motion Control тарифицируется по фактической длине загруженного видео,
        # поэтому не прижимаем его к фиксированным длительностям из общего video UX.
        return max(1, min(30, int(duration)))

    supported = _get_supported_video_durations(model)
    duration = int(duration)
    if duration in supported:
        return duration
    return min(supported, key=lambda value: (abs(value - duration), value))


async def _normalize_video_duration_state(state: FSMContext) -> None:
    """Keep stored duration aligned with the selected model."""
    data = await state.get_data()
    current_model = data.get("v_model", "v3_std")
    current_duration = int(data.get("v_duration", 5))
    normalized_duration = _normalize_video_duration_value(
        current_model, current_duration
    )
    if normalized_duration != current_duration:
        await state.update_data(v_duration=normalized_duration)


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
    if v_model not in {"avatar_std", "avatar_pro", "gemini_omni_audio", "gemini_omni_character"}:
        parts.append(f"📐 <code>{v_ratio}</code>")
    if v_model not in {"avatar_std", "avatar_pro", "gemini_omni_audio", "gemini_omni_character"}:
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
    if v_model == "gemini_omni_video":
        parts.append(f"🖥 <code>{data.get('omni_resolution', '720p')}</code>")
        if data.get("omni_seed") is not None:
            parts.append(f"🎲 <code>{data.get('omni_seed')}</code>")
        if data.get("omni_audio_ids"):
            parts.append(f"🎧 <code>{len(data.get('omni_audio_ids') or [])}</code>")
        if data.get("omni_character_ids"):
            parts.append(
                f"🧍 <code>{len(data.get('omni_character_ids') or [])}</code>"
            )
    if v_model == "gemini_omni_audio":
        parts.append(f"🎙 <code>{data.get('omni_base_voice', 'achernar')}</code>")
    if v_model == "gemini_omni_character":
        parts.append(f"🧍 <code>{data.get('omni_character_name') or 'auto'}</code>")

    return " | ".join(parts)


def _build_image_creation_text(data: dict) -> str:
    current_service = data.get("img_service", "banana_pro")
    current_ratio = data.get(
        "img_ratio", "auto" if current_service == "flux_pro" else "1:1"
    )
    current_count = data.get("img_count", 1)
    reference_images = data.get("reference_images", [])
    nsfw_enabled = data.get("nsfw_enabled", False)
    img_quality = data.get("img_quality", "2K")
    img_nsfw_checker = data.get("img_nsfw_checker", False)
    ratio_label = current_ratio.replace(":", "∶")
    # nano_quality_cost_display_v1
    unit_cost = preset_manager.get_generation_cost(current_service)
    if current_service in {
        "banana_pro",
        "banana_2",
        "nanobanana",
        "nano_banana_pro",
        "nano-banana-pro",
    }:
        unit_cost = 3.5 if str(img_quality or "2K").upper() == "4K" else 2.5
    total_cost = unit_cost * current_count

    # nano_quality_cost_info_v2
    if current_service in {
        "banana_pro",
        "banana_2",
        "nanobanana",
        "nano_banana_pro",
        "nano-banana-pro",
    }:
        unit_cost = 3.5 if str(img_quality or "2K").upper() == "4K" else 2.5
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
    max_refs = _get_max_image_references(current_service)
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
    max_refs = _get_max_image_references(current_service)
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
        + f"<i>Можно загрузить до {max_refs} фото. Когда всё готово, нажмите «Продолжить».</i>"
    )

    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.edit_text(
                text,
                reply_markup=get_reference_images_upload_keyboard(
                    current_count, max_refs, "new"
                ),
                parse_mode="HTML",
            )
        else:
            await message_or_callback.answer(
                text,
                reply_markup=get_reference_images_upload_keyboard(
                    current_count, max_refs, "new"
                ),
                parse_mode="HTML",
            )
    except Exception:
        await message_or_callback.answer(
            text,
            reply_markup=get_reference_images_upload_keyboard(
                current_count, max_refs, "new"
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
        img_quality=data.get("img_quality", "2K"),
        img_nsfw_checker=data.get("img_nsfw_checker", False),
    )

    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await message_or_callback.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
    except TelegramBadRequest as e:
        error_msg = str(e).lower()
        if "message is not modified" in error_msg:
            pass
        elif isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await message_or_callback.answer(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
    except AttributeError:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
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


async def _show_gemini_omni_mode_screen(
    message_or_callback, state: FSMContext, edit: bool = True
):
    user_id = (
        message_or_callback.from_user.id
        if hasattr(message_or_callback, "from_user")
        else None
    )
    user_credits = await get_user_credits(user_id) if user_id else 0
    audio_cost = preset_manager.get_video_cost("gemini_omni_audio", 6)
    character_cost = preset_manager.get_video_cost("gemini_omni_character", 6)
    video_cost_6 = preset_manager.get_video_cost("gemini_omni_video", 6)

    text = (
        "🔷 <b>Gemini Omni</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "<b>Что умеет</b>\n"
        "• <b>Video</b> — генерирует видео из текста, стартового изображения, фото-референсов, одного видео-рефа, Audio ID и Character ID.\n"
        "  Длительность: <code>4/6/8/10</code> сек, формат: <code>16:9</code> или <code>9:16</code>, качество: <code>720p/1080p/4k</code>, seed опционален.\n"
        "  Можно добавить до <code>7</code> визуальных референсов; один видео-реф тоже занимает часть этого лимита.\n\n"
        "• <b>Audio ID</b> — создаёт сохранённый голос: выберите базовый голос, имя, описание тембра и пример фразы. Бот вернёт ID, который потом вставляется в Video.\n\n"
        "• <b>Character ID</b> — создаёт сохранённого персонажа по одному изображению, описанию, имени и опциональному Audio ID. Бот вернёт ID персонажа для Video.\n\n"
        "<b>Как лучше пользоваться</b>\n"
        "1. Если нужен фирменный голос — сначала сделайте <b>Audio ID</b>.\n"
        "2. Если нужен постоянный герой — сделайте <b>Character ID</b> и при желании привяжите к нему Audio ID.\n"
        "3. Затем откройте <b>Video</b> и добавьте нужные ID вместе с промптом и референсами.\n\n"
        "<b>Подсказка</b>: ID можно скопировать из результата и вставить в настройки Gemini Omni Video.\n\n"
        f"<b>Стоимость</b>: Video от <code>{video_cost_6}</code>🍌 за 6 сек, "
        f"Audio ID <code>{audio_cost}</code>🍌, Character ID <code>{character_cost}</code>🍌."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🎬 Video", callback_data="omni_mode_video")
    builder.button(text="🎧 Audio ID", callback_data="omni_mode_audio")
    builder.button(text="🧍 Character ID", callback_data="omni_mode_character")
    builder.button(text="🤖 К моделям", callback_data="video_change_model")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 2, 2)
    keyboard = builder.as_markup()

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
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    except Exception:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.answer(
                text, reply_markup=keyboard, parse_mode="HTML"
            )
        else:
            await message_or_callback.answer(
                text, reply_markup=keyboard, parse_mode="HTML"
            )

    await state.set_state(GenerationStates.waiting_for_input)


async def _show_video_media_screen(
    message_or_callback, state: FSMContext, edit: bool = True
):
    def _fit_telegram_text(raw: str, limit: int = 4096) -> str:
        if len(raw) <= limit:
            return raw
        return raw[: limit - 1].rstrip() + "…"

    async def _safe_answer_message(target_message, raw_text: str):
        try:
            await target_message.answer(
                raw_text, reply_markup=keyboard, parse_mode="HTML"
            )
        except TelegramBadRequest as send_error:
            send_error_msg = str(send_error).lower()
            if "message_too_long" in send_error_msg or "message is too long" in send_error_msg:
                await target_message.answer(
                    _fit_telegram_text(raw_text, 3500),
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
            elif "message is not modified" in send_error_msg:
                pass
            else:
                raise

    data = await state.get_data()
    current_model = data.get("v_model", "v3_pro")
    current_v_type = data.get("v_type", "text")
    max_video_refs = get_max_video_references(current_model)
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
    elif current_v_type == "character":
        body = (
            "<b>Шаг 2. Character image</b>\n"
            f"Модель: <code>{get_video_model_label(current_model)}</code>\n\n"
            "Отправьте одно изображение персонажа. После этого можно переходить к описанию."
        )
        next_state = GenerationStates.waiting_for_video_prompt
    elif current_v_type == "audio":
        body = (
            "<b>Шаг 2. Audio ID</b>\n"
            f"Модель: <code>{get_video_model_label(current_model)}</code>\n\n"
            "Медиа не требуется. Настройте базовый голос и имя, затем отправьте описание."
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
            f"Загрузите до {max_video_refs} коротких видео или пропустите шаг."
        )
        next_state = GenerationStates.uploading_reference_videos
    else:
        body = (
            "<b>Шаг 2. Тип и медиа</b>\n"
            f"Модель: <code>{get_video_model_label(current_model)}</code>\n\n"
            "Выбран режим <b>Текст → Видео</b>.\n"
            "Ничего загружать не нужно. Можно сразу переходить дальше."
        )
        next_state = GenerationStates.waiting_for_video_prompt

    text = (
        "🎬 <b>Создание видео</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        f"{body}"
    )
    text = _fit_telegram_text(text)
    keyboard = get_video_media_step_keyboard(
        current_v_type=current_v_type,
        current_model=current_model,
        has_start_image=bool(v_image_url),
        reference_image_count=len(reference_images),
        reference_video_count=len(v_reference_videos),
        has_avatar_audio=bool(avatar_audio_url),
        max_reference_video_count=max_video_refs,
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
    except TelegramBadRequest as e:
        error_msg = str(e).lower()
        if "message is not modified" in error_msg:
            pass
        elif isinstance(message_or_callback, types.CallbackQuery):
            await _safe_answer_message(message_or_callback.message, text)
        else:
            await _safe_answer_message(message_or_callback, text)
    except AttributeError:
        if isinstance(message_or_callback, types.CallbackQuery):
            await _safe_answer_message(message_or_callback.message, text)
        else:
            await _safe_answer_message(message_or_callback, text)
    except Exception:
        logger.exception("Failed to render video media screen")

    await state.set_state(next_state)


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


async def _update_reference_upload_message(bot: Bot, chat_id: int, message_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    img_service = data.get("img_service", "banana_pro")
    preset_id = data.get("preset_id", "new")
    reference_images = list(data.get("reference_images") or [])
    max_refs = _get_max_image_references(img_service)
    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=(
            f"📎 <b>Загрузка референсов</b>\n"
            f"Загружено: <code>{len(reference_images)}/{max_refs}</code>\n\n"
            "Можно отправить ещё фото или открыть сохранённые рефы."
        ),
        reply_markup=get_reference_images_upload_keyboard(
            len(reference_images), max_refs, preset_id
        ),
        parse_mode="HTML",
    )


async def _send_saved_reference_preview(
    target_message: types.Message,
    state: FSMContext,
    *,
    refs: list,
    index: int,
) -> types.Message | None:
    if not refs:
        return None

    safe_index = max(0, min(index, len(refs) - 1))
    ref = refs[safe_index]
    data = await state.get_data()
    reference_images = list(data.get("reference_images") or [])
    already_selected = ref.file_url in reference_images
    created_at = ref.created_at.strftime("%d.%m.%Y %H:%M") if ref.created_at else "—"
    filename = ref.original_filename or os.path.basename(ref.file_url or "") or "reference"
    caption = (
        f"📚 <b>Сохранённый реф</b>\n"
        f"• {safe_index + 1} из {len(refs)}\n"
        f"• Файл: <code>{filename[:64]}</code>\n"
        f"• Сохранён: <code>{created_at}</code>\n"
        f"• Статус: <code>{'уже добавлен в текущую сессию' if already_selected else 'готов к использованию'}</code>"
    )
    reply_markup = get_saved_reference_picker_keyboard(
        ref.id,
        safe_index,
        len(refs),
        already_selected=already_selected,
    )

    try:
        return await target_message.answer_photo(
            photo=ref.file_url,
            caption=caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except TelegramBadRequest:
        from bot.services.media_input_utils import resolve_local_upload_path

        local_path = resolve_local_upload_path(ref.file_url)
        if not local_path or not os.path.exists(local_path):
            await target_message.answer(
                "Не удалось открыть сохранённый реф. Возможно, файл больше недоступен.",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return None

        with open(local_path, "rb") as f:
            image_bytes = f.read()
        return await target_message.answer_photo(
            photo=types.BufferedInputFile(image_bytes, filename=filename),
            caption=caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )


@router.callback_query(F.data == "savedref_noop")
async def saved_reference_noop(callback: types.CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "savedref_close")
async def close_saved_reference_preview(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Закрыл")


@router.callback_query(F.data == "ref_saved_library")
async def open_saved_reference_library(callback: types.CallbackQuery, state: FSMContext):
    saved_refs = await list_saved_references(callback.from_user.id, kind="image", limit=50)
    if not saved_refs:
        await callback.answer("Сохранённых рефов пока нет", show_alert=True)
        return

    await state.update_data(
        saved_ref_return_chat_id=callback.message.chat.id,
        saved_ref_return_message_id=callback.message.message_id,
    )
    await _send_saved_reference_preview(callback.message, state, refs=saved_refs, index=0)
    await callback.answer()


@router.callback_query(F.data.startswith("savedref_nav_"))
async def navigate_saved_reference_library(callback: types.CallbackQuery, state: FSMContext):
    try:
        index = int(callback.data.rsplit("_", 1)[-1])
    except ValueError:
        await callback.answer("Не удалось открыть реф", show_alert=True)
        return

    saved_refs = await list_saved_references(callback.from_user.id, kind="image", limit=50)
    if not saved_refs:
        await callback.answer("Сохранённых рефов больше нет", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return

    try:
        await callback.message.delete()
    except Exception:
        pass
    await _send_saved_reference_preview(callback.message, state, refs=saved_refs, index=index)
    await callback.answer()


@router.callback_query(F.data.startswith("savedref_use_"))
async def use_saved_reference_from_library(callback: types.CallbackQuery, state: FSMContext):
    try:
        reference_id = int(callback.data.rsplit("_", 1)[-1])
    except ValueError:
        await callback.answer("Не удалось добавить реф", show_alert=True)
        return

    saved_refs = await list_saved_references(callback.from_user.id, kind="image", limit=50)
    candidate = next((ref for ref in saved_refs if ref.id == reference_id), None)
    if not candidate:
        await callback.answer("Реф не найден", show_alert=True)
        return

    data = await state.get_data()
    img_service = data.get("img_service", "banana_pro")
    max_refs = _get_max_image_references(img_service)
    reference_images = list(data.get("reference_images") or [])
    if candidate.file_url in reference_images:
        await callback.answer("Этот реф уже добавлен", show_alert=True)
        return
    if len(reference_images) >= max_refs:
        await callback.answer("Уже достигнут лимит референсов", show_alert=True)
        return

    reference_images.append(candidate.file_url)
    await state.update_data(reference_images=reference_images)

    return_chat_id = data.get("saved_ref_return_chat_id")
    return_message_id = data.get("saved_ref_return_message_id")
    if return_chat_id and return_message_id:
        try:
            await _update_reference_upload_message(callback.bot, return_chat_id, return_message_id, state)
        except Exception:
            logger.exception("Failed to refresh upload screen after selecting saved ref")

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Реф добавлен")
    await callback.message.answer(
        f"✅ Сохранённый реф добавлен. Сейчас в сессии: <code>{len(reference_images)}/{max_refs}</code>",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("savedref_delete_"))
async def delete_saved_reference_from_library(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    if len(parts) < 4:
        await callback.answer("Не удалось удалить реф", show_alert=True)
        return
    try:
        reference_id = int(parts[2])
        current_index = int(parts[3])
    except ValueError:
        await callback.answer("Не удалось удалить реф", show_alert=True)
        return

    deleted = await delete_saved_reference(callback.from_user.id, reference_id)
    if not deleted:
        await callback.answer("Реф уже удалён", show_alert=True)
        return

    data = await state.get_data()
    reference_images = list(data.get("reference_images") or [])
    saved_refs_after = await list_saved_references(callback.from_user.id, kind="image", limit=50)
    valid_urls = {ref.file_url for ref in saved_refs_after}
    updated_reference_images = [url for url in reference_images if url in valid_urls]
    if len(updated_reference_images) != len(reference_images):
        await state.update_data(reference_images=updated_reference_images)
        return_chat_id = data.get("saved_ref_return_chat_id")
        return_message_id = data.get("saved_ref_return_message_id")
        if return_chat_id and return_message_id:
            try:
                await _update_reference_upload_message(callback.bot, return_chat_id, return_message_id, state)
            except Exception:
                logger.exception("Failed to refresh upload screen after deleting saved ref")

    try:
        await callback.message.delete()
    except Exception:
        pass

    if not saved_refs_after:
        await callback.answer("Реф удалён")
        await callback.message.answer("Сохранённых рефов больше нет.")
        return

    next_index = min(current_index, len(saved_refs_after) - 1)
    await _send_saved_reference_preview(callback.message, state, refs=saved_refs_after, index=next_index)
    await callback.answer("Реф удалён")


@router.callback_query(F.data == "ref_reload_new")
async def handle_ref_reload_new(callback: types.CallbackQuery, state: FSMContext):
    """Перезагружает референсы (очищает и начинает заново) для нового UX"""
    data = await state.get_data()
    generation_type = data.get("generation_type")

    # Очищаем референсы
    await state.update_data(reference_images=[])

    # Определяем preset_id для клавиатуры
    preset_id = "new" if generation_type != "video" else "video_new"
    current_service = data.get("img_service", "banana_pro")
    max_refs = _get_max_image_references(current_service)

    await callback.message.edit_text(
        (
            f"📎 <b>Перезагрузка референсов</b>\n"
            f"Загружено: <code>0/{max_refs}</code>\n"
            f"Отправьте новые фотографии для загрузки референсов:"
        ),
        reply_markup=get_reference_images_upload_keyboard(0, max_refs, preset_id),
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
    if current_v_type == "character":
        await callback.answer("Для Character нужно изображение", show_alert=True)
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
    if current_v_type == "character" and not data.get("v_image_url"):
        await callback.answer("Сначала загрузите изображение персонажа", show_alert=True)
        return
    if current_v_type == "imgtxt" and not data.get("v_image_url"):
        await callback.answer("Сначала загрузите стартовое фото", show_alert=True)
        return
    await state.update_data(video_flow_step="configure")
    await _show_video_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "avatar_upload_image")
async def handle_avatar_upload_image(
    callback: types.CallbackQuery, state: FSMContext
):
    """Переводит Avatar flow в режим ожидания фото."""
    await state.update_data(video_flow_step="media", v_type="avatar")
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    await callback.answer("Отправьте фото аватара")


@router.callback_query(F.data == "avatar_upload_audio")
async def handle_avatar_upload_audio(
    callback: types.CallbackQuery, state: FSMContext
):
    """Переводит Avatar flow в режим ожидания аудио."""
    await state.update_data(video_flow_step="media", v_type="avatar")
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    await callback.answer("Отправьте аудиофайл или голосовое")


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
    current_model = data.get("v_model")
    selected_model = choose_video_reference_model(current_model)
    updates = {"v_type": "video", "v_duration": 5, "v_model": selected_model}
    await state.update_data(**updates)
    await _show_video_media_screen(callback, state)
    if selected_model != current_model:
        await callback.answer("Для видео-референсов выбрана Seedance 2.0")
    else:
        await callback.answer("Загрузите видео-референсы")


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


@router.callback_query(
    F.data.in_({"omni_mode_video", "omni_mode_audio", "omni_mode_character"})
)
async def handle_gemini_omni_mode(callback: types.CallbackQuery, state: FSMContext):
    """Select a concrete Gemini Omni capability from the unified menu."""
    mode_to_model = {
        "omni_mode_video": "gemini_omni_video",
        "omni_mode_audio": "gemini_omni_audio",
        "omni_mode_character": "gemini_omni_character",
    }
    await state.update_data(video_flow_step="select_model")
    await _apply_video_model_selection(callback, state, mode_to_model[callback.data])


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
    if model == "gemini_omni":
        await state.update_data(
            v_model="gemini_omni",
            v_type="text",
            video_flow_step="omni_menu",
            reference_images=[],
            v_reference_videos=[],
        )
        await _show_gemini_omni_mode_screen(callback, state)
        await callback.answer()
        return

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
    elif model == "gemini_omni_video":
        await state.update_data(
            omni_resolution=data.get("omni_resolution", "720p"),
            omni_seed=data.get("omni_seed"),
            omni_audio_ids=data.get("omni_audio_ids", []),
            omni_character_ids=data.get("omni_character_ids", []),
        )
    elif model == "gemini_omni_audio":
        await state.update_data(
            reference_images=[],
            v_reference_videos=[],
            v_image_url=None,
            omni_base_voice=data.get("omni_base_voice", "achernar"),
            omni_voice_name=data.get("omni_voice_name", ""),
            omni_voice_description=data.get("omni_voice_description", ""),
            omni_example_dialogue=data.get("omni_example_dialogue", ""),
        )
    elif model == "gemini_omni_character":
        await state.update_data(
            reference_images=[],
            v_reference_videos=[],
            v_image_url=data.get("v_image_url"),
            omni_character_name=data.get("omni_character_name", ""),
            omni_character_audio_ids=data.get("omni_character_audio_ids", []),
        )

    # WanX LoRA is text-to-video only, so we force the UI into text mode
    # to expose aspect ratio and duration controls immediately.
    if model.startswith("wanx"):
        current_v_type = "text"
    if model == "glow":
        current_v_type = "video"
    if model in {"avatar_std", "avatar_pro"}:
        current_v_type = "avatar"
    if model == "gemini_omni_audio":
        current_v_type = "audio"
    if model == "gemini_omni_character":
        current_v_type = "character"
    if current_v_type == "video" and not video_model_supports_reference_videos(model):
        current_v_type = "text"
    if model == "v26_pro" and current_v_type == "video":
        current_v_type = "text"
    if model.startswith("veo3") and current_v_type == "video":
        current_v_type = "text"

    updates = {"v_model": model, "v_type": current_v_type}
    if data.get("video_flow_step") == "select_model":
        updates["video_flow_step"] = "media"
    await state.update_data(**updates)
    await _normalize_veo_state(state)
    await _normalize_video_duration_state(state)
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
        if current_type in {"imgtxt", "avatar"}:
            await state.set_state(GenerationStates.waiting_for_video_prompt)
        elif current_type == "text":
            await state.set_state(GenerationStates.waiting_for_video_prompt)
        elif current_type == "video":
            await state.set_state(GenerationStates.uploading_reference_videos)
        else:
            await state.set_state(GenerationStates.waiting_for_video_prompt)
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

    data = await state.get_data()
    current_model = data.get("v_model", "v3_std")
    if duration not in _get_supported_video_durations(current_model):
        await callback.answer("Эта длительность недоступна для выбранной модели")
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
    """Выбор модели Banana 2."""
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
    else:  # banana_2 / fallback banana family
        model_name = "🍌 Nano Banana 2"
        model_cost = str(preset_manager.get_generation_cost("banana_2"))

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
        reply_markup=get_reference_images_upload_keyboard(0, _get_max_image_references("banana_pro"), "generate_image"),
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
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    await state.update_data(generation_type="video", video_flow_step="configure")

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
    await state.set_state(GenerationStates.waiting_for_video_prompt)


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


async def show_preset_details(
    message_or_callback,
    preset,
    user_id: int,
    state: FSMContext = None,
):
    """Show preset details screen."""
    desc_line = f"— {preset.description}\n" if preset.description else ""
    text = (
        f"📋 <b>{preset.name}</b>\n"
        f"💰 Стоимость: <code>{preset.cost}🍌</code>\n"
        f"{desc_line}\n"
        f"Выберите действие:\n"
    )
    await message_or_callback.edit_text(
        text,
        reply_markup=get_preset_action_keyboard(
            preset.id, preset.requires_input, preset.category
        ),
        parse_mode="HTML",
    )
    if state:
        await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("ref_"))
async def handle_reference_images(callback: types.CallbackQuery, state: FSMContext):
    """
    Обработка работы с референсными изображениями (до 14 шт)
    Поддерживает загрузку, управление и подтверждение референсов
    """
    parts = callback.data.split("_")
    # parts[0] is "ref", parts[1] is action (upload, clear, skip, confirm, reload, accept)
    action = parts[1] if len(parts) > 1 else ""
    # Handle preset_id that may contain underscores (e.g. "my_preset")
    if len(parts) > 2:
        preset_id = "_".join(parts[2:])
    else:
        preset_id = None

    data = await state.get_data()
    img_service = data.get("img_service", "banana_pro")
    current_refs = data.get("reference_images", [])
    max_refs = _get_max_image_references(img_service)

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

    elif action == "skip":
        # Skip loading references
        if preset_id and preset_id != "new":
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id, state
                )
                await callback.answer()
                return
        skip_data = await state.get_data()
        if skip_data.get("generation_type") == "video":
            await _show_video_creation_screen(callback.message, state)
        else:
            await _show_image_creation_screen(callback, state)

    elif action == "confirm":
        # Переходим к подтверждению
        if not current_refs:
            await callback.answer("❌ Нет загруженных изображений", show_alert=True)
            return

        # Для нового UX (preset_id == "new") - сразу переходим к выбору модели
        # (пропускаем экран подтверждения референсов)
        if preset_id == "new":
            accept_gen_type = data.get("generation_type", "")
            if accept_gen_type == "video":
                await _show_video_creation_screen(callback.message, state)
            else:
                await _show_image_creation_screen(callback, state)
            await callback.answer()
            await state.set_state(GenerationStates.waiting_for_input)
        else:
            # Для пресетов - сразу переходим к экрану пресета (пропускаем экран подтверждения)
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id, state
                )
            else:
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
                    callback.message, preset, callback.from_user.id, state
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
    # Route state based on generation type
    gen_type_final = (await state.get_data()).get("generation_type", "")
    if gen_type_final == "video":
        await state.set_state(GenerationStates.waiting_for_video_prompt)
    else:
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
    if v_type not in {"imgtxt", "avatar", "character"}:
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
    if v_type in {"avatar", "character"} and file_size and file_size > 20 * 1024 * 1024:
        await message.answer(
            "❌ Фото слишком большое. Максимум 20MB.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return
    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)
    image_data = image_bytes.read()

    # Validate
    try:

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

    content_type = "image/jpeg" if file_ext == "jpg" else f"image/{file_ext}"
    image_url = await _persist_reusable_image_reference(
        message.from_user.id,
        image_data,
        file_ext,
        original_filename=f"video_ref_{photo.file_id}.{file_ext}",
        content_type=content_type,
    )
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

    if v_type == "character":
        await state.update_data(v_image_url=image_url)
        await message.answer("✅ Изображение персонажа загружено.")
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
    max_images = get_max_video_image_references(current_model)
    if total > max_images:
        await message.answer(
            f"❌ Можно загрузить максимум {max_images} фото для выбранной модели."
        )
        return

    if not v_image_url:
        # Первое фото - стартовый кадр
        await state.update_data(v_image_url=image_url)
        logger.info(f"Saved start image for video (1st photo): {image_url}")
        status = f"✅ Основное фото загружено. (1/{max_images})"
    else:
        # Последующие - референсы
        reference_images.append(image_url)
        await state.update_data(reference_images=reference_images)
        logger.info(
            f"Saved reference image for video (ref #{current_refs + 1}): {image_url}"
        )
        status = f"✅ Дополнительное фото загружено. Всего: {total}/{max_images}"

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
            f"📎 Загружено фото: <code>{total_photos}/{max_images}</code>\n"
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
    v_type = data.get("v_type", "")
    if (
        generation_type == "video"
        and v_type in ("imgtxt", "avatar", "video", "character")
        and data.get("video_flow_step") != "configure"
    ):
        if v_type == "imgtxt" and not data.get("v_image_url"):
            await message.answer("Сначала отправьте стартовое фото.")
            return
        if v_type == "avatar":
            if not data.get("v_image_url"):
                await message.answer("Сначала отправьте фото аватара.")
                return
            if not data.get("avatar_audio_url"):
                await message.answer("Сначала отправьте аудио для аватара.")
                return
        if v_type == "character" and not data.get("v_image_url"):
            await message.answer("Сначала отправьте изображение персонажа.")
            return
        await state.update_data(video_flow_step="configure")
    logger.info(f"Generation type: {generation_type}")

    await state.update_data(user_prompt=prompt)

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
    max_video_refs = get_max_video_references(v_model)
    video_urls = normalize_reference_urls(
        data.get("v_reference_videos", []),
        max_count=max_video_refs,
    )

    v_duration = _normalize_video_duration_value(
        v_model, int(data.get("v_duration", 5))
    )
    v_ratio = data.get("v_ratio", "16:9")
    v_image_url = data.get("v_image_url")
    v_video_url = data.get("v_video_url")
    veo_generation_type = data.get("veo_generation_type", "TEXT_2_VIDEO")
    veo_translation = data.get("veo_translation", True)
    veo_resolution = data.get("veo_resolution", "720p")
    veo_seed = data.get("veo_seed")
    veo_watermark = data.get("veo_watermark", "")
    motion_mode = data.get("v_mode", "720p")
    motion_direction = data.get("v_orientation", "video")
    omni_resolution = data.get("omni_resolution", "720p")
    omni_seed = data.get("omni_seed")
    omni_audio_ids = data.get("omni_audio_ids", [])
    omni_character_ids = data.get("omni_character_ids", [])
    omni_base_voice = data.get("omni_base_voice", "achernar")
    omni_voice_name = data.get("omni_voice_name", "")
    omni_voice_description = data.get("omni_voice_description", "")
    omni_example_dialogue = data.get("omni_example_dialogue", "")
    omni_character_name = data.get("omni_character_name", "")
    omni_character_audio_ids = data.get("omni_character_audio_ids", [])

    image_url = data.get("v_image_url")
    avatar_audio_url = data.get("avatar_audio_url")
    video_urls = (
        video_urls if v_type in {"video", "motion"} else None
    )
    image_refs = normalize_reference_urls(
        data.get("reference_images", []),
        max_count=get_max_video_image_references(v_model),
    )

    elements_list = None
    if v_type == "imgtxt" and len(image_refs) >= 2:
        elements_list = [
            {
                "description": "reference photos for video generation consistency and style",
                "reference_image_urls": image_refs[
                    :12
                ],  # Kling elements support up to 3x4=12 refs
            }
        ]

    if v_type == "video" and not video_model_supports_reference_videos(v_model):
        await message.answer(
            "❌ Эта модель не принимает видео-референсы. Выберите Seedance 2.0 "
            "или быстрый режим «Видео-референс»."
        )
        await state.clear()
        return

    cost = preset_manager.get_video_cost_with_quality(v_model, v_duration, motion_mode)

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
        from bot.services.kling_service import kling_service
        from bot.services.seedance_service import seedance_service

        if v_model == "gemini_omni_video":
            omni_images = []
            if image_url:
                omni_images.append(image_url)
            for ref_url in image_refs:
                if ref_url and ref_url not in omni_images:
                    omni_images.append(ref_url)

            omni_video_list = []
            for ref_url in video_urls or []:
                omni_video_list.append(
                    {
                        "url": ref_url,
                        "start": 0,
                        "ends": min(20, max(1, int(v_duration))),
                    }
                )
                break

            result = await gemini_omni_service.generate_video(
                prompt=prompt,
                duration=v_duration,
                aspect_ratio=v_ratio,
                resolution=omni_resolution,
                image_urls=omni_images or None,
                audio_ids=omni_audio_ids,
                video_list=omni_video_list or None,
                character_ids=omni_character_ids,
                seed=omni_seed,
                callBackUrl=(
                    config.kie_notification_url if config.WEBHOOK_HOST else None
                ),
            )

        elif v_model == "gemini_omni_audio":
            audio_name = omni_voice_name or _derive_omni_name(prompt, "Omni Voice")
            result = await gemini_omni_service.create_audio(
                audio_id=omni_base_voice,
                name=audio_name,
                voice_description=omni_voice_description or prompt,
                example_dialogue=omni_example_dialogue,
            )

        elif v_model == "gemini_omni_character":
            if not image_url:
                await message.answer(
                    "❌ Gemini Omni Character требует изображение персонажа."
                )
                if not is_admin:
                    await add_credits(message.from_user.id, cost)
                await processing_msg.delete()
                await state.clear()
                return

            character_name = omni_character_name or _derive_omni_name(
                prompt,
                "Character",
            )
            result = await gemini_omni_service.create_character(
                description=prompt,
                image_urls=[image_url],
                character_name=character_name,
                audio_ids=omni_character_audio_ids,
            )

        elif v_model.startswith("veo3"):
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
                        "❌ Изображение слишком маленькое (мин 300px)."
                    )
                    if not is_admin:
                        await add_credits(message.from_user.id, cost)
                    await processing_msg.delete()
                    await state.clear()
                    return

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
        elif v_model == "seedance_2":
            seedance_reference_images = []
            seedance_reference_videos = normalize_reference_urls(
                video_urls or [],
                max_count=get_max_video_references(v_model),
            )

            if v_type == "imgtxt":
                if not image_url:
                    await message.answer(
                        "❌ Для Seedance 2.0 в режиме Фото + Текст нужно стартовое фото."
                    )
                    if not is_admin:
                        await add_credits(message.from_user.id, cost)
                    await processing_msg.delete()
                    await state.clear()
                    return

                if image_refs or seedance_reference_videos:
                    seedance_reference_images.append(image_url)
                    for ref_url in image_refs:
                        if ref_url and ref_url not in seedance_reference_images:
                            seedance_reference_images.append(ref_url)

                result = await seedance_service.generate_video(
                    prompt=prompt,
                    duration=v_duration,
                    aspect_ratio=v_ratio,
                    resolution="720p",
                    generate_audio=True,
                    first_frame_url=image_url
                    if not (image_refs or seedance_reference_videos)
                    else None,
                    reference_image_urls=seedance_reference_images or None,
                    reference_video_urls=seedance_reference_videos or None,
                    callBackUrl=(
                        config.kie_notification_url if config.WEBHOOK_HOST else None
                    ),
                )
            else:
                if image_url:
                    seedance_reference_images.append(image_url)
                for ref_url in image_refs:
                    if ref_url and ref_url not in seedance_reference_images:
                        seedance_reference_images.append(ref_url)

                result = await seedance_service.generate_video(
                    prompt=prompt,
                    duration=v_duration,
                    aspect_ratio=v_ratio,
                    resolution="720p",
                    generate_audio=True,
                    reference_image_urls=seedance_reference_images or None,
                    reference_video_urls=seedance_reference_videos or None,
                    callBackUrl=(
                        config.kie_notification_url if config.WEBHOOK_HOST else None
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

            kling_negative_prompt = data.get("kling_negative_prompt", "")
            kling_cfg_scale = float(data.get("kling_cfg_scale", 0.5))

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
                image_input=(
                    image_refs if v_type != "imgtxt" or not elements_list else None
                ),
                elements=elements_list,
                negative_prompt=kling_negative_prompt or None,
                cfg_scale=kling_cfg_scale,
                motion_direction=motion_direction,
                motion_mode=motion_mode,
                webhook_url=(
                    config.kling_notification_url if config.WEBHOOK_HOST else None
                ),
            )

        await processing_msg.delete()

        if result and result.get("status") == "done" and result.get("asset_id"):
            asset_kind = result.get("asset_kind") or "asset"
            task_type = "audio" if asset_kind == "audio" else "character"
            asset_id = str(result["asset_id"])
            await add_generation_task(
                user.id,
                message.from_user.id,
                asset_id,
                task_type,
                "no_preset_video",
                model=v_model,
                duration=v_duration,
                aspect_ratio=v_ratio,
                prompt=prompt,
                cost=cost,
                request_data={
                    "source": "telegram",
                    "v_type": v_type,
                    "v_model": v_model,
                    "asset_kind": asset_kind,
                    "asset_id": asset_id,
                    "v_image_url": image_url,
                    "reference_images": image_refs,
                    "omni_base_voice": omni_base_voice,
                    "omni_voice_name": omni_voice_name,
                    "omni_voice_description": omni_voice_description,
                    "omni_example_dialogue": omni_example_dialogue,
                    "omni_character_name": omni_character_name,
                    "omni_character_audio_ids": omni_character_audio_ids,
                },
            )
            await complete_video_task(asset_id, asset_id)
            result_title = (
                "Audio ID создан"
                if asset_kind == "audio"
                else "Character ID создан"
            )
            await message.answer(
                f"✅ <b>{result_title}</b>\n"
                f"• Модель: <code>{get_video_model_label(v_model)}</code>\n"
                f"• ID: <code>{asset_id}</code>\n"
                f"💰 <code>{cost}</code>🍌 {'списано' if not is_admin else '(админ бесплатно)'}\n\n"
                "Этот ID можно использовать в Gemini Omni Video.",
                parse_mode="HTML",
                reply_markup=get_gemini_omni_result_keyboard(),
            )
            await state.clear()
            return

        if result and "task_id" in result:
            task_type = (
                "audio"
                if v_model == "gemini_omni_audio"
                else "character" if v_model == "gemini_omni_character" else "video"
            )
            await add_generation_task(
                user.id,
                message.from_user.id,
                result["task_id"],
                task_type,
                "no_preset_video",
                model=v_model,
                duration=v_duration,
                aspect_ratio=v_ratio,
                prompt=prompt,
                cost=cost,
                request_data={
                    "source": "telegram",
                    "v_type": v_type,
                    "v_model": v_model,
                    "v_image_url": image_url,
                    "reference_images": image_refs,
                    "v_reference_videos": video_urls or [],
                    "avatar_audio_url": avatar_audio_url,
                    "grok_mode": data.get("grok_mode", "normal"),
                    "veo_generation_type": veo_generation_type,
                    "veo_translation": veo_translation,
                    "veo_resolution": veo_resolution,
                    "veo_seed": veo_seed,
                    "veo_watermark": veo_watermark,
                    "kling_negative_prompt": data.get("kling_negative_prompt", ""),
                    "kling_cfg_scale": data.get("kling_cfg_scale", 0.5),
                    "motion_mode": motion_mode,
                    "motion_direction": motion_direction,
                    "omni_resolution": omni_resolution,
                    "omni_seed": omni_seed,
                    "omni_audio_ids": omni_audio_ids,
                    "omni_character_ids": omni_character_ids,
                    "omni_base_voice": omni_base_voice,
                    "omni_voice_name": omni_voice_name,
                    "omni_voice_description": omni_voice_description,
                    "omni_example_dialogue": omni_example_dialogue,
                    "omni_character_name": omni_character_name,
                    "omni_character_audio_ids": omni_character_audio_ids,
                },
            )
            queued_title = (
                "Audio ID создается"
                if v_model == "gemini_omni_audio"
                else (
                    "Character ID создается"
                    if v_model == "gemini_omni_character"
                    else "Видео задача запущена"
                )
            )
            await message.answer(
                f"✅ <b>{queued_title}!</b>"
                f"🆔 <code>{result['task_id']}</code>\n"
                f"{run_summary}\n"
                f"💰 <code>{cost}</code>🍌 {'списано' if not is_admin else '(админ бесплатно)'}"
                f"⏳ Результат через 1-5 мин в этом чате.",
                parse_mode="HTML",
            )
        else:
            if not is_admin:
                await add_credits(message.from_user.id, cost)
            error_text = ""
            if isinstance(result, dict):
                error_text = make_user_friendly_generation_error(
                    result.get("message") or result.get("error") or ""
                ) or ""
            details = (
                f"\nПричина: <code>{html.escape(error_text[:500])}</code>"
                if error_text
                else ""
            )
            await message.answer(
                "❌ Не получилось создать задачу. Бананы за попытку уже возвращены."
                f"{details}",
                parse_mode="HTML",
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
    """Service callback for informational inline buttons."""
    await callback.answer()


@router.message(GenerationStates.uploading_reference_images, F.photo)
async def upload_reference_image_for_any_image_flow(
    message: types.Message, state: FSMContext
):
    """Universal reference upload fallback for image flows, including Wan 2.7."""
    async with _get_reference_upload_lock(message.from_user.id):
        data = await state.get_data()
        img_service = data.get("img_service", "banana_pro")
        preset_id = data.get("preset_id", "new")
        max_refs = _get_max_image_references(img_service)

        reference_images = list(data.get("reference_images") or [])
        if len(reference_images) >= max_refs:
            await message.answer(
                "❌ Достигнут лимит фото. Нажмите «Продолжить».",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return

        try:
            photo = message.photo[-1]
            file = await message.bot.get_file(photo.file_id)
            downloaded = await message.bot.download_file(file.file_path)
            image_bytes = downloaded.read()

            public_url = await _persist_reusable_image_reference(
                message.from_user.id,
                image_bytes,
                "jpg",
                original_filename=f"telegram_photo_{photo.file_id}.jpg",
                content_type="image/jpeg",
            )
            if not public_url:
                await message.answer(
                    "Не удалось сохранить фото. Попробуйте другое изображение."
                )
                return

            reference_images.append(public_url)
            await state.update_data(reference_images=reference_images)

            title = (
                "🧪 Wan 2.7 Pro — тест" if img_service == "wan_27" else "🖼 Референсы"
            )
            await message.answer(
                f"{title}\n\n"
                f"✅ Фото добавлено: <code>{len(reference_images)}/{max_refs}</code>\n\n"
                "Можете загрузить ещё фото или нажать <b>▶️ Продолжить</b>.",
                reply_markup=get_reference_images_upload_keyboard(
                    len(reference_images), max_refs, preset_id
                ),
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Reference image upload failed")
            await message.answer("Не удалось загрузить фото. Попробуйте ещё раз.")


def _motion_quality_per_second(model_key: str, quality: str) -> float:
    total = preset_manager.get_video_cost_with_quality(model_key, 5, quality)
    raw = total / 5
    return preset_manager._format_cost(raw)


def get_motion_control_model_keyboard(current_model: str = "motion_control_v26"):
    builder = InlineKeyboardBuilder()
    rows = [
        ("motion_control_v26", "🎯 Kling 2.6 Motion Control"),
        ("motion_control_v30", "🚀 Kling 3.0 Motion Control"),
    ]
    for model_key, label in rows:
        check = "✅ " if current_model == model_key else ""
        ps_720 = _motion_quality_per_second(model_key, "720p")
        ps_1080 = _motion_quality_per_second(model_key, "1080p")
        builder.button(
            text=f"{check}{label} • {ps_720}-{ps_1080}🍌/с",
            callback_data=f"motion_model_{model_key}",
        )
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 1)
    return builder.as_markup()


# =============================================================================
# MOTION CONTROL DEDICATED MENU
# =============================================================================


@router.callback_query(F.data == "motion_control")
async def open_motion_control_menu(callback: types.CallbackQuery, state: FSMContext):
    """Open dedicated Motion Control version chooser."""
    await state.clear()
    user_credits = await get_user_credits(callback.from_user.id)
    await state.update_data(
        generation_type="video",
        v_type="motion",
        v_model="motion_control_v26",
        v_duration=5,
        v_ratio="1:1",
        v_image_url=None,
        v_reference_videos=[],
        v_mode="1080p",
        v_orientation="video",
    )
    text = (
        "🎯 <b>Motion Control</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "Выберите версию Kling. На кнопках указана только цена за 1 секунду."
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_motion_control_model_keyboard("motion_control_v26"),
        parse_mode="HTML",
    )
    await callback.answer()


def get_motion_quality_keyboard(model: str, current_mode: str = "1080p"):
    builder = InlineKeyboardBuilder()
    check_720 = "✅ " if current_mode == "720p" else ""
    check_1080 = "✅ " if current_mode == "1080p" else ""
    ps_720 = _motion_quality_per_second(model, "720p")
    ps_1080 = _motion_quality_per_second(model, "1080p")
    builder.button(
        text=f"{check_720}📱 720p • {ps_720}🍌/с",
        callback_data=f"motion_quality_{model}_720p",
    )
    builder.button(
        text=f"{check_1080}🖥 1080p • {ps_1080}🍌/с",
        callback_data=f"motion_quality_{model}_1080p",
    )
    builder.button(text="◀️ Назад", callback_data="motion_control")
    builder.adjust(2, 1)
    return builder.as_markup()


@router.callback_query(
    F.data.in_({"motion_model_motion_control_v26", "motion_model_motion_control_v30"})
)
async def select_motion_control_model(callback: types.CallbackQuery, state: FSMContext):
    """Select Motion Control model — show quality chooser."""
    model = callback.data.replace("motion_model_", "")
    label = (
        "Kling 3.0 Motion Control"
        if model == "motion_control_v30"
        else "Kling 2.6 Motion Control"
    )
    user_credits = await get_user_credits(callback.from_user.id)
    await state.update_data(
        generation_type="video",
        v_type="motion",
        v_model=model,
        v_duration=5,
        v_ratio="1:1",
        v_image_url=None,
        v_reference_videos=[],
        v_mode="1080p",
        v_orientation="video",
    )
    ps_720 = _motion_quality_per_second(model, "720p")
    ps_1080 = _motion_quality_per_second(model, "1080p")
    text = (
        f"🎯 <b>{label}</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n"
        f"💰 Стоимость: <code>{ps_720}</code>-<code>{ps_1080}</code>🍌/с "
        f"(зависит от качества)\n\n"
        "Выберите качество:"
    )
    await callback.message.edit_text(
        text, parse_mode="HTML", reply_markup=get_motion_quality_keyboard(model)
    )
    await callback.answer(label)


@router.callback_query(F.data.startswith("motion_quality_"))
async def select_motion_control_quality(
    callback: types.CallbackQuery, state: FSMContext
):
    """Select quality for Motion Control and ask for character photo."""
    # callback_data format: motion_quality_<model>_<quality>
    parts = callback.data.split("_")
    # parts: ["motion", "quality", "motion", "control", "v26/v30", "720p/1080p"]
    quality = parts[-1]  # "720p" or "1080p"
    model = "_".join(parts[2:-1])  # "motion_control_v26" or "motion_control_v30"

    await state.update_data(v_mode=quality)
    await state.set_state(GenerationStates.waiting_for_video_start_image)

    user_credits = await get_user_credits(callback.from_user.id)
    label = (
        "Kling 3.0 Motion Control"
        if model == "motion_control_v30"
        else "Kling 2.6 Motion Control"
    )
    mode_label = "Pro / 1080p" if quality == "1080p" else "Std / 720p"
    ps_quality = _motion_quality_per_second(model, quality)
    text = (
        f"🎯 <b>{label}</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n"
        f"💰 Стоимость: <code>{ps_quality}</code>🍌/с "
        f"(списывается по длине вашего видео)\n"
        f"⚙️ Режим: <b>{mode_label}</b>\n\n"
        "Шаг 1. Отправьте <b>фото персонажа</b>, которого нужно оживить."
    )
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer(quality)


@router.message(GenerationStates.waiting_for_video_start_image, F.photo)
async def motion_control_character_photo_upload(
    message: types.Message, state: FSMContext
):
    """Upload character photo for dedicated Motion Control flow."""
    data = await state.get_data()
    if data.get("v_type") != "motion":
        return

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    downloaded = await message.bot.download_file(file.file_path)
    image_url = save_uploaded_file(downloaded.read(), "jpg")
    await state.update_data(v_image_url=image_url)
    await state.set_state(GenerationStates.uploading_reference_videos)
    await message.answer(
        "✅ Фото персонажа загружено.\n\n"
        "Шаг 2. Теперь отправьте <b>видео движения</b>.",
        parse_mode="HTML",
    )


@router.message(
    GenerationStates.uploading_reference_videos,
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def motion_control_reference_video_upload(
    message: types.Message, state: FSMContext
):
    """Upload movement video for dedicated Motion Control flow."""
    data = await state.get_data()
    if data.get("v_type") != "motion":
        return

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

    file = await message.bot.get_file(video_obj.file_id)
    downloaded = await message.bot.download_file(file.file_path)
    video_url = save_uploaded_file(downloaded.read(), "mp4")

    raw_duration = getattr(video_obj, "duration", 0) or 0
    v_duration = max(1, min(30, raw_duration)) if raw_duration > 0 else 5

    await state.update_data(v_reference_videos=[video_url], v_duration=v_duration)
    data = await state.get_data()
    v_model = data.get("v_model", "motion_control_v26")
    v_mode = data.get("v_mode", "1080p")
    detected_cost = preset_manager.get_video_cost_with_quality(
        v_model, v_duration, v_mode
    )
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    await message.answer(
        f"✅ Видео движения загружено ({v_duration} сек).\n"
        f"💰 Стоимость: <code>{detected_cost}</code>🍌\n\n"
        "Шаг 3. Отправьте короткое описание результата.\n"
        "Например: <i>сохранить лицо, плавное движение, кинематографичный свет</i>.",
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
    if data.get("v_type") == "motion":
        return  # Propagate to motion_control_reference_video_upload
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")
    current_model = data.get("v_model", "seedance_2")
    max_refs = get_max_video_references(current_model)
    v_reference_videos = normalize_reference_urls(
        data.get("v_reference_videos", []),
        max_count=max_refs,
    )
    if v_reference_videos != (data.get("v_reference_videos", []) or []):
        await state.update_data(v_reference_videos=v_reference_videos)

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

        if len(v_reference_videos) >= max_refs:
            await message.answer(
                f"❌ Можно загрузить максимум {max_refs} видео. Дальше нажмите «Продолжить».",
                parse_mode="HTML",
                reply_markup=get_main_menu_button_keyboard(),
            )
            return

        file = await message.bot.get_file(video_obj.file_id)
        video_bytes = await message.bot.download_file(file.file_path)
        video_data = video_bytes.read()

        # Сохраняем видео и получаем URL
        video_url = await _persist_reusable_media_reference(
            message.from_user.id,
            video_data,
            "mp4",
            kind="video",
            original_filename=f"video_ref_{video_obj.file_id}.mp4",
            content_type=getattr(video_obj, "mime_type", None) or "video/mp4",
        )
        if video_url:
            v_reference_videos.append(video_url)
            v_reference_videos = normalize_reference_urls(
                v_reference_videos,
                max_count=max_refs,
            )
            await state.update_data(v_reference_videos=v_reference_videos)
            logger.info(f"Added reference video {len(v_reference_videos)}: {video_url}")

            if data.get("video_flow_step") == "media":
                await message.answer(
                    f"✅ Видео загружено. Сейчас файлов: <code>{len(v_reference_videos)}/{max_refs}</code>",
                    parse_mode="HTML",
                )
                await _show_video_media_screen(message, state, edit=False)
            else:
                current_count = len(v_reference_videos)
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
    async with _get_reference_upload_lock(message.from_user.id):
        data = await state.get_data()
        reference_images = list(data.get("reference_images") or [])
        v_type = data.get("v_type")
        img_service = data.get("img_service")
        max_refs = _get_max_image_references(img_service) if img_service else 9

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

        # Validate image size required by the video model.
        try:

            img = Image.open(io.BytesIO(image_data))
            width, height = img.size
            if width < 300 or height < 300:
                await message.answer(
                    "❌ Изображение слишком маленькое (мин 300px).",
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

        content_type = "image/jpeg" if file_ext == "jpg" else f"image/{file_ext}"
        image_url = await _persist_reusable_image_reference(
            message.from_user.id,
            image_data,
            file_ext,
            original_filename=f"reference_{photo.file_id}.{file_ext}",
            content_type=content_type,
        )

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
            except Exception:
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
    img_quality = data.get("img_quality", "2K")
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

    user = await get_or_create_user(message.from_user.id)
    unit_cost = preset_manager.get_generation_cost(img_service)
    img_quality_upper = str(img_quality or "2K").upper()
    if img_service in {
        "banana_pro",
        "nano_banana_pro",
        "nano-banana-pro",
        "banana_2",
        "nanobanana",
    }:
        unit_cost = 3.5 if img_quality_upper == "4K" else 2.5
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
        stable_reference_images = _prepare_banana_reference_images(
            img_service, reference_images
        )

        for index in range(img_count):
            variant_prompt = _build_image_variant_prompt(prompt, index, img_count)
            task_reference_images = list(stable_reference_images)
            logger.info(
                "Launching image variant %s/%s with %s references for model=%s",
                index + 1,
                img_count,
                len(task_reference_images),
                img_service,
            )

            launch_result = await _start_image_generation_task(
                user=user,
                telegram_id=message.from_user.id,
                img_service=img_service,
                prompt=variant_prompt,
                img_ratio=img_ratio,
                reference_images=task_reference_images,
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
    await callback.answer(f"Качество: {resolution}")


@router.callback_query(F.data.startswith("veo_gen_"))
async def handle_veo_generation_type(callback: types.CallbackQuery, state: FSMContext):
    """Set Veo image generation subtype."""
    generation_type = callback.data.replace("veo_gen_", "")
    data = await state.get_data()
    current_model = data.get("v_model", "veo3_fast")
    if generation_type == "REFERENCE_2_VIDEO" and current_model != "veo3_fast":
        await callback.answer(
            "❌ Изображение слишком маленькое (мин 300px).",
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
        "🏷 Введите метку для Veo или `off`, чтобы убрать её.\n"
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


@router.callback_query(F.data.startswith("omni_resolution_"))
async def handle_omni_resolution(callback: types.CallbackQuery, state: FSMContext):
    """Set Gemini Omni Video resolution."""
    resolution = callback.data.replace("omni_resolution_", "")
    if resolution not in {"720p", "1080p", "4k"}:
        await callback.answer()
        return
    await state.update_data(omni_resolution=resolution)
    await _show_video_creation_screen(callback, state)
    await callback.answer(f"Качество: {resolution}")


@router.callback_query(F.data == "omni_seed_edit")
async def handle_omni_seed_edit(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_seed = data.get("omni_seed")
    await callback.message.answer(
        "🎲 Введите seed для Gemini Omni (0-2147483647) или `auto`.\n"
        f"Сейчас: <code>{current_seed if current_seed is not None else 'auto'}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_seed)
    await callback.answer()


@router.callback_query(F.data == "omni_audio_ids_edit")
async def handle_omni_audio_ids_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    current_ids = ", ".join(data.get("omni_audio_ids") or []) or "off"
    await callback.message.answer(
        "🎧 Введите Audio ID для Gemini Omni Video или `off`.\n"
        f"Сейчас: <code>{current_ids}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_audio_ids)
    await callback.answer()


@router.callback_query(F.data == "omni_character_ids_edit")
async def handle_omni_character_ids_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    current_ids = ", ".join(data.get("omni_character_ids") or []) or "off"
    await callback.message.answer(
        "🧍 Введите до 3 Character ID через пробел/запятую или `off`.\n"
        f"Сейчас: <code>{current_ids}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_character_ids)
    await callback.answer()


@router.callback_query(F.data == "omni_voice_base_edit")
async def handle_omni_voice_base_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    current_voice = data.get("omni_base_voice", "achernar")
    voices = ", ".join(sorted(gemini_omni_service.BASE_VOICES))
    await callback.message.answer(
        "🎙 Введите базовый голос для Gemini Omni Audio.\n"
        f"Сейчас: <code>{current_voice}</code>\n"
        f"Доступно: <code>{voices}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_voice_base)
    await callback.answer()


@router.callback_query(F.data == "omni_voice_name_edit")
async def handle_omni_voice_name_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    current_name = data.get("omni_voice_name") or "auto"
    await callback.message.answer(
        "🏷 Введите имя голоса до 20 символов или `auto`.\n"
        f"Сейчас: <code>{current_name}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_voice_name)
    await callback.answer()


@router.callback_query(F.data == "omni_voice_desc_edit")
async def handle_omni_voice_desc_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    await callback.message.answer(
        "🗣 Введите описание голоса до 2000 символов или `off`.",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_voice_description)
    await callback.answer()


@router.callback_query(F.data == "omni_voice_dialogue_edit")
async def handle_omni_voice_dialogue_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    await callback.message.answer(
        "💬 Введите пример реплики до 2000 символов или `off`.",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_example_dialogue)
    await callback.answer()


@router.callback_query(F.data == "omni_character_name_edit")
async def handle_omni_character_name_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    current_name = data.get("omni_character_name") or "auto"
    await callback.message.answer(
        "🏷 Введите имя персонажа до 20 символов или `auto`.\n"
        f"Сейчас: <code>{current_name}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_character_name)
    await callback.answer()


@router.callback_query(F.data == "omni_character_audio_ids_edit")
async def handle_omni_character_audio_ids_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    current_ids = ", ".join(data.get("omni_character_audio_ids") or []) or "off"
    await callback.message.answer(
        "🎧 Введите Audio ID для Gemini Omni Character или `off`.\n"
        f"Сейчас: <code>{current_ids}</code>",
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_character_audio_ids)
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


@router.message(GenerationStates.waiting_for_omni_seed, F.text)
async def handle_omni_seed_input(message: types.Message, state: FSMContext):
    value = message.text.strip().lower()
    if value in {"auto", "off", "none", "random"}:
        await state.update_data(omni_seed=None)
    else:
        if not value.isdigit():
            await message.answer("❌ Seed должен быть числом 0-2147483647 или `auto`.")
            return
        seed = int(value)
        if seed < 0 or seed > 2_147_483_647:
            await message.answer("❌ Seed должен быть в диапазоне 0-2147483647.")
            return
        await state.update_data(omni_seed=seed)
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_audio_ids, F.text)
async def handle_omni_audio_ids_input(message: types.Message, state: FSMContext):
    ids = _parse_omni_ids(message.text, max_count=1)
    await state.update_data(omni_audio_ids=ids)
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_character_ids, F.text)
async def handle_omni_character_ids_input(message: types.Message, state: FSMContext):
    ids = _parse_omni_ids(message.text, max_count=3)
    await state.update_data(omni_character_ids=ids)
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_voice_base, F.text)
async def handle_omni_voice_base_input(message: types.Message, state: FSMContext):
    voice = message.text.strip().lower()
    if voice not in gemini_omni_service.BASE_VOICES:
        await message.answer("❌ Такого базового голоса нет в Gemini Omni.")
        return
    await state.update_data(omni_base_voice=voice)
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_voice_name, F.text)
async def handle_omni_voice_name_input(message: types.Message, state: FSMContext):
    value = message.text.strip()
    await state.update_data(
        omni_voice_name="" if value.lower() in {"auto", "off", "none"} else value[:20]
    )
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_voice_description, F.text)
async def handle_omni_voice_description_input(
    message: types.Message,
    state: FSMContext,
):
    value = message.text.strip()
    await state.update_data(
        omni_voice_description=""
        if value.lower() in {"off", "none"}
        else value[:2000]
    )
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_example_dialogue, F.text)
async def handle_omni_example_dialogue_input(
    message: types.Message,
    state: FSMContext,
):
    value = message.text.strip()
    await state.update_data(
        omni_example_dialogue=""
        if value.lower() in {"off", "none"}
        else value[:2000]
    )
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_character_name, F.text)
async def handle_omni_character_name_input(message: types.Message, state: FSMContext):
    value = message.text.strip()
    await state.update_data(
        omni_character_name="" if value.lower() in {"auto", "off", "none"} else value[:20]
    )
    await _show_video_creation_screen(message, state)


@router.message(GenerationStates.waiting_for_omni_character_audio_ids, F.text)
async def handle_omni_character_audio_ids_input(
    message: types.Message,
    state: FSMContext,
):
    ids = _parse_omni_ids(message.text, max_count=1)
    await state.update_data(omni_character_audio_ids=ids)
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
async def open_avatar_service(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(
        generation_type="video",
        video_flow_step="media",
        v_model="avatar_pro",
        v_type="avatar",
        v_duration=5,
        v_ratio="avatar",
        v_image_url=None,
        avatar_audio_url=None,
        audio_url=None,
    )
    await callback.message.edit_text(
        "🗣 <b>Kling Avatar</b>\n\n"
        "Создаёт говорящий аватар по фото и аудио.\n\n"
        "1. Загрузите фото персонажа\n"
        "2. Загрузите аудио или голосовое\n"
        "3. Отправьте короткую инструкцию",
        reply_markup=get_video_media_step_keyboard(
            current_v_type="avatar",
            current_model="avatar_pro",
            has_start_image=False,
            has_avatar_audio=False,
        ),
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    await callback.answer()


@router.callback_query(F.data == "img_quality_2k")
async def set_image_quality_2k(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(img_quality="2K")
    await callback.answer("Выбрано 2K")
    await _show_image_creation_screen(callback, state)


@router.callback_query(F.data == "img_quality_4k")
async def set_image_quality_4k(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(img_quality="4K")
    await callback.answer("Выбрано 4K")
    await _show_image_creation_screen(callback, state)
