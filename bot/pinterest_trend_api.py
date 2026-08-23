from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import replace
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp
from aiohttp import web

from bot import db as db_backend
from bot.config import config
from bot.database import get_or_create_user, get_prompt_by_id
from bot.generation_context import (
    parse_ratio,
    pick_closest_ratio,
    probe_image_size,
)
from bot.trend_api import (
    TrendRunValidationError,
    TrustedTrendRun,
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
_PINTEREST_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_PINTEREST_TOOL_TITLE = "Повтори фото с Pinterest"
_PINTEREST_TOOL_TAG = "pinterest-repeat"
_PINTEREST_TOOL_PROMPT = (
    "Create a photorealistic recreation of the source photograph using the provided user as the "
    "subject. Recreate the scene, pose, framing, camera perspective, lighting, shadows, background, "
    "wardrobe silhouette and mood from SCENE_REFERENCE while preserving the exact recognizable "
    "identity of USER_IDENTITY_REFERENCE. No text, no collage, no split-screen, no watermark."
)
_PINTEREST_TOOL_SETTINGS = {
    "kind": "image",
    "user_input": "photo",
    "model": "banana_pro",
    "ratio": "9:16",
    "quality": "2K",
    "count": 1,
    "reference_count": 2,
    "reference_labels": ["РЕФЕРЕНС", "ТЫ"],
    "nsfw_checker": False,
    "nsfw_enabled": False,
}
_PINTEREST_TOOL_TAGS = [
    "trend",
    "pinterest",
    _PINTEREST_TOOL_TAG,
    "portrait",
    "realism",
]
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
    return (
        host in _PINTEREST_HOSTS
        or host.endswith(".pinterest.com")
        or host.endswith(".pinimg.com")
    )


def _validated_pinterest_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        raise TrendRunValidationError("Вставьте ссылку на Pinterest")
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise TrendRunValidationError("Некорректная ссылка Pinterest") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not _is_pinterest_host(parsed.hostname or "")
    ):
        raise TrendRunValidationError(
            "Нужна ссылка с pinterest.com, pin.it или pinimg.com"
        )
    return url


def _measurement(
    body: dict[str, Any],
    key: str,
    *,
    minimum: int,
    maximum: int,
) -> int | None:
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
        raise TrendRunValidationError(
            "Для этого тренда нужны ровно 2 фото: референс и ваше фото"
        )
    cleaned = tuple(str(item or "").strip() for item in raw)
    if any(not item for item in cleaned):
        raise TrendRunValidationError("Загрузите оба фото")
    if cleaned[0] == cleaned[1]:
        raise TrendRunValidationError("Референс и ваше фото должны быть разными")
    for item in cleaned:
        if item.startswith(("blob:", "data:", "file:")):
            raise TrendRunValidationError("Дождитесь окончания загрузки фото")
        if not item.startswith(("https://", "http://", "/uploads/")):
            raise TrendRunValidationError("Некорректная ссылка на фото")
    return cleaned[0], cleaned[1]


