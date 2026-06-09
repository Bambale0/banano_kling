import hashlib
import hmac
import json
import logging
import mimetypes
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl, urlparse

import aiosqlite
from aiohttp import web

from bot.config import config
from bot.database import (
    DATABASE_PATH,
    MAX_ACTIVE_PROMPTS_PER_USER,
    SavedReference,
    add_credits,
    add_feed_comment,
    add_generation_task,
    approve_prompt,
    check_can_afford,
    complete_video_task,
    create_transaction,
    count_active_prompts_by_author,
    credit_feed_prompt_repeat,
    create_prompt,
    deduct_credits,
    deactivate_prompt,
    get_approved_prompts,
    get_and_clear_miniapp_notifications,
    get_author_prompts,
    get_feed_comments,
    get_feed_generation_card,
    get_feed_generations,
    get_generation_task_payload,
    get_or_create_user,
    get_partner_overview,
    get_promo_bonus_for_credits,
    get_promo_code_by_code,
    get_popular_prompts,
    get_prompt_by_id,
    get_prompts_by_tag,
    get_top_prompts,
    get_user_by_referral_code,
    get_user_feed_generations,
    get_user_stats,
    increment_feed_share,
    is_channel_subscription_required,
    like_feed_generation,
    like_prompt,
    list_saved_references,
    process_referral,
    reject_prompt,
    remove_from_feed,
    remove_from_library,
    save_user_channel_url,
    share_to_feed,
    share_to_library,
    touch_saved_references,
    update_user_profile,
    use_prompt,
)
from bot.handlers.batch_generation import get_batch_upload_keyboard
from bot.handlers.common import (
    AI_ASSISTANT_AUDIO_FORMATS,
    AIAssistantStates,
    _build_balance_text,
    _build_main_menu_text,
    _notify_partner_about_new_referral,
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
from bot.services.media_input_utils import (
    missing_local_upload_sources,
    resolve_local_upload_path,
)
from bot.services.reference_storage_service import save_reference_file
from bot.services.subscription_service import (
    REQUIRED_CHANNEL_USERNAME,
    check_required_channel_subscription,
)
from bot.services.preset_manager import preset_manager
from bot.utils.user_facing_errors import make_user_friendly_generation_error
from bot.services.yookassa_service import yookassa_service
from bot.utils.validators import detect_explicit_prompt_policy_violation
from bot.video_reference_policy import (
    get_max_video_image_references,
    get_max_video_references,
    normalize_reference_urls,
    video_model_supports_reference_videos,
)

logger = logging.getLogger(__name__)


def _saved_reference_payload(reference: SavedReference) -> dict[str, Any]:
    return {
        "id": str(reference.id),
        "kind": reference.kind,
        "url": reference.file_url,
        "filename": reference.original_filename or Path(reference.file_url).name,
        "content_type": reference.content_type,
        "source": reference.source,
        "created_at": reference.created_at.isoformat() if reference.created_at else None,
        "last_used_at": reference.last_used_at.isoformat() if reference.last_used_at else None,
    }

IMAGE_MODELS = (
    {
        "id": "banana_pro",
        "label": "Nano Banana Pro",
        "description": "Универсальная модель для качественных изображений",
        "cost": preset_manager.get_generation_cost("nano-banana-pro"),
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
        "requires_reference": False,
        "max_references": 8,
    },
    {
        "id": "banana_2",
        "label": "Nano Banana 2",
        "description": "Новая версия Nano Banana с улучшенной детализацией и цветопередачей",
        "cost": preset_manager.get_generation_cost("banana_2"),
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
        "requires_reference": False,
        "max_references": 8,
    },
    {
        "id": "seedream_edit",
        "label": "Seedream 4.5 Edit",
        "description": "Сильный edit по исходникам",
        "cost": preset_manager.get_generation_cost("seedream_edit"),
        "ratios": ["1:1", "9:16", "16:9", "3:4", "4:3", "2:3", "3:2", "21:9"],
        "requires_reference": True,
        "max_references": 9,
        "qualities": ["2K", "4K"],
        "supports_nsfw_checker": False,
    },
    {
        "id": "flux_pro",
        "label": "GPT Image 2",
        "description": "Детальная генерация и мягкий image-to-image",
        "cost": preset_manager.get_generation_cost("flux_pro"),
        "ratios": ["auto", "1:1", "9:16", "16:9", "3:4", "4:3", "2:3"],
        "requires_reference": False,
        "max_references": 9,
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
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
        "requires_reference": True,
        "max_references": 9,
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
        "supports": ["text", "imgtxt"],
        "max_image_references": 9,
    },
    {
        "id": "v3_std",
        "label": "Kling v3",
        "description": "Быстрее и дешевле для everyday-видео",
        "durations": [5, 10, 15],
        "ratios": ["16:9", "9:16", "1:1"],
        "supports": ["text", "imgtxt"],
        "max_image_references": 9,
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
        "max_image_references": 9,
    },
    {
        "id": "grok_imagine",
        "label": "Grok Imagine",
        "description": "Видео из фото с режимами Normal/Fun/Spicy",
        "durations": [6, 10, 20, 30],
        "ratios": ["16:9", "9:16", "1:1", "3:2", "2:3"],
        "supports": ["imgtxt"],
        "grok_modes": ["normal", "fun", "spicy"],
        "max_image_references": 6,
    },
    {
        "id": "grok_imagine_v15",
        "label": "Grok Imagine 1.5 NEW🔥🔥🔥",
        "description": "Видео 1-15 секунд из одного стартового фото",
        "durations": list(range(1, 16)),
        "ratios": ["auto", "16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"],
        "supports": ["imgtxt"],
        "grok_resolutions": ["480p", "720p"],
        "max_image_references": 0,
    },
    {
        "id": "seedance_2",
        "label": "Bytedance Seedance 2.0",
        "description": "Мультимодальная видео-модель с текстом, фото и видео-рефами",
        "durations": [5, 10, 15],
        "ratios": ["16:9", "9:16", "1:1"],
        "supports": ["text", "imgtxt", "video"],
        "max_image_references": 9,
        "max_video_references": 3,
    },
    {
        "id": "gemini_omni",
        "label": "Gemini Omni",
        "description": "Единое меню для Gemini Omni Video, Audio ID и Character ID",
        "durations": [4, 6, 8, 10],
        "ratios": ["16:9", "9:16"],
        "supports": ["text", "imgtxt", "video", "audio", "character"],
        "omni_modes": ["video", "audio", "character"],
        "omni_resolutions": ["720p", "1080p", "4k"],
        "supports_omni_seed": True,
        "supports_omni_audio_ids": True,
        "supports_omni_character_ids": True,
        "supports_omni_character_audio_ids": True,
        "omni_base_voices": [
            "achernar",
            "achird",
            "algenib",
            "algieba",
            "alnilam",
            "aoede",
            "autonoe",
            "callirrhoe",
            "charon",
            "despina",
            "enceladus",
            "erinome",
            "fenrir",
            "gacrux",
            "iapetus",
            "kore",
            "laomedeia",
            "leda",
            "orus",
            "puck",
            "pulcherrima",
            "rasalgethi",
            "sadachbia",
            "sadaltager",
            "schedar",
            "sulafat",
            "umbriel",
            "vindemiatrix",
            "zephyr",
            "zubenelgenubi",
        ],
        "max_image_references": 7,
        "max_video_references": 1,
        "max_audio_references": 1,
    },
    {
        "id": "veo3_fast",
        "label": "Veo 3.1 Fast",
        "description": "Быстрый кинематографичный рендер",
        "durations": [2, 4, 6, 8, 10],
        "ratios": ["16:9", "9:16", "Auto"],
        "supports": ["text", "imgtxt"],
        "veo_generation_types": [
            "TEXT_2_VIDEO",
            "FIRST_AND_LAST_FRAMES_2_VIDEO",
            "REFERENCE_2_VIDEO",
        ],
        "veo_resolutions": ["720p", "1080p", "4k"],
        "supports_translation": True,
        "supports_seed": True,
        "supports_watermark": True,
        "max_image_references": 9,
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
        "max_image_references": 9,
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
        "max_image_references": 9,
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
        "max_image_references": 9,
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
        "max_image_references": 9,
        "max_audio_references": 1,
    },
)

GEMINI_OMNI_INTERNAL_MODELS = {
    "gemini_omni_video",
    "gemini_omni_audio",
    "gemini_omni_character",
}


def _find_video_model_meta(model: str) -> dict[str, Any] | None:
    meta = next((item for item in VIDEO_MODELS if item["id"] == model), None)
    if meta:
        return meta
    if model in GEMINI_OMNI_INTERNAL_MODELS:
        return next((item for item in VIDEO_MODELS if item["id"] == "gemini_omni"), None)
    return None


def _resolve_gemini_omni_model(model: str, generation_type: str) -> str:
    if model != "gemini_omni":
        return model
    if generation_type == "audio":
        return "gemini_omni_audio"
    if generation_type == "character":
        return "gemini_omni_character"
    return "gemini_omni_video"


def _video_pricing_quality(
    model: str,
    veo_resolution: str | None = None,
    omni_resolution: str | None = None,
) -> str | None:
    key = preset_manager.normalize_video_model_key(model)
    if key.startswith("veo3"):
        return veo_resolution or "720p"
    if key == "gemini_omni_video":
        return omni_resolution or "720p"
    return None


def _clean_unique_values(values: list[Any] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _collect_gemini_omni_images(
    image_url: str | None,
    image_references: list[str] | None,
) -> list[str]:
    return _clean_unique_values([image_url, *list(image_references or [])])


def _collect_gemini_omni_video_urls(video_references: list[str] | None) -> list[str]:
    return _clean_unique_values(video_references)


def _build_gemini_omni_video_list(
    video_references: list[str],
    duration: int,
) -> list[dict[str, Any]]:
    try:
        ends = min(20, max(1, int(duration)))
    except (TypeError, ValueError):
        ends = 10
    return [{"url": url, "start": 0, "ends": ends} for url in video_references]


def _validate_gemini_omni_video_inputs(
    *,
    image_urls: list[str],
    video_urls: list[str],
    audio_ids: list[str],
    character_ids: list[str],
) -> str | None:
    if len(video_urls) > 1:
        return "Gemini Omni принимает только один видео-референс. Удалите текущий или замените его."
    if len(audio_ids) > 1:
        return "Gemini Omni Video принимает один Audio ID за запуск."
    if len(character_ids) > 3:
        return "Gemini Omni принимает максимум 3 Character ID."
    units = len(image_urls) + len(video_urls) * 2 + len(character_ids)
    if units > 7:
        return "Слишком много входов для Gemini Omni. Лимит: фото + видео*2 + Character ID <= 7."
    return None


FILE_KIND_MAP = {
    "image_reference": {"prefix": "image/", "fallback_ext": "png", "group": "image"},
    "video_reference": {"prefix": "video/", "fallback_ext": "mp4", "group": "video"},
    "audio_reference": {"prefix": "audio/", "fallback_ext": "mp3", "group": "audio"},
    "assistant_audio": {"prefix": "audio/", "fallback_ext": "webm", "group": "audio"},
}

MINIAPP_ASSISTANT_AUDIO_EXT_FORMATS = {
    "mp3": "mp3",
    "wav": "wav",
    "aac": "aac",
    "aiff": "aiff",
    "aif": "aiff",
    "ogg": "ogg",
    "oga": "ogg",
    "flac": "flac",
    "webm": "webm",
    "m4a": "m4a",
    "mp4": "m4a",
}


def _miniapp_assistant_audio_format(
    audio_url: str,
    content_type: str = "",
) -> tuple[str, str]:
    mime_type = (content_type or "").split(";", 1)[0].strip().lower()
    if not mime_type:
        mime_type = (mimetypes.guess_type(audio_url)[0] or "").strip().lower()

    audio_format = AI_ASSISTANT_AUDIO_FORMATS.get(mime_type, "")
    if audio_format:
        return mime_type, audio_format

    ext = Path(urlparse(audio_url).path or audio_url).suffix.lstrip(".").lower()
    audio_format = MINIAPP_ASSISTANT_AUDIO_EXT_FORMATS.get(ext, "")
    return mime_type, audio_format


def _load_miniapp_assistant_audio(
    audio_url: str,
    content_type: str = "",
) -> tuple[bytes, str, str]:
    local_path = resolve_local_upload_path(audio_url)
    if not local_path:
        raise ValueError("Аудио не найдено. Запишите или загрузите его ещё раз.")

    path = Path(local_path)
    if path.stat().st_size > config.PHOTO_PROMPT_MAX_AUDIO_BYTES:
        max_mb = max(1, config.PHOTO_PROMPT_MAX_AUDIO_BYTES // (1024 * 1024))
        raise ValueError(f"Аудио слишком большое. Максимум {max_mb}MB.")

    audio_bytes = path.read_bytes()
    if len(audio_bytes) > config.PHOTO_PROMPT_MAX_AUDIO_BYTES:
        max_mb = max(1, config.PHOTO_PROMPT_MAX_AUDIO_BYTES // (1024 * 1024))
        raise ValueError(f"Аудио слишком большое. Максимум {max_mb}MB.")

    mime_type, audio_format = _miniapp_assistant_audio_format(
        audio_url,
        content_type=content_type,
    )
    if not audio_format:
        raise ValueError("Этот аудиоформат не поддерживается. Попробуйте ogg, mp3, wav или webm.")

    return audio_bytes, mime_type, audio_format


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


def _referral_code_from_start_param(start_param: Any) -> str:
    raw = str(start_param or "").strip()
    if not raw:
        return ""

    if raw.startswith("ref_"):
        return raw.replace("ref_", "", 1).strip().upper()

    if raw.startswith("feed_"):
        _, sep, referral_code = raw.replace("feed_", "", 1).partition("_ref_")
        return referral_code.strip().upper() if sep else ""

    if raw.startswith("posts_"):
        _, sep, referral_code = raw.replace("posts_", "", 1).partition("_ref_")
        return referral_code.strip().upper() if sep else ""

    return ""


async def _activate_start_param_referral(
    app: web.Application,
    *,
    telegram_id: int,
    telegram_user: dict[str, Any],
    start_param: Any,
) -> None:
    referral_code = _referral_code_from_start_param(start_param)
    if not referral_code:
        if start_param:
            logger.info(
                "Mini App referral skipped: unsupported start_param user_id=%s start_param=%s",
                telegram_id,
                start_param,
            )
        return

    try:
        logger.info(
            "Mini App referral requested: user_id=%s username=%s start_param=%s code=%s",
            telegram_id,
            telegram_user.get("username"),
            start_param,
            referral_code,
        )
        referrer = await get_user_by_referral_code(referral_code)
        processed = await process_referral(telegram_id, referral_code)
    except Exception:
        logger.exception(
            "Failed to activate Mini App referral for user_id=%s start_param=%s",
            telegram_id,
            start_param,
        )
        return

    if not processed:
        logger.info(
            "Mini App referral not applied: user_id=%s username=%s start_param=%s code=%s referrer_found=%s",
            telegram_id,
            telegram_user.get("username"),
            start_param,
            referral_code,
            bool(referrer),
        )
        return

    if processed and referrer:
        referred = SimpleNamespace(
            id=telegram_id,
            username=telegram_user.get("username"),
            first_name=telegram_user.get("first_name"),
            last_name=telegram_user.get("last_name"),
            full_name=" ".join(
                str(telegram_user.get(key) or "").strip()
                for key in ("first_name", "last_name")
                if str(telegram_user.get(key) or "").strip()
            ),
        )
        await _notify_partner_about_new_referral(
            app["bot"],
            referrer_telegram_id=referrer.telegram_id,
            referred=referred,
        )
        logger.info(
            "Mini App referral applied: user_id=%s username=%s code=%s referrer_telegram_id=%s",
            telegram_id,
            telegram_user.get("username"),
            referral_code,
            referrer.telegram_id,
        )


async def _get_user_context(app: web.Application, init_data: str) -> tuple[int, dict]:
    payload = _validate_init_data(init_data, config.BOT_TOKEN)
    telegram_user = payload["user"]
    telegram_id = int(telegram_user["id"])
    if await is_channel_subscription_required():
        result = await check_required_channel_subscription(app["bot"], telegram_id)
        if not result.ok:
            raise PermissionError(
                f"Подпишитесь на @{REQUIRED_CHANNEL_USERNAME}, чтобы пользоваться ботом."
            )

    user = await get_or_create_user(telegram_id)
    try:
        await update_user_profile(
            telegram_id,
            username=telegram_user.get("username"),
            first_name=telegram_user.get("first_name"),
            last_name=telegram_user.get("last_name"),
        )
    except Exception:
        logger.exception("Unable to sync Mini App profile for %s", telegram_id)

    await _activate_start_param_referral(
        app,
        telegram_id=telegram_id,
        telegram_user=telegram_user,
        start_param=payload.get("start_param"),
    )
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


def _task_has_source_feed(row_or_payload: Any) -> bool:
    try:
        return bool(row_or_payload["source_feed_gen_id"])
    except Exception:
        return bool(getattr(row_or_payload, "source_feed_gen_id", None))


def _task_prompt_hidden(row_or_payload: Any) -> bool:
    return False


def _task_prompt_actions_allowed(row_or_payload: Any) -> bool:
    return not _task_has_source_feed(row_or_payload)


def _public_result_urls(payload: dict[str, Any]) -> list[str]:
    urls = payload.get("result_urls") or []
    if isinstance(urls, str):
        try:
            urls = json.loads(urls)
        except (TypeError, json.JSONDecodeError):
            urls = []
    normalized = [str(item) for item in urls if str(item).strip()]
    result_url = payload.get("result_url")
    if result_url and result_url not in normalized:
        normalized.insert(0, result_url)
    return normalized


async def _miniapp_payload(request: web.Request) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if request.can_read_body:
        try:
            raw = await request.json()
            if isinstance(raw, dict):
                payload.update(raw)
        except Exception:
            pass
    payload.update(dict(request.query))
    for key, value in request.match_info.items():
        payload.setdefault(key, value)
    if "gen_id" not in payload and "generation_id" in payload:
        payload["gen_id"] = payload["generation_id"]
    if "prompt_id" in payload and str(payload["prompt_id"]).isdigit():
        payload["prompt_id"] = int(payload["prompt_id"])
    init_data = request.headers.get("X-Telegram-Init-Data")
    if init_data and not payload.get("init_data"):
        payload["init_data"] = init_data
    return payload


def _normalize_video_ratio(ratio: str) -> str:
    if ratio == "Auto":
        return "auto"
    return ratio or "16:9"


async def _fetch_recent_tasks(telegram_id: int, limit: int = 8) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, task_id, type, model, duration, aspect_ratio, prompt, cost, status,
                   result_url, result_urls, is_public_feed, is_prompt_library,
                   source_feed_gen_id, created_at
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
                "duration": row["duration"],
                "aspect_ratio": row["aspect_ratio"] or "",
                "status": row["status"] or "pending",
                "result_url": row["result_url"],
                "result_urls": _public_result_urls(dict(row)),
                "created_at": row["created_at"],
                "prompt_preview": "" if _task_prompt_hidden(row) else _task_preview(row["prompt"]),
                "prompt_hidden": _task_prompt_hidden(row),
                "prompt_actions_allowed": _task_prompt_actions_allowed(row),
                "is_public_feed": bool(row["is_public_feed"]),
                "is_prompt_library": bool(row["is_prompt_library"]),
                "feed_id": row["id"],
                "cost": row["cost"] or 0,
            }
        )
    return tasks


async def _fetch_task_detail(telegram_id: int, task_id: str) -> dict[str, Any] | None:
    lookup_value = str(task_id or "").strip()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, task_id, type, model, duration, aspect_ratio, prompt, cost, status,
                   result_url, result_urls, is_public_feed, is_prompt_library,
                   source_feed_gen_id, created_at, request_data
            FROM generation_tasks
            WHERE telegram_id = ? AND task_id = ?
            LIMIT 1
            """,
            (telegram_id, lookup_value),
        )
        row = await cursor.fetchone()
        if not row and lookup_value.isdigit():
            cursor = await db.execute(
                """
                SELECT id, task_id, type, model, duration, aspect_ratio, prompt, cost, status,
                       result_url, result_urls, is_public_feed, is_prompt_library,
                       source_feed_gen_id, created_at, request_data
                FROM generation_tasks
                WHERE telegram_id = ? AND id = ?
                LIMIT 1
                """,
                (telegram_id, int(lookup_value)),
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
        "feed_id": row["id"],
        "type": task_type,
        "model": model,
        "model_label": model_label,
        "duration": row["duration"],
        "aspect_ratio": row["aspect_ratio"] or "",
        "prompt": "" if _task_prompt_hidden(row) else (row["prompt"] or ""),
        "prompt_hidden": _task_prompt_hidden(row),
        "prompt_actions_allowed": _task_prompt_actions_allowed(row),
        "cost": row["cost"] or 0,
        "status": row["status"] or "pending",
        "result_url": row["result_url"],
        "result_urls": _public_result_urls(dict(row)),
        "is_public_feed": bool(row["is_public_feed"]),
        "is_prompt_library": bool(row["is_prompt_library"]),
        "created_at": row["created_at"],
        "request_data": request_data,
    }


def _classify_video_generation_result(result: Any) -> tuple[str, str | None]:
    if isinstance(result, dict):
        if result.get("status") == "done" and result.get("asset_id"):
            return "done", None
        if result.get("task_id"):
            return "queued", None
        return "failed", make_user_friendly_generation_error(
            result.get("message") or result.get("error") or str(result)
        )
    if isinstance(result, (bytes, bytearray)):
        return "done", None
    if result:
        return "failed", make_user_friendly_generation_error(
            f"Unexpected result type: {type(result).__name__}"
        )
    return "failed", None


def _derive_miniapp_asset_name(text: str, fallback: str) -> str:
    value = " ".join(str(text or "").strip().split())
    value = "".join(ch for ch in value if ch.isalnum() or ch in {" ", ".", "-", "_"})
    return (value[:20] or fallback)[:20]


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
    grok_resolution: str = "480p",
    veo_generation_type: str = "TEXT_2_VIDEO",
    veo_translation: bool = True,
    veo_resolution: str = "720p",
    veo_seed: int | None = None,
    veo_watermark: str | None = None,
    kling_negative_prompt: str | None = None,
    kling_cfg_scale: float | None = None,
    omni_resolution: str = "720p",
    omni_seed: int | None = None,
    omni_audio_ids: list[str] | None = None,
    omni_character_ids: list[str] | None = None,
    omni_base_voice: str = "achernar",
    omni_voice_name: str | None = None,
    omni_voice_description: str | None = None,
    omni_example_dialogue: str | None = None,
    omni_character_name: str | None = None,
    omni_character_audio_ids: list[str] | None = None,
    source_feed_gen_id: int | None = None,
    parent_generation_id: int | None = None,
    action_type: str | None = None,
) -> dict[str, Any]:
    from bot.services.gemini_omni_service import gemini_omni_service
    from bot.services.grok_service import grok_service
    from bot.services.kling_service import kling_service
    from bot.services.seedance_service import seedance_service
    from bot.services.veo_service import veo_service

    normalized_ratio = _normalize_video_ratio(aspect_ratio)
    callback_url = config.kling_notification_url if config.WEBHOOK_HOST else None
    if model == "gemini_omni_video":
        image_references = _clean_unique_values(image_references)
        video_references = _clean_unique_values(video_references)
    else:
        image_references = normalize_reference_urls(
            image_references,
            max_count=get_max_video_image_references(model),
        )
        video_references = normalize_reference_urls(
            video_references,
            max_count=get_max_video_references(model),
        )

    if model == "gemini_omni_video":
        omni_images = _collect_gemini_omni_images(image_url, image_references)
        omni_video_list = _build_gemini_omni_video_list(video_references, duration)
        result = await gemini_omni_service.generate_video(
            prompt=prompt,
            duration=duration,
            aspect_ratio=normalized_ratio,
            resolution=omni_resolution,
            image_urls=omni_images or None,
            audio_ids=omni_audio_ids or None,
            video_list=omni_video_list or None,
            character_ids=omni_character_ids or None,
            seed=omni_seed,
            callBackUrl=(config.kie_notification_url if config.WEBHOOK_HOST else None),
        )
    elif model == "gemini_omni_audio":
        audio_name = omni_voice_name or _derive_miniapp_asset_name(prompt, "Omni Voice")
        result = await gemini_omni_service.create_audio(
            audio_id=omni_base_voice,
            name=audio_name,
            voice_description=omni_voice_description or prompt,
            example_dialogue=omni_example_dialogue or "",
        )
    elif model == "gemini_omni_character":
        character_name = omni_character_name or _derive_miniapp_asset_name(
            prompt,
            "Character",
        )
        character_images = [image_url] if image_url else []
        result = await gemini_omni_service.create_character(
            description=prompt,
            image_urls=character_images,
            character_name=character_name,
            audio_ids=omni_character_audio_ids or None,
        )
    elif model in {"avatar_std", "avatar_pro"}:
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
            image_urls=([image_url] if image_url else []) + image_references[:6],
            prompt=prompt,
            mode=grok_mode,
            duration=duration,
            resolution="720p",
            aspect_ratio=normalized_ratio,
            callBackUrl=(config.kie_notification_url if config.WEBHOOK_HOST else None),
        )
    elif model == "grok_imagine_v15":
        result = await grok_service.generate_image_to_video_v15(
            image_urls=[image_url] if image_url else [],
            prompt=prompt,
            duration=duration,
            resolution=grok_resolution,
            aspect_ratio=normalized_ratio,
            callBackUrl=(config.kie_notification_url if config.WEBHOOK_HOST else None),
        )
    elif model == "seedance_2":
        seedance_reference_images: list[str] = []
        seedance_reference_videos = video_references
        if generation_type == "imgtxt" and image_url:
            if image_references or seedance_reference_videos:
                seedance_reference_images.append(image_url)
                for ref_url in image_references:
                    if ref_url and ref_url not in seedance_reference_images:
                        seedance_reference_images.append(ref_url)
            result = await seedance_service.generate_video(
                prompt=prompt,
                duration=duration,
                aspect_ratio=normalized_ratio,
                resolution="720p",
                generate_audio=True,
                first_frame_url=image_url
                if not (image_references or seedance_reference_videos)
                else None,
                reference_image_urls=seedance_reference_images
                if (image_references or seedance_reference_videos)
                else None,
                reference_video_urls=seedance_reference_videos or None,
                callBackUrl=(config.kie_notification_url if config.WEBHOOK_HOST else None),
            )
        else:
            if image_url:
                seedance_reference_images.append(image_url)
            for ref_url in image_references:
                if ref_url and ref_url not in seedance_reference_images:
                    seedance_reference_images.append(ref_url)
            result = await seedance_service.generate_video(
                prompt=prompt,
                duration=duration,
                aspect_ratio=normalized_ratio,
                resolution="720p",
                generate_audio=True,
                reference_image_urls=seedance_reference_images or None,
                reference_video_urls=seedance_reference_videos or None,
                callBackUrl=(config.kie_notification_url if config.WEBHOOK_HOST else None),
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
            image_input=(
                image_references
                if generation_type != "imgtxt" or len(image_references) < 2
                else None
            ),
            elements=(
                [
                    {
                        "description": "reference photos for video generation consistency and style",
                        "reference_image_urls": image_references[:12],
                    }
                ]
                if generation_type == "imgtxt" and len(image_references) >= 2
                else None
            ),
            negative_prompt=kling_negative_prompt,
            cfg_scale=kling_cfg_scale,
            webhook_url=callback_url,
        )

    result_status, error_message = _classify_video_generation_result(result)
    pricing_quality = _video_pricing_quality(model, veo_resolution, omni_resolution)
    cost = preset_manager.get_video_cost_with_quality(model, duration, pricing_quality)
    task_type = (
        "audio"
        if model == "gemini_omni_audio"
        else "character" if model == "gemini_omni_character" else "video"
    )

    if result_status == "queued":
        await add_generation_task(
            user.id,
            telegram_id,
            result["task_id"],
            task_type,
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
                "grok_resolution": (
                    grok_resolution if model == "grok_imagine_v15" else ""
                ),
                "resolution": (
                    grok_resolution
                    if model == "grok_imagine_v15"
                    else "720p" if model == "grok_imagine" else ""
                ),
                "veo_generation_type": veo_generation_type,
                "veo_translation": veo_translation,
                "veo_resolution": veo_resolution,
                "veo_seed": veo_seed,
                "veo_watermark": veo_watermark,
                "kling_negative_prompt": kling_negative_prompt,
                "kling_cfg_scale": kling_cfg_scale,
                "omni_resolution": omni_resolution,
                "omni_seed": omni_seed,
                "omni_audio_ids": omni_audio_ids or [],
                "omni_character_ids": omni_character_ids or [],
                "omni_base_voice": omni_base_voice,
                "omni_voice_name": omni_voice_name,
                "omni_voice_description": omni_voice_description,
                "omni_example_dialogue": omni_example_dialogue,
                "omni_character_name": omni_character_name,
                "omni_character_audio_ids": omni_character_audio_ids or [],
                "source_feed_gen_id": source_feed_gen_id,
                "parent_generation_id": parent_generation_id,
                "action_type": action_type,
            },
            source_feed_gen_id=source_feed_gen_id,
            parent_generation_id=parent_generation_id,
            action_type=action_type,
        )
        return {
            "status": "queued",
            "task_id": result["task_id"],
            "cost": cost,
            "task_type": task_type,
        }

    if (
        result_status == "done"
        and isinstance(result, dict)
        and result.get("asset_id")
    ):
        asset_id = str(result["asset_id"])
        await add_generation_task(
            user.id,
            telegram_id,
            asset_id,
            task_type,
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
                "asset_kind": result.get("asset_kind"),
                "asset_id": asset_id,
                "v_image_url": image_url,
                "reference_images": image_references,
                "audio_url": audio_url,
                "omni_base_voice": omni_base_voice,
                "omni_voice_name": omni_voice_name,
                "omni_voice_description": omni_voice_description,
                "omni_example_dialogue": omni_example_dialogue,
                "omni_character_name": omni_character_name,
                "omni_character_audio_ids": omni_character_audio_ids or [],
                "source_feed_gen_id": source_feed_gen_id,
                "parent_generation_id": parent_generation_id,
                "action_type": action_type,
            },
            source_feed_gen_id=source_feed_gen_id,
            parent_generation_id=parent_generation_id,
            action_type=action_type,
        )
        await complete_video_task(asset_id, asset_id)
        return {
            "status": "done",
            "task_id": asset_id,
            "saved_url": asset_id,
            "cost": cost,
            "task_type": task_type,
        }

    local_task_id = f"miniapp_video_{int(time.time() * 1000)}_{telegram_id}"
    await add_generation_task(
        user.id,
        telegram_id,
        local_task_id,
        task_type,
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
            "grok_resolution": (
                grok_resolution if model == "grok_imagine_v15" else ""
            ),
            "resolution": (
                grok_resolution
                if model == "grok_imagine_v15"
                else "720p" if model == "grok_imagine" else ""
            ),
            "veo_generation_type": veo_generation_type,
            "veo_translation": veo_translation,
            "veo_resolution": veo_resolution,
            "veo_seed": veo_seed,
            "veo_watermark": veo_watermark,
            "kling_negative_prompt": kling_negative_prompt,
            "kling_cfg_scale": kling_cfg_scale,
            "omni_resolution": omni_resolution,
            "omni_seed": omni_seed,
            "omni_audio_ids": omni_audio_ids or [],
            "omni_character_ids": omni_character_ids or [],
            "source_feed_gen_id": source_feed_gen_id,
            "parent_generation_id": parent_generation_id,
            "action_type": action_type,
        },
        source_feed_gen_id=source_feed_gen_id,
        parent_generation_id=parent_generation_id,
        action_type=action_type,
    )

    if result_status == "done":
        saved_url = save_uploaded_file(bytes(result), "mp4")
        await complete_video_task(local_task_id, saved_url)
        return {
            "status": "done",
            "task_id": local_task_id,
            "saved_url": saved_url,
            "cost": cost,
            "task_type": task_type,
        }

    await complete_video_task(local_task_id, None)
    return {
        "status": "failed",
        "task_id": local_task_id,
        "error": error_message or "Не удалось создать видео задачу",
        "cost": cost,
        "task_type": task_type,
    }


async def _send_main_menu(app: web.Application, telegram_id: int):
    user = await get_or_create_user(telegram_id)
    text = _build_main_menu_text(user.credits)
    await app["bot"].send_message(
        telegram_id,
        text,
        reply_markup=get_main_menu_keyboard(user.credits, telegram_id),
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
        img_quality="2K",
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
        reply_markup=get_main_menu_keyboard(user.credits, telegram_id),
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
        f"• Повторы prompt: <code>{stats.get('prompt_repeat_balance_rub', 0)}</code> ₽\n"
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
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        telegram_id, ctx = await _get_user_context(request.app, init_data)
        user = ctx["user"]
        telegram_user = ctx["payload"]["user"]
        me = await request.app["bot"].get_me()
        profile_link = (
            f"https://t.me/{me.username}?start=posts_{user.referral_code}_ref_{user.referral_code}"
            if me.username and user.referral_code
            else config.mini_app_url
        )
        referral_link = (
            f"https://t.me/{me.username}?start=ref_{user.referral_code}"
            if me.username and user.referral_code
            else config.mini_app_url
        )
        recent_tasks = await _fetch_recent_tasks(telegram_id)
        partner_stats = await get_partner_overview(telegram_id)
        data = {
            "ok": True,
            "telegram_id": telegram_id,
            "credits": user.credits,
            "first_name": telegram_user.get("first_name", ""),
            "last_name": telegram_user.get("last_name", ""),
            "telegram_username": telegram_user.get("username", ""),
            "photo_url": telegram_user.get("photo_url", ""),
            "referral_code": user.referral_code or "",
            "profile_link": profile_link,
            "referral_link": referral_link,
            "channel_url": user.channel_url or "",
            "prompt_repeat_balance_rub": float(
                partner_stats.get("prompt_repeat_balance_rub", 0) or 0
            ),
            "prompt_repeat_total_rub": float(
                partner_stats.get("prompt_repeat_total_rub", 0) or 0
            ),
            "bot_username": me.username,
            "username": me.username,
            "mini_app_url": config.mini_app_url,
            "is_admin": config.is_admin(telegram_id),
            "actions": sorted(ACTIONS.keys()),
            "payment_packages": preset_manager.get_packages(),
            "image_models": [
                {**item, "cost": preset_manager.get_generation_cost(item["id"])}
                for item in IMAGE_MODELS
            ],
            "video_models": [
                {
                    **item,
                    "costs": {
                        str(duration): preset_manager.get_video_cost(
                            item["id"], duration
                        )
                        for duration in item["durations"]
                    },
                    "quality_costs": preset_manager.get_video_quality_costs(
                        item["id"]
                    ),
                    **(
                        {
                            "omni_audio_cost": preset_manager.get_video_cost(
                                "gemini_omni_audio", 6
                            ),
                            "omni_character_cost": preset_manager.get_video_cost(
                                "gemini_omni_character", 6
                            ),
                        }
                        if item["id"] == "gemini_omni"
                        else {}
                    ),
                }
                for item in VIDEO_MODELS
            ],
            "recent_tasks": recent_tasks,
            "saved_references": [
                _saved_reference_payload(item)
                for item in await list_saved_references(telegram_id, limit=24)
            ],
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
        public_url = None
        saved_reference = None
        if file_kind.endswith("_reference"):
            public_url, saved_reference = await save_reference_file(
                telegram_id,
                bytes(raw),
                file_ext=extension,
                kind=config_entry["group"],
                original_filename=getattr(upload, "filename", "") or None,
                content_type=content_type or None,
                source="miniapp",
            )
        if not public_url:
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
                "reference": (
                    _saved_reference_payload(saved_reference) if saved_reference else None
                ),
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
        promo_code = body.get("promo_code")

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
        promo = (
            await get_promo_code_by_code(promo_code, active_only=True)
            if promo_code
            else None
        )
        promo_bonus = (
            get_promo_bonus_for_credits(package["credits"]) if promo else 0
        )
        total_credits = (
            package["credits"] + package.get("bonus_credits", 0) + promo_bonus
        )
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
            promo_code_id=promo.id if promo and promo_bonus > 0 else None,
            promo_code=promo.code if promo and promo_bonus > 0 else None,
            promo_bonus_credits=promo_bonus,
        )

        return web.json_response(
            {
                "ok": True,
                "order_id": order_id,
                "payment_id": payment_id,
                "payment_url": payment_url,
                "credits": total_credits,
                "promo_bonus_credits": promo_bonus,
                "promo_code": promo.code if promo and promo_bonus > 0 else "",
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
                "gemini_omni_prompt": result.get("gemini_omni_prompt", ""),
                "voice_transcript": result.get("voice_transcript", ""),
                "voice_prompt_summary_ru": result.get("voice_prompt_summary_ru", ""),
                "voice_description_ru": result.get("voice_description_ru", ""),
                "key_details": result.get("key_details", []),
            }
        )
    except Exception as e:
        logger.exception("Mini App photo-to-prompt failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_prompts(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        source = (
            "my"
            if request.path.endswith("/prompts/my")
            else str(body.get("source", "catalog") or "catalog")
        )
        tag = str(body.get("tag", "") or "").strip()
        category = str(body.get("category", "") or "").strip() or None
        page = max(int(body.get("page", 1) or 1), 1)
        limit = min(max(int(body.get("limit", 300) or 300), 1), 300)

        _telegram_id, ctx = await _get_user_context(request.app, init_data)
        user = ctx["user"]

        if source == "my":
            prompts = await get_author_prompts(user.id)
        elif source == "top":
            prompts = await get_top_prompts(limit)
        elif source in {"popular", "trending", "best"}:
            prompts = await get_popular_prompts(limit)
        elif source == "tag" and tag:
            prompts = await get_prompts_by_tag(tag, limit)
        else:
            prompts = await get_approved_prompts(
                category=category,
                offset=(page - 1) * limit,
                limit=limit,
            )

        return web.json_response({"ok": True, "prompts": prompts})
    except Exception as e:
        logger.exception("Mini App prompts list failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_prompt_detail(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        prompt_id = int(body.get("prompt_id") or 0)
        _telegram_id, ctx = await _get_user_context(request.app, init_data)
        user = ctx["user"]

        prompt = await get_prompt_by_id(prompt_id)
        if not prompt:
            return web.json_response({"ok": False, "error": "Промпт не найден"}, status=404)
        if not (prompt["status"] == "approved" and prompt["is_public"]) and prompt["author_id"] != user.id:
            return web.json_response({"ok": False, "error": "Промпт недоступен"}, status=403)
        return web.json_response({"ok": True, "prompt": prompt})
    except Exception as e:
        logger.exception("Mini App prompt detail failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_prompt_like(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        prompt_id = int(body.get("prompt_id") or 0)
        _telegram_id, ctx = await _get_user_context(request.app, init_data)
        prompt = await like_prompt(prompt_id, ctx["user"].id)
        if not prompt:
            return web.json_response(
                {"ok": False, "error": "Можно лайкать только опубликованные промпты"},
                status=404,
            )
        return web.json_response({"ok": True, "prompt": prompt})
    except Exception as e:
        logger.exception("Mini App prompt like failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_prompt_use(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        prompt_id = int(body.get("prompt_id") or 0)
        _telegram_id, ctx = await _get_user_context(request.app, init_data)
        prompt = await use_prompt(prompt_id, ctx["user"].id)
        if not prompt:
            return web.json_response(
                {"ok": False, "error": "Промпт не найден или ещё не опубликован"},
                status=404,
            )
        return web.json_response({"ok": True, "prompt": prompt})
    except Exception as e:
        logger.exception("Mini App prompt use failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_prompt_link(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        prompt_id = int(body.get("prompt_id") or 0)
        _telegram_id, ctx = await _get_user_context(request.app, init_data)
        user = ctx["user"]
        prompt = await get_prompt_by_id(prompt_id)
        if not prompt:
            return web.json_response({"ok": False, "error": "Промпт не найден"}, status=404)
        if not (prompt["status"] == "approved" and prompt["is_public"]) and prompt["author_id"] != user.id:
            return web.json_response({"ok": False, "error": "Промпт недоступен"}, status=403)
        me = await request.app["bot"].get_me()
        link = f"https://t.me/{me.username}?start=prompt_{prompt_id}" if me.username else config.mini_app_url
        return web.json_response({"ok": True, "prompt": prompt, "link": link})
    except Exception as e:
        logger.exception("Mini App prompt link failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_prompt_submit(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        telegram_id, ctx = await _get_user_context(request.app, init_data)
        user = ctx["user"]
        prompt_text = str(body.get("prompt_text", "") or body.get("prompt", "") or "").strip()
        if not prompt_text:
            return web.json_response({"ok": False, "error": "Введите текст промпта"}, status=400)

        policy_error = detect_explicit_prompt_policy_violation(prompt_text)
        if policy_error:
            return web.json_response({"ok": False, "error": policy_error}, status=400)

        active_count = await count_active_prompts_by_author(user.id)
        if active_count >= MAX_ACTIVE_PROMPTS_PER_USER and not config.is_admin(telegram_id):
            return web.json_response(
                {"ok": False, "error": f"Лимит активных промптов: {MAX_ACTIVE_PROMPTS_PER_USER}"},
                status=400,
            )

        prompt = await create_prompt(
            author_id=user.id,
            prompt_text=prompt_text,
            title=str(body.get("title", "") or "").strip() or None,
            description=str(body.get("description", "") or "").strip() or None,
            category=str(body.get("category", "") or "").strip() or None,
            preview_url=str(body.get("preview_url", "") or "").strip() or None,
            model=str(body.get("model", "") or "").strip() or None,
            tags=[str(item) for item in list(body.get("tags", []) or [])],
            is_public=True,
        )
        if prompt:
            prompt = await approve_prompt(prompt["id"])
        return web.json_response({"ok": True, "prompt": prompt})
    except Exception as e:
        logger.exception("Mini App prompt submit failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_prompt_deactivate(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        prompt_id = int(body.get("prompt_id") or 0)
        _telegram_id, ctx = await _get_user_context(request.app, init_data)
        prompt = await deactivate_prompt(prompt_id, author_id=ctx["user"].id)
        return web.json_response({"ok": True, "prompt": prompt})
    except Exception as e:
        logger.exception("Mini App prompt deactivate failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_prompt_moderate(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        prompt_id = int(body.get("prompt_id") or 0)
        action = str(body.get("action", "") or "")
        telegram_id, _ctx = await _get_user_context(request.app, init_data)
        if not config.is_admin(telegram_id):
            return web.json_response({"ok": False, "error": "Нет доступа"}, status=403)
        if action == "approve":
            prompt = await approve_prompt(prompt_id)
        elif action == "reject":
            prompt = await reject_prompt(prompt_id, str(body.get("reason", "") or ""))
        elif action == "deactivate":
            prompt = await deactivate_prompt(prompt_id)
        else:
            return web.json_response({"ok": False, "error": "Неизвестное действие"}, status=400)
        return web.json_response({"ok": True, "prompt": prompt})
    except Exception as e:
        logger.exception("Mini App prompt moderate failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_feed(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        source = str(body.get("source", "recent") or "recent")
        limit = min(max(int(body.get("limit", 40) or 40), 1), 100)
        _telegram_id, ctx = await _get_user_context(request.app, init_data)
        feed = await get_feed_generations(
            limit=limit,
            source=source,
            viewer_user_id=ctx["user"].id,
        )
        return web.json_response({"ok": True, "feed": feed})
    except Exception as e:
        logger.exception("Mini App feed list failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_my_feed(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        limit = min(max(int(body.get("limit", 200) or 200), 1), 400)
        _telegram_id, ctx = await _get_user_context(request.app, init_data)
        feed = await get_user_feed_generations(ctx["user"].id, limit=limit)
        return web.json_response({"ok": True, "feed": feed})
    except Exception as e:
        logger.exception("Mini App my feed failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


def _miniapp_profile_payload(author, bot_username: str, *, viewer_user_id: int | None = None) -> dict[str, Any]:
    referral_code = str(getattr(author, "referral_code", "") or "").strip().upper()
    username = str(getattr(author, "username", "") or "").strip().lstrip("@")
    first_name = str(getattr(author, "first_name", "") or "").strip()
    last_name = str(getattr(author, "last_name", "") or "").strip()
    display_name = " ".join(part for part in (first_name, last_name) if part)
    if not display_name:
        display_name = username or f"user_{getattr(author, 'telegram_id', '') or getattr(author, 'id', '')}"

    profile_link = (
        f"https://t.me/{bot_username}?start=posts_{referral_code}_ref_{referral_code}"
        if bot_username and referral_code
        else config.mini_app_url
    )
    referral_link = (
        f"https://t.me/{bot_username}?start=ref_{referral_code}"
        if bot_username and referral_code
        else config.mini_app_url
    )
    return {
        "referral_code": referral_code,
        "first_name": first_name,
        "last_name": last_name,
        "username": username,
        "display_name": display_name,
        "photo_url": "",
        "profile_link": profile_link,
        "referral_link": referral_link,
        "channel_url": getattr(author, "channel_url", None) or "",
        "is_me": bool(viewer_user_id and getattr(author, "id", None) == viewer_user_id),
    }


async def miniapp_profile_feed(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        referral_code = str(body.get("referral_code", "") or "").strip().upper()
        limit = min(max(int(body.get("limit", 120) or 120), 1), 400)
        if not referral_code:
            return web.json_response({"ok": False, "error": "Не указан профиль"}, status=400)

        _telegram_id, ctx = await _get_user_context(request.app, init_data)
        author = await get_user_by_referral_code(referral_code)
        if not author:
            return web.json_response({"ok": False, "error": "Профиль не найден"}, status=404)

        feed = await get_user_feed_generations(author.id, limit=limit)
        is_mine = bool(author.id == ctx["user"].id)
        for item in feed:
            item["is_mine"] = is_mine

        me = await request.app["bot"].get_me()
        profile = _miniapp_profile_payload(
            author,
            me.username or "",
            viewer_user_id=ctx["user"].id,
        )
        return web.json_response({"ok": True, "profile": profile, "feed": feed})
    except Exception as e:
        logger.exception("Mini App profile feed failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_profile_channel_save(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        channel_url = str(body.get("channel_url", "") or "")
        telegram_id, _ctx = await _get_user_context(request.app, init_data)
        normalized = await save_user_channel_url(telegram_id, channel_url)
        return web.json_response({"ok": True, "channel_url": normalized})
    except ValueError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    except Exception as e:
        logger.exception("Mini App profile channel save failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_generation_share(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        _telegram_id, ctx = await _get_user_context(request.app, init_data)
        card = await share_to_feed(gen_id, ctx["user"].id)
        if not card:
            return web.json_response(
                {"ok": False, "error": "Нельзя опубликовать эту генерацию в ленту"},
                status=403,
            )
        return web.json_response({"ok": True, "feed_item": card})
    except Exception as e:
        logger.exception("Mini App share generation failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_feed_remove(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        _telegram_id, ctx = await _get_user_context(request.app, init_data)
        removed = await remove_from_feed(gen_id, ctx["user"].id)
        return web.json_response({"ok": True, "removed": removed})
    except Exception as e:
        logger.exception("Mini App remove feed failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_feed_like(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        _telegram_id, ctx = await _get_user_context(request.app, init_data)
        card = await like_feed_generation(gen_id, ctx["user"].id)
        if not card:
            return web.json_response({"ok": False, "error": "Пост ленты не найден"}, status=404)
        return web.json_response({"ok": True, "feed_item": card})
    except Exception as e:
        logger.exception("Mini App feed like failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_feed_share(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        telegram_id, _ctx = await _get_user_context(request.app, init_data)
        card = await increment_feed_share(gen_id)
        if not card:
            return web.json_response({"ok": False, "error": "Пост ленты не найден"}, status=404)
        me = await request.app["bot"].get_me()
        author_referral_code = str(card.get("author_referral_code") or "").strip().upper()
        start_param = (
            f"feed_{card['id']}_ref_{author_referral_code}"
            if author_referral_code
            else f"feed_{card['id']}"
        )
        link = f"https://t.me/{me.username}?start={start_param}" if me.username else config.mini_app_url
        logger.info("Feed share link issued by %s for feed %s", telegram_id, card["id"])
        return web.json_response({"ok": True, "feed_item": card, "link": link})
    except Exception as e:
        logger.exception("Mini App feed share failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_feed_comments(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        limit = min(max(int(body.get("limit", 80) or 80), 1), 150)
        _telegram_id, ctx = await _get_user_context(request.app, init_data)
        comments = await get_feed_comments(
            gen_id,
            limit=limit,
            viewer_user_id=ctx["user"].id,
        )
        return web.json_response({"ok": True, "comments": comments})
    except Exception as e:
        logger.exception("Mini App feed comments failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_feed_comment_add(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        text = str(body.get("text", "") or "")
        _telegram_id, ctx = await _get_user_context(request.app, init_data)
        comment = await add_feed_comment(gen_id, ctx["user"].id, text)
        if not comment:
            return web.json_response(
                {"ok": False, "error": "Комментарий не удалось добавить"},
                status=400,
            )
        card = await get_feed_generation_card(gen_id, viewer_user_id=ctx["user"].id)
        return web.json_response(
            {
                "ok": True,
                "comment": comment,
                "comments_count": int((card or {}).get("comments_count") or 0),
            }
        )
    except Exception as e:
        logger.exception("Mini App feed comment add failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_generation_share_library(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        _telegram_id, ctx = await _get_user_context(request.app, init_data)
        task = await share_to_library(gen_id, ctx["user"].id)
        if not task:
            return web.json_response(
                {"ok": False, "error": "Нельзя сохранить prompt этой генерации"},
                status=403,
            )
        return web.json_response({"ok": True, "generation": task})
    except Exception as e:
        logger.exception("Mini App share library failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_generation_remove_library(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        _telegram_id, ctx = await _get_user_context(request.app, init_data)
        removed = await remove_from_library(gen_id, ctx["user"].id)
        return web.json_response({"ok": True, "removed": removed})
    except Exception as e:
        logger.exception("Mini App remove library failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_feed_remix(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        telegram_id, ctx = await _get_user_context(request.app, init_data)
        user = ctx["user"]

        source = await get_generation_task_payload(gen_id)
        if not source or not (
            source.get("type") == "image"
            and source.get("status") == "completed"
            and source.get("result_url")
            and bool(source.get("is_public_feed"))
        ):
            return web.json_response({"ok": False, "error": "Пост ленты не найден"}, status=404)

        source_prompt = str(source.get("prompt") or "").strip()
        if not source_prompt:
            return web.json_response({"ok": False, "error": "У исходной генерации нет prompt"}, status=400)
        prompt = str(body.get("prompt", "") or "").strip() or source_prompt

        img_service = str(body.get("img_service") or body.get("model") or source.get("model") or "banana_pro")
        img_ratio = str(body.get("img_ratio") or source.get("aspect_ratio") or "1:1")
        references = [str(item) for item in list(body.get("reference_images", []) or []) if str(item).strip()]
        if not references and source.get("result_url"):
            references = [str(source["result_url"])]
        img_quality = str(body.get("img_quality", "2K"))
        img_nsfw_checker = bool(body.get("img_nsfw_checker", False))
        nsfw_enabled = bool(body.get("nsfw_enabled", False))

        model_meta = next((item for item in IMAGE_MODELS if item["id"] == img_service), None)
        if not model_meta:
            return web.json_response({"ok": False, "error": f"Неизвестная модель: {img_service}"}, status=400)
        if model_meta["requires_reference"] and not references:
            return web.json_response({"ok": False, "error": "Для этой модели нужен референс"}, status=400)
        if len(references) > model_meta["max_references"]:
            return web.json_response(
                {"ok": False, "error": f"Слишком много референсов. Максимум: {model_meta['max_references']}"},
                status=400,
            )
        if missing_local_upload_sources(references):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Один или несколько старых референсов уже удалены. Загрузите фото заново.",
                },
                status=400,
            )

        user_references = [url for url in references if url != source.get("result_url")]
        if user_references:
            await touch_saved_references(telegram_id, user_references, kind="image")

        unit_cost = (
            QUALITY_COSTS.get(img_quality, preset_manager.get_generation_cost(img_service))
            if img_service in ("banana_pro", "banana_2")
            else preset_manager.get_generation_cost(img_service)
        )
        is_admin = config.is_admin(telegram_id)
        if not is_admin and not await check_can_afford(telegram_id, unit_cost):
            return web.json_response(
                {"ok": False, "error": f"Недостаточно бананов. Нужно {unit_cost}🍌", "credits": user.credits},
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
            source_feed_gen_id=int(source["id"]),
            parent_generation_id=int(source["id"]),
            action_type="remix",
        )

        if launch_result["status"] == "failed":
            if not is_admin:
                await add_credits(telegram_id, unit_cost)
            return web.json_response(
                {"ok": False, "error": "Не удалось запустить remix. Бананы уже возвращены."},
                status=500,
            )

        await credit_feed_prompt_repeat(
            int(source["id"]),
            user.id,
            repeat_task_id=str(launch_result.get("task_id") or ""),
            credits_spent=unit_cost,
        )

        fresh_user = await get_or_create_user(telegram_id)
        return web.json_response(
            {
                "ok": True,
                "status": launch_result["status"],
                "task_id": launch_result["task_id"],
                "saved_url": launch_result.get("saved_url"),
                "task_type": "image",
                "credits": fresh_user.credits,
                "cost": unit_cost,
                "model_label": get_image_model_label(img_service),
                "prompt_hidden": False,
                "prompt_actions_allowed": False,
                "source_feed_gen_id": int(source["id"]),
            }
        )
    except Exception as e:
        logger.exception("Mini App feed remix failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def miniapp_generate_image(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        telegram_id, ctx = await _get_user_context(request.app, init_data)
        user = ctx["user"]

        prompt = str(body.get("prompt", "")).strip()
        prompt_id_raw = body.get("prompt_id")
        prompt_id = int(prompt_id_raw) if str(prompt_id_raw or "").isdigit() else None
        references = [
            str(item).strip()
            for item in list(body.get("reference_images", []) or [])
            if str(item).strip()
        ]
        source_feed_gen_id_raw = body.get("source_feed_gen_id") or body.get("sourceFeedGenId")
        source_feed_gen_id = (
            int(source_feed_gen_id_raw)
            if str(source_feed_gen_id_raw or "").isdigit()
            else None
        )
        source_feed_task = None
        if source_feed_gen_id:
            source_feed_task = await get_generation_task_payload(source_feed_gen_id)
            if not source_feed_task or not (
                source_feed_task.get("type") == "image"
                and source_feed_task.get("status") == "completed"
                and source_feed_task.get("result_url")
                and bool(source_feed_task.get("is_public_feed"))
            ):
                return web.json_response(
                    {"ok": False, "error": "Пост ленты не найден"},
                    status=404,
                )
            source_prompt = str(source_feed_task.get("prompt") or "").strip()
            if not source_prompt:
                return web.json_response(
                    {"ok": False, "error": "У исходной генерации нет prompt"},
                    status=400,
                )
            if not prompt:
                prompt = source_prompt
            if not references:
                return web.json_response(
                    {"ok": False, "error": "Добавьте своё фото или референс для remix"},
                    status=400,
                )

        img_service = str(
            body.get("img_service")
            or (source_feed_task or {}).get("model")
            or "banana_pro"
        )
        img_ratio = str(
            body.get("img_ratio")
            or (source_feed_task or {}).get("aspect_ratio")
            or "1:1"
        )
        img_quality = str(body.get("img_quality", "2K"))
        img_nsfw_checker = bool(body.get("img_nsfw_checker", False))
        nsfw_enabled = bool(body.get("nsfw_enabled", False))

        prompt_source = None
        if prompt_id and not source_feed_gen_id:
            prompt_source = await get_prompt_by_id(prompt_id, approved_public_only=True)
            if not prompt_source:
                return web.json_response(
                    {"ok": False, "error": "Промпт не найден или ещё не опубликован"},
                    status=404,
                )
            prompt = str(prompt_source["prompt_text"]).strip()

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
        if missing_local_upload_sources(references):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Один или несколько старых референсов уже удалены. Загрузите фото заново.",
                },
                status=400,
            )

        if references:
            await touch_saved_references(telegram_id, references, kind="image")

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
            prompt_source_id=(None if source_feed_gen_id else prompt_id),
            source_feed_gen_id=source_feed_gen_id,
            parent_generation_id=source_feed_gen_id,
            action_type=("remix" if source_feed_gen_id else None),
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

        if source_feed_gen_id:
            await credit_feed_prompt_repeat(
                source_feed_gen_id,
                user.id,
                repeat_task_id=str(launch_result.get("task_id") or ""),
                credits_spent=unit_cost,
            )
        elif prompt_id:
            await use_prompt(prompt_id, user.id, credits_spent=unit_cost)

        fresh_user = await get_or_create_user(telegram_id)
        prompt_hidden = False
        return web.json_response(
            {
                "ok": True,
                "status": launch_result["status"],
                "task_id": launch_result["task_id"],
                "saved_url": launch_result.get("saved_url"),
                "task_type": launch_result.get("task_type", "image"),
                "credits": fresh_user.credits,
                "cost": unit_cost,
                "model_label": get_image_model_label(img_service),
                "prompt_hidden": prompt_hidden,
                "prompt_actions_allowed": not bool(source_feed_gen_id),
                "prompt_id": (None if source_feed_gen_id else prompt_id),
                "source_feed_gen_id": source_feed_gen_id,
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
        source_feed_gen_id_raw = body.get("source_feed_gen_id") or body.get("sourceFeedGenId")
        source_feed_gen_id = (
            int(source_feed_gen_id_raw)
            if str(source_feed_gen_id_raw or "").isdigit()
            else None
        )
        source_feed_task = None
        source_request_data: dict[str, Any] = {}
        if source_feed_gen_id:
            source_feed_task = await get_generation_task_payload(source_feed_gen_id)
            if not source_feed_task or not (
                source_feed_task.get("type") == "video"
                and source_feed_task.get("status") == "completed"
                and source_feed_task.get("result_url")
                and bool(source_feed_task.get("is_public_feed"))
            ):
                return web.json_response(
                    {"ok": False, "error": "Видео из ленты не найдено"},
                    status=404,
                )
            source_prompt = str(source_feed_task.get("prompt") or "").strip()
            if not source_prompt:
                return web.json_response(
                    {"ok": False, "error": "У исходного видео нет prompt"},
                    status=400,
                )
            if not prompt:
                prompt = source_prompt
            source_request_data = source_feed_task.get("request_data") or {}
            if not isinstance(source_request_data, dict):
                source_request_data = {}

        model = str(
            body.get("v_model")
            or (source_feed_task or {}).get("model")
            or "v3_pro"
        )
        generation_type = str(
            body.get("v_type")
            or source_request_data.get("v_type")
            or "text"
        )
        duration = int(
            body.get("v_duration")
            or (source_feed_task or {}).get("duration")
            or 5
        )
        aspect_ratio = str(
            body.get("v_ratio")
            or (source_feed_task or {}).get("aspect_ratio")
            or "16:9"
        )
        image_url = str(body.get("v_image_url", "") or "") or None
        image_references = list(body.get("reference_images", []) or [])
        video_references = list(body.get("v_reference_videos", []) or [])
        audio_url = str(body.get("audio_url", "") or "") or None
        if not audio_url:
            audio_url = str(body.get("audio_reference", "") or "") or None
        audio_references = list(body.get("audio_references", []) or [])
        if not audio_url and audio_references:
            audio_url = str(audio_references[0] or "") or None
        grok_mode = str(body.get("grok_mode", "normal") or "normal")
        grok_resolution = str(body.get("grok_resolution", "480p") or "480p")
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
        omni_resolution = str(body.get("omni_resolution", "720p") or "720p")
        omni_seed_raw = body.get("omni_seed")
        try:
            omni_seed = (
                int(omni_seed_raw)
                if omni_seed_raw not in (None, "", False)
                else None
            )
        except (TypeError, ValueError):
            return web.json_response(
                {"ok": False, "error": "Seed должен быть числом"},
                status=400,
            )
        omni_audio_ids = [
            str(item).strip()
            for item in list(body.get("omni_audio_ids", []) or [])
            if str(item).strip()
        ]
        omni_character_ids = [
            str(item).strip()
            for item in list(body.get("omni_character_ids", []) or [])
            if str(item).strip()
        ]
        omni_base_voice = str(body.get("omni_base_voice", "achernar") or "achernar")
        omni_voice_name = str(body.get("omni_voice_name", "") or "")[:20] or None
        omni_voice_description = (
            str(body.get("omni_voice_description", "") or "")[:2000] or None
        )
        omni_example_dialogue = (
            str(body.get("omni_example_dialogue", "") or "")[:2000] or None
        )
        omni_character_name = (
            str(body.get("omni_character_name", "") or "")[:20] or None
        )
        omni_character_audio_ids = [
            str(item).strip()
            for item in list(body.get("omni_character_audio_ids", []) or [])
            if str(item).strip()
        ][:1]

        if not prompt:
            return web.json_response(
                {"ok": False, "error": "Введите промпт для генерации видео"},
                status=400,
            )
        model_meta = _find_video_model_meta(model)
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
        effective_model = _resolve_gemini_omni_model(model, generation_type)
        if effective_model in {"gemini_omni_audio", "gemini_omni_character"}:
            duration = 6

        if effective_model == "grok_imagine_v15":
            normalized_grok_ratio = _normalize_video_ratio(aspect_ratio)
            if normalized_grok_ratio not in model_meta["ratios"]:
                return web.json_response(
                    {"ok": False, "error": "Недопустимый формат для Grok Imagine 1.5"},
                    status=400,
                )
            if grok_resolution not in model_meta.get("grok_resolutions", []):
                return web.json_response(
                    {"ok": False, "error": "Недопустимое качество для Grok Imagine 1.5"},
                    status=400,
                )
            if image_references:
                return web.json_response(
                    {
                        "ok": False,
                        "error": "Grok Imagine 1.5 принимает только одно стартовое фото без дополнительных референсов",
                    },
                    status=400,
                )

        if generation_type == "video" and not video_model_supports_reference_videos(effective_model):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для нескольких видео-референсов выберите Seedance 2.0",
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
        if (
            generation_type == "imgtxt"
            and not image_url
            and effective_model != "gemini_omni_video"
        ):
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для режима Фото + Текст загрузите стартовое фото",
                },
                status=400,
            )
        if generation_type == "character" and not image_url:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Для Gemini Omni Character загрузите изображение персонажа",
                },
                status=400,
            )
        if (
            generation_type == "video"
            and not video_references
            and effective_model != "gemini_omni_video"
        ):
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

        max_image_references = int(model_meta.get("max_image_references", 0) or 0)
        if max_image_references and len(image_references) > max_image_references:
            return web.json_response(
                {
                    "ok": False,
                    "error": f"Слишком много фото-референсов. Максимум: {max_image_references}",
                },
                status=400,
            )

        max_video_references = int(model_meta.get("max_video_references", 0) or 0)
        if max_video_references and len(video_references) > max_video_references:
            return web.json_response(
                {
                    "ok": False,
                    "error": f"Слишком много видео-референсов. Максимум: {max_video_references}",
                },
                status=400,
            )
        if effective_model == "gemini_omni_video":
            omni_images = _collect_gemini_omni_images(image_url, image_references)
            omni_video_urls = _collect_gemini_omni_video_urls(video_references)
            validation_error = _validate_gemini_omni_video_inputs(
                image_urls=omni_images,
                video_urls=omni_video_urls,
                audio_ids=omni_audio_ids,
                character_ids=omni_character_ids,
            )
            if validation_error:
                return web.json_response(
                    {"ok": False, "error": validation_error},
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

        missing_video_images = missing_local_upload_sources(
            _clean_unique_values([image_url, *image_references])
        )
        if missing_video_images:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Один или несколько старых фото-референсов уже удалены. Загрузите фото заново.",
                },
                status=400,
            )

        if image_url:
            await touch_saved_references(telegram_id, [image_url], kind="image")
        if image_references:
            await touch_saved_references(telegram_id, image_references, kind="image")
        if video_references:
            await touch_saved_references(telegram_id, video_references, kind="video")
        if audio_url:
            await touch_saved_references(telegram_id, [audio_url], kind="audio")

        pricing_quality = _video_pricing_quality(
            effective_model, veo_resolution, omni_resolution
        )
        cost = preset_manager.get_video_cost_with_quality(
            effective_model, duration, pricing_quality
        )
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
            model=effective_model,
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            generation_type=generation_type,
            image_url=image_url,
            image_references=image_references,
            video_references=video_references,
            audio_url=audio_url,
            grok_mode=grok_mode,
            grok_resolution=grok_resolution,
            veo_generation_type=veo_generation_type,
            veo_translation=veo_translation,
            veo_resolution=veo_resolution,
            veo_seed=veo_seed,
            veo_watermark=veo_watermark,
            kling_negative_prompt=kling_negative_prompt,
            kling_cfg_scale=kling_cfg_scale,
            omni_resolution=omni_resolution,
            omni_seed=omni_seed,
            omni_audio_ids=omni_audio_ids,
            omni_character_ids=omni_character_ids,
            omni_base_voice=omni_base_voice,
            omni_voice_name=omni_voice_name,
            omni_voice_description=omni_voice_description,
            omni_example_dialogue=omni_example_dialogue,
            omni_character_name=omni_character_name,
            omni_character_audio_ids=omni_character_audio_ids,
            source_feed_gen_id=source_feed_gen_id,
            parent_generation_id=source_feed_gen_id,
            action_type=("repeat" if source_feed_gen_id else None),
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

        if source_feed_gen_id:
            await credit_feed_prompt_repeat(
                source_feed_gen_id,
                user.id,
                repeat_task_id=str(launch_result.get("task_id") or ""),
                credits_spent=cost,
            )

        fresh_user = await get_or_create_user(telegram_id)
        return web.json_response(
            {
                "ok": True,
                "status": launch_result["status"],
                "task_id": launch_result["task_id"],
                "saved_url": launch_result.get("saved_url"),
                "task_type": launch_result.get("task_type"),
                "credits": fresh_user.credits,
                "cost": cost,
                "model_label": get_video_model_label(effective_model),
                "prompt_hidden": False,
                "prompt_actions_allowed": not bool(source_feed_gen_id),
                "source_feed_gen_id": source_feed_gen_id,
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

        raw_duration = body.get("motion_duration")
        if raw_duration in (None, ""):
            duration = 5
        else:
            try:
                duration = int(raw_duration)
            except (TypeError, ValueError):
                return web.json_response(
                    {"ok": False, "error": "Длительность Motion Control должна быть целым числом от 3 до 30 секунд"},
                    status=400,
                )
            if duration < 3 or duration > 30:
                return web.json_response(
                    {"ok": False, "error": "Длительность Motion Control должна быть от 3 до 30 секунд"},
                    status=400,
                )

        await touch_saved_references(telegram_id, [image_url], kind="image")
        await touch_saved_references(telegram_id, [video_url], kind="video")

        cost = preset_manager.get_video_cost_with_quality(model, duration, mode)

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
                "prompt_repeat_balance_rub": float(
                    stats.get("prompt_repeat_balance_rub", 0) or 0
                ),
                "prompt_repeat_total_rub": float(
                    stats.get("prompt_repeat_total_rub", 0) or 0
                ),
                "channel_url": user.channel_url or "",
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
    """AI-ассистент через настоящий LLM backend."""
    try:
        body = await request.json()
        init_data = body.get("init_data", "")
        user_message = str(body.get("message", "")).strip()
        audio_url = str(body.get("audio_url", "") or "").strip()
        audio_content_type = str(body.get("audio_content_type", "") or "").strip()
        history = list(body.get("history", []) or [])

        if not user_message and not audio_url:
            return web.json_response(
                {"ok": False, "error": "Сообщение не может быть пустым"}, status=400
            )

        telegram_id, ctx = await _get_user_context(request.app, init_data)
        user = ctx["user"]
        audio_bytes = None
        audio_format = ""

        if audio_url:
            try:
                audio_bytes, _mime_type, audio_format = _load_miniapp_assistant_audio(
                    audio_url,
                    content_type=audio_content_type,
                )
            except ValueError as e:
                return web.json_response(
                    {"ok": False, "error": str(e)},
                    status=400,
                )

        context = {
            "user_credits": user.credits,
            "menu_location": "mini_app_assistant",
        }

        if audio_bytes:
            response_text = await ai_assistant_service.get_assistant_response_with_audio(
                user_message=user_message,
                context=context,
                audio_bytes=audio_bytes,
                audio_format=audio_format,
            )
        else:
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


async def miniapp_api_not_found(request: web.Request) -> web.Response:
    logger.warning(
        "Mini App API route not found: method=%s path=%s",
        request.method,
        request.path,
    )
    return web.json_response(
        {"ok": False, "error": "API endpoint not found"},
        status=404,
    )


def setup_miniapp_routes(app: web.Application):
    miniapp_path = config.MINI_APP_PATH or "/mini-app"
    if not miniapp_path.startswith("/"):
        miniapp_path = f"/{miniapp_path}"
    miniapp_root = miniapp_path.rstrip("/")

    @web.middleware
    async def _miniapp_api_json_errors(
        request: web.Request,
        handler,
    ) -> web.StreamResponse:
        try:
            return await handler(request)
        except web.HTTPException as exc:
            if request.path.startswith(f"{miniapp_root}/api/") or request.path.startswith(
                "/api/v1/"
            ):
                return web.json_response(
                    {"ok": False, "error": exc.reason or "API request failed"},
                    status=exc.status,
                )
            raise

    app.middlewares.append(_miniapp_api_json_errors)

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

    async def _miniapp_root_file(request: web.Request) -> web.Response:
        asset_name = request.match_info.get("asset", "") or "icon-light-32x32.png"
        asset_path = miniapp_out_dir / asset_name
        if asset_path.exists() and asset_path.is_file():
            return web.FileResponse(asset_path)
        if asset_name == "favicon.ico":
            for fallback_name in ("icon.svg", "icon-light-32x32.png"):
                fallback_path = miniapp_out_dir / fallback_name
                if fallback_path.exists() and fallback_path.is_file():
                    return web.FileResponse(fallback_path)
        raise web.HTTPNotFound()

    async def _empty_vercel_insights(request: web.Request) -> web.Response:
        # The exported miniapp can request Vercel Insights from the site root.
        # We do not run Vercel here, so serve a no-op script instead of noisy 404s.
        return web.Response(
            text="/* Vercel Insights disabled on self-hosted deployment. */\n",
            content_type="application/javascript",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    # Do not mount the full `out/` directory as a static resource here.
    # Serving of `index.html` and other files is handled explicitly by
    # `miniapp_index` and `miniapp_asset` so we avoid conflicts where the
    # static resource would match `/mini-app/` and return 403 for directory
    # requests when `show_index` is disabled. Keep only `_next/static`
    # mounted above for Next.js runtime assets.
    app.router.add_get("/icon-light-32x32.png", _miniapp_root_file)
    app.router.add_get("/icon.svg", _miniapp_root_file)
    app.router.add_get("/icon-dark-32x32.png", _miniapp_root_file)
    app.router.add_get("/favicon.ico", _miniapp_root_file)
    app.router.add_get("/_vercel/insights/script.js", _empty_vercel_insights)
    app.router.add_get(miniapp_root, miniapp_index)
    app.router.add_get(f"{miniapp_root}/", miniapp_index)
    app.router.add_post(miniapp_root + "/api/bootstrap", miniapp_bootstrap)
    app.router.add_post(miniapp_root + "/api/action", miniapp_action)
    app.router.add_post(miniapp_root + "/api/upload", miniapp_upload)
    app.router.add_post(miniapp_root + "/api/photo-to-prompt", miniapp_photo_to_prompt)
    app.router.add_post(miniapp_root + "/api/prompts", miniapp_prompts)
    app.router.add_post(miniapp_root + "/api/prompts/detail", miniapp_prompt_detail)
    app.router.add_post(miniapp_root + "/api/prompts/like", miniapp_prompt_like)
    app.router.add_post(miniapp_root + "/api/prompts/use", miniapp_prompt_use)
    app.router.add_post(miniapp_root + "/api/prompts/link", miniapp_prompt_link)
    app.router.add_post(miniapp_root + "/api/prompts/submit", miniapp_prompt_submit)
    app.router.add_post(miniapp_root + "/api/prompts/deactivate", miniapp_prompt_deactivate)
    app.router.add_post(miniapp_root + "/api/admin/prompts/moderate", miniapp_prompt_moderate)
    app.router.add_post(miniapp_root + "/api/feed", miniapp_feed)
    app.router.add_post(miniapp_root + "/api/feed/my", miniapp_my_feed)
    app.router.add_get(miniapp_root + "/api/feed/profile", miniapp_profile_feed)
    app.router.add_post(miniapp_root + "/api/feed/profile", miniapp_profile_feed)
    app.router.add_post(miniapp_root + "/api/profile/channel", miniapp_profile_channel_save)
    app.router.add_post(miniapp_root + "/api/feed/like", miniapp_feed_like)
    app.router.add_post(miniapp_root + "/api/feed/share", miniapp_feed_share)
    app.router.add_get(miniapp_root + "/api/feed/comments", miniapp_feed_comments)
    app.router.add_post(miniapp_root + "/api/feed/comments", miniapp_feed_comments)
    app.router.add_post(miniapp_root + "/api/feed/comment", miniapp_feed_comment_add)
    app.router.add_post(miniapp_root + "/api/feed/remove", miniapp_feed_remove)
    app.router.add_post(miniapp_root + "/api/feed/remix", miniapp_feed_remix)
    app.router.add_post(miniapp_root + "/api/generations/share", miniapp_generation_share)
    app.router.add_post(miniapp_root + "/api/generations/publish", miniapp_generation_share)
    app.router.add_post(
        miniapp_root + "/api/generations/share-library",
        miniapp_generation_share_library,
    )
    app.router.add_post(
        miniapp_root + "/api/generations/remove-library",
        miniapp_generation_remove_library,
    )
    app.router.add_post(miniapp_root + "/api/generate-image", miniapp_generate_image)
    app.router.add_post(miniapp_root + "/api/generate-video", miniapp_generate_video)
    app.router.add_post(miniapp_root + "/api/generate-motion", miniapp_generate_motion)
    app.router.add_post(
        miniapp_root + "/api/partner-overview", miniapp_partner_overview
    )
    app.router.add_post(miniapp_root + "/api/create-payment", miniapp_create_payment)
    app.router.add_post(miniapp_root + "/api/task-detail", miniapp_task_detail)
    app.router.add_post(miniapp_root + "/api/ai-assistant", miniapp_ai_assistant)
    app.router.add_route("*", miniapp_root + "/api/{tail:.*}", miniapp_api_not_found)

    api_v1_root = "/api/v1"
    app.router.add_get(api_v1_root + "/feed", miniapp_feed)
    app.router.add_get(api_v1_root + "/me/feed", miniapp_my_feed)
    app.router.add_get(api_v1_root + "/feed/profile", miniapp_profile_feed)
    app.router.add_post(api_v1_root + "/feed/profile", miniapp_profile_feed)
    app.router.add_get(api_v1_root + "/profiles/{referral_code}/feed", miniapp_profile_feed)
    app.router.add_post(api_v1_root + "/profiles/{referral_code}/feed", miniapp_profile_feed)
    app.router.add_post(api_v1_root + "/me/channel", miniapp_profile_channel_save)
    app.router.add_get(api_v1_root + "/feed/{gen_id}/comments", miniapp_feed_comments)
    app.router.add_post(api_v1_root + "/feed/{gen_id}/comments", miniapp_feed_comment_add)
    app.router.add_post(api_v1_root + "/generations/{gen_id}/share", miniapp_generation_share)
    app.router.add_post(api_v1_root + "/generations/{gen_id}/publish", miniapp_generation_share)
    app.router.add_post(
        api_v1_root + "/generations/{gen_id}/share-library",
        miniapp_generation_share_library,
    )
    app.router.add_post(
        api_v1_root + "/generations/{gen_id}/remove-library",
        miniapp_generation_remove_library,
    )
    app.router.add_post(api_v1_root + "/feed/{gen_id}/remove", miniapp_feed_remove)
    app.router.add_post(api_v1_root + "/feed/{gen_id}/like", miniapp_feed_like)
    app.router.add_post(api_v1_root + "/feed/{gen_id}/remix", miniapp_feed_remix)
    app.router.add_get(api_v1_root + "/feed/{gen_id}/link", miniapp_feed_share)
    app.router.add_get(api_v1_root + "/prompts", miniapp_prompts)
    app.router.add_post(api_v1_root + "/prompts", miniapp_prompt_submit)
    app.router.add_get(api_v1_root + "/prompts/my", miniapp_prompts)
    app.router.add_get(api_v1_root + "/prompts/{prompt_id}", miniapp_prompt_detail)
    app.router.add_get(api_v1_root + "/prompts/{prompt_id}/link", miniapp_prompt_link)
    app.router.add_post(api_v1_root + "/prompts/{prompt_id}/like", miniapp_prompt_like)
    app.router.add_post(api_v1_root + "/prompts/{prompt_id}/use", miniapp_prompt_use)
    app.router.add_post(
        api_v1_root + "/prompts/{prompt_id}/deactivate",
        miniapp_prompt_deactivate,
    )
    app.router.add_post(api_v1_root + "/generate/image", miniapp_generate_image)
    app.router.add_route("*", api_v1_root + "/{tail:.*}", miniapp_api_not_found)
    app.router.add_get(miniapp_root + "/{tail:.*}", miniapp_asset)
