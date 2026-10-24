from __future__ import annotations

import hashlib
import json
import logging
import re
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
            raise TypeError("Некорректный запрос")

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
    except (TypeError, ValueError) as error:
        return web.json_response({"ok": False, "error": str(error)}, status=400)
    except Exception:
        logger.exception("Mini App trend preview update failed")
        return web.json_response(
            {"ok": False, "error": "Не удалось обновить превью тренда"},
            status=500,
        )


def setup_trend_preview_admin_routes(app: web.Application, miniapp_root: str) -> None:
    root = str(miniapp_root or "/mini-app").rstrip("/") or "/mini-app"
    app.router.add_post(f"{root}/api/admin/trends/content", miniapp_admin_trend_content)
    app.router.add_post(
        f"{root}/api/admin/trends/preview",
        miniapp_admin_update_trend_preview,
    )


def _content_revision(prompt: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        [prompt.get("title"), prompt.get("prompt_text")],
        sort_keys=True, ensure_ascii=False,
    ).encode()).hexdigest()


def _content_payload(prompt: dict[str, Any]) -> dict[str, Any]:
    settings = prompt.get("generation_settings") or {}
    separate_recipe = bool(settings.get("genjutsu_recipe_id") or settings.get("wan3_recipe_version"))
    return {
        "id": prompt["id"], "title": prompt["title"],
        "prompt_text": "" if separate_recipe else prompt["prompt_text"],
        "prompt_editable": not separate_recipe,
        "revision": _content_revision(prompt),
    }


def _validate_content_prompt(prompt: dict[str, Any], text: str) -> None:
    from bot.seedance_trend_recipe import _PROMPT_LIMITS, _mentioned_tags
    from bot.trend_user_fields import normalize_user_fields_settings

    model = str(prompt.get("model") or "")
    if not text:
        raise ValueError("Промпт не должен быть пустым")
    limit = _PROMPT_LIMITS.get(model)
    if limit and len(text) > limit:
        raise ValueError(f"Промпт должен быть не длиннее {limit} символов")
    original = str(prompt.get("prompt_text") or "")
    if model in _PROMPT_LIMITS and _mentioned_tags(text) != _mentioned_tags(original):
        raise ValueError("Сохраните ссылки на референсы @Image, @Video и @Audio")
    if set(re.findall(r"{{(.*?)}}", text)) != set(re.findall(r"{{(.*?)}}", original)):
        raise ValueError("Сохраните переменные шаблона в двойных фигурных скобках")
    normalize_user_fields_settings(prompt.get("generation_settings"), prompt=text)


async def miniapp_admin_trend_content(request: web.Request) -> web.Response:
    """Private editor; never send the recipe to the public catalog."""
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise TypeError("Некорректный запрос")
        from bot import miniapp as miniapp_module

        telegram_id, _ = await miniapp_module._get_user_context(
            request.app, str(body.get("init_data") or ""), body.get("start_param_fallback"),
        )
        if not config.is_admin(telegram_id):
            return web.json_response({"ok": False, "error": "Нет доступа"}, status=403)
        prompt_id = body.get("prompt_id")
        if not str(prompt_id or "").isdigit():
            raise ValueError("Некорректный тренд")
        prompt_id = int(prompt_id)
        prompt = await get_prompt_by_id(prompt_id)
        if not _is_trend(prompt):
            return web.json_response({"ok": False, "error": "Тренд не найден"}, status=404)
        operation = body.get("op", "get")
        if operation == "update":
            if body.get("revision") != _content_revision(prompt):
                return web.json_response({"ok": False, "error": "Тренд уже изменён. Откройте редактор заново."}, status=409)
            title = body.get("title")
            text = body.get("prompt_text", prompt["prompt_text"])
            if not isinstance(title, str) or not title.strip() or len(title.strip()) > 80:
                raise ValueError("Название должно содержать от 1 до 80 символов")
            if not isinstance(text, str):
                raise ValueError("Некорректный промпт")
            text = text.strip()
            if text != prompt["prompt_text"]:
                if not _content_payload(prompt)["prompt_editable"]:
                    raise ValueError("Промпт этого тренда редактируется в исходном рецепте")
                _validate_content_prompt(prompt, text)
            async with db_backend.connect() as db:
                # CAS protects simultaneous editors; update only text columns so
                # preview uploads, counters, references and category links survive.
                cursor = await db.execute(
                    "UPDATE user_prompts SET title = ?, prompt_text = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND title = ? AND prompt_text = ?",
                    (title.strip(), text, prompt_id, prompt["title"], prompt["prompt_text"]),
                )
                if cursor.rowcount != 1:
                    return web.json_response({"ok": False, "error": "Тренд уже изменён. Откройте редактор заново."}, status=409)
                await db.commit()
            logger.info("Trend content updated: prompt_id=%s admin=%s prompt_changed=%s",
                        prompt_id, telegram_id, text != prompt["prompt_text"])
            prompt = await get_prompt_by_id(prompt_id)
        elif operation != "get":
            raise ValueError("Неизвестная операция")
        return web.json_response({"ok": True, "content": _content_payload(prompt)},
                                 headers={"Cache-Control": "no-store"})
    except (TypeError, ValueError) as error:
        return web.json_response({"ok": False, "error": str(error)}, status=400)
    except Exception:
        logger.exception("Mini App trend content editor failed")
        return web.json_response({"ok": False, "error": "Не удалось сохранить тренд"}, status=500)