def _augmented_prompt(
    base_prompt: str,
    *,
    height_cm: int | None,
    weight_kg: int | None,
) -> str:
    measurements: list[str] = []
    if height_cm is not None:
        measurements.append(f"height {height_cm} cm")
    if weight_kg is not None:
        measurements.append(f"weight {weight_kg} kg")
    measurement_text = ", ".join(measurements) if measurements else "not provided"

    return (
        f"{base_prompt.strip()}\n\n"
        "STRICT IDENTITY PRESERVATION CONTRACT\n"
        "Reference naming:\n"
        "- Image 1 = SCENE_REFERENCE.\n"
        "- Image 2 = USER_IDENTITY_REFERENCE.\n"
        "Priority rules:\n"
        "- Use SCENE_REFERENCE only for scene-level attributes: composition, framing, camera angle, "
        "crop, pose, body positioning, lighting direction, shadow pattern, background, wardrobe "
        "silhouette, styling mood, and overall photographic setup.\n"
        "- Use USER_IDENTITY_REFERENCE as the only identity anchor.\n"
        "- If the references conflict, identity from USER_IDENTITY_REFERENCE always wins.\n"
        "Identity lock:\n"
        "- Preserve the person from USER_IDENTITY_REFERENCE as the same recognizable real person.\n"
        "- Keep facial geometry consistent: face shape, jawline, cheekbones, forehead proportions, "
        "nose shape, eye shape, eye spacing, eyebrow shape, lip shape, ears, skin tone, apparent age, "
        "and distinctive facial features.\n"
        "- Preserve hairstyle, hairline, hair color, and other distinctive identity features from "
        "USER_IDENTITY_REFERENCE.\n"
        "- Preserve natural body proportions and overall build from USER_IDENTITY_REFERENCE.\n"
        f"- User measurements: {measurement_text}. Use them only to keep body scale and proportions "
        "realistic; never render these numbers or any measurement text into the image.\n"
        "Negative identity rules:\n"
        "- Do NOT copy the face, identity, ethnicity, apparent age, skin tone, or hair from "
        "SCENE_REFERENCE.\n"
        "- Do NOT beautify, redesign, replace, average, or blend the user's identity with the person "
        "from SCENE_REFERENCE.\n"
        "- Do NOT create a face-swap look, deepfake artifacting, collage, split-screen, or composited "
        "cutout.\n"
        "Output goal:\n"
        "- The final image must look like the person from USER_IDENTITY_REFERENCE was actually "
        "photographed in the scene from SCENE_REFERENCE.\n"
        "- Keep the result photorealistic, coherent, believable, and naturally recognizable.\n"
        "- Keep anatomy, hands, gaze, skin texture, and facial expression natural.\n"
        "- Keep the face clearly recognizable and visible unless the source composition genuinely "
        "requires otherwise.\n"
        "USER EXPECTATION LOCK:\n"
        "- Follow the requested transformation as literally as possible.\n"
        "- Prefer faithful execution over artistic reinterpretation.\n"
        "- Change only what the user expects to change.\n"
        "- Preserve everything the user expects to remain the same, especially identity, "
        "recognizability, body scale, composition intent, and scene logic.\n"
        "- Do not introduce extra people, props, text, accessories, or visual changes that are not "
        "supported by the references."
    )


def _supported_image_ratios(model: str) -> list[str]:
    """Ratios supported by the image model, from the Mini App model catalog."""

    try:
        from bot import miniapp as miniapp_module

        meta = next(
            (item for item in miniapp_module.IMAGE_MODELS if item["id"] == model),
            None,
        )
    except Exception:  # noqa: BLE001 - catalog lookup must never break runs
        meta = None
    ratios = [str(item).strip() for item in (meta or {}).get("ratios") or []]
    valid = [item for item in ratios if parse_ratio(item)]
    return valid or ["1:1", "3:4", "4:3", "9:16", "16:9"]


async def _scene_matched_ratio(
    scene_url: str,
    model: str,
    current_ratio: str,
) -> str:
    """Match the output ratio to the scene reference aspect.

    A 3:4 source must not be stretched into the default 9:16 canvas. Falls
    back to the configured ratio when probing fails or the closest supported
    ratio is within a small tolerance of the configured one.
    """

    size = await probe_image_size(scene_url)
    if not size:
        return current_ratio
    candidate = pick_closest_ratio(size[0], size[1], _supported_image_ratios(model))
    if not candidate:
        return current_ratio
    candidate_value = parse_ratio(candidate)
    current_value = parse_ratio(current_ratio)
    if not candidate_value or not current_value:
        return current_ratio
    if abs(candidate_value / current_value - 1.0) <= 0.05:
        return current_ratio
    logger.info(
        "Pinterest scene ratio override: %s -> %s (source %dx%d)",
        current_ratio,
        candidate,
        size[0],
        size[1],
    )
    return candidate


async def _lock_pinterest_run(
    trusted: TrustedTrendRun,
    *,
    height_cm: int | None,
    weight_kg: int | None,
    scene_url: str | None = None,
) -> TrustedTrendRun:
    """Force the product contract even if the stored trend is edited later."""

    locked_settings = dict(_PINTEREST_TOOL_SETTINGS)
    ratio = str(locked_settings.get("ratio") or trusted.ratio)
    if scene_url:
        ratio = await _scene_matched_ratio(scene_url, "banana_pro", ratio)
    locked_settings["ratio"] = ratio
    # Provider order for nano-banana-pro: the USER comes first so the model
    # treats the user as the subject and the scene as the frame to re-shoot.
    # Semantic roles stay unchanged: urls[0] was SCENE, urls[1:] identity.
    reordered_references = (*trusted.reference_urls[1:], trusted.reference_urls[0])
    return replace(
        trusted,
        model="banana_pro",
        ratio=ratio,
        reference_urls=reordered_references,
        settings=locked_settings,
        prompt=_augmented_prompt(
            _PINTEREST_TOOL_PROMPT,
            height_cm=height_cm,
            weight_kg=weight_kg,
        ),
    )


