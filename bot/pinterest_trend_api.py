from __future__ import annotations

import html
import logging
import re
from dataclasses import replace
from typing import Any
from urllib.parse import urlparse

import aiohttp
from aiohttp import web

from bot.database import get_prompt_by_id
from bot.trend_api import (
    TrendRunValidationError,
    _run_image_trend,
    trusted_trend_run,
)

logger = logging.getLogger(__name__)

_PINTEREST_HOSTS = {
    "pinterest.com",
    "www.pinterest.com",
    "pin.it",
    "www.pin.it",
    "i.pinimg.com",
    "pinimg.com",
    "www.pinimg.com",
}
_OG_IMAGE_RE = re.compile(
    r'<meta\s+(?:[^>]*?property=["\']og:image["\'][^>]*?content=["\']([^"\']+)["\']|'
    r'[^>]*?content=["\']([^"\']+)["\'][^>]*?property=["\']og:image["\'])[^>]*>',
    re.IGNORECASE,
)
_IMAGE_SRC_RE = re.compile(
    r'https://i\.pinimg\.com/[^"\'<>\s]+',
    re.IGNORECASE,
)


def _is_pinterest_host(hostname: str) -> bool:
    host = str(hostname or "").strip().lower().rstrip(".")
    return host in _PINTEREST_HOSTS or host.endswith(".pinterest.com") or host.endswith(".pinimg.com")


def _validated_pinterest_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        raise TrendRunValidationError("Вставьте ссылку на Pinterest")
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise TrendRunValidationError("Некорректная ссылка Pinterest") from exc
    if parsed.scheme not in {"http", "https"} or not _is_pinterest_host(parsed.hostname or ""):
        raise TrendRunValidationError("Нужна ссылка с pinterest.com, pin.it или pinimg.com")
    return url


def _measurement(body: dict[str, Any], key: str, *, minimum: int, maximum: int) -> int | None:
    raw = body.get(key)
    if raw in (None, ""):
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise TrendRunValidationError("Рост и вес должны быть числами") from exc
    if value < minimum or value > maximum:
        label = "Рост" if key == "height_cm" else "Вес"
        raise TrendRunValidationError(f"{label} вне допустимого диапазона")
    return value


def _reference_urls(body: dict[str, Any]) -> tuple[str, str]:
    raw = body.get("reference_urls")
    if not isinstance(raw, list) or len(raw) != 2:
        raise TrendRunValidationError("Для этого тренда нужны ровно 2 фото: референс и ваше фото")
    cleaned = tuple(str(item or "").strip() for item in raw)
    if any(not item for item in cleaned):
        raise TrendRunValidationError("Загрузите оба фото")
    for item in cleaned:
        if item.startswith(("blob:", "data:", "file:")):
            raise TrendRunValidationError("Дождитесь окончания загрузки фото")
        if not item.startswith(("https://", "http://", "/uploads/")):
            raise TrendRunValidationError("Некорректная ссылка на фото")
    return cleaned[0], cleaned[1]


def _augmented_prompt(base_prompt: str, *, height_cm: int | None, weight_kg: int | None) -> str:
    measurements: list[str] = []
    if height_cm is not None:
        measurements.append(f"height {height_cm} cm")
    if weight_kg is not None:
        measurements.append(f"weight {weight_kg} kg")
    measurement_text = ", ".join(measurements) if measurements else "not provided"

    return (
        f"{base_prompt.strip()}\n\n"
        "REFERENCE CONTRACT (mandatory):\n"
        "- Input image 1 is the SOURCE / COMPOSITION REFERENCE. Copy its camera angle, framing, "
        "crop, pose, body position, lighting direction, shadow pattern, background, styling mood, "
        "and overall photographic composition.\n"
        "- Input image 2 is the USER / IDENTITY REFERENCE. Preserve this person's identity, facial "
        "geometry, recognizable features, hair, skin characteristics and natural body proportions.\n"
        "- Do NOT copy the identity or face from image 1. Do NOT change the user into the person from "
        "image 1. The final image must look like the user from image 2 photographed in the scene from "
        "image 1.\n"
        "- Keep anatomy realistic, hands natural, facial expression believable, and the result "
        "photorealistic rather than composited or face-swapped.\n"
        f"- User measurements: {measurement_text}. Use them only to keep body scale and proportions "
        "plausible; never render the numbers or any text into the image."
    )


