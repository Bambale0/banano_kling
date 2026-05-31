import asyncio
import html
import json
import logging
import os
import random
import sys
import time
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
from typing import Any, Awaitable, Callable

# Добавляем родительскую директорию в путь для импортов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Загружаем переменные из .env файла
from dotenv import load_dotenv

load_dotenv(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
)

from aiogram import BaseMiddleware, Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    Update,
)
from aiohttp import web

from bot.config import config
from bot.database import (
    cleanup_orphaned_reference_files,
    cleanup_saved_references,
    cleanup_stale_local_generation_tasks,
    init_db,
    is_maintenance_mode_enabled,
    is_user_banned,
)
from bot.handlers import (
    admin_router,
    batch_generation_router,
    common_router,
    generation_router,
    image_analyzer_router,
    payments_router,
)
from bot.handlers.payments import (
    cleanup_stale_cryptobot_pending,
    handle_cryptobot_webhook,
    handle_lava_webhook,
    handle_yookassa_webhook,
)
from bot.miniapp import setup_miniapp_routes
from bot.services.preset_manager import preset_manager
from bot.services.redis_service import redis_service
from bot.services.yookassa_service import yookassa_service

CLEANUP_INTERVAL_SECONDS = 24 * 3600
UPLOAD_RETENTION_SECONDS = 24 * 3600
LOG_RETENTION_SECONDS = 24 * 3600
ACTIVE_LOG_FILENAMES = {"bot.log"}

YOOKASSA_RECONCILE_INTERVAL_SECONDS = 5 * 60
YOOKASSA_RECONCILE_BATCH_SIZE = 50

USER_BOT_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="feed", description="Лента работ"),
    BotCommand(command="prompts", description="Библиотека промптов"),
    BotCommand(command="help", description="Помощь и возможности"),
    BotCommand(command="ref", description="Партнёрская программа"),
    BotCommand(command="earn", description="Заработок на рефералах"),
]
USER_BOT_COMMAND_SCOPES = (
    BotCommandScopeDefault(),
    BotCommandScopeAllPrivateChats(),
)
USER_BOT_COMMAND_LANGUAGES = (None, "ru")


async def _yookassa_reconcile_loop() -> None:
    while True:
        try:
            results = await yookassa_service.poll_pending_transactions(
                limit=YOOKASSA_RECONCILE_BATCH_SIZE
            )
            if results:
                completed = sum(1 for item in results if item.get("action") == "completed")
                failed = sum(1 for item in results if item.get("action") == "failed")
                still_pending = sum(1 for item in results if item.get("action") == "still_pending")
                not_found = sum(1 for item in results if item.get("status") == "not_found")
                errors = sum(1 for item in results if item.get("error"))
                logger.info(
                    "YooKassa reconcile tick: checked=%s completed=%s failed=%s pending=%s not_found=%s errors=%s",
                    len(results),
                    completed,
                    failed,
                    still_pending,
                    not_found,
                    errors,
                )
        except Exception:
            logger.exception("YooKassa reconcile loop failed")
        await asyncio.sleep(YOOKASSA_RECONCILE_INTERVAL_SECONDS)