async def _resolve_pinterest_image(source_url: str) -> str:
    current_url = _validated_pinterest_url(source_url)
    parsed = urlparse(current_url)
    if (parsed.hostname or "").lower().endswith("pinimg.com"):
        return current_url

    timeout = aiohttp.ClientTimeout(total=12, connect=5, sock_read=7)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
            "Chrome/130.0 Mobile Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }
    text = ""
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        for _ in range(6):
            _validated_pinterest_url(current_url)
            async with session.get(current_url, allow_redirects=False) as response:
                if response.status in _PINTEREST_REDIRECT_STATUSES:
                    location = str(response.headers.get("Location") or "").strip()
                    if not location:
                        raise TrendRunValidationError(
                            "Pinterest вернул некорректное перенаправление"
                        )
                    next_url = urljoin(str(response.url), location)
                    current_url = _validated_pinterest_url(next_url)
                    continue
                if response.status >= 400:
                    raise TrendRunValidationError("Не удалось открыть ссылку Pinterest")
                content_type = str(
                    response.headers.get("Content-Type") or ""
                ).lower()
                if content_type.startswith("image/"):
                    return str(response.url)
                text = await response.text(errors="ignore")
                break
        else:
            raise TrendRunValidationError(
                "Слишком много перенаправлений Pinterest"
            )

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

    return _validated_pinterest_url(candidate)


async def _ensure_pinterest_tool(_: web.Application) -> None:
    """Idempotently expose the system Pinterest repeat tool in Trends."""

    if not config.admin_ids:
        logger.warning(
            "Pinterest trend seed skipped: ADMIN_IDS is empty"
        )
        return

    try:
        author = await get_or_create_user(config.admin_ids[0])
        tags_json = json.dumps(_PINTEREST_TOOL_TAGS, ensure_ascii=False)
        settings_json = json.dumps(_PINTEREST_TOOL_SETTINGS, ensure_ascii=False)

        async with db_backend.connect() as db:
            cursor = await db.execute(
                """
                SELECT id
                FROM user_prompts
                WHERE title = ? OR tags LIKE ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (_PINTEREST_TOOL_TITLE, f'%"{_PINTEREST_TOOL_TAG}"%'),
            )
            row = await cursor.fetchone()
            if row:
                await db.execute(
                    """
                    UPDATE user_prompts
                    SET title = ?,
                        description = ?,
                        category = 'photo',
                        prompt_text = ?,
                        model = 'banana_pro',
                        tags = ?,
                        generation_settings = ?,
                        is_public = TRUE,
                        status = 'approved',
                        reject_reason = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        _PINTEREST_TOOL_TITLE,
                        "Повтори сцену, свет и позу с Pinterest — со своей внешностью",
                        _PINTEREST_TOOL_PROMPT,
                        tags_json,
                        settings_json,
                        int(row["id"]),
                    ),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO user_prompts (
                        author_id,
                        title,
                        description,
                        category,
                        prompt_text,
                        preview_url,
                        model,
                        tags,
                        generation_settings,
                        likes,
                        uses_count,
                        is_public,
                        status,
                        created_at
                    ) VALUES (?, ?, ?, 'photo', ?, NULL, 'banana_pro', ?, ?, 0, 0, TRUE, 'approved', CURRENT_TIMESTAMP)
                    """,
                    (
                        int(author.id),
                        _PINTEREST_TOOL_TITLE,
                        "Повтори сцену, свет и позу с Pinterest — со своей внешностью",
                        _PINTEREST_TOOL_PROMPT,
                        tags_json,
                        settings_json,
                    ),
                )
            await db.commit()
        logger.info("Pinterest repeat trend is ready")
    except Exception:
        logger.exception("Failed to seed Pinterest repeat trend")


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
            raise TrendRunValidationError(
                "Повтор фото с Pinterest доступен только для фото-тренда"
            )

        tags = {
            str(tag or "").strip().lower()
            for tag in list((prompt or {}).get("tags") or [])
            if str(tag or "").strip()
        }
        title = str((prompt or {}).get("title") or "").lower()
        if "pinterest" not in tags and "pinterest" not in title:
            raise TrendRunValidationError("Этот шаблон не является Pinterest-трендом")

        trusted = await _lock_pinterest_run(
            trusted,
            height_cm=height_cm,
            weight_kg=weight_kg,
            scene_url=references[0] if references else None,
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
    if _ensure_pinterest_tool not in app.on_startup:
        app.on_startup.append(_ensure_pinterest_tool)