async def _resolve_pinterest_image(source_url: str) -> str:
    parsed = urlparse(source_url)
    host = (parsed.hostname or "").lower()
    if host.endswith("pinimg.com"):
        return source_url

    timeout = aiohttp.ClientTimeout(total=12, connect=5, sock_read=7)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
            "Chrome/130.0 Mobile Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(source_url, allow_redirects=True, max_redirects=5) as response:
            final_host = (response.url.host or "").lower()
            if not _is_pinterest_host(final_host):
                raise TrendRunValidationError("Pinterest перенаправил на неподдерживаемый сайт")
            if response.status >= 400:
                raise TrendRunValidationError("Не удалось открыть ссылку Pinterest")
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if content_type.startswith("image/"):
                return str(response.url)
            text = await response.text(errors="ignore")

    match = _OG_IMAGE_RE.search(text)
    candidate = ""
    if match:
        candidate = html.unescape(match.group(1) or match.group(2) or "").strip()
    if not candidate:
        fallback = _IMAGE_SRC_RE.search(text)
        candidate = html.unescape(fallback.group(0)).strip() if fallback else ""
    if not candidate:
        raise TrendRunValidationError(
            "Не удалось получить изображение из этого пина. Загрузите референс файлом."
        )

    try:
        candidate_host = urlparse(candidate).hostname or ""
    except ValueError as exc:
        raise TrendRunValidationError("Pinterest вернул некорректную ссылку на изображение") from exc
    if not _is_pinterest_host(candidate_host):
        raise TrendRunValidationError("Pinterest вернул неподдерживаемый источник изображения")
    return candidate


async def miniapp_resolve_pinterest_reference(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise TrendRunValidationError("Некорректный запрос")

        from bot import miniapp as miniapp_module

        await miniapp_module._get_user_context(
            request.app,
            str(body.get("init_data") or ""),
            body.get("start_param_fallback"),
        )
        source_url = _validated_pinterest_url(body.get("url"))
        image_url = await _resolve_pinterest_image(source_url)
        return web.json_response(
            {
                "ok": True,
                "source_url": source_url,
                "image_url": image_url,
            }
        )
    except TrendRunValidationError as error:
        return web.json_response({"ok": False, "error": str(error)}, status=400)
    except Exception:
        logger.exception("Pinterest reference resolution failed")
        return web.json_response(
            {"ok": False, "error": "Не удалось загрузить фото из Pinterest"},
            status=500,
        )


async def miniapp_run_pinterest_repeat(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise TrendRunValidationError("Некорректный запрос")

        raw_trend_id = body.get("trend_id")
        if not str(raw_trend_id or "").isdigit():
            raise TrendRunValidationError("Тренд не найден")
        references = _reference_urls(body)
        height_cm = _measurement(body, "height_cm", minimum=120, maximum=230)
        weight_kg = _measurement(body, "weight_kg", minimum=30, maximum=250)

        from bot import miniapp as miniapp_module

        telegram_id, context = await miniapp_module._get_user_context(
            request.app,
            str(body.get("init_data") or ""),
            body.get("start_param_fallback"),
        )
        prompt = await get_prompt_by_id(int(raw_trend_id), approved_public_only=True)
        trusted = trusted_trend_run(prompt, references)
        if trusted.kind != "image":
            raise TrendRunValidationError("Повтор фото с Pinterest доступен только для фото-тренда")

        tags = {
            str(tag or "").strip().lower()
            for tag in list((prompt or {}).get("tags") or [])
            if str(tag or "").strip()
        }
        title = str((prompt or {}).get("title") or "").lower()
        if "pinterest" not in tags and "pinterest" not in title:
            raise TrendRunValidationError("Этот шаблон не является Pinterest-трендом")

        trusted = replace(
            trusted,
            prompt=_augmented_prompt(
                trusted.prompt,
                height_cm=height_cm,
                weight_kg=weight_kg,
            ),
        )
        return await _run_image_trend(
            request,
            telegram_id=telegram_id,
            user=context["user"],
            trend=trusted,
        )
    except TrendRunValidationError as error:
        return web.json_response({"ok": False, "error": str(error)}, status=400)
    except Exception:
        logger.exception("Mini App Pinterest repeat generation failed")
        return web.json_response(
            {"ok": False, "error": "Не удалось запустить повтор фото"},
            status=500,
        )


def setup_pinterest_trend_routes(app: web.Application, miniapp_root: str) -> None:
    root = str(miniapp_root or "/mini-app").rstrip("/") or "/mini-app"
    app.router.add_post(
        f"{root}/api/trends/pinterest-reference",
        miniapp_resolve_pinterest_reference,
    )
    app.router.add_post(
        f"{root}/api/trends/pinterest-repeat/run",
        miniapp_run_pinterest_repeat,
    )
