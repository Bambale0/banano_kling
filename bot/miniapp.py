import hashlib
import hmac
import json
import logging
import mimetypes
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl

import aiosqlite
from aiohttp import web

from bot.config import config
from bot.database import (
    DATABASE_PATH,
    add_credits,
    add_generation_task,
    check_can_afford,
    complete_video_task,
    create_transaction,
    deduct_credits,
    get_and_clear_miniapp_notifications,
    get_or_create_user,
    get_partner_overview,
    get_user_stats,
)
from bot.handlers.batch_generation import get_batch_upload_keyboard
from bot.handlers.common import (
    AIAssistantStates,
    _build_balance_text,
    _build_main_menu_text,
)
from bot.handlers.generation import (
    _init_default_video_state,
    _show_image_model_selection_screen,
    _show_video_model_selection_screen,
    _start_image_generation_task,
    save_uploaded_file,
)
from bot.handlers.image_analyzer import ImageAnalyzerStates
from bot.keyboards import (
    get_ai_assistant_keyboard,
    get_animate_hub_keyboard,
    get_balance_keyboard,
    get_create_hub_keyboard,
    get_edit_hub_keyboard,
    get_image_model_label,
    get_main_menu_button_keyboard,
    get_main_menu_keyboard,
    get_more_menu_keyboard,
    get_partner_program_keyboard,
    get_payment_packages_keyboard,
    get_support_keyboard,
    get_video_model_label,
)
from bot.quality_pricing import QUALITY_COSTS
from bot.services.ai_assistant_service import ai_assistant_service
from bot.services.preset_manager import preset_manager
from bot.services.yookassa_service import yookassa_service

logger = logging.getLogger(__name__)

IMAGE_MODELS = (
    {
        "id": "banana_pro",
        "label": "Nano Banana Pro",
        "description": "Универсальная модель для качественных изображений",
        "cost": preset_manager.get_generation_cost("nano-banana-pro"),
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:2"],
        "requires_reference": False,
        "max_references": 14,
    },
    {
        "id": "banana_2",
        "label": "Nano Banana 2",
        "description": "Новая версия Nano Banana с улучшенной детализацией и цветопередачей",
        "cost": preset_manager.get_generation_cost("banana_2"),
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:2"],
        "requires_reference": False,
        "max_references": 14,
    },
    {
        "id": "seedream_edit",
        "label": "Seedream 4.5 Edit",
        "description": "Сильный edit по исходникам",
        "cost": preset_manager.get_generation_cost("seedream_edit"),
        "ratios": ["1:1", "9:16", "16:9", "3:4", "4:3", "2:3", "3:2", "21:9"],
        "requires_reference": True,
        "max_references": 14,
        "qualities": ["2K", "4K"],
        "supports_nsfw_checker": False,
    },
    {
        "id": "flux_pro",
        "label": "GPT Image 2",
        "description": "Детальная генерация и мягкий image-to-image",
        "cost": preset_manager.get_generation_cost("flux_pro"),
        "ratios": ["auto", "1:1", "9:16", "16:9", "3:4", "4:3"],
        "requires_reference": False,
        "max_references": 16,
        "supports_nsfw_checker": True,
    },
    {
        "id": "wan_27",
        "label": "Wan 2.7 Pro",
        "description": "Генерация и редактирование через Wan 2.7",
        "cost": preset_manager.get_generation_cost("wan_27"),
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "21:9"],
        "requires_reference": False,
        "max_references": 9,
        "supports_nsfw_checker": False,
        "supports_wan_options": True,
    },
    {
        "id": "grok_imagine_i2i",
        "label": "Grok Imagine",
        "description": "I2I-сценарий для ярких переработок",
        "cost": preset_manager.get_generation_cost("grok_imagine_i2i"),
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:2"],
        "requires_reference": True,
        "max_references": 7,
        "supports_nsfw_mode": True,
    },
)

VIDEO_MODELS = (
    {
        "id": "v3_pro",
        "label": "Kling 3.0",
        "description": "Флагманский видео-режим",
        "durations": [5, 10, 15],
        "ratios": ["16:9", "9:16", "1:1"],
        "supports": ["text", "imgtxt", "video"],
        "max_image_references": 12,
        "max_video_references": 5,
    },
    {
        "id": "v3_std",
        "label": "Kling v3",
        "description": "Быстрее и дешевле для everyday-видео",
        "durations": [5, 10, 15],
        "ratios": ["16:9", "9:16", "1:1"],
        "supports": ["text", "imgtxt", "video"],
        "max_image_references": 12,
        "max_video_references": 5,
    },
    {
        "id": "v26_pro",
        "label": "Kling 2.5 Turbo Pro",
        "description": "Хорош для image-to-video",
        "durations": [5, 10],
        "ratios": ["16:9", "9:16", "1:1"],
        "supports": ["text", "imgtxt"],
        "supports_negative_prompt": True,
        "supports_cfg_scale": True,
        "max_image_references": 12,
    },
    {
        "id": "grok_imagine",
        "label": "Grok Imagine",
        "description": "Длинные ролики из фото",
        "durations": [6, 10, 20, 30],
        "ratios": ["16:9", "9:16", "1:1", "3:2", "2:3"],
        "supports": ["imgtxt"],
        "grok_modes": ["normal", "fun", "spicy"],
        "max_image_references": 6,
    },
    {
        "id": "veo3_fast",
        "label": "Veo 3.1 Fast",
        "description": "Быстрый кинематографичный рендер",
        "durations": [5, 8],
        "ratios": ["16:9", "9:16", "Auto"],
        "supports": ["text", "imgtxt"],
        "veo_generation_types": [
            "TEXT_2_VIDEO",
            "FIRST_AND_LAST_FRAMES_2_VIDEO",
            "REFERENCE_2_VIDEO",
        ],
        "veo_resolutions": ["720p"],
        "supports_translation": True,
        "supports_seed": True,
        "supports_watermark": True,
        "max_image_references": 3,
    },
    {
        "id": "motion_control_v26",
        "label": "Kling 2.6 Motion Control",
        "description": "Перенос движения по фото персонажа и видео движения",
        "durations": [5],
        "ratios": ["1:1"],
        "supports": ["motion"],
        "motion_versions": ["2.6"],
        "motion_modes": ["720p", "1080p"],
        "max_image_references": 1,
        "max_video_references": 1,
    },
    {
        "id": "motion_control_v30",
        "label": "Kling 3.0 Motion Control",
        "description": "Обновлённая версия Motion Control для фото и видео движения",
        "durations": [5],
        "ratios": ["motion"],
        "supports": ["motion"],
        "motion_versions": ["3.0"],
        "motion_modes": ["720p", "1080p"],
        "max_image_references": 1,
        "max_video_references": 1,
    },
    {
        "id": "avatar_std",
        "label": "Kling Avatar Standard",
        "description": "Говорящий аватар по фото и аудио",
        "durations": [5],
        "ratios": ["avatar"],
        "supports": ["avatar"],
        "requires_audio": True,
        "requires_image": True,
        "max_image_references": 1,
        "max_audio_references": 1,
    },
    {
        "id": "avatar_pro",
        "label": "Kling Avatar Pro",
        "description": "Качественный говорящий аватар по фото и аудио",
        "durations": [5],
        "ratios": ["avatar"],
        "supports": ["avatar"],
        "requires_audio": True,
        "requires_image": True,
        "max_image_references": 1,
        "max_audio_references": 1,
    },
)