def _configure_logging() -> None:
    if os.environ.get("BANANO_DISABLE_FILE_LOGGING") == "1":
        logging.basicConfig(
            level=logging.INFO,
            handlers=[logging.NullHandler()],
            force=True,
        )
        return

    os.makedirs("logs", exist_ok=True)

    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler = TimedRotatingFileHandler(
        "logs/bot.log",
        when="midnight",
        interval=1,
        backupCount=1,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    handlers = [file_handler]
    if os.environ.get("BANANO_LOG_TO_STDOUT") == "1":
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        handlers.append(stream_handler)

    logging.basicConfig(
        level=logging.INFO,
        handlers=handlers,
        force=True,
    )

    for logger_name in (
        "aiohttp.access",
        "aiohttp.server",
        "aiogram",
        "aiogram.event",
        "aiogram.dispatcher",
    ):
        named_logger = logging.getLogger(logger_name)
        named_logger.handlers.clear()
        named_logger.propagate = True


_configure_logging()
logger = logging.getLogger(__name__)


class AccessGuardMiddleware(BaseMiddleware):
    """Blocks banned users and non-admin traffic while maintenance is enabled."""

    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if not user or config.is_admin(user.id):
            return await handler(event, data)

        try:
            if await is_user_banned(user.id):
                await self._reply(event, "⛔ Доступ к боту ограничен.")
                return None
            if await is_maintenance_mode_enabled():
                await self._reply(
                    event,
                    "🛠 Бот временно на техническом обслуживании. Попробуйте позже.",
                )
                return None
        except Exception:
            logger.exception("Access guard failed; passing update through")

        return await handler(event, data)

    async def _reply(self, event: types.TelegramObject, text: str) -> None:
        if isinstance(event, types.CallbackQuery):
            try:
                await event.answer(text, show_alert=True)
            except Exception:
                logger.debug("Failed to answer blocked callback", exc_info=True)
            return
        if isinstance(event, types.Message):
            try:
                await event.answer(text)
            except Exception:
                logger.debug("Failed to answer blocked message", exc_info=True)


def _preview_log_payload(value, limit: int = 1200) -> str:
    def _redact_payload(obj):
        if isinstance(obj, dict):
            redacted = {}
            for key, item in obj.items():
                key_str = str(key)
                lowered = key_str.lower()
                if lowered in {"prompt", "negative_prompt", "system_prompt", "raw_body", "body_text", "param", "params"}:
                    if isinstance(item, str):
                        redacted[key_str] = f"[redacted:{len(item)} chars]"
                    else:
                        redacted[key_str] = "[redacted]"
                    continue
                if "url" in lowered and isinstance(item, str):
                    redacted[key_str] = "[redacted:url]"
                    continue
                redacted[key_str] = _redact_payload(item)
            return redacted
        if isinstance(obj, list):
            return [_redact_payload(item) for item in obj]
        if isinstance(obj, str):
            if obj.startswith(("http://", "https://")):
                return "[redacted:url]"
            return obj
        return obj

    try:
        prepared = _redact_payload(value)
        if isinstance(prepared, (dict, list)):
            text = json.dumps(prepared, ensure_ascii=False, default=str)
        elif isinstance(prepared, bytes):
            text = prepared.decode("utf-8", errors="replace")
        else:
            text = str(prepared)
    except Exception:
        text = repr(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"


def _build_dispatcher_storage():
    try:
        from aiogram.fsm.storage.redis import DefaultKeyBuilder, RedisStorage

        storage = RedisStorage.from_url(
            config.redis_url,
            key_builder=DefaultKeyBuilder(prefix=config.REDIS_PREFIX, with_bot_id=True),
        )
        logger.info("FSM storage configured via Redis: %s", config.redis_url)
        return storage
    except Exception as exc:
        logger.warning("Redis FSM storage unavailable, fallback to MemoryStorage: %s", exc)
        return MemoryStorage()


def _get_task_model_label(model: str | None, task_type: str | None = None) -> str:
    """Возвращает аккуратное имя модели для пользовательских уведомлений."""
    if not model:
        return "AI"

    mapping = {
        "aleph": "Aleph Video",
        "glow": "Kling Glow",
        "grok_imagine": "Grok Imagine",
        "seedance_2": "Bytedance Seedance 2.0",
        "grok_imagine_i2i": "Grok Imagine i2i",
        "v3_std": "Kling 3 Std",
        "v3_pro": "Kling 3 Pro",
        "veo3": "Veo 3.1 Quality",
        "veo3_fast": "Veo 3.1 Fast",
        "veo3_lite": "Veo 3.1 Lite",
        "gemini_omni": "Gemini Omni",
        "gemini_omni_video": "Gemini Omni Video",
        "gemini_omni_audio": "Gemini Omni Audio",
        "gemini_omni_character": "Gemini Omni Character",
        "banana_pro": "Banana Pro",
        "banana_2": "Banana 2",
        "seedream_edit": "Seedream 4.5",
        "flux_pro": "GPT Image 2",
        "v26_pro": "Kling 2.5 Turbo Pro",
        "avatar_std": "Kling AI Avatar Standard",
        "avatar_pro": "Kling AI Avatar Pro",
        "nanobanana": "Nano Banana",
    }
    return mapping.get(
        model, model if task_type != "image" else model.replace("_", " ").title()
    )


async def _resolve_task_telegram_id(task, *, context: str = "") -> int | None:
    """Resolve the Telegram chat for a generation task.

    generation_tasks stores both the internal users.id and the launch-time
    telegram_id. Prefer the launch-time telegram_id because it is the exact chat
    that created the task; use users.id lookup only as a compatibility fallback.
    """
    if not task:
        return None

    stored_telegram_id = getattr(task, "telegram_id", None)
    internal_user_id = getattr(task, "user_id", None)
    task_id = getattr(task, "task_id", None)
    resolved_telegram_id = None

    if internal_user_id is not None:
        try:
            from bot.database import get_telegram_id_by_user_id

            resolved_telegram_id = await get_telegram_id_by_user_id(internal_user_id)
        except Exception:
            logger.exception(
                "Failed to resolve telegram_id by internal user_id=%s for task=%s context=%s",
                internal_user_id,
                task_id,
                context,
            )

    if stored_telegram_id:
        try:
            normalized_stored = int(stored_telegram_id)
        except (TypeError, ValueError):
            normalized_stored = None

        if normalized_stored:
            if (
                resolved_telegram_id
                and int(resolved_telegram_id) != normalized_stored
            ):
                logger.error(
                    "Task recipient mismatch: task=%s context=%s internal_user_id=%s "
                    "generation_tasks.telegram_id=%s users.telegram_id=%s. "
                    "Using generation_tasks.telegram_id.",
                    task_id,
                    context,
                    internal_user_id,
                    normalized_stored,
                    resolved_telegram_id,
                )
            return normalized_stored

    if resolved_telegram_id:
        logger.warning(
            "Task %s has no generation_tasks.telegram_id; using users.telegram_id=%s "
            "from internal_user_id=%s context=%s",
            task_id,
            resolved_telegram_id,
            internal_user_id,
            context,
        )
        return int(resolved_telegram_id)

    logger.error(
        "Cannot resolve telegram_id for task=%s internal_user_id=%s context=%s",
        task_id,
        internal_user_id,
        context,
    )
    return None


def _extract_first(obj, keys):
    """Рекурсивно извлекает первое непустое значение по списку ключей."""
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if value not in (None, ""):
                return value
        for value in obj.values():
            found = _extract_first(value, keys)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _extract_first(item, keys)
            if found not in (None, ""):
                return found
    return None


def _extract_gemini_omni_asset_id(obj, asset_kind: str):
    """Extract Gemini Omni Audio ID or Character ID from async KIE payloads."""
    if asset_kind == "audio":
        keys = (
            "kieAudioId",
            "kieAudioID",
            "audioId",
            "audioID",
            "audio_id",
        )
    elif asset_kind == "character":
        keys = (
            "kieCharacterId",
            "kieCharacterID",
            "characterId",
            "characterID",
            "character_id",
        )
    else:
        return None

    candidates = [obj]
    result_json = _extract_first(obj, ("resultJson", "result_json"))
    if isinstance(result_json, str) and result_json.strip():
        try:
            candidates.append(json.loads(result_json))
        except json.JSONDecodeError:
            pass

    for candidate in candidates:
        found = _extract_first(candidate, keys)
        if isinstance(found, list):
            found = found[0] if found else None
        if found not in (None, ""):
            return str(found)
    return None


def _extract_task_request_data(task) -> dict:
    """Safely decode stored request_data for debug logging."""
    if not task or not getattr(task, "request_data", None):
        return {}
    try:
        return json.loads(task.request_data)
    except Exception:
        return {}


def _normalize_user_prompt(candidate: str) -> str:
    if not isinstance(candidate, str):
        return ""
    text = candidate.strip()
    if not text:
        return ""

    normalized = text.replace("\r\n", "\n")
    markers = [
        "User request:",
        "User prompt:",
        "Промпт пользователя:",
        "Запрос пользователя:",
    ]
    for marker in markers:
        idx = normalized.find(marker)
        if idx != -1:
            tail = normalized[idx + len(marker):].strip()
            if tail:
                return tail
    return text


def _extract_used_prompt(task) -> str:
    request_data = _extract_task_request_data(task)
    for candidate in (
        request_data.get("user_prompt"),
        request_data.get("original_prompt"),
        request_data.get("prompt"),
        getattr(task, "prompt", None),
        request_data.get("effective_prompt"),
    ):
        normalized = _normalize_user_prompt(candidate)
        if normalized:
            return normalized
    return ""


def _get_result_prompt_caption(task) -> tuple[str, str]:
    used_prompt = _extract_used_prompt(task)
    if not used_prompt:
        return "<pre>—</pre>", "Промпт"

    escaped = html.escape(used_prompt.strip())
    return f"<pre>{escaped}</pre>", "Промпт"


async def _send_full_prompt_message(bot_instance: Bot, telegram_id: int, task, reference_urls: list[str] | None = None) -> None:
    return


async def _download_remote_bytes(url: str, timeout_seconds: int = 30) -> bytes | None:
    try:
        import aiohttp

        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=timeout_seconds) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Download failed: {resp.status}")
                return await resp.read()
    except Exception as e:
        logger.error(f"Failed to download remote file {url}: {e}")
        return None


def _build_preview_photo_bytes(image_bytes: bytes, max_photo_size: int = 10 * 1024 * 1024) -> bytes | None:
    if not image_bytes:
        return None
    if len(image_bytes) <= max_photo_size:
        return image_bytes

    try:
        from io import BytesIO
        from PIL import Image

        with Image.open(BytesIO(image_bytes)) as img:
            img = img.convert("RGB")
            max_side = 2048
            if max(img.size) > max_side:
                img.thumbnail((max_side, max_side))

            for quality in (92, 85, 78, 70, 62, 55):
                out = BytesIO()
                img.save(out, format="JPEG", quality=quality, optimize=True)
                data = out.getvalue()
                if len(data) <= max_photo_size:
                    logger.info(
                        "Built preview photo bytes: original=%s preview=%s quality=%s",
                        len(image_bytes),
                        len(data),
                        quality,
                    )
                    return data

            out = BytesIO()
            img.save(out, format="JPEG", quality=45, optimize=True)
            data = out.getvalue()
            logger.info(
                "Built oversized fallback preview photo bytes: original=%s preview=%s",
                len(image_bytes),
                len(data),
            )
            return data if data else None
    except Exception as e:
        logger.error(f"Failed to build preview photo bytes: {e}")
        return None


def _guess_result_filename(result_url: str, fallback_base: str = "original") -> str:
    from urllib.parse import urlparse
    parsed = urlparse(str(result_url or ""))
    name = Path(parsed.path).name or fallback_base
    if "." not in name:
        name = f"{name}.png"
    return name


async def _send_original_file(bot_instance: Bot, telegram_id: int, result_url: str, image_bytes: bytes | None = None) -> None:
    if not result_url:
        return
    filename = _guess_result_filename(result_url)
    try:
        if image_bytes:
            await bot_instance.send_document(
                chat_id=telegram_id,
                document=types.BufferedInputFile(image_bytes, filename=filename),
                caption="📎 Исходник файлом",
            )
            return
        await bot_instance.send_document(
            chat_id=telegram_id,
            document=result_url,
            caption="📎 Исходник файлом",
        )
    except Exception as e:
        logger.error(f"Failed to send original file to {telegram_id}: {e}")


def _should_send_prompt_followup(task, caption_prompt_threshold: int = 650) -> bool:
    return bool(_extract_used_prompt(task))


def _format_named_links(urls: list[str], label: str) -> str:
    if not urls:
        return ""
    parts = []
    for idx, url in enumerate(urls, start=1):
        safe_url = html.escape(url, quote=True)
        parts.append(f"<a href='{safe_url}'>#{idx}</a>")
    return f"{label}: " + ", ".join(parts)


def _get_task_resolution(task) -> str:
    request_data = _extract_task_request_data(task)
    for key in ("resolution", "quality"):
        value = request_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _get_task_mode_label(task, reference_urls: list[str]) -> str:
    task_type = str(getattr(task, "type", "") or "").lower()
    if task_type == "video":
        return "Изображение → Видео" if reference_urls else "Текст → Видео"
    return "Изображение → Изображение" if reference_urls else "Текст → Изображение"


async def _send_used_prompt_message(bot_instance: Bot, telegram_id: int, task, result_url: str | None = None) -> None:
    prompt = (_extract_used_prompt(task) or "").strip()
    if not prompt:
        return

    result_urls = [result_url] if result_url else []
    source_urls = _extract_reference_image_urls(task)
    model_label = _get_task_model_label(getattr(task, "model", None), getattr(task, "type", None))
    mode_label = _get_task_mode_label(task, source_urls)
    resolution = _get_task_resolution(task)

    header_lines = [
        "✅ <b>Готово!</b>",
        "",
        f"ID: <code>{html.escape(str(getattr(task, 'task_id', '')))}</code>",
        "",
        f"Модель: <b>{html.escape(model_label)}</b>",
        f"Режим: {html.escape(mode_label)}",
    ]
    if getattr(task, "aspect_ratio", None):
        header_lines.append(f"Формат: {html.escape(str(task.aspect_ratio).replace(':', '∶'))}")
    if resolution:
        header_lines.append(f"Разрешение: {html.escape(resolution)}")
    if getattr(task, "cost", None) is not None:
        header_lines.append(f"Списано: <b>{html.escape(str(task.cost))}</b>")

    link_lines = []
    result_line = _format_named_links(result_urls, "Результат")
    if result_line:
        link_lines.append(result_line)
    source_line = _format_named_links(source_urls, "Исходники")
    if source_line:
        link_lines.append(source_line)

    prefix = "\n".join(header_lines)
    if link_lines:
        prefix += "\n\n" + "\n\n".join(link_lines)
    prefix += "\n\nПромпт:\n"

    def make_block(chunk: str) -> str:
        return f"<blockquote expandable><code>{html.escape(chunk)}</code></blockquote>"

    max_chars = 3900
    first_budget = max_chars - len(prefix) - 80
    if first_budget < 400:
        first_budget = 400

    if len(prompt) <= first_budget:
        await bot_instance.send_message(
            chat_id=telegram_id,
            text=prefix + make_block(prompt),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    first_chunk = prompt[:first_budget]
    await bot_instance.send_message(
        chat_id=telegram_id,
        text=prefix + make_block(first_chunk),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    rest = prompt[first_budget:]
    chunk_size = 3200
    chunks = [rest[i:i + chunk_size] for i in range(0, len(rest), chunk_size)]
    for idx, chunk in enumerate(chunks, start=2):
        await bot_instance.send_message(
            chat_id=telegram_id,
            text=f"Промпт (продолжение {idx}):\n" + make_block(chunk),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


def _collect_http_urls(value) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.startswith(("http://", "https://")):
            urls.append(candidate)
        return urls
    if isinstance(value, dict):
        for key in ("url", "file_url", "public_url", "source_url"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip().startswith(("http://", "https://")):
                urls.append(candidate.strip())
        for nested in value.values():
            urls.extend(_collect_http_urls(nested))
        return urls
    if isinstance(value, (list, tuple, set)):
        for item in value:
            urls.extend(_collect_http_urls(item))
    return urls


def _normalize_reference_key(url: str) -> str:
    candidate = str(url or "").strip().split("?")[0].rstrip("/")
    name = candidate.rsplit("/", 1)[-1]
    if name.startswith("refs_image_"):
        parts = name.split("_", 4)
        if len(parts) >= 5:
            name = parts[-1]
    return name.lower()


def _score_reference_url(url: str) -> tuple[int, int]:
    candidate = str(url or "")
    score = 0
    if "tanyapi.chillcreative.ru/uploads/refs/" in candidate:
        score += 20
    if "tempfile.redpandaai.co" in candidate:
        score -= 5
    if candidate.startswith("https://"):
        score += 1
    return (score, -len(candidate))


def _dedupe_urls(urls: list[str], limit: int = 6) -> list[str]:
    best_by_key: dict[str, str] = {}
    for raw in urls:
        url = str(raw or "").strip()
        if not url:
            continue
        key = _normalize_reference_key(url)
        prev = best_by_key.get(key)
        if prev is None or _score_reference_url(url) > _score_reference_url(prev):
            best_by_key[key] = url

    result = sorted(best_by_key.values(), key=lambda item: (_normalize_reference_key(item), item))
    return result[:limit]

def _extract_reference_image_urls(task=None, webhook_data: dict | None = None) -> list[str]:
    urls: list[str] = []
    request_data = _extract_task_request_data(task)
    for key in (
        "reference_images",
        "image_urls",
        "image_input",
        "input_urls",
        "first_frame_url",
        "last_frame_url",
        "reference_image_urls",
        "image_url",
    ):
        urls.extend(_collect_http_urls(request_data.get(key)))

    if webhook_data:
        try:
            param_str = webhook_data.get("param", "{}")
            param_json = json.loads(param_str) if isinstance(param_str, str) else (param_str or {})
            input_str = param_json.get("input", "{}")
            input_json = json.loads(input_str) if isinstance(input_str, str) else (input_str or {})
            for key in (
                "image_urls",
                "image_input",
                "input_urls",
                "first_frame_url",
                "last_frame_url",
                "reference_image_urls",
                "image_url",
            ):
                urls.extend(_collect_http_urls(input_json.get(key)))
        except Exception:
            pass

    return _dedupe_urls(urls, limit=4)


def _format_reference_links(urls: list[str]) -> str:
    return ""


def _sanitize_base_caption(base_caption: str) -> str:
    base = str(base_caption or "").strip()
    for marker in ("\n\n🎯", "🎯 Промпт:", "🎯 <b>Промпт</b>", "\n🖼 <b>Рефы:</b>"):
        idx = base.find(marker)
        if idx != -1:
            base = base[:idx].rstrip()
    return base


def _with_original_link(base_caption: str, result_url: str | None) -> str:
    base = str(base_caption or "").strip()
    if not result_url:
        return base
    if "Открыть оригинал" in base or "Скачать оригинал" in base:
        return base
    safe_url = html.escape(str(result_url), quote=True)
    return f"{base}\n\n🔗 <a href='{safe_url}'>Открыть оригинал</a>"


def _html_fragment(value, limit: int | None = None) -> str:
    text = "" if value is None else str(value)
    if limit is not None and len(text) > limit:
        text = text[:limit]
    return html.escape(text)


def _build_plain_result_link_text(
    *,
    media_label: str,
    model_label: str,
    task_id: str,
    result_url: str,
    notice: str | None = None,
) -> str:
    lines = [
        f"{media_label} готово.",
        f"Модель: {model_label or 'AI'}",
        f"ID: {task_id}",
        "",
        notice or "Telegram не смог прикрепить файл автоматически.",
        "Оригинал можно открыть по ссылке:",
        str(result_url),
    ]
    text = "\n".join(lines)
    return text[:4000]


async def _send_plain_result_link(
    bot_instance: Bot,
    telegram_id: int,
    *,
    media_label: str,
    model_label: str,
    task_id: str,
    result_url: str,
    reply_markup=None,
    notice: str | None = None,
) -> None:
    await bot_instance.send_message(
        chat_id=telegram_id,
        text=_build_plain_result_link_text(
            media_label=media_label,
            model_label=model_label,
            task_id=task_id,
            result_url=result_url,
            notice=notice,
        ),
        reply_markup=reply_markup,
        disable_web_page_preview=False,
    )


def _build_failure_notification_text(
    *,
    service_name: str,
    task_id: str,
    reason: str | None,
    media_kind: str = "результата",
    refund_text: str = "",
) -> str:
    safe_reason = _html_fragment(reason or "сервис не смог обработать запрос", limit=700)
    return (
        f"Не удалось завершить генерацию {media_kind}.\n"
        f"• Модель: <code>{_html_fragment(service_name or 'AI')}</code>\n"
        f"• ID: <code>{_html_fragment(task_id)}</code>\n"
        f"• Причина: <code>{safe_reason}</code>"
        f"{refund_text}"
    )


def _build_single_result_caption(base_caption: str, task, reference_urls: list[str] | None = None, max_length: int = 980) -> str:
    return _sanitize_base_caption(base_caption)[:max_length]


async def _send_reference_preview(bot_instance: Bot, telegram_id: int, urls: list[str]) -> None:
    return

def _is_retryable_kie_blank_task_failure(fail_code, fail_msg) -> bool:
    return str(fail_code) == "422" and "task id is blank" in str(fail_msg or "").lower()


def _is_retryable_kie_timeout_failure(task, fail_code, fail_msg) -> bool:
    if not task or getattr(task, "type", None) != "image":
        return False
    model_name = str(getattr(task, "model", "") or "").strip()
    if model_name not in {"banana_pro", "nanobanana", "banana_2", "seedream_edit"}:
        return False
    normalized = str(fail_msg or "").lower()
    retryable_markers = (
        "timed out",
        "timeout while downloading",
        "timeout downloading",
        "no results were returned",
    )
    return str(fail_code) == "500" and any(marker in normalized for marker in retryable_markers)


def _is_retryable_wan_timeout_failure(task, fail_code, fail_msg) -> bool:
    if not task or getattr(task, "type", None) != "image":
        return False
    model_name = str(getattr(task, "model", "") or "").strip()
    if model_name != "wan_27":
        return False
    return str(fail_code) == "500" and "timed out" in str(fail_msg or "").lower()


async def _retry_transient_wan_timeout_failure(task, failed_task_id: str) -> str | None:
    if not task or getattr(task, "type", None) != "image":
        return None

    request_data = _extract_task_request_data(task)
    retry_attempt = int(request_data.get("auto_retry_attempt") or 0)
    if retry_attempt >= 1:
        return None

    prompt = (
        request_data.get("effective_prompt")
        or request_data.get("prompt")
        or getattr(task, "prompt", None)
    )
    if not prompt:
        return None

    from bot.services.wan27_service import wan27_service

    reference_images = request_data.get("reference_images") or []
    img_ratio = request_data.get("img_ratio") or getattr(task, "aspect_ratio", None) or "1:1"
    callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None
    result = await wan27_service.generate_image(
        prompt=prompt,
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

    new_task_id = result.get("task_id") if isinstance(result, dict) else None
    if not new_task_id or new_task_id == failed_task_id:
        return None

    retry_request_data = dict(request_data)
    retry_request_data["auto_retry_attempt"] = retry_attempt + 1
    retry_request_data["last_auto_retry_from_task_id"] = failed_task_id

    import aiosqlite
    from bot.database import DATABASE_PATH

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE generation_tasks SET task_id = ?, request_data = ?, status = 'pending', updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND user_id = ?",
            (new_task_id, json.dumps(retry_request_data, ensure_ascii=False), failed_task_id, task.user_id),
        )
        await db.commit()

    logger.warning(
        "Auto-retried Wan timeout failure: old_task_id=%s new_task_id=%s attempt=%s",
        failed_task_id,
        new_task_id,
        retry_attempt + 1,
    )
    return new_task_id


async def _retry_transient_kie_image_failure(task, failed_task_id: str) -> str | None:
    if not task or getattr(task, "type", None) != "image":
        return None

    request_data = _extract_task_request_data(task)
    runtime_img_service = (
        request_data.get("img_service") or getattr(task, "model", None) or ""
    ).strip()
    if runtime_img_service not in {"banana_pro", "nanobanana", "banana_2", "seedream_edit"}:
        return None

    retry_attempt = int(request_data.get("auto_retry_attempt") or 0)
    if retry_attempt >= 1:
        return None

    effective_prompt = (
        request_data.get("effective_prompt")
        or request_data.get("prompt")
        or getattr(task, "prompt", None)
    )
    if not effective_prompt:
        return None

    reference_images = request_data.get("reference_images") or []
    img_ratio = request_data.get("img_ratio") or getattr(task, "aspect_ratio", None) or "1:1"
    callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None

    if runtime_img_service == "seedream_edit":
        from bot.services.seedream_service import seedream_service

        result = await seedream_service.generate_image(
            prompt=effective_prompt,
            model="seedream/4.5-edit",
            aspect_ratio=img_ratio,
            image_urls=reference_images,
            quality=str(request_data.get("img_quality") or "basic"),
            nsfw_checker=False,
            callBackUrl=callback_url,
        )
    elif runtime_img_service == "banana_2":
        from bot.services.nano_banana_2_service import nano_banana_2_service

        result = await nano_banana_2_service.generate_image(
            prompt=effective_prompt,
            aspect_ratio=img_ratio,
            resolution=str(request_data.get("img_quality") or "2K").upper(),
            image_input=reference_images,
            callback_url=callback_url,
        )
    else:
        from bot.services.nano_banana_pro_service import nano_banana_pro_service

        result = await nano_banana_pro_service.generate_image(
            prompt=effective_prompt,
            aspect_ratio=img_ratio,
            resolution=str(request_data.get("img_quality") or "2K").upper(),
            image_input=reference_images,
            callback_url=callback_url,
        )

    new_task_id = result.get("task_id") if isinstance(result, dict) else None
    if not new_task_id or new_task_id == failed_task_id:
        return None

    retry_request_data = dict(request_data)
    retry_request_data["auto_retry_attempt"] = retry_attempt + 1
    retry_request_data["last_auto_retry_from_task_id"] = failed_task_id

    import aiosqlite
    from bot.database import DATABASE_PATH

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE generation_tasks SET task_id = ?, request_data = ?, status = 'pending', updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND user_id = ?",
            (new_task_id, json.dumps(retry_request_data, ensure_ascii=False), failed_task_id, task.user_id),
        )
        await db.commit()

    logger.warning(
        "Auto-retried transient KIE image failure: old_task_id=%s new_task_id=%s model=%s attempt=%s",
        failed_task_id,
        new_task_id,
        runtime_img_service,
        retry_attempt + 1,
    )
    return new_task_id


async def _remove_old_files(
    base_dir: str,
    max_age_seconds: int,
    *,
    skip_filenames: set[str] | None = None,
    skip_dirnames: set[str] | None = None,
):
    """Удаляет файлы старше max_age_seconds в каталоге base_dir (рекурсивно)."""
    try:
        now = time.time()
        if not os.path.exists(base_dir):
            return
        skip_filenames = skip_filenames or set()
        skip_dirnames = skip_dirnames or set()

        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [name for name in dirs if name not in skip_dirnames]
            for name in files:
                if name in skip_filenames:
                    continue
                path = os.path.join(root, name)
                try:
                    mtime = os.path.getmtime(path)
                    if now - mtime > max_age_seconds:
                        os.remove(path)
                        logger.info(f"Removed old file: {path}")
                except Exception:
                    logger.exception(f"Failed to remove file: {path}")

            # После обработки файлов: если папка пуста — удаляем её
            try:
                if not os.listdir(root):
                    os.rmdir(root)
                    logger.info(f"Removed empty dir: {root}")
            except Exception as e:
                # Игнорируем ошибки удаления каталогов
                pass
    except Exception:
        logger.exception("Error during cleanup for %s", base_dir)


async def _cleanup_loop():
    """Фоновая задача, очищающая временные файлы и старые логи раз в 24 часа."""
    while True:
        try:
            await _remove_old_files(
                "static/uploads",
                max_age_seconds=UPLOAD_RETENTION_SECONDS,
                skip_filenames=set(),
                skip_dirnames={"refs"},
            )
            await _remove_old_files(
                "logs",
                max_age_seconds=LOG_RETENTION_SECONDS,
                skip_filenames=ACTIVE_LOG_FILENAMES,
            )
            pruned_refs = await cleanup_saved_references()
            orphaned_refs = await cleanup_orphaned_reference_files(
                max_age_seconds=UPLOAD_RETENTION_SECONDS
            )
            stale_tasks = await cleanup_stale_local_generation_tasks()
            if pruned_refs or orphaned_refs["removed_count"]:
                logger.info(
                    "Reference cleanup removed db_rows=%s orphan_files=%s orphan_bytes=%s",
                    pruned_refs,
                    orphaned_refs["removed_count"],
                    orphaned_refs["removed_bytes"],
                )
            if stale_tasks["failed_count"]:
                logger.info("Stale local generation cleanup stats: %s", stale_tasks)
        except Exception:
            logger.exception("Cleanup iteration failed")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


async def on_startup(bot: Bot):
    """Действия при старте бота"""
    logger.info("Bot starting...")

    # База данных уже инициализирована в main() функции
    logger.info("Database already initialized")

    try:
        for scope in USER_BOT_COMMAND_SCOPES:
            for language_code in USER_BOT_COMMAND_LANGUAGES:
                await bot.set_my_commands(
                    USER_BOT_COMMANDS,
                    scope=scope,
                    language_code=language_code,
                )
        logger.info(
            "Registered user bot commands: %s",
            ", ".join(f"/{command.command}" for command in USER_BOT_COMMANDS),
        )
    except Exception:
        logger.exception("Failed to register user bot commands")

    try:
        await redis_service.get_client()
    except Exception:
        logger.exception("Redis warmup failed during startup")

    # Устанавливаем вебхук для Telegram (если используем webhook mode)
    if config.WEBHOOK_HOST:
        await bot.set_webhook(config.webhook_url)
        logger.info(f"Webhook set to {config.webhook_url}")

    # Загружаем пресеты
    preset_manager.load_all()
    logger.info(f"Loaded {len(preset_manager._presets)} presets")

    try:
        cleanup_stats = await cleanup_stale_cryptobot_pending()
        logger.info("Startup payment cleanup stats: %s", cleanup_stats)
    except Exception:
        logger.exception("Failed startup cleanup for stale CryptoBot pending transactions")

    try:
        reconcile_stats = await yookassa_service.poll_pending_transactions(
            limit=YOOKASSA_RECONCILE_BATCH_SIZE
        )
        logger.info("Startup YooKassa reconcile stats: %s", reconcile_stats[:10])
    except Exception:
        logger.exception("Failed startup YooKassa reconciliation")

    try:
        stale_task_stats = await cleanup_stale_local_generation_tasks()
        logger.info("Startup stale local generation cleanup stats: %s", stale_task_stats)
    except Exception:
        logger.exception("Failed startup cleanup for stale local generation tasks")

    # Запускаем фоновую очистку static/uploads и старых логов раз в 24 часа
    try:
        # aiogram.Bot does not expose an event loop attribute in some versions.
        # Use asyncio.create_task to schedule background tasks on the running loop.
        asyncio.create_task(_cleanup_loop())
        asyncio.create_task(_yookassa_reconcile_loop())
        logger.info(
            "Scheduled cleanup task for static/uploads/logs and YooKassa reconciliation"
        )
    except Exception:
        logger.exception("Failed to schedule background tasks")


async def on_shutdown(bot: Bot):
    """Действия при остановке"""
    logger.info("Bot shutting down...")
    try:
        from bot.services.cryptobot_service import cryptobot_service

        await cryptobot_service.close()
    except Exception:
        logger.exception("Failed to close CryptoBot session")

    try:
        from bot.services.lava_service import lava_service

        await lava_service.close()
    except Exception:
        logger.exception("Failed to close Lava session")

    try:
        await redis_service.close()
    except Exception:
        logger.exception("Failed to close Redis client")
    await bot.delete_webhook()
    await bot.session.close()


async def errors_handler(event: types.ErrorEvent):
    """Глобальный обработчик ошибок"""
    error = event.exception

    # Обработка ошибок Telegram API
    if isinstance(error, TelegramBadRequest):
        error_msg = str(error).lower()
        if "chat not found" in error_msg:
            logger.warning(
                f"Chat not found error (user deleted chat or blocked bot): {error}"
            )
            return True
        elif "bot was blocked" in error_msg:
            logger.warning(f"Bot was blocked by user: {error}")
            return True
        elif "user is deactivated" in error_msg:
            logger.warning(f"User is deactivated: {error}")
            return True
        elif "message is not modified" in error_msg:
            return True
        elif "query is too old" in error_msg or "query id is invalid" in error_msg:
            logger.info(f"Ignoring stale callback query error: {error}")
            return True

    # Логируем другие ошибки
    logger.exception(f"Unhandled error: {error}")
    return True


def setup_dispatcher() -> Dispatcher:
    """Настройка диспетчера с роутерами"""
    dp = Dispatcher(storage=_build_dispatcher_storage())

    # Регистрируем глобальный обработчик ошибок
    dp.errors.register(errors_handler)
    access_guard = AccessGuardMiddleware()
    dp.message.outer_middleware(access_guard)
    dp.callback_query.outer_middleware(access_guard)

    # ⭐ КРИТИЧЕСКИ ВАЖНО: Порядок роутеров в aiogram 3.x
    # Первый зарегистрированный роутер имеет НАИВЫСШИЙ приоритет!
    # Сообщение передаётся ВСЕМ роутерам одновременно, но обрабатывается
    # тем, у кого более специфичный фильтр (например, StateFilter)
    #
    # Правильный порядок:
    # 1. generation_router (FSM состояния - самые специфичные)
    # 2. admin_router (админ команды)
    # 3. payments_router (платежи)
    # 4. batch_generation_router (пакетная генерация)
    # 5. common_router (общие команды /start /help - самые общие)

    dp.include_router(generation_router)  # FSM состояния - ПЕРВЫЙ!
    dp.include_router(image_analyzer_router)  # Анализ фото в промпт
    dp.include_router(admin_router)  # Админ-команды
    dp.include_router(payments_router)  # Платежи
    dp.include_router(batch_generation_router)  # Пакетная генерация
    dp.include_router(common_router)  # Общие команды - ПОСЛЕДНИЙ!

    return dp


async def handle_telegram_webhook(
    request: web.Request, bot: Bot, dp: Dispatcher
) -> web.Response:
    """Обработчик вебхука от Telegram"""
    try:
        raw_body = await request.read()
        if not raw_body:
            logger.warning("Telegram webhook received empty body")
            return web.Response(text="OK", status=200)

        try:
            update_data = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as decode_error:
            logger.warning(f"Telegram webhook received invalid JSON: {decode_error}")
            return web.Response(text="OK", status=200)

        # Создаём объект Update
        update = Update(**update_data)

        async def _process_update():
            try:
                await dp.feed_webhook_update(bot, update)
            except TelegramBadRequest as e:
                error_msg = str(e).lower()
                if (
                    "chat not found" in error_msg
                    or "bot was blocked" in error_msg
                    or "user is deactivated" in error_msg
                ):
                    logger.warning(f"Chat error (safe to ignore): {e}")
                    return
                if "query is too old" in error_msg or "query id is invalid" in error_msg:
                    logger.info(f"Ignoring stale callback query in background task: {e}")
                    return
                logger.exception(f"Telegram API error in background task: {e}")
            except Exception as e:
                logger.exception(f"Webhook background task error: {e}")

        # Сразу отвечаем Telegram, а обработку уводим в фон,
        # чтобы длинные операции не вызывали повторную доставку update.
        asyncio.create_task(_process_update())

        return web.Response(text="OK", status=200)
    except TelegramBadRequest as e:
        # Ошибки Telegram API (chat not found, user blocked bot, etc.)
        # Возвращаем 200, чтобы Telegram не повторял запрос
        error_msg = str(e).lower()
        if (
            "chat not found" in error_msg
            or "bot was blocked" in error_msg
            or "user is deactivated" in error_msg
        ):
            logger.warning(f"Chat error (safe to ignore): {e}")
            return web.Response(text="OK", status=200)
        logger.exception(f"Telegram API error: {e}")
        return web.Response(text="Bad Request", status=200)
    except Exception as e:
        logger.exception(f"Webhook error: {e}")
        # Возвращаем 200 даже при ошибках, чтобы Telegram не спамил
        return web.Response(text="OK", status=200)


async def handle_kling_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от Kling/PiAPI/Replicate/Kie.ai"""
    try:
        # Verify Replicate webhook signature if configured
        from bot.config import config as _config

        def _verify_replicate_signature(
            secret: str, body: bytes, headers: dict
        ) -> bool:
            """Verify HMAC SHA256 signature using common header names."""
            if not secret:
                return True
            import hashlib
            import hmac

            body_bytes = (
                body if isinstance(body, (bytes, bytearray)) else body.encode("utf-8")
            )

            candidates = [
                headers.get("x-replicate-signature"),
                headers.get("x-signature"),
                headers.get("replicate-signature"),
                headers.get("signature"),
                headers.get("webhook-signature"),
            ]

            secret_bytes = secret.encode("utf-8")

            for sig in candidates:
                if not sig:
                    continue

                sig_str = sig if isinstance(sig, str) else str(sig)
                parts = [p.strip() for p in sig_str.split(",") if p.strip()]
                sig_candidate = parts[-1]

                if sig_candidate.startswith("sha256="):
                    sig_val = sig_candidate.split("=", 1)[1]
                elif sig_candidate.startswith("v1="):
                    sig_val = sig_candidate.split("=", 1)[1]
                else:
                    sig_val = sig_candidate

                try:
                    computed_hex = hmac.new(
                        secret_bytes, body_bytes, hashlib.sha256
                    ).hexdigest()
                    if hmac.compare_digest(computed_hex, sig_val):
                        return True
                except Exception as e:
                    pass

            return False

        # Read raw body for verification
        raw_body = await request.read()
        if not _verify_replicate_signature(
            _config.REPLICATE_WEBHOOK_SECRET, raw_body, dict(request.headers)
        ):
            logger.warning(
                "Rejected Kling webhook: replicate signature verification failed"
            )
            return web.Response(status=200)

        # Логируем все заголовки для отладки
        logger.info(f"Kling webhook headers: {dict(request.headers)}")

        # Проверяем, есть ли данные в теле запроса
        if not raw_body:
            logger.warning("Kling webhook received empty body")
            return web.Response(status=200)

        try:
            body_text = raw_body.decode("utf-8")
            logger.info("Kling webhook raw body: %s", _preview_log_payload(body_text))
            data = json.loads(body_text)
        except Exception as e:
            logger.warning(f"Kling webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info("Kling webhook parsed data: %s", _preview_log_payload(data))

        # Kling specific format: {'code': 200, 'data': {'result_video_url': '...'}, 'msg': '...', 'taskId': '...'}
        if "code" in data and data.get("code") == 200 and "taskId" in data:
            task_id = data["taskId"]
            video_url = data["data"].get("result_video_url")
            if task_id and video_url:
                from bot.database import (
                    complete_video_task,
                    get_task_by_id,
                )
                from bot.keyboards import get_video_result_keyboard

                task = await get_task_by_id(task_id)
                model_display = task.model if task and task.model else "Kling"
                if model_display == "aleph":
                    model_display = "Aleph Video"
                elif model_display == "glow":
                    model_display = "Kling Glow"
                logger.info(
                    f"{model_display} success webhook: task {task_id}, video {video_url[:50]}..."
                )
                if task:
                    reference_preview_urls = _extract_reference_image_urls(task, data.get("data"))
                    telegram_id = await _resolve_task_telegram_id(
                        task, context="kling_success_code200"
                    )
                    if telegram_id:
                        bot_instance = Bot(token=config.BOT_TOKEN)
                        try:
                            caption = f"✅ <b>Видео ({_html_fragment(model_display)}) готово!</b>\\n\\nID: <code>{_html_fragment(task_id)}</code>"
                            if task.duration:
                                caption += f"\\n⏱ <code>{_html_fragment(task.duration)}с</code>"
                            if task.aspect_ratio:
                                caption += f"\\n📐 <code>{_html_fragment(task.aspect_ratio)}</code>"
                            if task.cost:
                                caption += f"\\n💰 <code>{_html_fragment(task.cost)}🍌</code>"
                            if task.preset_id == "no_preset" and task.prompt:
                                prompt_preview = _html_fragment(
                                    f"{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}"
                                )
                                caption += f"\\n\\n🎯 Промпт: <code>{prompt_preview}</code>"
                            else:
                                caption += f"\\n\\n🎯 Пресет: {_html_fragment(task.preset_id)}"
                            video_kb = get_video_result_keyboard(
                                video_url,
                                task_id=task_id,
                                model=task.model if task else model_display,
                                is_public_feed=task.is_public_feed if task else False,
                            )

                            delivered = False
                            try:
                                await bot_instance.send_video(
                                    chat_id=telegram_id,
                                    video=video_url,
                                    caption=_build_single_result_caption(_with_original_link(caption, video_url), task, reference_preview_urls),
                                    parse_mode="HTML",
                                    supports_streaming=True,
                                    reply_markup=video_kb,
                                )
                                delivered = True
                            except Exception as send_e:
                                logger.error(
                                    f"Failed to send {model_display} video media to {telegram_id}: {send_e}"
                                )
                                try:
                                    await _send_plain_result_link(
                                        bot_instance,
                                        telegram_id,
                                        media_label="Видео",
                                        model_label=model_display,
                                        task_id=task_id,
                                        result_url=video_url,
                                        reply_markup=video_kb,
                                    )
                                    delivered = True
                                except Exception as link_e:
                                    logger.error(
                                        f"Failed to send {model_display} video link to {telegram_id}: {link_e}"
                                    )
                            await complete_video_task(task_id, video_url)
                            if delivered:
                                logger.info(f"{model_display} video sent to {telegram_id}")
                            else:
                                logger.warning(
                                    f"{model_display} result stored but Telegram delivery failed for {telegram_id}"
                                )
                        except Exception as e:
                            logger.error(
                                f"Failed to notify {model_display} user {telegram_id}: {e}"
                            )
                        finally:
                            await bot_instance.session.close()
                return web.Response(status=200)

        # Detect Kie.ai format (code:200/501, data.taskId, data.resultJson or failMsg)
        if "code" in data and "data" in data:
            kie_data = data["data"]
            task_id = kie_data.get("taskId")
            status = kie_data.get("state", "").lower()
            result_json_str = kie_data.get("resultJson", "{}")
            fail_code = kie_data.get("failCode")
            fail_msg = kie_data.get("failMsg", "")
            try:
                result_json = json.loads(result_json_str)
                video_url = result_json.get("resultUrls", [None])[0]
            except (json.JSONDecodeError, KeyError):
                video_url = None

            if task_id:
                from bot.database import (
                    add_credits,
                    complete_video_task,
                    get_task_by_id,
                )

                task = await get_task_by_id(task_id)
                model_display = _get_task_model_label(
                    task.model if task else None,
                    task.type if task else None,
                )
                logger.info(
                    f"{model_display} webhook: task {task_id}, status {status}, "
                    + f"video {video_url[:50] if video_url else None}..., "
                    + f"fail: {fail_code}/{fail_msg[:50]}..."
                )
                if task:
                    reference_preview_urls = _extract_reference_image_urls(task, kie_data)
                    telegram_id = await _resolve_task_telegram_id(
                        task, context="kie_legacy"
                    )
                    if telegram_id:
                        bot_instance = Bot(token=config.BOT_TOKEN)
                        try:
                            if status in {"success", "completed"} and video_url:
                                # Success case
                                model_display = _get_task_model_label(
                                    task.model, task.type
                                )
                                caption = (
                                    f"✅ <b>{'Видео' if task.type == 'video' else 'Изображение'} готово</b>\n"
                                    f"• Модель: <code>{_html_fragment(model_display)}</code>\n"
                                    f"• ID: <code>{_html_fragment(task_id)}</code>"
                                )
                                if task.duration:
                                    caption += f"\n• Длительность: <code>{_html_fragment(task.duration)}с</code>"
                                if task.aspect_ratio:
                                    caption += f"\n• Формат: <code>{_html_fragment(str(task.aspect_ratio).replace(':', '∶'))}</code>"
                                if task.cost:
                                    caption += (
                                        f"\n• Стоимость: <code>{_html_fragment(task.cost)}🍌</code>"
                                    )
                                if task.preset_id == "no_preset" and task.prompt:
                                    prompt_preview = _html_fragment(
                                        f"{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}"
                                    )
                                    caption += (
                                        f"\n\n🎯 <b>Промпт</b>\n"
                                        f"<code>{prompt_preview}</code>"
                                    )
                                else:
                                    caption += f"\n\n🎯 <b>Пресет</b>\n<code>{_html_fragment(task.preset_id)}</code>"
                                import os

                                # Отправляем видео - всегда скачиваем для Kie.ai
                                import tempfile

                                import aiohttp
                                from aiogram.types import FSInputFile

                                from bot.keyboards import get_video_result_keyboard

                                video_kb = get_video_result_keyboard(
                                    video_url,
                                    task_id=task_id,
                                    model=task.model if task else model_display,
                                    is_public_feed=task.is_public_feed if task else False,
                                )
                                delivered = False
                                tmp_file = None
                                try:
                                    async with aiohttp.ClientSession() as sess:
                                        headers = {
                                            "User-Agent": "Mozilla/5.0 (compatible; Telegram Bot SDK/1.0)",
                                            "Accept": "*/*",
                                        }
                                        async with sess.get(
                                            video_url,
                                            headers=headers,
                                            timeout=aiohttp.ClientTimeout(total=120),
                                        ) as resp:
                                            if resp.status != 200:
                                                raise RuntimeError(
                                                    f"Download failed: status {resp.status}"
                                                )
                                            tmp = tempfile.NamedTemporaryFile(
                                                delete=False, suffix=".mp4"
                                            )
                                            tmp_file = tmp.name
                                            with open(tmp_file, "wb") as f:
                                                async for (
                                                    chunk
                                                ) in resp.content.iter_chunked(
                                                    1024 * 64
                                                ):
                                                    if chunk:
                                                        f.write(chunk)
                                    video_file = FSInputFile(tmp_file)
                                    await bot_instance.send_video(
                                        chat_id=telegram_id,
                                        video=video_file,
                                        caption=_build_single_result_caption(_with_original_link(caption, video_url), task, reference_preview_urls),
                                        parse_mode="HTML",
                                        supports_streaming=True,
                                        reply_markup=video_kb,
                                    )
                                    delivered = True
                                    logger.info(
                                        f"Kie.ai video downloaded and sent to {telegram_id}"
                                    )
                                except Exception as dl_e:
                                    logger.error(
                                        f"Kie.ai video download failed: {dl_e}"
                                    )
                                    # Fallback to URL
                                    try:
                                        await bot_instance.send_video(
                                            chat_id=telegram_id,
                                            video=video_url,
                                            caption=_build_single_result_caption(_with_original_link(caption, video_url), task, reference_preview_urls),
                                            parse_mode="HTML",
                                            supports_streaming=True,
                                            reply_markup=video_kb,
                                        )
                                        delivered = True
                                        logger.info(
                                            f"Kie.ai video sent via URL to {telegram_id}"
                                        )
                                    except Exception as url_e:
                                        logger.error(
                                            f"Kie.ai video URL send failed: {url_e}"
                                        )
                                        try:
                                            await _send_plain_result_link(
                                                bot_instance,
                                                telegram_id,
                                                media_label="Видео",
                                                model_label=model_display,
                                                task_id=task_id,
                                                result_url=video_url,
                                                reply_markup=video_kb,
                                                notice=(
                                                    "Telegram не смог прикрепить видео файлом "
                                                    "из-за ограничения размера."
                                                ),
                                            )
                                            delivered = True
                                            logger.info(
                                                f"Kie.ai video link sent to {telegram_id}"
                                            )
                                        except Exception as link_e:
                                            logger.error(
                                                f"Kie.ai video link fallback failed: {link_e}"
                                            )
                                finally:
                                    if tmp_file and os.path.exists(tmp_file):
                                        try:
                                            os.remove(tmp_file)
                                        except Exception:
                                            pass
                                await complete_video_task(task_id, video_url)
                                if delivered:
                                    logger.info(f"Kie.ai result sent to {telegram_id}")
                                else:
                                    logger.warning(
                                        f"Kie.ai result stored but Telegram delivery failed for {telegram_id}"
                                    )
                            else:
                                # Fail case
                                policy_violation = "Prohibited Use policy" in fail_msg
                                error_msg = (
                                    "Запрос не прошёл проверку политики безопасности из-за чувствительного контента."
                                    if policy_violation
                                    else fail_msg[:100]
                                )
                                await add_credits(telegram_id, task.cost or 0)
                                refund_text = "\n\nБананы за эту попытку уже возвращены."
                                await bot_instance.send_message(
                                    chat_id=telegram_id,
                                    text=_build_failure_notification_text(
                                        service_name=model_display,
                                        task_id=task_id,
                                        reason=error_msg,
                                        media_kind=(
                                            "видео"
                                            if task.type == "video"
                                            else "результата"
                                        ),
                                        refund_text=refund_text,
                                    ),
                                    parse_mode="HTML",
                                )
                                await complete_video_task(task_id, None)
                                logger.info(
                                    f"Kie.ai fail notified to {telegram_id}, credits returned"
                                )
                        except Exception as e:
                            logger.error(f"Failed to notify user {telegram_id}: {e}")
                        finally:
                            await bot_instance.session.close()
                return web.Response(status=200)

        # Fallback to PiAPI/Replicate parsing
        webhook_data = data
        task_id = _extract_first(
            webhook_data, ("taskId", "task_id", "id", "prediction_id", "predictionId")
        )
        status = _extract_first(
            webhook_data, ("status", "state", "result", "prediction_status")
        )

        if not task_id:
            logger.error(
                f"Kling webhook missing task id. Top-level keys: {list(data.keys())}, "
                + f"payload: {webhook_data}"
            )
            return web.Response(status=200)

        logger.info(f"Processing Kling task {task_id} with status {status}")

        normalized_status = str(status).lower() if status else ""

        if normalized_status in {"completed", "succeeded", "success", "finished"}:
            # Replicate can return either a direct URL/string or a nested object.
            output = (
                webhook_data.get("output", {}) if isinstance(webhook_data, dict) else {}
            )
            video_url = (
                (output.get("video_url") if isinstance(output, dict) else None)
                or (output.get("video") if isinstance(output, dict) else None)
                or (output if isinstance(output, str) else None)
                or (
                    output.get("works")
                    and output["works"][0]
                    .get("video", {})
                    .get("resource_without_watermark")
                    if isinstance(output, dict)
                    else None
                )
            )

            if not video_url:
                logger.error(f"No video URL in completed task: {webhook_data}")
                return web.Response(status=200)

            logger.info(f"Extracted video URL: {video_url[:50]}...")

            # Находим задачу в БД
            from bot.database import (
                complete_video_task,
                get_task_by_id,
            )

            task = await get_task_by_id(task_id)

            if not task:
                logger.info(
                    "Ignoring orphan webhook for Kling task %s: task not found in database",
                    task_id,
                )
                return web.Response(status=200)

            telegram_id = await _resolve_task_telegram_id(
                task, context="kling_fallback_success"
            )

            if not telegram_id:
                return web.Response(status=200)

            logger.info(
                f"Found task for user {task.user_id}, telegram_id: {telegram_id}, "
                + f"preset: {task.preset_id}"
            )

            model_display = task.model or task.preset_id or "Kling"
            reference_preview_urls = _extract_reference_image_urls(task, webhook_data)
            caption = f"✅ <b>Видео ({_html_fragment(model_display)}) готово!</b>\\n\\nID: <code>{_html_fragment(task_id)}</code>"
            if task.duration:
                caption += f"\\n⏱ <code>{_html_fragment(task.duration)}с</code>"
            if task.aspect_ratio:
                caption += f"\\n📐 <code>{_html_fragment(task.aspect_ratio)}</code>"
            if task.cost:
                caption += f"\\n💰 <code>{_html_fragment(task.cost)}🍌</code>"
            if task.preset_id == "no_preset" and task.prompt:
                prompt_preview = _html_fragment(
                    f"{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}"
                )
                caption += f"\\n\\n🎯 Промпт: <code>{prompt_preview}</code>"
            else:
                caption += f"\\n\\n🎯 Пресет: {_html_fragment(task.preset_id)}"

            # Отправляем видео пользователю
            bot_instance = Bot(token=config.BOT_TOKEN)
            video_kb = None

            try:
                from bot.keyboards import get_video_result_keyboard

                video_kb = get_video_result_keyboard(
                    video_url,
                    task_id=task_id,
                    model=task.model if task else model_display,
                    is_public_feed=task.is_public_feed if task else False,
                )
                await bot_instance.send_video(
                    chat_id=telegram_id,
                    video=video_url,
                    caption=_build_single_result_caption(_with_original_link(caption, video_url), task, reference_preview_urls),
                    parse_mode="HTML",
                    supports_streaming=True,
                    reply_markup=video_kb,
                )

                await complete_video_task(task_id, video_url)
                logger.info(f"Video sent to user {telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send video via URL: {e}")
                # If sending by URL failed (Telegram can't fetch remote file),
                # try to download the file locally and upload it to Telegram.
                try:
                    # Only attempt download for http(s) URLs
                    if isinstance(video_url, str) and video_url.lower().startswith(
                        "http"
                    ):
                        import os
                        import tempfile

                        import aiohttp as _aiohttp

                        logger.info(
                            "Attempting to download video and upload to Telegram as file"
                        )
                        tmp_file = None
                        try:
                            async with _aiohttp.ClientSession() as sess:
                                async with sess.get(video_url, timeout=60) as resp:
                                    if resp.status != 200:
                                        raise RuntimeError(
                                            f"Failed to download video, status={resp.status}"
                                        )
                                    # Create temporary file
                                    tmp = tempfile.NamedTemporaryFile(delete=False)
                                    tmp_file = tmp.name
                                    # Stream write
                                    with open(tmp_file, "wb") as f:
                                        async for chunk in resp.content.iter_chunked(
                                            1024 * 64
                                        ):
                                            if chunk:
                                                f.write(chunk)

                            # Send downloaded file
                            from aiogram.types import FSInputFile

                            video_file = FSInputFile(tmp_file)
                            await bot_instance.send_video(
                                chat_id=telegram_id,
                                video=video_file,
                                caption=_build_single_result_caption(_with_original_link(caption, video_url), task, reference_preview_urls),
                                parse_mode="HTML",
                                supports_streaming=True,
                                reply_markup=video_kb,
                            )

                            await complete_video_task(task_id, video_url)
                            logger.info(
                                f"Video downloaded and sent to user {telegram_id}"
                            )
                        finally:
                            if tmp_file and os.path.exists(tmp_file):
                                try:
                                    os.remove(tmp_file)
                                except Exception as e:
                                    logger.exception(
                                        "Failed to remove temporary video file"
                                    )
                    else:
                        # Fallback — отправляем как ссылка
                        await _send_plain_result_link(
                            bot_instance,
                            telegram_id,
                            media_label="Видео",
                            model_label=model_display,
                            task_id=task_id,
                            result_url=video_url,
                            reply_markup=video_kb,
                        )
                except Exception as fallback_error:
                    logger.error(
                        f"Failed to send fallback message or upload video: {fallback_error}"
                    )
                    try:
                        await _send_plain_result_link(
                            bot_instance,
                            telegram_id,
                            media_label="Видео",
                            model_label=model_display,
                            task_id=task_id,
                            result_url=video_url,
                            reply_markup=video_kb,
                            notice="Telegram не смог прикрепить видео автоматически.",
                        )
                        logger.info(f"Video link sent to user {telegram_id}")
                    except Exception as link_error:
                        logger.error(
                            f"Failed to send fallback video link to {telegram_id}: {link_error}"
                        )
            finally:
                try:
                    await complete_video_task(task_id, video_url)
                except Exception as complete_error:
                    logger.error(f"Failed to store completed video task {task_id}: {complete_error}")
                await bot_instance.session.close()
        else:
            logger.error(f"Kling task {task_id} failed with status: {status}")

            from bot.database import (
                add_credits,
                complete_video_task,
                get_task_by_id,
            )

            task = await get_task_by_id(task_id)
            if task and task.cost:
                telegram_id = await _resolve_task_telegram_id(
                    task, context="kling_failure"
                )
                if telegram_id:
                    bot_instance = Bot(token=config.BOT_TOKEN)
                    try:
                        fail_msg = data.get(
                            "msg", str(status) if status else "Unknown error"
                        )
                        await add_credits(telegram_id, task.cost)
                        refund_text = "\n\nКредиты возвращены."
                        await bot_instance.send_message(
                            chat_id=telegram_id,
                            text=_build_failure_notification_text(
                                service_name="Kling",
                                task_id=task_id,
                                reason=fail_msg,
                                media_kind="видео",
                                refund_text=refund_text,
                            ),
                            parse_mode="HTML",
                        )
                        await complete_video_task(task_id, None)
                        logger.info(f"Kling failure notified to {telegram_id}")
                    except Exception as e:
                        logger.error(
                            f"Failed to notify Kling failure to {telegram_id}: {e}"
                        )
                    finally:
                        await bot_instance.session.close()

            # Check for sensitive content error
            # webhook_data['error'] or webhook_data['logs'] may be dicts (or other types)
            # so convert them to strings safely before concatenation to avoid TypeError
            def _to_str(value):
                if value is None:
                    return ""
                if isinstance(value, (str, int, float)):
                    return str(value)
                try:
                    return json.dumps(value, ensure_ascii=False)
                except Exception:
                    return str(value)

            # Safely stringify possible dict/complex types in webhook error/logs
            error_msg = (
                _to_str(webhook_data.get("error"))
                + " "
                + _to_str(webhook_data.get("logs"))
            ).lower()
            if "sensitive" in error_msg or "e005" in error_msg:
                from bot.database import (
                    add_credits,
                    get_task_by_id,
                )

                task = await get_task_by_id(task_id)
                if task:
                    telegram_id = await _resolve_task_telegram_id(
                        task, context="kling_sensitive_failure"
                    )
                    if telegram_id:
                        bot_instance = Bot(token=config.BOT_TOKEN)
                        try:
                            # Try to get preset cost from preset manager (presets.json)
                            preset = preset_manager.get_preset(task.preset_id)
                            preset_cost = preset.cost if preset else 0
                            await add_credits(telegram_id, preset_cost)
                            await bot_instance.send_message(
                                chat_id=telegram_id,
                                text=(
                                    "❌ <b>Ваш промпт был помечен как чувствительный контент</b>"
                                    "Пожалуйста, попробуйте другой промпт без чувствительного контента."
                                    "🍌 Кредиты возвращены на счёт."
                                ),
                                parse_mode="HTML",
                            )
                            logger.info(
                                f"Sent sensitive content notification to {telegram_id}, returned {preset_cost} credits"
                            )
                        except Exception as notify_error:
                            logger.error(
                                f"Failed to notify user about sensitive content: {notify_error}"
                            )
                        finally:
                            await bot_instance.session.close()

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Kling webhook error: {e}")
        # Return 200 even on unexpected errors to avoid webhook relayers
        # repeatedly retrying the same payload. The error is logged above
        # for investigation.
        return web.Response(status=200)


async def handle_seedream_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от Novita AI (Seedream) API

    Novita AI webhook format (ASYNC_TASK_RESULT event):
    {
        "event_type": "ASYNC_TASK_RESULT",
        "payload": {
            "task": {
                "task_id": "...",
                "status": "TASK_STATUS_SUCCEED",
                "task_type": "TXT_TO_IMG"
            },
            "images": [{"image_url": "https://..."}],
            "extra": {...}
        }
    }
    """
    try:
        logger.info(f"Seedream webhook headers: {dict(request.headers)}")

        body = await request.text()
        logger.info(f"Seedream webhook raw body: {repr(body)[:500]}")

        if not body:
            logger.warning("Seedream webhook received empty body")
            return web.Response(status=200)

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            logger.warning(f"Seedream webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info(f"Seedream webhook parsed data: {data}")

        # Check event type - Novita AI sends ASYNC_TASK_RESULT
        event_type = data.get("event_type")
        if event_type != "ASYNC_TASK_RESULT":
            logger.warning(f"Unexpected event_type: {event_type}, ignoring")
            return web.Response(status=200)

        # Get payload
        payload = data.get("payload", {})

        # Get task info from payload.task
        task_info = payload.get("task", {})
        task_id = task_info.get("task_id")
        status = task_info.get("status")

        if not task_id:
            logger.warning(f"No task_id in Seedream webhook: {data}")
            return web.Response(status=200)

        logger.info(f"Seedream task {task_id} status: {status}")

        # Novita AI status: TASK_STATUS_SUCCEED, TASK_STATUS_FAILED
        if status == "TASK_STATUS_SUCCEED":
            # Get images from payload.images array
            images = payload.get("images", [])

            if not images:
                logger.error(f"No images in completed task: {data}")
                return web.Response(status=200)

            # Novita returns images as objects with image_url field
            image_url = None
            if isinstance(images[0], dict):
                image_url = images[0].get("image_url")
            elif isinstance(images[0], str):
                image_url = images[0]

            if not image_url:
                logger.error(f"Invalid images format: {images}")
                return web.Response(status=200)

            logger.info(f"Extracted image URL: {image_url[:50]}...")

            # Находим задачу в БД по task_id
            from bot.database import complete_video_task, get_task_by_id

            task = await get_task_by_id(task_id)

            if not task:
                logger.warning(f"Task {task_id} not found in database")
                return web.Response(status=200)

            telegram_id = await _resolve_task_telegram_id(
                task, context="seedream_success"
            )

            if not telegram_id:
                return web.Response(status=200)

            logger.info(
                f"Found task for user {task.user_id}, telegram_id: {telegram_id}, preset: {task.preset_id}"
            )
            request_data = _extract_task_request_data(task)
            selected_model = request_data.get("img_service") or task.model
            provider_model = request_data.get("provider_model")
            webhook_model = task_info.get("model") or payload.get("model")
            logger.info(
                "Seedream webhook route: task_id=%s selected_model=%s stored_model=%s provider_model=%s webhook_model=%s preset=%s",
                task_id,
                selected_model,
                task.model,
                provider_model,
                webhook_model,
                task.preset_id,
            )
            if webhook_model and task.model and webhook_model != task.model:
                logger.warning(
                    "Seedream webhook model mismatch: task_id=%s selected_model=%s stored_model=%s webhook_model=%s provider_model=%s",
                    task_id,
                    selected_model,
                    task.model,
                    webhook_model,
                    provider_model,
                )

            model_display = task.model or task.preset_id or "Seedream"
            caption = f"✅ <b>Изображение ({model_display}) готово!</b>\\n\\nID: <code>{task_id}</code>"
            if task.aspect_ratio:
                caption += f"\\n📐 <code>{task.aspect_ratio}</code>"
            if task.cost:
                caption += f"\\n💰 <code>{task.cost}🍌</code>"
            if task.preset_id == "no_preset" and task.prompt:
                caption += f"\\n\\n🎯 Промпт: <code>{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}</code>"
            else:
                caption += f"\\n\\n🎯 Пресет: {task.preset_id}"

            from bot.keyboards import get_image_result_keyboard
            reference_preview_urls = _extract_reference_image_urls(task)

            # Обновляем задачу в БД
            await complete_video_task(task_id, image_url)

            # Отправляем изображение пользователю
            bot_instance = Bot(token=config.BOT_TOKEN)

            try:
                image_bytes = None
                try:
                    import aiohttp

                    async with aiohttp.ClientSession() as session:
                        async with session.get(image_url, timeout=30) as resp:
                            if resp.status == 200:
                                image_bytes = await resp.read()
                except Exception as download_error:
                    logger.error(
                        f"Failed to download seedream result image bytes: {download_error}"
                    )

                if image_bytes:
                    photo = types.BufferedInputFile(
                        image_bytes, filename="seedream.png"
                    )
                    await bot_instance.send_photo(
                        chat_id=telegram_id,
                        photo=photo,
                        caption=_build_single_result_caption(_with_original_link(caption, image_url), task, reference_preview_urls),
                        parse_mode="HTML",
                        reply_markup=get_image_result_keyboard(
                            image_url, task_id=task_id
                        ),
                    )
                else:
                    await bot_instance.send_photo(
                        chat_id=telegram_id,
                        photo=image_url,
                        caption=_build_single_result_caption(_with_original_link(caption, image_url), task, reference_preview_urls),
                        parse_mode="HTML",
                        reply_markup=get_image_result_keyboard(
                            image_url, task_id=task_id
                        ),
                    )

                logger.info(f"Image sent to user {telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send image: {e}")
                # Fallback — отправляем как ссылку
                try:
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=f"🖼️ Ваше изображение готово!{image_url}",
                        reply_markup=get_image_result_keyboard(
                            image_url, task_id=task_id
                        ),
                    )
                except Exception as fallback_error:
                    logger.error(f"Failed to send fallback message: {fallback_error}")
            finally:
                await bot_instance.session.close()

        elif status == "TASK_STATUS_FAILED":
            reason = task_info.get("reason", "Unknown error")
            logger.error(f"Seedream task {task_id} failed: {reason}")

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Seedream webhook error: {e}")
        return web.Response(status=500)


async def handle_novita_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от Novita AI (FLUX.2 Pro) API

    Novita AI webhook format (ASYNC_TASK_RESULT event):
    {
        "event_type": "ASYNC_TASK_RESULT",
        "payload": {
            "task": {
                "task_id": "...",
                "status": "TASK_STATUS_SUCCEED",
                "task_type": "TXT_TO_IMG"
            },
            "images": [{"image_url": "https://..."}],
            "extra": {...}
        }
    }
    """
    try:
        logger.info(f"Novita FLUX webhook headers: {dict(request.headers)}")

        body = await request.text()
        logger.info(f"Novita FLUX webhook raw body: {repr(body)[:500]}")

        if not body:
            logger.warning("Novita FLUX webhook received empty body")
            return web.Response(status=200)

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            logger.warning(f"Novita FLUX webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info(f"Novita FLUX webhook parsed data: {data}")

        # Check event type - Novita AI sends ASYNC_TASK_RESULT
        event_type = data.get("event_type")
        if event_type != "ASYNC_TASK_RESULT":
            logger.warning(f"Unexpected event_type: {event_type}, ignoring")
            return web.Response(status=200)

        # Get payload
        payload = data.get("payload", {})

        # Get task info from payload.task
        task_info = payload.get("task", {})
        task_id = task_info.get("task_id")
        status = task_info.get("status")

        if not task_id:
            logger.warning(f"No task_id in Novita FLUX webhook: {data}")
            return web.Response(status=200)

        logger.info(f"Novita FLUX task {task_id} status: {status}")

        # Novita AI status: TASK_STATUS_SUCCEED, TASK_STATUS_FAILED
        if status == "TASK_STATUS_SUCCEED":
            # Get images from payload.images array
            images = payload.get("images", [])

            if not images:
                logger.error(f"No images in completed task: {data}")
                return web.Response(status=200)

            # Novita returns images as objects with image_url field
            image_url = None
            if isinstance(images[0], dict):
                image_url = images[0].get("image_url")
            elif isinstance(images[0], str):
                image_url = images[0]

            if not image_url:
                logger.error(f"Invalid images format: {images}")
                return web.Response(status=200)

            logger.info(f"Extracted image URL: {image_url[:50]}...")

            # Находим задачу в БД по task_id
            from bot.database import complete_video_task, get_task_by_id

            task = await get_task_by_id(task_id)

            if not task:
                logger.warning(f"Task {task_id} not found in database")
                return web.Response(status=200)

            telegram_id = await _resolve_task_telegram_id(
                task, context="novita_success"
            )

            if not telegram_id:
                return web.Response(status=200)

            logger.info(
                f"Found task for user {task.user_id}, telegram_id: {telegram_id}, preset: {task.preset_id}"
            )

            # Determine caption based on preset
            if task.preset_id == "no_preset" and task.prompt:
                caption = f"✅ <b>Ваше изображение (FLUX.2 Pro) готово!</b>🎯 Промпт: <code>{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}</code>"
            else:
                caption = f"✅ <b>Ваше изображение (FLUX.2 Pro) готово!</b>🎯 Пресет: {task.preset_id}"

            from bot.keyboards import get_image_result_keyboard
            reference_preview_urls = _extract_reference_image_urls(task)

            # Обновляем задачу в БД
            await complete_video_task(task_id, image_url)

            # Отправляем изображение пользователю
            bot_instance = Bot(token=config.BOT_TOKEN)

            try:
                image_bytes = None
                try:
                    import aiohttp

                    async with aiohttp.ClientSession() as session:
                        async with session.get(image_url, timeout=30) as resp:
                            if resp.status == 200:
                                image_bytes = await resp.read()
                except Exception as download_error:
                    logger.error(
                        f"Failed to download novita result image bytes: {download_error}"
                    )

                if image_bytes:
                    photo = types.BufferedInputFile(image_bytes, filename="flux.png")
                    await bot_instance.send_photo(
                        chat_id=telegram_id,
                        photo=photo,
                        caption=_build_single_result_caption(_with_original_link(caption, image_url), task, reference_preview_urls),
                        parse_mode="HTML",
                        reply_markup=get_image_result_keyboard(
                            image_url, task_id=task_id
                        ),
                    )
                else:
                    await bot_instance.send_photo(
                        chat_id=telegram_id,
                        photo=image_url,
                        caption=_build_single_result_caption(_with_original_link(caption, image_url), task, reference_preview_urls),
                        parse_mode="HTML",
                        reply_markup=get_image_result_keyboard(
                            image_url, task_id=task_id
                        ),
                    )

                logger.info(f"Image sent to user {telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send image: {e}")
                # Fallback — отправляем как ссылку
                try:
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=f"🖼️ Ваше изображение (FLUX.2 Pro) готово!{image_url}",
                        reply_markup=get_image_result_keyboard(
                            image_url, task_id=task_id
                        ),
                    )
                except Exception as fallback_error:
                    logger.error(f"Failed to send fallback message: {fallback_error}")
            finally:
                await bot_instance.session.close()

        elif status == "TASK_STATUS_FAILED":
            reason = task_info.get("reason", "Unknown error")
            logger.error(f"Novita FLUX task {task_id} failed: {reason}")

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Novita FLUX webhook error: {e}")
        return web.Response(status=500)


async def handle_wanx_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от PiAPI WanX API"""
    try:
        logger.info(f"WanX webhook headers: {dict(request.headers)}")

        body = await request.text()
        logger.info(f"WanX webhook raw body: {repr(body)[:500]}")

        if not body:
            logger.warning("WanX webhook received empty body")
            return web.Response(status=200)

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            logger.warning(f"WanX webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info(f"WanX webhook parsed data: {data}")

        webhook_data = data.get("data") or data.get("payload") or data
        task_id = webhook_data.get("task_id")
        status = webhook_data.get("status")

        if not task_id:
            logger.warning(f"No task_id in WanX webhook: {data}")
            return web.Response(status=200)

        normalized_status = str(status).lower() if status else ""
        logger.info(f"WanX task {task_id} status: {status}")

        if normalized_status in (
            "completed",
            "succeeded",
            "success",
            "task_status_succeed",
        ):
            output = webhook_data.get("output", {})
            video_url = (
                output.get("video_url")
                or output.get("video")
                or (
                    output.get("works")
                    and output["works"][0]
                    .get("video", {})
                    .get("resource_without_watermark")
                )
            )

            if not video_url:
                logger.error(f"No video URL in WanX completed task: {webhook_data}")
                return web.Response(status=200)

            from bot.database import (
                complete_video_task,
                get_task_by_id,
            )

            task = await get_task_by_id(task_id)
            if not task:
                logger.info(f"Ignoring orphan webhook for WanX task {task_id}: task not found in database")
                return web.Response(status=200)

            telegram_id = await _resolve_task_telegram_id(
                task, context="wanx_success"
            )
            if not telegram_id:
                return web.Response(status=200)

            reference_preview_urls = _extract_reference_image_urls(task, webhook_data)
            caption = (
                f"✅ <b>Ваше видео WanX готово!</b>🎯 Промпт: <code>{task.prompt[:100]}{'...' if task.prompt and len(task.prompt) > 100 else ''}</code>"
                if task.preset_id == "no_preset" and task.prompt
                else f"✅ <b>Ваше видео WanX готово!</b>🎯 Пресет: {task.preset_id}"
            )

            bot_instance = Bot(token=config.BOT_TOKEN)
            try:
                from bot.keyboards import get_video_result_keyboard

                await bot_instance.send_video(
                    chat_id=telegram_id,
                    video=video_url,
                    caption=_build_single_result_caption(_with_original_link(caption, video_url), task, reference_preview_urls),
                    parse_mode="HTML",
                    supports_streaming=True,
                    reply_markup=get_video_result_keyboard(
                        video_url,
                        task_id=task_id,
                        model=task.model if task else None,
                        is_public_feed=task.is_public_feed if task else False,
                    ),
                )
                await complete_video_task(task_id, video_url)
                logger.info(f"WanX video sent to user {telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send WanX video: {e}")
                try:
                    from bot.keyboards import get_video_result_keyboard

                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=f"🎬 Ваше видео WanX готово!{video_url}",
                        reply_markup=get_video_result_keyboard(
                            video_url,
                            task_id=task_id,
                            model=task.model if task else None,
                            is_public_feed=task.is_public_feed if task else False,
                        ),
                        parse_mode="HTML",
                    )
                except Exception as fallback_error:
                    logger.error(
                        f"Failed to send WanX fallback message: {fallback_error}"
                    )
            finally:
                await bot_instance.session.close()

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"WanX webhook error: {e}")
        return web.Response(status=500)


async def handle_kie_ai_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от Kie.ai (Nano Banana 2) API"""
    try:
        logger.info(f"Kie.ai webhook headers: {dict(request.headers)}")

        raw_body = await request.read()
        if not raw_body:
            logger.warning("Kie.ai webhook received empty body")
            return web.Response(status=200)

        try:
            body_text = raw_body.decode("utf-8")
            logger.info("Kie.ai webhook raw body: %s", _preview_log_payload(body_text))
            data = json.loads(body_text)
        except Exception as e:
            logger.warning(f"Kie.ai webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info("Kie.ai webhook parsed data: %s", _preview_log_payload(data))

        from bot.database import (
            add_credits,
            complete_video_task,
            get_task_by_id,
        )
        from bot.keyboards import (
            get_gemini_omni_result_keyboard,
            get_video_result_keyboard,
        )

        # Flexible extraction for task_id, status, image_url
        webhook_data = data.get("data") if isinstance(data.get("data"), dict) else data
        task_id = (
            webhook_data.get("taskId")
            or webhook_data.get("task_id")
            or webhook_data.get("id")
        )
        status = webhook_data.get("state") or webhook_data.get("status")
        normalized_status = str(status).lower() if status else ""
        response_code = data.get("code")
        veo_info = webhook_data.get("info") if isinstance(webhook_data, dict) else None
        is_veo_payload = bool(veo_info) or str(task_id).startswith("veo_")

        model = webhook_data.get("model", "")
        model_lower = model.lower()
        if "gpt-image-2" in model_lower:
            service_name = "GPT Image 2"
        elif "seedream" in model_lower:
            service_name = "Seedream"
            if "4.5-edit" in model_lower:
                service_name += " 4.5 Edit"
            elif "lite" in model_lower:
                service_name += " Lite"
        elif "nano-banana" in model_lower or "nano_banana" in model_lower:
            service_name = "Nano Banana"
            if "pro" in model_lower:
                service_name += " Pro"
            else:
                service_name += " 2"
        elif "kling/ai-avatar-standard" in model_lower:
            service_name = "Kling AI Avatar Standard"
        elif "kling/ai-avatar-pro" in model_lower:
            service_name = "Kling AI Avatar Pro"
        elif "kling/v2-5-turbo" in model_lower:
            service_name = "Kling 2.5 Turbo Pro"
        elif "seedance" in model_lower:
            service_name = "Bytedance Seedance 2.0"
        elif "veo" in model_lower or is_veo_payload:
            service_name = "Veo 3.1"
        elif "gemini-omni-video" in model_lower:
            service_name = "Gemini Omni Video"
        elif "gemini-omni-audio" in model_lower:
            service_name = "Gemini Omni Audio"
        elif "gemini-omni-character" in model_lower:
            service_name = "Gemini Omni Character"
        else:
            service_name = model or "AI"

        logger.info(
            f"Processing {service_name} task {task_id} with status {status} (normalized: {normalized_status})"
        )

        if not task_id:
            logger.error(f"Kie.ai webhook missing task id. Payload: {webhook_data}")
            return web.Response(status=200)

        # Find task in DB early for both success and failure
        task = await get_task_by_id(task_id)
        telegram_id = None
        if task:
            telegram_id = await _resolve_task_telegram_id(
                task, context="kie_ai"
            )

        if is_veo_payload and not normalized_status:
            if response_code == 200:
                normalized_status = "success"
            elif response_code in {400, 422, 500, 501}:
                normalized_status = "failed"

        if normalized_status in {"success", "completed", "succeeded", "finished"}:
            # Parse resultJson for Kie.ai specific format
            result_json_str = webhook_data.get("resultJson", "{}")
            result_url = None
            if is_veo_payload:
                from bot.services.veo_service import veo_service

                veo_urls = veo_service.extract_result_urls(data)
                result_url = veo_urls[0] if veo_urls else None
            else:
                try:
                    result_json = json.loads(result_json_str)
                    result_urls = result_json.get("resultUrls", [])
                    result_url = result_urls[0] if result_urls else None
                except (json.JSONDecodeError, KeyError, IndexError):
                    logger.warning(
                        f"Failed to parse Kie.ai resultJson: {result_json_str}"
                    )
                if not result_url:
                    direct_result = _extract_first(
                        webhook_data,
                        (
                            "resultUrl",
                            "result_url",
                            "videoUrl",
                            "imageUrl",
                            "url",
                        ),
                    )
                    if isinstance(direct_result, list) and direct_result:
                        direct_result = direct_result[0]
                    if isinstance(direct_result, str) and direct_result.startswith("http"):
                        result_url = direct_result

            if result_url:
                logger.info(
                    f"Extracted {service_name} result URL: {result_url[:50]}..."
                )
            else:
                asset_kind = None
                if task and task.type in {"audio", "character"}:
                    asset_kind = task.type
                elif "gemini-omni-audio" in model_lower:
                    asset_kind = "audio"
                elif "gemini-omni-character" in model_lower:
                    asset_kind = "character"

                asset_id = (
                    _extract_gemini_omni_asset_id(webhook_data, asset_kind)
                    if asset_kind
                    else None
                )
                if asset_id:
                    if not task:
                        logger.info(
                            "Ignoring orphan webhook for %s task %s: task not found in database",
                            service_name,
                            task_id,
                        )
                        return web.Response(status=200)
                    if not telegram_id:
                        logger.error(
                            "Cannot find telegram_id for user_id %s",
                            task.user_id,
                        )
                        return web.Response(status=200)

                    model_label = _get_task_model_label(task.model, task.type)
                    title = (
                        "Audio ID готов"
                        if asset_kind == "audio"
                        else "Character ID готов"
                    )
                    bot_instance = Bot(token=config.BOT_TOKEN)
                    try:
                        await bot_instance.send_message(
                            chat_id=telegram_id,
                            text=(
                                f"✅ <b>{title}</b>\n"
                                f"• Модель: <code>{html.escape(model_label)}</code>\n"
                                f"• ID: <code>{html.escape(asset_id)}</code>\n\n"
                                "Этот ID можно использовать в Gemini Omni Video."
                            ),
                            parse_mode="HTML",
                            reply_markup=get_gemini_omni_result_keyboard(),
                        )
                    finally:
                        await bot_instance.session.close()

                    await complete_video_task(task_id, asset_id)
                    logger.info(
                        "%s asset id %s sent to user %s",
                        service_name,
                        asset_id,
                        telegram_id,
                    )
                    return web.Response(status=200)

                logger.error(
                    f"No result URL found in {service_name} result: {webhook_data.get('resultJson', 'N/A')}"
                )
                if telegram_id:
                    bot_instance = Bot(token=config.BOT_TOKEN)
                    try:
                        await bot_instance.send_message(
                            chat_id=telegram_id,
                            text=(
                                "Не получилось завершить генерацию.\n"
                                f"• Модель: <code>{service_name}</code>\n"
                                f"• ID: <code>{task_id}</code>\n\n"
                                "Мы не получили готовый файл от сервиса.\n"
                                "Попробуйте повторить запуск немного позже."
                            ),
                            parse_mode="HTML",
                        )
                    finally:
                        await bot_instance.session.close()
                return web.Response(status=200)

            if not task:
                logger.info(f"Ignoring orphan webhook for {service_name} task {task_id}: task not found in database")
                return web.Response(status=200)
            if not telegram_id:
                logger.error(f"Cannot find telegram_id for user_id {task.user_id}")
                return web.Response(status=200)

            logger.info(
                f"Found {service_name} task for user {task.user_id}, telegram_id: {telegram_id}, preset: {task.preset_id}"
            )

            reference_preview_urls = _extract_reference_image_urls(
                task,
                webhook_data=webhook_data,
            )
            source_links = _format_reference_links(reference_preview_urls)

            is_video = False
            if result_url:
                url_lower = result_url.lower()
                video_exts = [".mp4", ".mov", ".avi", ".mkv", ".webm", ".3gp", ".flv"]
                if task and task.type == "video":
                    is_video = True
                elif task and (task.model or "").startswith("veo3"):
                    is_video = True
                elif any(ext in url_lower.split("?", 1)[0] for ext in video_exts):
                    is_video = True
                elif "video" in model_lower:
                    is_video = True

            # Build ultra-compact caption with minimal line breaks
            info_lines = []
            prompt_or_preset, label = _get_result_prompt_caption(task)
            model_label = _get_task_model_label(
                task.model if task else None, task.type if task else None
            )
            full_caption = (
                f"✅ <b>{'Видео' if is_video else 'Изображение'} готово</b>\n"
                f"• Модель: <code>{_html_fragment(model_label)}</code>\n"
                f"• ID: <code>{_html_fragment(task_id)}</code>"
            )
            if task.cost:
                full_caption += f"\n• Стоимость: <code>{_html_fragment(task.cost)}🍌</code>"
            if task.duration:
                full_caption += f"\n• Длительность: <code>{_html_fragment(task.duration)}с</code>"
            if task.aspect_ratio:
                full_caption += (
                    f"\n• Формат: <code>{_html_fragment(str(task.aspect_ratio).replace(':', '∶'))}</code>"
                )
            if is_video:
                if source_links:
                    full_caption += source_links
                full_caption += (
                    f"\n\n🔗 <a href='{html.escape(str(result_url), quote=True)}'>"
                    "Открыть оригинал</a>"
                )
            if len(full_caption) > 980:
                full_caption = full_caption[:977] + "..."

            from bot.keyboards import get_image_result_keyboard

            kb_link = (
                get_video_result_keyboard(
                    result_url,
                    task_id=task_id,
                    model=task.model if task else None,
                    is_public_feed=task.is_public_feed if task else False,
                )
                if is_video
                else get_image_result_keyboard(result_url, task_id=task_id)
            )

            bot_instance = Bot(token=config.BOT_TOKEN)
            try:
                sent_media = False
                if is_video:
                    video_kb = get_video_result_keyboard(
                        result_url,
                        task_id=task_id,
                        model=task.model if task else None,
                        is_public_feed=task.is_public_feed if task else False,
                    )
                    # Try URL first
                    try:
                        await bot_instance.send_video(
                            chat_id=telegram_id,
                            video=result_url,
                            caption=_build_single_result_caption(_with_original_link(full_caption, result_url), task, reference_preview_urls),
                            parse_mode="HTML",
                            supports_streaming=True,
                            reply_markup=video_kb,
                        )
                        logger.info(
                            f"{service_name} video sent via URL to user {telegram_id}"
                        )
                        sent_media = True
                    except Exception as e:
                        logger.warning(
                            f"Video URL send failed ({e}), trying file upload"
                        )
                        tmp_file = None
                        try:
                            import os
                            import tempfile

                            import aiohttp

                            async with aiohttp.ClientSession() as session:
                                async with session.get(result_url, timeout=60) as resp:
                                    if resp.status != 200:
                                        raise RuntimeError(
                                            f"Download failed: {resp.status}"
                                        )
                                    tmp = tempfile.NamedTemporaryFile(
                                        delete=False, suffix=".mp4"
                                    )
                                    tmp_file = tmp.name
                                    with open(tmp_file, "wb") as f:
                                        async for chunk in resp.content.iter_chunked(
                                            1024 * 64
                                        ):
                                            if chunk:
                                                f.write(chunk)
                            from aiogram.types import FSInputFile

                            video_file = FSInputFile(tmp_file)
                            await bot_instance.send_video(
                                chat_id=telegram_id,
                                video=video_file,
                                caption=_build_single_result_caption(_with_original_link(full_caption, result_url), task, reference_preview_urls),
                                parse_mode="HTML",
                                supports_streaming=True,
                                reply_markup=video_kb,
                            )
                            logger.info(
                                f"{service_name} video sent as file to user {telegram_id}"
                            )
                            sent_media = True
                        except Exception as dl_e:
                            logger.error(f"Video file upload failed: {dl_e}")
                        finally:
                            if tmp_file and os.path.exists(tmp_file):
                                try:
                                    os.remove(tmp_file)
                                except:
                                    pass
                else:
                    # Image
                    image_bytes = await _download_remote_bytes(result_url, timeout_seconds=30)
                    if not is_video:
                        if _should_send_prompt_followup(task):
                            try:
                                await _send_used_prompt_message(bot_instance, telegram_id, task, result_url)
                            except Exception as prompt_e:
                                logger.error(
                                    f"Failed to send prompt follow-up to {telegram_id}: {prompt_e}"
                                )
                        await _send_original_file(bot_instance, telegram_id, result_url, image_bytes)
                    preview_sent = False
                    try:
                        await bot_instance.send_photo(
                            chat_id=telegram_id,
                            photo=result_url,
                            caption=_build_single_result_caption(_with_original_link(full_caption, result_url), task, reference_preview_urls),
                            parse_mode="HTML",
                            reply_markup=kb_link,
                        )
                        logger.info(
                            f"{service_name} image preview sent via URL to user {telegram_id}"
                        )
                        preview_sent = True
                    except Exception as url_send_e:
                        logger.info(
                            f"Image URL send failed ({url_send_e}), trying direct download"
                        )
                        if image_bytes:
                            preview_bytes = _build_preview_photo_bytes(image_bytes)
                            if preview_bytes:
                                photo = types.BufferedInputFile(
                                    preview_bytes, filename="generated_preview.jpg"
                                )
                                await bot_instance.send_photo(
                                    chat_id=telegram_id,
                                    photo=photo,
                                    caption=_build_single_result_caption(_with_original_link(full_caption, result_url), task, reference_preview_urls),
                                    parse_mode="HTML",
                                    reply_markup=kb_link,
                                )
                                logger.info(
                                    f"{service_name} image preview sent as file-photo to user {telegram_id}"
                                )
                                preview_sent = True

                    if preview_sent:
                        sent_media = True
                    else:
                        logger.warning(f"No image bytes and no preview sent for {service_name}")

                if sent_media:
                    await complete_video_task(task_id, result_url)
                else:
                    await _send_plain_result_link(
                        bot_instance,
                        telegram_id,
                        media_label="Видео" if is_video else "Изображение",
                        model_label=model_label,
                        task_id=task_id,
                        result_url=result_url,
                        reply_markup=kb_link,
                    )
                    await complete_video_task(task_id, result_url)
                    logger.info(
                        f"{service_name} fallback text sent to user {telegram_id}"
                    )
            except Exception as send_e:
                logger.error(
                    f"Failed to send {service_name} result to {telegram_id}: {send_e}"
                )
                try:
                    await complete_video_task(task_id, result_url)
                    logger.warning(
                        f"{service_name} result stored but Telegram delivery failed for {telegram_id}"
                    )
                except Exception as complete_e:
                    logger.error(
                        f"Failed to store completed {service_name} task {task_id}: {complete_e}"
                    )
            finally:
                await bot_instance.session.close()
        else:
            # Enhanced failure logging and user notification
            fail_code = (
                webhook_data.get("failCode")
                or webhook_data.get("errorCode")
                or data.get("code")
                or "unknown"
            )
            fail_msg = (
                webhook_data.get("failMsg")
                or webhook_data.get("errorMessage")
                or data.get("msg")
                or "No details"
            )
            user_fail_msg = fail_msg
            fail_msg_lower = str(fail_msg).lower()
            if "generative ai prohibited use policy" in fail_msg_lower:
                user_fail_msg = (
                    "внешний safety-фильтр провайдера не пропустил результат. "
                    "Это не обязательно значит, что запрос запрещён, но текущая модель "
                    "не вернула картинку."
                )
            logger.error(
                f"{service_name} task {task_id} FAILED: failCode={fail_code}, failMsg={fail_msg}, full data: {webhook_data}"
            )

            if task and (
                _is_retryable_kie_blank_task_failure(fail_code, fail_msg)
                or _is_retryable_kie_timeout_failure(task, fail_code, fail_msg)
            ):
                try:
                    retried_task_id = await _retry_transient_kie_image_failure(task, task_id)
                    if retried_task_id:
                        logger.info(
                            "%s task %s requeued automatically as %s after transient KIE upstream failure",
                            service_name,
                            task_id,
                            retried_task_id,
                        )
                        return web.Response(status=200)
                except Exception as retry_error:
                    logger.exception(
                        "Automatic retry failed for transient KIE image task %s: %s",
                        task_id,
                        retry_error,
                    )

            if task and _is_retryable_wan_timeout_failure(task, fail_code, fail_msg):
                try:
                    retried_task_id = await _retry_transient_wan_timeout_failure(task, task_id)
                    if retried_task_id:
                        logger.info(
                            "%s task %s requeued automatically as %s after WAN timeout",
                            service_name,
                            task_id,
                            retried_task_id,
                        )
                        return web.Response(status=200)
                except Exception as retry_error:
                    logger.exception(
                        "Automatic retry failed for transient WAN image task %s: %s",
                        task_id,
                        retry_error,
                    )

            if task and task.cost and task.cost > 0:
                await add_credits(telegram_id, task.cost)

            if telegram_id:
                bot_instance = Bot(token=config.BOT_TOKEN)
                try:
                    refund_text = (
                        "\n\nБананы за эту попытку уже возвращены."
                        if task and task.cost and task.cost > 0
                        else "\n\nПопробуйте упростить промпт или повторить попытку немного позже."
                    )
                    error_msg = _build_failure_notification_text(
                        service_name=service_name,
                        task_id=task_id,
                        reason=user_fail_msg,
                        media_kind=(
                            "видео"
                            if task and task.type == "video"
                            else "результата"
                        ),
                        refund_text=refund_text,
                    )
                    reply_markup = None
                    if task and task.type == "image":
                        from bot.keyboards import get_failed_image_retry_keyboard

                        reply_markup = get_failed_image_retry_keyboard(task_id)
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=error_msg,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                    )
                    logger.info(f"Failure notification sent to {telegram_id}")
                except Exception as notify_e:
                    logger.error(f"Failed to notify user {telegram_id}: {notify_e}")
                finally:
                    await bot_instance.session.close()
            else:
                logger.warning(
                    f"No telegram_id for failed task {task_id} (user_id: {task.user_id if task else 'unknown'})"
                )

            await complete_video_task(task_id, None)

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Kie.ai webhook error: {e}")
        return web.Response(status=200)


def setup_web_server(dp: Dispatcher, bot: Bot) -> web.Application:
    """Настройка aiohttp сервера для вебхуков"""

    def _normalize_path(path: str, fallback: str) -> str:
        raw = (path or "").strip()
        if not raw:
            return fallback
        return raw if raw.startswith("/") else f"/{raw}"

    app = web.Application(client_max_size=60 * 1024 * 1024)
    app["bot"] = bot
    app["dp"] = dp

    # Serve static uploads directory to fix 404 errors for Novita image downloads
    app.router.add_static(
        "/uploads/", path="static/uploads", show_index=False, name="uploads"
    )
    setup_miniapp_routes(app)

    # Вебхук Telegram
    async def telegram_webhook_handler(request: web.Request) -> web.Response:
        return await handle_telegram_webhook(request, bot, dp)

    app.router.add_post(
        _normalize_path(config.WEBHOOK_PATH, "/telegram/webhook"),
        telegram_webhook_handler,
    )

    # Вебхук CryptoBot
    app.router.add_post(
        _normalize_path(config.CRYPTOBOT_WEBHOOK_PATH, "/cryptobot/webhook"),
        handle_cryptobot_webhook,
    )

    # Вебхук Lava
    app.router.add_post(
        _normalize_path(config.LAVA_WEBHOOK_PATH, "/lava/webhook"),
        handle_lava_webhook,
    )

    # Вебхук YooKassa
    app.router.add_post("/yookassa/webhook", handle_yookassa_webhook)
    # Alternative path (matches provided URL https://.../webhook/yookassa)
    app.router.add_post("/webhook/yookassa", handle_yookassa_webhook)

    # Вебхук Kling
    app.router.add_post("/webhook/kling", handle_kling_webhook)

    # Вебхук Kie.ai (Nano Banana 2)
    app.router.add_post(
        _normalize_path(config.KIE_AI_WEBHOOK_PATH, "/webhook/kie_ai"),
        handle_kie_ai_webhook,
    )

    # Health check endpoint
    async def health_check(request: web.Request) -> web.Response:
        return web.Response(text="OK")

    app.router.add_get("/health", health_check)

    return app


async def main():
    """Главная функция"""
    # Создаём директорию для логов если её нет
    os.makedirs("logs", exist_ok=True)

    # Проверяем наличие токена
    if not config.BOT_TOKEN:
        logger.error(
            "BOT_TOKEN is not set! Please set the BOT_TOKEN environment variable."
        )
        sys.exit(1)

    # Инициализируем базу данных ДО создания бота
    logger.info("Initializing database before bot startup...")
    await init_db()
    logger.info("Database initialized successfully")

    # Создаём бота
    bot = Bot(
        token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # Настраиваем диспатчер
    dp = setup_dispatcher()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    if config.WEBHOOK_HOST:
        # Webhook mode (для production)
        logger.info("Starting in webhook mode...")
        app = setup_web_server(dp, bot)
        runner = web.AppRunner(app)
        await runner.setup()

        site = web.TCPSite(runner, "0.0.0.0", config.WEBHOOK_PORT)
        await site.start()

        logger.info(f"Server started on port {config.WEBHOOK_PORT}")
        await on_startup(bot)

        # Держим бота запущенным
        await asyncio.Event().wait()
    else:
        # Polling mode (для разработки)
        logger.info("Starting in polling mode...")
        await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception(f"Bot crashed: {e}")

# TODO: register Lava webhook route manually: app.router.add_post(config.LAVA_WEBHOOK_PATH, handle_lava_webhook)
