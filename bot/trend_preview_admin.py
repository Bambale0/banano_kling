from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web

from bot import db as db_backend
from bot.config import config
from bot.database import get_prompt_by_id

logger = logging.getLogger(__name__)

_TREND_TAG = "trend"
_ALLOWED_VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v")
_ALLOWED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".heic", ".heif")


def _is_trend(prompt: dict[str, Any] | None) -> bool:
    if not prompt:
        return False
    return any(
        str(tag or "").strip().lower() == _TREND_TAG
        for tag in list(prompt.get("tags") or [])
    )


def _validate_preview_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        raise ValueError("Загрузите фото или видео для превью")
    lowered = url.lower()
    if lowered.startswith(("blob:", "data:", "file:")):
        raise ValueError("Дождитесь окончания загрузки превью")
    if not url.startswith(("/uploads/", "http://", "https://")):
        raise ValueError("Некорректная ссылка превью")
    return url


def _validate_preview_kind(value: Any, preview_url: str) -> str:
    kind = str(value or "").strip().lower()
    if kind not in {"image", "video"}:
        path = preview_url.lower().split("?", 1)[0].split("#", 1)[0]
        if path.endswith(_ALLOWED_VIDEO_EXTENSIONS):
            return "video"
        if path.endswith(_ALLOWED_IMAGE_EXTENSIONS):
            return "image"
        raise ValueError("Укажите тип превью: image или video")
    return kind


async def miniapp_admin_update_trend_preview(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Некорректный запрос")

        from bot import miniapp as miniapp_module

        telegram_id, _context = await miniapp_module._get_user_context(
            request.app,
            str(body.get("init_data") or ""),
            body.get("start_param_fallback"),
        )
        if not config.is_admin(telegram_id):
            return web.json_response({"ok": False, "error": "Нет доступа"}, status=403)

        raw_prompt_id = body.get("prompt_id")
        if not str(raw_prompt_id or "").isdigit():
            return web.json_response({"ok": False, "error": "Тренд не найден"}, status=404)
        prompt_id = int(raw_prompt_id)
        prompt = await get_prompt_by_id(prompt_id)
        if not _is_trend(prompt):
            return web.json_response({"ok": False, "error": "Тренд не найден"}, status=404)

        preview_url = _validate_preview_url(body.get("preview_url"))
        preview_kind = _validate_preview_kind(body.get("preview_kind"), preview_url)
        generation_settings = dict(prompt.get("generation_settings") or {})
        generation_settings["preview_type"] = preview_kind

        async with db_backend.connect() as db:
            await db.execute(
                """
                UPDATE user_prompts
                SET preview_url = ?,
                    generation_settings = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    preview_url,
                    json.dumps(generation_settings, ensure_ascii=False),
                    prompt_id,
                ),
            )
            await db.commit()

        updated = await get_prompt_by_id(prompt_id)
        logger.info(
            "Trend preview updated: prompt_id=%s kind=%s admin=%s",
            prompt_id,
            preview_kind,
            telegram_id,
        )
        return web.json_response(
            {
                "ok": True,
                "prompt": updated,
                "preview_kind": preview_kind,
            }
        )
    except ValueError as error:
        return web.json_response({"ok": False, "error": str(error)}, status=400)
    except Exception:
        logger.exception("Mini App trend preview update failed")
        return web.json_response(
            {"ok": False, "error": "Не удалось обновить превью тренда"},
            status=500,
        )


def setup_trend_preview_admin_routes(app: web.Application, miniapp_root: str) -> None:
    root = str(miniapp_root or "/mini-app").rstrip("/") or "/mini-app"
    app.router.add_post(
        f"{root}/api/admin/trends/preview",
        miniapp_admin_update_trend_preview,
    )