FILE_KIND_MAP = {
    "image_reference": {"prefix": "image/", "fallback_ext": "png", "group": "image"},
    "video_reference": {"prefix": "video/", "fallback_ext": "mp4", "group": "video"},
    "audio_reference": {"prefix": "audio/", "fallback_ext": "mp3", "group": "audio"},
}


def _resolve_miniapp_static_root() -> Path:
    """Prefer a built Next.js export when available, fallback to bundled static app.

    Use repository-relative absolute paths (based on this file location) so
    resolution does not depend on the process working directory.
    """
    base = Path(__file__).resolve().parent.parent
    candidates = [
        base / "frontend" / "miniapp-v0" / "out",
        base / "frontend" / "miniapp-v0" / "dist",
        base / "static" / "miniapp",
    ]
    for candidate in candidates:
        index_file = candidate / "index.html"
        if index_file.exists():
            return candidate
    # Fallback to repo static path (absolute) even if index missing — callers
    # will handle missing file and return correct 404. This avoids relying on
    # the current working directory.
    return base / "static" / "miniapp"


class _MessageTarget:
    """Tiny adapter so existing helpers can send messages outside updates."""

    def __init__(self, bot, telegram_id: int):
        self._bot = bot
        self.from_user = SimpleNamespace(id=telegram_id)
        self._telegram_id = telegram_id

    async def answer(self, text: str, **kwargs):
        return await self._bot.send_message(self._telegram_id, text, **kwargs)


def _validate_init_data(init_data: str, bot_token: str) -> dict[str, Any]:
    if not init_data:
        raise ValueError("Missing init_data")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    their_hash = parsed.pop("hash", "")
    if not their_hash:
        raise ValueError("Missing Telegram hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, their_hash):
        raise ValueError("Invalid Telegram signature")

    auth_date = int(parsed.get("auth_date", "0") or 0)
    if not auth_date or abs(time.time() - auth_date) > 86400:
        raise ValueError("Expired Telegram session")

    user = json.loads(parsed.get("user", "{}") or "{}")
    if not user or "id" not in user:
        raise ValueError("Missing Telegram user")

    parsed["user"] = user
    return parsed


async def _get_user_context(app: web.Application, init_data: str) -> tuple[int, dict]:
    payload = _validate_init_data(init_data, config.BOT_TOKEN)
    telegram_id = int(payload["user"]["id"])
    user = await get_or_create_user(telegram_id)
    return telegram_id, {"payload": payload, "user": user}


async def _get_state(app: web.Application, telegram_id: int):
    dp = app["dp"]
    bot = app["bot"]
    return dp.fsm.get_context(bot=bot, chat_id=telegram_id, user_id=telegram_id)


def _guess_extension(filename: str, content_type: str, fallback_ext: str) -> str:
    guessed = ""
    if filename:
        guessed = Path(filename).suffix.lstrip(".").lower()
    if guessed:
        return guessed
    guessed = mimetypes.guess_extension(content_type or "") or ""
    guessed = guessed.lstrip(".").lower()
    return guessed or fallback_ext


def _task_preview(prompt: str, limit: int = 90) -> str:
    if not prompt:
        return ""
    compact = " ".join(str(prompt).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _parse_request_data(raw_value: str | None) -> dict[str, Any]:
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_video_ratio(ratio: str) -> str:
    if ratio == "Auto":
        return "auto"
    return ratio or "16:9"


async def _fetch_recent_tasks(telegram_id: int, limit: int = 8) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT task_id, type, model, aspect_ratio, prompt, cost, status, result_url, created_at
            FROM generation_tasks
            WHERE telegram_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (telegram_id, limit),
        )
        rows = await cursor.fetchall()

    tasks: list[dict[str, Any]] = []
    for row in rows:
        task_type = row["type"] or "image"
        model = row["model"] or ""
        label = (
            get_image_model_label(model)
            if task_type == "image"
            else get_video_model_label(model)
        )
        tasks.append(
            {
                "task_id": row["task_id"],
                "type": task_type,
                "model": model,
                "model_label": label,
                "aspect_ratio": row["aspect_ratio"] or "",
                "status": row["status"] or "pending",
                "result_url": row["result_url"],
                "created_at": row["created_at"],
                "prompt_preview": _task_preview(row["prompt"]),
                "cost": row["cost"] or 0,
            }
        )
    return tasks


async def _fetch_task_detail(telegram_id: int, task_id: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT task_id, type, model, duration, aspect_ratio, prompt, cost, status,
                   result_url, created_at, request_data
            FROM generation_tasks
            WHERE telegram_id = ? AND task_id = ?
            LIMIT 1
            """,
            (telegram_id, task_id),
        )
        row = await cursor.fetchone()

    if not row:
        return None

    task_type = row["type"] or "image"
    model = row["model"] or ""
    request_data = _parse_request_data(row["request_data"])
    model_label = (
        get_image_model_label(model)
        if task_type == "image"
        else get_video_model_label(model)
    )
    return {
        "task_id": row["task_id"],
        "type": task_type,
        "model": model,
        "model_label": model_label,
        "duration": row["duration"],
        "aspect_ratio": row["aspect_ratio"] or "",
        "prompt": row["prompt"] or "",
        "cost": row["cost"] or 0,
        "status": row["status"] or "pending",
        "result_url": row["result_url"],
        "created_at": row["created_at"],
        "request_data": request_data,
    }


def _classify_video_generation_result(result: Any) -> tuple[str, str | None]:
    if isinstance(result, dict):
        if result.get("task_id"):
            return "queued", None
        return "failed", result.get("message") or result.get("error") or str(result)
    if isinstance(result, (bytes, bytearray)):
        return "done", None
    if result:
        return "failed", f"Unexpected result type: {type(result).__name__}"
    return "failed", None


async def _launch_video_generation_task(
    *,
    telegram_id: int,
    user,
    model: str,
    prompt: str,
    duration: int,
    aspect_ratio: str,
    generation_type: str,
    image_url: str | None,
    image_references: list[str],
    video_references: list[str],
    audio_url: str | None = None,
    grok_mode: str = "normal",
    veo_generation_type: str = "TEXT_2_VIDEO",
    veo_translation: bool = True,
    veo_resolution: str = "720p",
    veo_seed: int | None = None,
    veo_watermark: str | None = None,
    kling_negative_prompt: str | None = None,
    kling_cfg_scale: float | None = None,
) -> dict[str, Any]:
    from bot.services.grok_service import grok_service
    from bot.services.kling_service import kling_service
    from bot.services.veo_service import veo_service

    normalized_ratio = _normalize_video_ratio(aspect_ratio)
    callback_url = config.kling_notification_url if config.WEBHOOK_HOST else None

    if model in {"avatar_std", "avatar_pro"}:
        result = await kling_service.generate_video(
            prompt=prompt,
            model=model,
            duration=duration,
            aspect_ratio=normalized_ratio,
            image_url=image_url,
            video_urls=[audio_url] if audio_url else [],
            webhook_url=callback_url,
        )
    elif model == "motion_control_v26":
        result = await kling_service.generate_video(
            prompt=prompt,
            model=model,
            duration=duration,
            aspect_ratio=normalized_ratio,
            image_url=image_url,
            video_urls=video_references[:1],
            webhook_url=callback_url,
        )
    elif model == "grok_imagine":
        result = await grok_service.generate_image_to_video(
            image_urls=[image_url] + image_references[:6],
            prompt=prompt,
            mode=grok_mode,
            duration=duration,
            aspect_ratio=normalized_ratio,
            callBackUrl=callback_url,
        )
    elif model.startswith("veo3"):
        veo_image_urls = []
        generation_mode = "TEXT_2_VIDEO"
        if generation_type == "imgtxt":
            generation_mode = "FIRST_AND_LAST_FRAMES_2_VIDEO"
            if image_url:
                veo_image_urls.append(image_url)
            for ref_url in image_references:
                if ref_url not in veo_image_urls:
                    veo_image_urls.append(ref_url)
                if len(veo_image_urls) >= 2:
                    break
        result = await veo_service.generate_video(
            prompt=prompt,
            model=model,
            duration=duration,
            generation_type=veo_generation_type or generation_mode,
            image_urls=veo_image_urls or None,
            aspect_ratio=normalized_ratio,
            enable_translation=veo_translation,
            watermark=veo_watermark,
            resolution=veo_resolution or "720p",
            seeds=veo_seed,
            callBackUrl=(config.kie_notification_url if config.WEBHOOK_HOST else None),
        )
    else:
        result = await kling_service.generate_video(
            prompt=prompt,
            model=model,
            duration=duration,
            aspect_ratio=normalized_ratio,
            image_url=image_url,
            video_urls=video_references if generation_type == "video" else None,
            image_input=image_references if generation_type != "imgtxt" else None,
            elements=(
                [
                    {
                        "description": "reference photos for video generation consistency and style",
                        "reference_image_urls": image_references[:12],
                    }
                ]
                if generation_type == "imgtxt" and image_references
                else None
            ),
            negative_prompt=kling_negative_prompt,
            cfg_scale=kling_cfg_scale,
            webhook_url=callback_url,
        )

    result_status, error_message = _classify_video_generation_result(result)
    cost = preset_manager.get_video_cost(model, duration)

    if result_status == "queued":
        await add_generation_task(
            user.id,
            telegram_id,
            result["task_id"],
            "video",
            "miniapp_video",
            model=model,
            duration=duration,
            aspect_ratio=normalized_ratio,
            prompt=prompt,
            cost=cost,
            request_data={
                "source": "miniapp",
                "v_type": generation_type,
                "v_model": model,
                "v_image_url": image_url,
                "reference_images": image_references,
                "v_reference_videos": video_references,
                "audio_url": audio_url,
                "grok_mode": grok_mode,
                "veo_generation_type": veo_generation_type,
                "veo_translation": veo_translation,
                "veo_resolution": veo_resolution,
                "veo_seed": veo_seed,
                "veo_watermark": veo_watermark,
                "kling_negative_prompt": kling_negative_prompt,
                "kling_cfg_scale": kling_cfg_scale,
            },
        )
        return {
            "status": "queued",
            "task_id": result["task_id"],
            "cost": cost,
        }

    local_task_id = f"miniapp_video_{int(time.time() * 1000)}_{telegram_id}"
    await add_generation_task(
        user.id,
        telegram_id,
        local_task_id,
        "video",
        "miniapp_video",
        model=model,
        duration=duration,
        aspect_ratio=normalized_ratio,
        prompt=prompt,
        cost=cost,
        request_data={"source": "miniapp", "v_type": generation_type},
    )

    if result_status == "done":
        saved_url = save_uploaded_file(bytes(result), "mp4")
        await complete_video_task(local_task_id, saved_url)
        return {
            "status": "done",
            "task_id": local_task_id,
            "saved_url": saved_url,
            "cost": cost,
        }

    await complete_video_task(local_task_id, None)
    return {
        "status": "failed",
        "task_id": local_task_id,
        "error": error_message or "Не удалось создать видео задачу",
        "cost": cost,
    }


async def _send_main_menu(app: web.Application, telegram_id: int):
    user = await get_or_create_user(telegram_id)
    text = _build_main_menu_text(user.credits)
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_main_menu_keyboard(user.credits),
        parse_mode="HTML",
    )


async def _send_create_hub(app: web.Application, telegram_id: int):
    user = await get_or_create_user(telegram_id)
    text = (
        "✨ <b>Создать</b>\n"
        f"🍌 Баланс: <code>{user.credits}</code> бананов\n\n"
        "Выберите, что хотите получить. Можно использовать готовый сценарий "
        "или открыть пошаговый режим."
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_create_hub_keyboard(),
        parse_mode="HTML",
    )


async def _send_edit_hub(app: web.Application, telegram_id: int):
    user = await get_or_create_user(telegram_id)
    text = (
        "✏️ <b>Изменить фото</b>\n"
        f"🍌 Баланс: <code>{user.credits}</code> бананов\n\n"
        "Здесь можно поменять стиль, фон, одежду, детали или настроение кадра.\n"
        "Сначала выберите сценарий ниже."
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_edit_hub_keyboard(),
        parse_mode="HTML",
    )


async def _send_animate_hub(app: web.Application, telegram_id: int):
    user = await get_or_create_user(telegram_id)
    text = (
        "🎬 <b>Оживить</b>\n"
        f"🍌 Баланс: <code>{user.credits}</code> бананов\n\n"
        "Выберите, как хотите сделать видео:\n"
        "• оживить фото\n"
        "• перенести движение\n"
        "• использовать видео-референсы"
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_animate_hub_keyboard(),
        parse_mode="HTML",
    )


async def _send_more_menu(app: web.Application, telegram_id: int):
    user = await get_or_create_user(telegram_id)
    text = (
        "⋯ <b>Ещё</b>\n"
        f"🍌 Баланс: <code>{user.credits}</code> бананов\n\n"
        "Здесь находятся баланс, история, помощь, поддержка и партнёрская программа."
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_more_menu_keyboard(),
        parse_mode="HTML",
    )


async def _send_create_image(app: web.Application, telegram_id: int):
    state = await _get_state(app, telegram_id)
    await state.clear()
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
    await _show_image_model_selection_screen(
        _MessageTarget(app["bot"], telegram_id), state, edit=False
    )


async def _send_create_video(app: web.Application, telegram_id: int):
    state = await _get_state(app, telegram_id)
    await state.clear()
    await _init_default_video_state(
        state, v_model="v3_pro", v_duration=5, v_ratio="16:9"
    )
    await state.update_data(video_flow_step="select_model")
    await _show_video_model_selection_screen(
        _MessageTarget(app["bot"], telegram_id), state, edit=False
    )


async def _send_photo_prompt(app: web.Application, telegram_id: int):
    state = await _get_state(app, telegram_id)
    await state.clear()
    await state.set_state(ImageAnalyzerStates.waiting_for_photo)
    user = await get_or_create_user(telegram_id)
    text = (
        "📸 <b>Анализ фото -> Промпт</b>\n"
        f"🍌 Баланс: <code>{user.credits}</code> бананов\n\n"
        "<b>Что делает этот режим</b>\n"
        "Отправьте фото, и бот соберёт по нему аккуратный промпт для дальнейшей генерации.\n\n"
        "Обычно хорошо распознаются:\n"
        "• персонажи, лица и одежда\n"
        "• поза, композиция и ракурс\n"
        "• свет, фон и общее настроение\n\n"
        "<i>Анализ бесплатный.</i>"
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_main_menu_button_keyboard(),
        parse_mode="HTML",
    )


async def _send_balance(app: web.Application, telegram_id: int):
    user = await get_or_create_user(telegram_id)
    stats = await get_user_stats(telegram_id)
    await app["bot"].send_message(
        telegram_id,
        _build_balance_text(stats),
        reply_markup=get_balance_keyboard(user.credits),
        parse_mode="HTML",
    )


async def _send_topup(app: web.Application, telegram_id: int):
    packages = preset_manager.get_packages()
    text = (
        "🍌 <b>Пополнение баланса</b>\n\n"
        "Оплата выполняется через CryptoBot.\n"
        "Выберите пакет бананов ниже.\n\n"
        "<i>Чем больше пакет, тем выгоднее цена за банан.</i>"
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_payment_packages_keyboard(packages),
        parse_mode="HTML",
    )


async def _send_support(app: web.Application, telegram_id: int):
    text = (
        "🆘 <b>Поддержка</b>\n\n"
        "Можно написать прямо сюда — AI-ассистент поможет с:\n"
        "• генерацией изображений и видео\n"
        "• выбором модели и настроек\n"
        "• оплатой и балансом\n"
        "• любыми непонятными шагами в боте\n\n"
        "<b>Если нужен человек:</b>\n"
        "@only_tany"
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_support_keyboard(),
        parse_mode="HTML",
    )


async def _send_ai_assistant(app: web.Application, telegram_id: int):
    state = await _get_state(app, telegram_id)
    await state.clear()
    await state.set_state(AIAssistantStates.waiting_for_message)
    await state.update_data(ai_mode="main_menu")
    text = """🍌 <b>AI-ассистент</b>

Я помогу с моделями, промптами, настройками и сценариями генерации.

<b>Например, можно спросить:</b>
• какая модель лучше для фотореализма
• что выбрать для видео из фото
• как использовать референсы
• как собрать промпт под fashion / anime / product
• чем отличается Veo от Kling
• как работает Motion Control

<i>Просто напишите вопрос — отвечу по делу и подскажу следующий шаг в боте.</i>"""
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_ai_assistant_keyboard(),
        parse_mode="HTML",
    )


async def _send_history(app: web.Application, telegram_id: int):
    user = await get_or_create_user(telegram_id)
    stats = await get_user_stats(telegram_id)
    text = (
        "📋 <b>История</b>\n\n"
        f"• Всего генераций: <code>{stats['generations']}</code>\n"
        f"• Потрачено бананов: <code>{stats['total_spent']}</code>\n"
        f"• Текущий баланс: <code>{user.credits}</code>🍌\n"
        f"• Дата регистрации: <code>{stats['member_since']}</code>\n\n"
        "<i>Подробная история запусков появится здесь чуть позже.</i>"
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_main_menu_keyboard(user.credits),
        parse_mode="HTML",
    )


async def _send_batch_edit(app: web.Application, telegram_id: int):
    state = await _get_state(app, telegram_id)
    await state.clear()
    await state.update_data(
        batch_mode="reference_edit",
        main_image=None,
        reference_images=[],
    )
    from bot.states import GenerationStates

    await state.set_state(GenerationStates.waiting_for_batch_image)
    user_credits = (await get_or_create_user(telegram_id)).credits
    text = (
        "🎨 <b>Редактирование по референсам</b>\n"
        f"🍌 Ваш баланс: <code>{user_credits}</code> бананов\n\n"
        "1. Загрузите <b>главное фото</b> для редактирования\n"
        "2. Добавьте до <b>14 референсов</b>\n"
        "3. Введите промпт\n"
        "4. Получите результат с учётом исходников\n\n"
        "💰 Стоимость: <b>4🍌</b>\n"
        "<i>📸 Отправьте главное фото для редактирования.</i>"
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_batch_upload_keyboard(),
        parse_mode="HTML",
    )


async def _send_partner(app: web.Application, telegram_id: int):
    stats = await get_partner_overview(telegram_id)
    user = await get_or_create_user(telegram_id)
    me = await app["bot"].get_me()
    referral_link = (
        f"https://t.me/{me.username}?start=ref_{user.referral_code}"
        if user.referral_code
        else ""
    )
    text = (
        "🤝 <b>Партнёрская программа</b>\n\n"
        f"• Рефералов: <code>{stats.get('referrals_count', 0)}</code>\n"
        f"• Баланс партнёра: <code>{stats.get('balance_rub', 0)}</code> ₽\n"
        f"• Статус: <code>{'partner' if stats.get('is_partner') else 'basic'}</code>\n\n"
        "<i>Ниже доступны оферта, статистика, вывод и ваша ссылка.</i>"
    )
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_partner_program_keyboard(
            referral_link, is_partner=stats.get("is_partner", False)
        ),
        parse_mode="HTML",
    )


async def _send_admin(app: web.Application, telegram_id: int):
    from bot.database import get_admin_stats
    from bot.keyboards import get_admin_keyboard

    if not config.is_admin(telegram_id):
        await app["bot"].send_message(
            telegram_id,
            "⛔ У вас нет доступа к админ-панели.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    stats = await get_admin_stats()
    text = f"""
🔧 <b>Админ-панель</b>

📊 <b>Статистика:</b>
• Пользователей: <code>{stats['total_users']}</code>
• Генераций: <code>{stats['total_generations']}</code>
• Транзакций: <code>{stats['total_transactions']}</code>
• Выручка: <code>{stats['total_revenue']:.0f}</code> ₽

Выберите действие:
"""
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML",
    )


ACTIONS = {
    "open_main_menu": _send_main_menu,
    "open_create_hub": _send_create_hub,
    "open_edit_hub": _send_edit_hub,
    "open_animate_hub": _send_animate_hub,
    "open_more_menu": _send_more_menu,
    "create_image": _send_create_image,
    "create_video": _send_create_video,
    "photo_prompt": _send_photo_prompt,
    "show_balance": _send_balance,
    "show_topup": _send_topup,
    "show_support": _send_support,
    "show_ai_assistant": _send_ai_assistant,
    "show_history": _send_history,
    "open_batch_edit": _send_batch_edit,
    "show_partner": _send_partner,
    "show_admin": _send_admin,
}


async def miniapp_index(_request: web.Request) -> web.Response:
    root = _resolve_miniapp_static_root()
    index_path = root / "index.html"
    logger.info(
        "Miniapp index requested, resolved static root=%s index_exists=%s",
        str(root),
        str(index_path.exists()),
    )
    response = web.FileResponse(index_path)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


async def miniapp_asset(request: web.Request) -> web.Response:
    static_root = _resolve_miniapp_static_root().resolve()
    tail = request.match_info.get("tail", "").lstrip("/")
    asset_path = (static_root / tail).resolve()
    logger.info(
        "Miniapp asset request: tail=%s static_root=%s asset_path=%s exists=%s",
        tail,
        str(static_root),
        str(asset_path),
        str(asset_path.exists()),
    )

    try:
        asset_path.relative_to(static_root)
    except ValueError:
        raise web.HTTPNotFound()

    if not asset_path.exists() or not asset_path.is_file():
        raise web.HTTPNotFound()

    response = web.FileResponse(asset_path)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


async def miniapp_bootstrap(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        telegram_id, ctx = await _get_user_context(request.app, init_data)
        user = ctx["user"]
        me = await request.app["bot"].get_me()
        recent_tasks = await _fetch_recent_tasks(telegram_id)
        data = {
            "ok": True,
            "telegram_id": telegram_id,
            "credits": user.credits,
            "first_name": ctx["payload"]["user"].get("first_name", ""),
            "username": me.username,
            "mini_app_url": config.mini_app_url,
            "is_admin": config.is_admin(telegram_id),
            "actions": sorted(ACTIONS.keys()),
            "payment_packages": preset_manager.get_packages(),
            "image_models": list(IMAGE_MODELS),
            "video_models": [
                {
                    **item,
                    "costs": {
                        str(duration): preset_manager.get_video_cost(
                            item["id"], duration
                        )
                        for duration in item["durations"]
                    },
                }
                for item in VIDEO_MODELS
            ],
            "recent_tasks": recent_tasks,
            "notifications": await get_and_clear_miniapp_notifications(telegram_id),
        }
        return web.json_response(data)
    except Exception as e:
        logger.warning("Mini App bootstrap failed: %s", e)
        return web.json_response({"ok": False, "error": str(e)}, status=400)


async def miniapp_action(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        action = body.get("action", "")
        telegram_id, _ctx = await _get_user_context(request.app, init_data)

        handler = ACTIONS.get(action)
        if not handler:
            return web.json_response(
                {"ok": False, "error": f"Unknown action: {action}"}, status=400
            )

        await handler(request.app, telegram_id)
        return web.json_response({"ok": True})
    except Exception as e:
        logger.exception("Mini App action failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_upload(request: web.Request) -> web.Response:
    try:
        data = await request.post()
        init_data = str(data.get("init_data", ""))
        file_kind = str(data.get("file_kind", "image_reference"))
        upload = data.get("file")

        telegram_id, _ctx = await _get_user_context(request.app, init_data)
        _ = telegram_id

        if file_kind not in FILE_KIND_MAP:
            return web.json_response(
                {"ok": False, "error": f"Unsupported file_kind: {file_kind}"},
                status=400,
            )
        if upload is None or not getattr(upload, "file", None):
            return web.json_response(
                {"ok": False, "error": "Файл не был передан"}, status=400
            )

        config_entry = FILE_KIND_MAP[file_kind]
        content_type = getattr(upload, "content_type", "") or ""
        if not content_type.startswith(config_entry["prefix"]):
            return web.json_response(
                {
                    "ok": False,
                    "error": f"Ожидался тип {config_entry['prefix']}*, получен {content_type or 'unknown'}",
                },
                status=400,
            )

        raw = upload.file.read()
        if not isinstance(raw, (bytes, bytearray)) or not raw:
            return web.json_response(
                {"ok": False, "error": "Не удалось прочитать файл"}, status=400
            )

        if len(raw) > 50 * 1024 * 1024:
            return web.json_response(
                {"ok": False, "error": "Файл слишком большой, максимум 50MB"},
                status=400,
            )

        extension = _guess_extension(
            getattr(upload, "filename", ""),
            content_type,
            config_entry["fallback_ext"],
        )
        public_url = save_uploaded_file(bytes(raw), extension)
        if not public_url:
            return web.json_response(
                {"ok": False, "error": "Не удалось сохранить файл"}, status=500
            )

        return web.json_response(
            {
                "ok": True,
                "url": public_url,
                "kind": config_entry["group"],
                "filename": getattr(upload, "filename", "") or Path(public_url).name,
                "content_type": content_type,
            }
        )
    except Exception as e:
        logger.exception("Mini App upload failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_create_payment(request: web.Request) -> web.Response:
    """Create a YooKassa payment for a selected package from the mini-app."""
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        package_id = body.get("package_id")

        if not package_id:
            return web.json_response(
                {"ok": False, "error": "package_id is required"}, status=400
            )

        telegram_id, ctx = await _get_user_context(request.app, init_data)
        user = ctx["user"]

        package = preset_manager.get_package(package_id)
        if not package:
            return web.json_response(
                {"ok": False, "error": "Package not found"}, status=404
            )

        order_id = f"{telegram_id}_{int(time.time())}_{package_id}"
        total_credits = package["credits"] + package.get("bonus_credits", 0)
        description = f"Покупка {total_credits} бананов ({package['name']})"

        # Create YooKassa payment (use service directly)
        if not yookassa_service.enabled:
            return web.json_response(
                {"ok": False, "error": "YooKassa not configured"}, status=500
            )

        result = await yookassa_service.create_payment(
            amount_rub=float(package["price_rub"]),
            order_id=order_id,
            description=description,
            return_url=config.YOOKASSA_RETURN_URL or config.mini_app_url,
            notification_url=config.yookassa_notification_url,
        )

        if not result or not (result.get("Success") or result.get("PaymentId")):
            return web.json_response(
                {"ok": False, "error": result or "Failed to create payment"}, status=500
            )

        payment_id = result.get("PaymentId")
        payment_url = result.get("PaymentURL")

        # Persist transaction
        await create_transaction(
            order_id=order_id,
            user_id=user.id,
            payment_id=payment_id,
            provider="yookassa",
            credits=total_credits,
            amount_rub=float(package["price_rub"]),
            status="pending",
        )

        return web.json_response(
            {
                "ok": True,
                "order_id": order_id,
                "payment_id": payment_id,
                "payment_url": payment_url,
            }
        )

    except Exception as e:
        logger.exception("Mini App create-payment failed: %s", e)
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_photo_to_prompt(request: web.Request) -> web.Response:
    """Analyze a reference image and return generation prompts via GPT 5.4."""
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        image_url = str(body.get("image_url", "") or "").strip()
        preserve = str(body.get("preserve", "") or "").strip()
        goal = str(body.get("goal", "") or "").strip()

        await _get_user_context(request.app, init_data)

        if not image_url:
            return web.json_response(
                {"ok": False, "error": "Загрузите фото для анализа"},
                status=400,
            )

        from bot.services.photo_prompt_service import photo_prompt_service

        result = await photo_prompt_service.analyze_photo(
            image_url=image_url,
            preserve=preserve,
            goal=goal,
        )

        return web.json_response(
            {
                "ok": True,
                "prompt_en": result["prompt_en"],
                "prompt_ru": result["prompt_ru"],
                "negative_prompt": result["negative_prompt"],
                "model_hint": result["model_hint"],
                "key_details": result.get("key_details", []),
            }
        )
    except Exception as e:
        logger.exception("Mini App photo-to-prompt failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_generate_image(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        telegram_id, ctx = await _get_user_context(request.app, init_data)
        user = ctx["user"]

        prompt = str(body.get("prompt", "")).strip()
        img_service = str(body.get("img_service", "banana_pro"))
        img_ratio = str(body.get("img_ratio", "1:1"))
        references = list(body.get("reference_images", []) or [])
        img_quality = str(body.get("img_quality", "basic"))
        img_nsfw_checker = bool(body.get("img_nsfw_checker", False))
        nsfw_enabled = bool(body.get("nsfw_enabled", False))

        if not prompt:
            return web.json_response(
                {"ok": False, "error": "Введите промпт для генерации фото"},
                status=400,
            )

        model_meta = next(
            (item for item in IMAGE_MODELS if item["id"] == img_service), None
        )
        if not model_meta:
            return web.json_response(
                {"ok": False, "error": f"Неизвестная модель: {img_service}"},
                status=400,
            )

        if model_meta["requires_reference"] and not references:
            return web.json_response(
                {"ok": False, "error": "Для этой модели нужен хотя бы один исходник"},
                status=400,
            )
        if len(references) > model_meta["max_references"]:
            return web.json_response(
                {
                    "ok": False,
                    "error": f"Слишком много референсов. Максимум: {model_meta['max_references']}",
                },
                status=400,
            )

        if img_service in ("banana_pro", "banana_2"):
            unit_cost = QUALITY_COSTS.get(
                img_quality, preset_manager.get_generation_cost(img_service)
            )
        else:
            unit_cost = preset_manager.get_generation_cost(img_service)
        is_admin = config.is_admin(telegram_id)
        if not is_admin and not await check_can_afford(telegram_id, unit_cost):
            return web.json_response(
                {
                    "ok": False,
                    "error": f"Недостаточно бананов. Нужно {unit_cost}🍌",
                    "credits": user.credits,
                },
                status=400,
            )

        if not is_admin:
            await deduct_credits(telegram_id, unit_cost)

        launch_result = await _start_image_generation_task(
            user=user,
            telegram_id=telegram_id,
            img_service=img_service,
            prompt=prompt,
            img_ratio=img_ratio,
            reference_images=references,
            unit_cost=unit_cost,
            img_quality=img_quality,
            img_nsfw_checker=img_nsfw_checker,
            nsfw_enabled=nsfw_enabled,
            callback_url=(config.kie_notification_url if config.WEBHOOK_HOST else None),
        )

        if launch_result["status"] == "failed":
            if not is_admin:
                await add_credits(telegram_id, unit_cost)
            return web.json_response(
                {
                    "ok": False,
                    "error": "Не удалось запустить генерацию. Бананы уже возвращены.",
                },
                status=500,
            )

        fresh_user = await get_or_create_user(telegram_id)
        return web.json_response(
            {
                "ok": True,
                "status": launch_result["status"],
                "task_id": launch_result["task_id"],
                "saved_url": launch_result.get("saved_url"),
                "credits": fresh_user.credits,
                "cost": unit_cost,
                "model_label": get_image_model_label(img_service),
            }
        )
    except Exception as e:
        logger.exception("Mini App image generation failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_generate_video(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        telegram_id, ctx = await _get_user_context(request.app, init_data)
        user = ctx["user"]

        prompt = str(body.get("prompt", "")).strip()
        model = str(body.get("v_model", "v3_pro"))
        generation_type = str(body.get("v_type", "text"))
        duration = int(body.get("v_duration", 5))
        aspect_ratio = str(body.get("v_ratio", "16:9"))
        image_url = str(body.get("v_image_url", "") or "") or None
        image_references = list(body.get("reference_images", []) or [])
        video_references = list(body.get("v_reference_videos", []) or [])
        audio_url = str(body.get("audio_url", "") or "") or None
        audio_references = list(body.get("audio_references", []) or [])
        if not audio_url and audio_references:
            audio_url = str(audio_references[0] or "") or None
        grok_mode = str(body.get("grok_mode", "normal") or "normal")
        veo_generation_type = str(
            body.get("veo_generation_type", "TEXT_2_VIDEO") or "TEXT_2_VIDEO"
        )
        veo_translation = bool(body.get("veo_translation", True))
        veo_resolution = str(body.get("veo_resolution", "720p") or "720p")
        veo_seed_raw = body.get("veo_seed")
        veo_seed = int(veo_seed_raw) if veo_seed_raw not in (None, "", False) else None
        veo_watermark = str(body.get("veo_watermark", "") or "") or None
        kling_negative_prompt = str(body.get("kling_negative_prompt", "") or "") or None
        kling_cfg_scale_raw = body.get("kling_cfg_scale", 0.5)
        kling_cfg_scale = (
            float(kling_cfg_scale_raw)
            if kling_cfg_scale_raw not in (None, "")
            else None
        )

        if not prompt:
            return web.json_response(
                {"ok": False, "error": "Введите промпт для генерации видео"},
                status=400,
            )

        model_meta = next((item for item in VIDEO_MODELS if item["id"] == model), None)
        if not model_meta:
            return web.json_response(
                {"ok": False, "error": f"Неизвестная видео модель: {model}"},
                status=400,
            )
        if generation_type not in model_meta["supports"]:
            return web.json_response(
                {
                    "ok": False,
                    "error": f"{model_meta['label']} не поддерживает режим {generation_type}",
                },
                status=400,
            )
        if duration not in model_meta["durations"]:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Недопустимая длительность для выбранной модели",
                },
                status=400,
            )
        if generation_type == "imgtxt" and not image_url:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для режима Фото + Текст загрузите стартовое фото",
                },
                status=400,
            )
        if generation_type == "video" and not video_references:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для режима Видео + Текст нужен хотя бы один видео-референс",
                },
                status=400,
            )
        if generation_type == "motion" and (not image_url or not video_references):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для Motion Control загрузите фото персонажа и видео движения",
                },
                status=400,
            )
        if generation_type == "avatar" and (not image_url or not audio_url):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для Kling Avatar загрузите фото персонажа и аудиофайл",
                },
                status=400,
            )
        if generation_type == "motion" and (not image_url or not video_references):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для Motion Control загрузите фото персонажа и видео движения",
                },
                status=400,
            )
        if generation_type == "avatar" and (not image_url or not audio_url):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для Kling Avatar загрузите фото персонажа и аудиофайл",
                },
                status=400,
            )

        cost = preset_manager.get_video_cost(model, duration)
        is_admin = config.is_admin(telegram_id)
        if not is_admin and not await check_can_afford(telegram_id, cost):
            return web.json_response(
                {
                    "ok": False,
                    "error": f"Недостаточно бананов. Нужно {cost}🍌",
                    "credits": user.credits,
                },
                status=400,
            )
        if not is_admin:
            await deduct_credits(telegram_id, cost)

        launch_result = await _launch_video_generation_task(
            telegram_id=telegram_id,
            user=user,
            model=model,
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            generation_type=generation_type,
            image_url=image_url,
            image_references=image_references,
            video_references=video_references,
            audio_url=audio_url,
            grok_mode=grok_mode,
            veo_generation_type=veo_generation_type,
            veo_translation=veo_translation,
            veo_resolution=veo_resolution,
            veo_seed=veo_seed,
            veo_watermark=veo_watermark,
            kling_negative_prompt=kling_negative_prompt,
            kling_cfg_scale=kling_cfg_scale,
        )

        if launch_result["status"] == "failed":
            if not is_admin:
                await add_credits(telegram_id, cost)
            return web.json_response(
                {
                    "ok": False,
                    "error": launch_result.get("error") or "Не удалось запустить видео",
                },
                status=500,
            )

        fresh_user = await get_or_create_user(telegram_id)
        return web.json_response(
            {
                "ok": True,
                "status": launch_result["status"],
                "task_id": launch_result["task_id"],
                "saved_url": launch_result.get("saved_url"),
                "credits": fresh_user.credits,
                "cost": cost,
                "model_label": get_video_model_label(model),
            }
        )
    except Exception as e:
        logger.exception("Mini App video generation failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_generate_motion(request: web.Request) -> web.Response:
    """Mini App endpoint for Motion Control."""
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        telegram_id, ctx = await _get_user_context(request.app, init_data)
        user = ctx["user"]

        prompt = str(body.get("prompt", "") or "").strip()
        model = str(
            body.get("motion_model", "motion_control_v26") or "motion_control_v26"
        )
        image_url = str(body.get("motion_image_url", "") or "").strip()
        video_url = str(body.get("motion_video_url", "") or "").strip()
        mode = str(body.get("motion_mode", "720p") or "720p")
        motion_direction = str(body.get("motion_direction", "video") or "video")

        if not image_url:
            return web.json_response(
                {"ok": False, "error": "Загрузите фото персонажа"},
                status=400,
            )
        if not video_url:
            return web.json_response(
                {"ok": False, "error": "Загрузите видео движения"},
                status=400,
            )
        if mode not in {"720p", "1080p"}:
            return web.json_response(
                {"ok": False, "error": "Недопустимое качество Motion Control"},
                status=400,
            )
        if motion_direction not in {"video", "image"}:
            motion_direction = "video"
        if model not in {"motion_control_v26", "motion_control_v30"}:
            model = "motion_control_v26"

        from bot.services.kling_service import kling_service

        duration = 5
        cost = preset_manager.get_video_cost(model, duration)

        is_admin = config.is_admin(telegram_id)
        if not is_admin and not await check_can_afford(telegram_id, cost):
            return web.json_response(
                {
                    "ok": False,
                    "error": f"Недостаточно бананов. Нужно {cost}🍌",
                    "credits": user.credits,
                },
                status=400,
            )

        if not is_admin:
            await deduct_credits(telegram_id, cost)

        callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None
        api_motion_model = (
            "kling-3.0/motion-control"
            if model == "motion_control_v30"
            else "kling-2.6/motion-control"
        )
        model_label = (
            "Kling 3.0 Motion Control"
            if model == "motion_control_v30"
            else "Kling 2.6 Motion Control"
        )
        result = await kling_service.generate_motion_control(
            image_url=image_url,
            video_urls=[video_url],
            prompt=prompt,
            mode=mode,
            motion_direction=motion_direction,
            motion_model=api_motion_model,
            webhook_url=callback_url,
        )

        result_status, error_message = _classify_video_generation_result(result)

        if result_status == "queued":
            task_id = result["task_id"]
            await add_generation_task(
                user.id,
                telegram_id,
                task_id,
                "video",
                "miniapp_motion_control",
                model=model,
                duration=duration,
                aspect_ratio="1:1",
                prompt=prompt,
                cost=cost,
                request_data={
                    "source": "miniapp",
                    "v_type": "motion_control",
                    "motion_image_url": image_url,
                    "motion_video_url": video_url,
                    "motion_mode": mode,
                    "motion_direction": motion_direction,
                },
            )
            fresh_user = await get_or_create_user(telegram_id)
            return web.json_response(
                {
                    "ok": True,
                    "status": "queued",
                    "task_id": task_id,
                    "credits": fresh_user.credits,
                    "cost": cost,
                    "model_label": model_label,
                }
            )

        local_task_id = f"miniapp_motion_{int(time.time() * 1000)}_{telegram_id}"
        await add_generation_task(
            user.id,
            telegram_id,
            local_task_id,
            "video",
            "miniapp_motion_control",
            model=model,
            duration=duration,
            aspect_ratio="1:1",
            prompt=prompt,
            cost=cost,
            request_data={
                "source": "miniapp",
                "v_type": "motion_control",
                "motion_image_url": image_url,
                "motion_video_url": video_url,
                "motion_mode": mode,
                "motion_direction": motion_direction,
            },
        )

        if result_status == "done":
            saved_url = save_uploaded_file(bytes(result), "mp4")
            await complete_video_task(local_task_id, saved_url)
            fresh_user = await get_or_create_user(telegram_id)
            return web.json_response(
                {
                    "ok": True,
                    "status": "done",
                    "task_id": local_task_id,
                    "saved_url": saved_url,
                    "credits": fresh_user.credits,
                    "cost": cost,
                    "model_label": model_label,
                }
            )

        await complete_video_task(local_task_id, None)
        if not is_admin:
            await add_credits(telegram_id, cost)

        return web.json_response(
            {
                "ok": False,
                "error": error_message or "Не удалось запустить Motion Control",
            },
            status=500,
        )

    except Exception as e:
        logger.exception("Mini App Motion Control generation failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_partner_overview(request: web.Request) -> web.Response:
    """Return real partner program data for Mini App."""
    try:
        body = await request.json()
        init_data = body.get("init_data", "")

        telegram_id, _ctx = await _get_user_context(request.app, init_data)
        stats = await get_partner_overview(telegram_id)
        user = await get_or_create_user(telegram_id)
        me = await request.app["bot"].get_me()

        referral_link = (
            f"https://t.me/{me.username}?start=ref_{user.referral_code}"
            if user.referral_code
            else ""
        )

        return web.json_response(
            {
                "ok": True,
                "is_partner": bool(stats.get("is_partner")),
                "referrals_count": int(stats.get("referrals_count", 0) or 0),
                "balance_rub": float(stats.get("balance_rub", 0) or 0),
                "referral_link": referral_link,
                "status": "partner" if stats.get("is_partner") else "basic",
            }
        )
    except Exception as e:
        logger.exception("Mini App partner overview failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_task_detail(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        task_id = str(body.get("task_id", "")).strip()
        if not task_id:
            return web.json_response(
                {"ok": False, "error": "task_id is required"}, status=400
            )

        telegram_id, _ctx = await _get_user_context(request.app, init_data)
        detail = await _fetch_task_detail(telegram_id, task_id)
        if not detail:
            return web.json_response(
                {"ok": False, "error": "Задача не найдена"}, status=404
            )

        return web.json_response({"ok": True, "task": detail})
    except Exception as e:
        logger.exception("Mini App task detail failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_ai_assistant(request: web.Request) -> web.Response:
    """AI-ассистент через настоящий LLM backend (Kie.ai GPT 5.2)."""
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        user_message = str(body.get("message", "")).strip()
        history = list(body.get("history", []) or [])

        if not user_message:
            return web.json_response(
                {"ok": False, "error": "Сообщение не может быть пустым"}, status=400
            )

        telegram_id, ctx = await _get_user_context(request.app, init_data)
        user = ctx["user"]

        context = {
            "user_credits": user.credits,
            "menu_location": "mini_app_assistant",
        }

        response_text = await ai_assistant_service.get_assistant_response(
            user_message=user_message,
            context=context,
        )

        if response_text is None:
            return web.json_response(
                {
                    "ok": False,
                    "error": "AI-ассистент временно недоступен. Попробуйте позже.",
                },
                status=503,
            )

        return web.json_response({"ok": True, "reply": response_text})
    except Exception as e:
        logger.exception("Mini App AI assistant failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


def setup_miniapp_routes(app: web.Application):
    miniapp_path = config.MINI_APP_PATH or "/mini-app"
    if not miniapp_path.startswith("/"):
        miniapp_path = f"/{miniapp_path}"
    miniapp_root = miniapp_path.rstrip("/")

    async def _redirect_to_slash(request: web.Request) -> web.Response:
        raise web.HTTPFound(f"{miniapp_root}/")

    # miniapp_static_mount_v1
    from pathlib import Path as _MiniAppPath

    miniapp_out_dir = (
        _MiniAppPath(__file__).resolve().parent.parent
        / "frontend"
        / "miniapp-v0"
        / "out"
    )
    miniapp_next_static_dir = miniapp_out_dir / "_next" / "static"
    if miniapp_next_static_dir.exists():
        app.router.add_static(
            "/mini-app/_next/static/",
            path=str(miniapp_next_static_dir),
            name="miniapp_next_static",
        )

    # Do not mount the full `out/` directory as a static resource here.
    # Serving of `index.html` and other files is handled explicitly by
    # `miniapp_index` and `miniapp_asset` so we avoid conflicts where the
    # static resource would match `/mini-app/` and return 403 for directory
    # requests when `show_index` is disabled. Keep only `_next/static`
    # mounted above for Next.js runtime assets.
    app.router.add_get(miniapp_root, _redirect_to_slash)
    app.router.add_get(f"{miniapp_root}/", miniapp_index)
    app.router.add_post(miniapp_root + "/api/bootstrap", miniapp_bootstrap)
    app.router.add_post(miniapp_root + "/api/action", miniapp_action)
    app.router.add_post(miniapp_root + "/api/upload", miniapp_upload)
    app.router.add_post(miniapp_root + "/api/photo-to-prompt", miniapp_photo_to_prompt)
    app.router.add_post(miniapp_root + "/api/generate-image", miniapp_generate_image)
    app.router.add_post(miniapp_root + "/api/generate-video", miniapp_generate_video)
    app.router.add_post(miniapp_root + "/api/generate-motion", miniapp_generate_motion)
    app.router.add_post(
        miniapp_root + "/api/partner-overview", miniapp_partner_overview
    )
    app.router.add_post(miniapp_root + "/api/create-payment", miniapp_create_payment)
    app.router.add_post(miniapp_root + "/api/task-detail", miniapp_task_detail)
    app.router.add_post(miniapp_root + "/api/ai-assistant", miniapp_ai_assistant)
    app.router.add_get(miniapp_root + "/{tail:.*}", miniapp_asset)
