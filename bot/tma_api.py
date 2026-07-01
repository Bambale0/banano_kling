from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import aiosqlite
from aiohttp import web

from bot import database
from bot.config import config
from bot.image_models import IMAGE_MODEL_CONFIGS, normalize_image_options, resolve_image_model
from bot.services.admin_config_service import admin_package_config_service
from bot.services.cryptobot_service import cryptobot_service
from bot.services.gemini_omni_service import gemini_omni_service
from bot.services.gpt55_service import gpt55_service
from bot.services.gpt_image_service import gpt_image_service
from bot.services.grok_service import grok_service
from bot.services.ideogram_service import ideogram_service
from bot.services.image_analyzer_service import image_analyzer_service
from bot.services.kling_service import kling_service
from bot.services.feed_preview import feed_preview_url
from bot.services.nano_banana_2_service import nano_banana_2_service
from bot.services.nano_banana_pro_service import nano_banana_pro_service
from bot.services.preset_manager import preset_manager
from bot.services.push_scenario_service import PushScenarioConfig, push_scenario_service
from bot.services.referral_admin_config import referral_admin_config_service
from bot.services.runway_service import runway_service
from bot.services.seedream_service import seedream_lite_service
from bot.services.tbank_service import tbank_service
from bot.services.subscription_service import PRO_IMAGE_MODELS, subscription_service
from bot.tma_realtime import keep_ws_alive, register_ws, unregister_ws
from bot.video_models import VIDEO_MODEL_CONFIGS

logger = logging.getLogger(__name__)
TMA_MIX_PHOTO_MODELS = ("banana_2", "grok_i2i", "gpt_image_2")
TMA_MAX_IMAGE_VARIATIONS = 6


def _clean_tma_prompt(value: str) -> str:
    text = str(value or "").strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1].strip()
    return text


async def _improve_tma_prompt(prompt: str, refs_count: int = 0) -> str:
    refs_text = (
        f"Учти, что пользователь загрузил {refs_count} референс(ов); сохрани важные объекты, стиль и идентичность, если они явно нужны."
        if refs_count
        else "Если референсов нет, не добавляй несуществующие детали."
    )
    task = (
        "Улучши промпт для генерации изображения/видео в BOOM Studio. "
        "Сохрани исходный смысл, сделай запрос конкретнее: сцена, объект, стиль, свет, камера, композиция, качество. "
        "Убери двусмысленные или рискованные формулировки. "
        f"{refs_text}\n\n"
        f"Исходный промпт: {prompt}\n\n"
        "Верни только готовый промпт без пояснений."
    )
    try:
        improved = await asyncio.wait_for(
            gpt55_service.ask(
                user_content=[{"type": "input_text", "text": task}],
                history=[],
                reasoning_effort="medium",
                web_search=False,
            ),
            timeout=45,
        )
    except Exception:
        logger.exception("TMA prompt improvement failed")
        return prompt
    improved = _clean_tma_prompt(improved or "")
    return improved if 3 <= len(improved) <= 6000 else prompt


def _apply_tma_face_prompt(prompt: str, face_mode: str, ref_count: int) -> str:
    if not ref_count or face_mode == "none":
        return prompt
    if face_mode == "enhance":
        instruction = (
            "Use the reference photo(s) as identity guidance. Keep the person recognizable: "
            "preserve facial structure, age, eye color, face shape and distinctive features, "
            "while allowing subtle flattering improvements to lighting, skin texture and photo quality."
        )
    else:
        instruction = (
            "Use the reference photo(s) as strict identity guidance. Preserve the exact person: "
            "facial structure, age, eye color, face shape, proportions, hairline and distinctive features "
            "must remain unchanged. Change only the requested style, background, outfit or scene."
        )
    return f"{prompt}\n\n{instruction}"


async def _run_tma_image_model(
    model: str,
    prompt: str,
    refs: list[str],
    options: dict,
    callback_url: str | None,
) -> dict | None:
    model_cfg = IMAGE_MODEL_CONFIGS.get(model, IMAGE_MODEL_CONFIGS["banana_pro"])
    aspect_ratio = str(options.get("aspect_ratio") or model_cfg["defaults"].get("aspect_ratio") or "1:1")
    if model == "banana_2":
        return await nano_banana_2_service.generate_image(
            prompt,
            aspect_ratio=aspect_ratio,
            resolution=str(options.get("resolution") or "4K"),
            image_input=refs,
            output_format=str(options.get("output_format") or "png"),
            callback_url=callback_url,
        )
    if model in {"wan_27_image", "wan_27_image_pro"}:
        return await kling_service.generate_wan_image(
            prompt=prompt,
            model=model,
            input_urls=refs,
            n=int(options.get("n") or 1),
            enable_sequential=bool(options.get("enable_sequential", False)),
            resolution=str(options.get("resolution") or "2K"),
            thinking_mode=bool(options.get("thinking_mode", model == "wan_27_image")),
            aspect_ratio=aspect_ratio,
            watermark=bool(options.get("watermark", False)),
            seed=options.get("seed"),
            nsfw_checker=bool(options.get("nsfw_checker", True)),
            callback_url=callback_url,
        )
    if model == "gpt_image_2":
        return await gpt_image_service.generate_image(
            prompt,
            image_urls=refs,
            aspect_ratio=aspect_ratio,
            nsfw_checker=bool(options.get("nsfw_checker", False)),
            callback_url=callback_url,
        )
    if model == "grok_t2i":
        return await grok_service.generate_text_to_image(
            prompt,
            aspect_ratio=aspect_ratio,
            enable_pro=bool(options.get("enable_pro", False)),
            nsfw_checker=bool(options.get("nsfw_checker", False)),
            callback_url=callback_url,
        )
    if model == "grok_i2i":
        return await grok_service.generate_image_to_image(
            refs[0] if refs else "",
            prompt=prompt,
            nsfw_checker=bool(options.get("nsfw_checker", False)),
            callback_url=callback_url,
        )
    if model == "ideogram_character":
        return await ideogram_service.generate_character(
            prompt,
            reference_image_urls=refs,
            aspect_ratio=aspect_ratio,
            rendering_speed=str(options.get("rendering_speed") or "BALANCED"),
            style=str(options.get("style") or "AUTO"),
            expand_prompt=bool(options.get("expand_prompt", True)),
            nsfw_checker=bool(options.get("nsfw_checker", False)),
            callback_url=callback_url,
        )
    if model in {"seedream_5_lite", "seedream_edit"}:
        return await seedream_lite_service.generate_image(
            prompt,
            model=str(model_cfg.get("api_model") or "seedream/4.5"),
            image_urls=refs,
            aspect_ratio=aspect_ratio,
            quality=str(options.get("quality") or "basic"),
            callback_url=callback_url,
        )
    return await nano_banana_pro_service.generate_image(
        prompt,
        aspect_ratio=aspect_ratio,
        resolution=str(options.get("resolution") or "4K"),
        image_input=refs,
        output_format=str(options.get("output_format") or "png"),
        callback_url=callback_url,
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _json(data: Any, *, status: int = 200) -> web.Response:
    return web.Response(
        text=json.dumps(data, ensure_ascii=False, default=_json_default),
        status=status,
        content_type="application/json",
    )


def validate_tma_init_data(init_data: str) -> dict | None:
    if not init_data or not config.BOT_TOKEN:
        return None

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", "")
    if not received_hash:
        return None

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(parsed.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        config.BOT_TOKEN.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        return None

    try:
        auth_date = int(parsed.get("auth_date") or 0)
    except (TypeError, ValueError):
        return None
    max_age = int(getattr(config, "TMA_INIT_DATA_MAX_AGE_SECONDS", 24 * 3600) or 0)
    if max_age > 0 and (auth_date <= 0 or time.time() - auth_date > max_age):
        return None

    if parsed.get("user"):
        try:
            parsed["user"] = json.loads(parsed["user"])
        except json.JSONDecodeError:
            return None
    return parsed


def _init_data_from_request(request: web.Request) -> str:
    return (
        request.headers.get("x-telegram-init-data")
        or request.headers.get("X-Telegram-Init-Data")
        or request.query.get("initData", "")
    )


async def require_admin(request: web.Request) -> dict:
    init_payload = validate_tma_init_data(_init_data_from_request(request))
    user = init_payload.get("user") if isinstance(init_payload, dict) else None
    if not isinstance(user, dict):
        raise web.HTTPUnauthorized(text="Telegram initData is required")
    telegram_id = int(user.get("id") or 0)
    if not config.is_admin(telegram_id):
        raise web.HTTPForbidden(text="Admin access required")
    return user


async def require_tma_user(request: web.Request) -> dict:
    init_payload = validate_tma_init_data(_init_data_from_request(request))
    user = init_payload.get("user") if isinstance(init_payload, dict) else None
    if not isinstance(user, dict):
        raise web.HTTPUnauthorized(text="Telegram initData is required")
    telegram_id = int(user.get("id") or 0)
    if not telegram_id:
        raise web.HTTPUnauthorized(text="Telegram user is required")
    if await database.is_user_banned(telegram_id):
        raise web.HTTPForbidden(text="User is banned")
    await database.get_or_create_user(
        telegram_id,
        username=user.get("username"),
        first_name=user.get("first_name"),
        last_name=user.get("last_name"),
    )
    return user


async def _read_json(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _telegram_id(user: dict) -> int:
    return int(user.get("id") or 0)


def _absolute_media_url(url: Any) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith("/"):
        return f"{config.static_base_url.rstrip('/')}{value}"
    if value.startswith("uploads/"):
        return f"{config.static_base_url.rstrip('/')}/{value}"
    return value


def _reference_preview_url(reference_images: Any) -> str:
    refs = reference_images
    if isinstance(reference_images, str):
        try:
            refs = json.loads(reference_images)
        except json.JSONDecodeError:
            refs = [reference_images]
    if not isinstance(refs, list):
        return ""
    for item in refs:
        url = _absolute_media_url(item)
        if url and not re.search(r"\.(mp4|mov|webm|m4v)(\?|#|$)", url, re.I):
            return url
    return _absolute_media_url(refs[0]) if refs else ""


def _decorate_media_fields(row: dict) -> dict:
    result_url = _absolute_media_url(row.get("result_url"))
    preview_url = result_url or _reference_preview_url(row.get("reference_images"))
    return {
        **row,
        "result_url": result_url,
        "preview_url": preview_url,
    }


def _public_task(task: Any) -> dict:
    return _decorate_media_fields({
        "task_id": task.task_id,
        "type": task.type,
        "preset_id": task.preset_id,
        "model": task.model,
        "duration": task.duration,
        "aspect_ratio": task.aspect_ratio,
        "prompt": task.prompt,
        "cost": task.cost,
        "status": task.status,
        "result_url": task.result_url,
        "reference_images": task.reference_images,
        "created_at": task.created_at,
        "is_public_feed": task.is_public_feed,
        "likes_count": task.likes_count,
        "shares_count": task.shares_count,
        "published_at": getattr(task, "published_at", None),
        "feed_status": getattr(task, "feed_status", "approved"),
    })


async def _user_tasks(telegram_id: int, limit: int = 40) -> list[dict]:
    rows = await _query_all(
        """
        SELECT gt.*
        FROM generation_tasks gt
        WHERE gt.telegram_id = ?
        ORDER BY gt.id DESC
        LIMIT ?
        """,
        (telegram_id, max(1, min(int(limit or 40), 200))),
    )
    return [_decorate_media_fields(row) for row in rows]


async def _user_payments(telegram_id: int, limit: int = 20) -> list[dict]:
    return await _query_all(
        """
        SELECT t.order_id, t.payment_id, t.provider, t.credits, t.amount_rub,
               t.original_amount_rub, t.promo_code, t.promo_discount_percent,
               t.status, t.created_at
        FROM transactions t
        JOIN users u ON u.id = t.user_id
        WHERE u.telegram_id = ?
        ORDER BY t.id DESC
        LIMIT ?
        """,
        (telegram_id, max(1, min(int(limit or 20), 100))),
    )


def _feature_catalog() -> dict:
    image_costs = {
        model_id: int(preset_manager.get_generation_cost(cfg.get("cost_key") or model_id))
        for model_id, cfg in IMAGE_MODEL_CONFIGS.items()
    }
    video_durations = sorted(
        {
            int(duration)
            for cfg in VIDEO_MODEL_CONFIGS.values()
            for duration in (cfg.get("durations") or [3, 5, 6, 8, 10, 15])
        }
    )
    video_costs = {
        model_id: {
            str(duration): int(preset_manager.get_video_cost(model_id, duration))
            for duration in (cfg.get("durations") or video_durations or [5])
        }
        for model_id, cfg in VIDEO_MODEL_CONFIGS.items()
    }
    return {
        "generation": {
            "image_models": IMAGE_MODEL_CONFIGS,
            "video_models": VIDEO_MODEL_CONFIGS,
            "costs": {"image_models": image_costs, "video_models": video_costs},
            "image_ratios": ["auto", "1:1", "16:9", "9:16", "4:3", "3:2"],
            "video_ratios": ["16:9", "9:16", "1:1"],
            "durations": [3, 5, 6, 8, 10, 15],
            "upload_limits": {"image_refs": 14, "video_refs": 5},
        },
        "flows": [
            "image",
            "image_edit",
            "multi_photo",
            "video_text",
            "image_to_video",
            "video_edit",
            "motion_control",
            "gemini_omni",
            "batch_edit",
            "upscale",
            "photo_to_prompt",
            "prompt_builder",
            "gpt55",
            "feed",
            "payments",
            "partner",
            "settings",
            "support",
        ],
    }


def _production_limit(request: web.Request | None = None) -> int:
    raw_value = request.query.get("limit") if request is not None else None
    try:
        value = int(raw_value or config.MINI_APP_PRODUCTION_LIMIT or 500)
    except (TypeError, ValueError):
        value = 500
    return max(1, min(value, 5000))


async def _query_all(sql: str, params: tuple = ()) -> list[dict]:
    async with aiosqlite.connect(database.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(sql, params)
        return [dict(row) for row in await cursor.fetchall()]


async def _query_one(sql: str, params: tuple = ()) -> dict:
    rows = await _query_all(sql, params)
    return rows[0] if rows else {}


async def _dashboard() -> dict:
    stats = await database.get_admin_stats()
    extra = await _query_one(
        """
        SELECT
            (
                SELECT COALESCE(SUM(amount_rub), 0)
                FROM transactions
                WHERE status = 'completed' AND date(created_at) = date('now')
            ) AS today_revenue,
            (
                SELECT COUNT(*)
                FROM transactions
                WHERE status = 'completed' AND date(created_at) = date('now')
            ) AS today_payments,
            (
                SELECT COUNT(*)
                FROM generation_tasks
                WHERE status IN ('pending', 'processing')
                  AND created_at >= datetime('now', '-24 hours')
            ) AS active_tasks,
            (
                SELECT COUNT(*)
                FROM generation_tasks
                WHERE status = 'failed'
            ) AS failed_tasks
        """
    )
    return {
        **stats,
        "today_revenue": round(float(extra.get("today_revenue") or 0), 2),
        "today_payments": int(extra.get("today_payments") or 0),
        "active_tasks": int(extra.get("active_tasks") or 0),
        "failed_tasks": int(extra.get("failed_tasks") or 0),
        "maintenance": await database.is_maintenance_mode(),
    }


async def _users(search: str = "", limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit or 50), 5000))
    search = str(search or "").strip()
    if search:
        pattern = f"%{search}%"
        return await _query_all(
            """
            SELECT telegram_id, username, first_name, last_name, credits, is_banned,
                   has_paid, referral_code, referral_earned, free_generations,
                   created_at, updated_at
            FROM users
            WHERE CAST(telegram_id AS TEXT) LIKE ?
               OR COALESCE(username, '') LIKE ?
               OR COALESCE(first_name, '') LIKE ?
               OR COALESCE(last_name, '') LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (pattern, pattern, pattern, pattern, limit),
        )
    return await _query_all(
        """
        SELECT telegram_id, username, first_name, last_name, credits, is_banned,
               has_paid, referral_code, referral_earned, free_generations,
               created_at, updated_at
        FROM users
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )


async def _payments(limit: int = 80) -> list[dict]:
    return await _query_all(
        """
        SELECT t.order_id, t.payment_id, t.provider, t.credits, t.amount_rub,
               t.original_amount_rub, t.promo_code, t.promo_discount_percent,
               t.status, t.created_at, u.telegram_id, u.username
        FROM transactions t
        JOIN users u ON u.id = t.user_id
        ORDER BY t.id DESC
        LIMIT ?
        """,
        (max(1, min(int(limit or 80), 5000)),),
    )


async def _subscriptions(limit: int = 80) -> list[dict]:
    return await _query_all(
        """
        SELECT s.id, s.package_id, s.package_name, s.status, s.image_limit,
               s.video_limit, s.includes_pro, s.expires_at, s.created_at,
               COALESCE(SUM(CASE WHEN u.usage_type = 'image' AND u.refunded = 0 THEN 1 ELSE 0 END), 0) AS images_used,
               COALESCE(SUM(CASE WHEN u.usage_type = 'video' AND u.refunded = 0 THEN 1 ELSE 0 END), 0) AS videos_used,
               usr.telegram_id, usr.username
        FROM user_subscriptions s
        JOIN users usr ON usr.id = s.user_id
        LEFT JOIN subscription_usage u ON u.subscription_id = s.id
        GROUP BY s.id
        ORDER BY s.id DESC
        LIMIT ?
        """,
        (max(1, min(int(limit or 80), 5000)),),
    )


async def _recurring(limit: int = 80) -> list[dict]:
    return await _query_all(
        """
        SELECT r.*, u.username
        FROM recurring_subscriptions r
        JOIN users u ON u.id = r.user_id
        ORDER BY r.id DESC
        LIMIT ?
        """,
        (max(1, min(int(limit or 80), 5000)),),
    )


async def _generations(limit: int = 80) -> list[dict]:
    rows = await _query_all(
        """
        SELECT gt.task_id, gt.type, gt.preset_id, gt.model, gt.duration,
               gt.aspect_ratio, gt.cost, gt.status, gt.result_url,
               gt.reference_images, gt.is_public_feed,
               gt.likes_count, gt.shares_count, gt.created_at, gt.completed_at,
               gt.billing_source, u.telegram_id, u.username
        FROM generation_tasks gt
        JOIN users u ON u.id = gt.user_id
        ORDER BY gt.id DESC
        LIMIT ?
        """,
        (max(1, min(int(limit or 80), 5000)),),
    )
    return [_decorate_media_fields(row) for row in rows]


async def _feed(limit: int = 40) -> list[dict]:
    limit = max(1, min(int(limit or 40), 1000))
    tasks = await database.get_feed_tasks(limit=limit)
    telegram_ids = [int(task.telegram_id or 0) for task in tasks if task.telegram_id]
    users_by_telegram_id: dict[int, dict] = {}
    if telegram_ids:
        placeholders = ",".join("?" for _ in telegram_ids)
        rows = await _query_all(
            f"""
            SELECT telegram_id, username, first_name, last_name
            FROM users
            WHERE telegram_id IN ({placeholders})
            """,
            tuple(telegram_ids),
        )
        users_by_telegram_id = {int(row["telegram_id"]): row for row in rows}
    return [
        {
            "task_id": task.task_id,
            "username": users_by_telegram_id.get(int(task.telegram_id or 0), {}).get("username"),
            "first_name": users_by_telegram_id.get(int(task.telegram_id or 0), {}).get("first_name"),
            "last_name": users_by_telegram_id.get(int(task.telegram_id or 0), {}).get("last_name"),
            "author_code": "creator-"
            + hashlib.sha256(
                str(task.telegram_id or task.user_id or task.task_id).encode("utf-8")
            ).hexdigest()[:8],
            "type": task.type,
            "preset_id": task.preset_id,
            "model": task.model,
            "prompt": task.prompt,
            "result_url": _absolute_media_url(task.result_url),
            "reference_images": task.reference_images,
            "preview_url": feed_preview_url(task.task_id, task.result_url)
            or _absolute_media_url(task.result_url)
            or _reference_preview_url(task.reference_images),
            "likes_count": task.likes_count,
            "shares_count": task.shares_count,
            "created_at": task.created_at,
            "published_at": task.published_at,
            "is_public_feed": task.is_public_feed,
        }
        for task in tasks
    ]


async def _partners(search: str = "", limit: int = 80) -> list[dict]:
    limit = max(1, min(int(limit or 80), 5000))
    search = str(search or "").strip()
    where = "WHERE u.partner_agreed_at IS NOT NULL"
    params: list[Any] = []
    if search:
        where += """
            AND (
                CAST(u.telegram_id AS TEXT) LIKE ?
                OR COALESCE(u.username, '') LIKE ?
                OR COALESCE(u.first_name, '') LIKE ?
                OR COALESCE(u.last_name, '') LIKE ?
                OR COALESCE(u.referral_code, '') LIKE ?
            )
        """
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern, pattern, pattern])
    params.append(limit)
    rows = await _query_all(
        f"""
        SELECT
            u.id,
            u.telegram_id,
            u.username,
            u.first_name,
            u.last_name,
            u.referral_code,
            u.partner_agreed_at,
            u.partner_total_revenue_rub,
            u.partner_balance_rub,
            u.partner_tier,
            COUNT(DISTINCT referred.id) AS users_count,
            COUNT(DISTINCT CASE WHEN t.status = 'completed' THEN t.id END) AS payments_count,
            COALESCE(SUM(CASE WHEN t.status = 'completed' THEN t.amount_rub ELSE 0 END), 0) AS revenue_rub,
            COALESCE(SUM(CASE WHEN t.status = 'completed' AND date(t.created_at) = date('now') THEN 1 ELSE 0 END), 0) AS today_payments,
            COALESCE(SUM(CASE WHEN t.status = 'completed' AND date(t.created_at) = date('now') THEN t.amount_rub ELSE 0 END), 0) AS today_revenue_rub,
            COALESCE(w.withdrawn_rub, 0) AS withdrawn_rub
        FROM users u
        LEFT JOIN users referred ON referred.referred_by = u.id
        LEFT JOIN transactions t ON t.user_id = referred.id
        LEFT JOIN (
            SELECT user_id, SUM(amount_rub) AS withdrawn_rub
            FROM partner_withdrawals
            WHERE status = 'completed'
            GROUP BY user_id
        ) w ON w.user_id = u.id
        {where}
        GROUP BY u.id
        ORDER BY revenue_rub DESC, users_count DESC, u.partner_agreed_at DESC
        LIMIT ?
        """,
        tuple(params),
    )
    partners: list[dict] = []
    for row in rows:
        total_revenue = round(max(float(row.get("partner_total_revenue_rub") or 0), float(row.get("revenue_rub") or 0)), 2)
        balance_rub = round(float(row.get("partner_balance_rub") or 0), 2)
        withdrawn_rub = round(float(row.get("withdrawn_rub") or 0), 2)
        partners.append(
            {
                "telegram_id": row.get("telegram_id"),
                "username": row.get("username"),
                "first_name": row.get("first_name"),
                "last_name": row.get("last_name"),
                "referral_code": row.get("referral_code") or "",
                "partner_agreed_at": row.get("partner_agreed_at"),
                "users_count": row.get("users_count") or 0,
                "payments_count": row.get("payments_count") or 0,
                "revenue_rub": total_revenue,
                "commission_rub": round(balance_rub + withdrawn_rub, 2),
                "balance_rub": balance_rub,
                "withdrawn_rub": withdrawn_rub,
                "tier": database.get_partner_tier_by_total(total_revenue),
                "percent": database.get_partner_percent_by_total(total_revenue),
                "today_payments": row.get("today_payments") or 0,
                "today_revenue_rub": round(float(row.get("today_revenue_rub") or 0), 2),
            }
        )
    return partners


async def _withdrawals(limit: int = 100) -> list[dict]:
    return await _query_all(
        """
        SELECT w.*, u.telegram_id, u.username
        FROM partner_withdrawals w
        JOIN users u ON u.id = w.user_id
        ORDER BY w.id DESC
        LIMIT ?
        """,
        (max(1, min(int(limit or 100), 5000)),),
    )


async def _referrals() -> dict:
    cfg = await referral_admin_config_service.get_config()
    payouts = await referral_admin_config_service.list_payouts()
    return {
        "config": cfg.to_dict(),
        "payouts": [payout.to_dict() for payout in payouts],
    }


async def _push() -> dict:
    cfg = await push_scenario_service.get_config()
    due = await push_scenario_service.collect_due_events(limit=20, mark_enqueued=False)
    return {
        "config": cfg.to_json(),
        "due_events": [
            {
                "scenario_key": event.scenario_key,
                "telegram_id": event.telegram_id,
                "title": event.title,
                "message": event.message,
                "due_at": event.due_at,
                "payload": event.payload,
            }
            for event in due
        ],
    }


async def _system() -> dict:
    return {
        "bot_token": bool(config.BOT_TOKEN),
        "webhook_host": config.WEBHOOK_HOST,
        "webhook_path": config.WEBHOOK_PATH,
        "mini_app_url": config.MINI_APP_URL,
        "mini_app_mode": config.MINI_APP_MODE,
        "mini_app_production_limit": config.MINI_APP_PRODUCTION_LIMIT,
        "database_path": database.DATABASE_PATH,
        "payment_provider": config.payment_provider,
        "tbank": bool(config.TBANK_TERMINAL_KEY and config.TBANK_SECRET_KEY),
        "cryptobot": bool(config.CRYPTOBOT_API_TOKEN),
        "kie_ai": bool(config.KIE_AI_API_KEY),
        "ai_webhook_secret": bool(config.AI_WEBHOOK_SECRET),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def _user_bootstrap(telegram_user: dict) -> dict:
    telegram_id = _telegram_id(telegram_user)
    packages = [
        package
        for package in await admin_package_config_service.list_packages(include_hidden=False)
        if not package.get("hidden")
    ]
    return {
        "user": telegram_user,
        "is_admin": config.is_admin(telegram_id),
        "stats": await database.get_user_stats(telegram_id),
        "settings": await database.get_user_settings(telegram_id),
        "packages": packages,
        "payments": await _user_payments(telegram_id),
        "tasks": await _user_tasks(telegram_id),
        "feed": await _feed(limit=60),
        "partner": await database.get_partner_overview(telegram_id),
        "withdrawals": await database.get_recent_partner_withdrawals(telegram_id, limit=10),
        "recurring": await database.get_recurring_subscription(telegram_id),
        "gpt55_history": await database.get_gpt55_history(telegram_id, limit=20),
        "features": _feature_catalog(),
        "support": {"contact": "@S_k7222"},
    }


async def handle_tma_app_bootstrap(request: web.Request) -> web.Response:
    user = await require_tma_user(request)
    return _json({"ok": True, "data": await _user_bootstrap(user)})


async def handle_tma_app_ws(request: web.Request) -> web.StreamResponse:
    user = await require_tma_user(request)
    telegram_id = _telegram_id(user)
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(request)
    await register_ws(telegram_id, ws)
    await ws.send_str(json.dumps({"type": "connected"}, ensure_ascii=False))
    try:
        await keep_ws_alive(ws)
    finally:
        await unregister_ws(telegram_id, ws)
    return ws


async def handle_tma_app_upload(request: web.Request) -> web.Response:
    await require_tma_user(request)
    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "file":
        return _json({"ok": False, "error": "file_required"}, status=400)
    filename = field.filename or "upload.bin"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    if ext not in {"jpg", "jpeg", "png", "webp", "mp4", "mov"}:
        return _json({"ok": False, "error": "bad_file_type"}, status=400)
    data = await field.read(decode=False)
    max_bytes = 80 * 1024 * 1024 if ext in {"mp4", "mov"} else 12 * 1024 * 1024
    if len(data) > max_bytes:
        return _json({"ok": False, "error": "file_too_large"}, status=400)
    from bot.handlers.generation import save_uploaded_file

    url = save_uploaded_file(data, "mp4" if ext == "mov" else ext, is_reference=True)
    if not url:
        return _json({"ok": False, "error": "upload_failed"}, status=500)
    return _json({"ok": True, "url": url})


async def _charge_generation(
    telegram_id: int,
    *,
    usage_type: str,
    model: str,
    task_id: str,
    cost: int,
    metadata: dict | None = None,
) -> tuple[bool, str, int | None]:
    decision = await subscription_service.consume(
        telegram_id,
        usage_type=usage_type,
        model=model,
        external_id=task_id,
        metadata=metadata or {},
    )
    if decision.allowed:
        return True, "subscription", decision.usage_id
    ok = await database.deduct_credits(
        telegram_id,
        cost,
        reason="tma_generation_charge",
        external_id=task_id,
        metadata=metadata or {},
    )
    return bool(ok), "credits", None


async def _can_start_generation(
    telegram_id: int,
    cost: int,
    *,
    usage_type: str,
    model: str,
    count: int = 1,
) -> bool:
    if config.is_admin(telegram_id):
        return True
    if await database.check_can_afford(telegram_id, cost):
        return True
    subscription = await database.get_active_subscription(telegram_id)
    if not subscription:
        return False
    if usage_type == "image" and str(model).lower() in PRO_IMAGE_MODELS and not bool(subscription.get("includes_pro")):
        return False
    limit_key = "image_limit" if usage_type == "image" else "video_limit"
    used_key = "images_used" if usage_type == "image" else "videos_used"
    remaining = int(subscription.get(limit_key) or 0) - int(subscription.get(used_key) or 0)
    return remaining >= max(1, int(count or 1))


async def handle_tma_app_generation(request: web.Request) -> web.Response:
    user = await require_tma_user(request)
    telegram_id = _telegram_id(user)
    payload = await _read_json(request)
    flow = str(payload.get("flow") or "image")
    prompt = str(payload.get("prompt") or "").strip()
    if len(prompt) < 3:
        return _json({"ok": False, "error": "prompt_required"}, status=400)
    refs = payload.get("references") if isinstance(payload.get("references"), list) else []
    refs = [str(item) for item in refs if str(item).startswith(("http://", "https://"))][:14]
    options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
    if bool(options.get("improve_prompt")):
        prompt = await _improve_tma_prompt(prompt, len(refs))
    prompt = _apply_tma_face_prompt(prompt, str(options.get("face_preservation") or "none"), len(refs))
    user_row = await database.get_or_create_user(telegram_id)
    callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None
    task_id = ""

    if flow in {"image", "image_edit", "multi_photo", "upscale"}:
        model = resolve_image_model(str(payload.get("model") or payload.get("image_service") or "banana_pro"))
        model_cfg = IMAGE_MODEL_CONFIGS.get(model, IMAGE_MODEL_CONFIGS["banana_pro"])
        aspect_ratio = str(options.get("aspect_ratio") or payload.get("aspect_ratio") or model_cfg["defaults"].get("aspect_ratio") or "1:1")
        if flow == "multi_photo" and len(refs) < 2:
            return _json({"ok": False, "error": "multi_photo_refs_required"}, status=400)
        if flow == "multi_photo":
            mix_jobs = []
            for mix_model in TMA_MIX_PHOTO_MODELS:
                mix_options = normalize_image_options(
                    mix_model,
                    {"aspect_ratio": aspect_ratio, **options},
                )
                mix_jobs.append(
                    {
                        "model": mix_model,
                        "options": mix_options,
                        "cost": int(preset_manager.get_generation_cost(mix_model)),
                    }
                )
            total_cost = sum(job["cost"] for job in mix_jobs)
            if not await _can_start_generation(telegram_id, total_cost, usage_type="image", model="mix_photo"):
                return _json({"ok": False, "error": "insufficient_balance"}, status=402)
            tasks = []
            for job in mix_jobs:
                result = await _run_tma_image_model(
                    str(job["model"]),
                    prompt,
                    refs,
                    job["options"],
                    callback_url,
                )
                job_task_id = str((result or {}).get("task_id") or "")
                if not job_task_id:
                    continue
                charged, source, usage_id = await _charge_generation(
                    telegram_id,
                    usage_type="image",
                    model=str(job["model"]),
                    task_id=job_task_id,
                    cost=int(job["cost"]),
                    metadata={"flow": "multi_photo", "model": job["model"], "mix": True},
                )
                if not charged:
                    continue
                await database.add_generation_task(
                    user_id=user_row.id,
                    telegram_id=telegram_id,
                    task_id=job_task_id,
                    type="image",
                    preset_id="multi_photo",
                    model=str(job["model"]),
                    duration=None,
                    aspect_ratio=str(job["options"].get("aspect_ratio") or aspect_ratio),
                    prompt=prompt,
                    cost=int(job["cost"]),
                    reference_images=json.dumps(refs, ensure_ascii=False),
                    billing_source=source,
                    subscription_usage_id=usage_id,
                )
                task = await _query_one("SELECT * FROM generation_tasks WHERE task_id = ?", (job_task_id,))
                if task:
                    tasks.append(task)
            if not tasks:
                return _json({"ok": False, "error": "provider_failed"}, status=502)
            return _json(
                {
                    "ok": True,
                    "tasks": tasks,
                    "task": tasks[0],
                    "stats": await database.get_user_stats(telegram_id),
                }
            )
        if model_cfg.get("requires_refs") and not refs:
            return _json({"ok": False, "error": "refs_required"}, status=400)
        cost = int(preset_manager.get_generation_cost(model_cfg.get("cost_key") or model))
        try:
            img_count = int(payload.get("count") or payload.get("img_count") or 1)
        except (TypeError, ValueError):
            img_count = 1
        img_count = max(1, min(img_count, TMA_MAX_IMAGE_VARIATIONS))
        total_cost = cost * img_count
        if not await _can_start_generation(telegram_id, total_cost, usage_type="image", model=model, count=img_count):
            return _json({"ok": False, "error": "insufficient_balance"}, status=402)
        model_options = normalize_image_options(
            model,
            {"aspect_ratio": aspect_ratio, **options},
        )
        tasks = []
        for index in range(img_count):
            result = await _run_tma_image_model(
                model,
                prompt,
                refs,
                model_options,
                callback_url,
            )
            job_task_id = str((result or {}).get("task_id") or "")
            if not job_task_id:
                continue
            charged, source, usage_id = await _charge_generation(
                telegram_id,
                usage_type="image",
                model=model,
                task_id=job_task_id,
                cost=cost,
                metadata={
                    "flow": flow,
                    "model": model,
                    "count": img_count,
                    "variation": index + 1,
                },
            )
            if not charged:
                continue
            await database.add_generation_task(
                user_id=user_row.id,
                telegram_id=telegram_id,
                task_id=job_task_id,
                type="image",
                preset_id=flow,
                model=model,
                duration=None,
                aspect_ratio=str(model_options.get("aspect_ratio") or aspect_ratio),
                prompt=prompt,
                cost=cost,
                reference_images=json.dumps(refs, ensure_ascii=False),
                billing_source=source,
                subscription_usage_id=usage_id,
            )
            task = await _query_one("SELECT * FROM generation_tasks WHERE task_id = ?", (job_task_id,))
            if task:
                tasks.append(task)
        if not tasks:
            return _json({"ok": False, "error": "provider_failed"}, status=502)
        return _json(
            {
                "ok": True,
                "tasks": tasks,
                "task": tasks[0],
                "stats": await database.get_user_stats(telegram_id),
            }
        )
    elif flow in {"video_text", "image_to_video", "video_edit", "motion_control", "gemini_omni"}:
        model = str(payload.get("model") or "v3_std")
        model_cfg = VIDEO_MODEL_CONFIGS.get(model, VIDEO_MODEL_CONFIGS["v3_std"])
        duration = int(payload.get("duration") or 5)
        aspect_ratio = str(payload.get("aspect_ratio") or "16:9")
        if model_cfg.get("requires_refs") and not refs:
            return _json({"ok": False, "error": "refs_required"}, status=400)
        cost = int(preset_manager.get_video_cost(model, duration))
        if not await _can_start_generation(telegram_id, cost, usage_type="video", model=model):
            return _json({"ok": False, "error": "insufficient_balance"}, status=402)
        image_refs = [
            url for url in refs if not re.search(r"\.(mp4|mov|webm|m4v)(\?|#|$)", url, re.I)
        ]
        video_refs = [
            url for url in refs if re.search(r"\.(mp4|mov|webm|m4v)(\?|#|$)", url, re.I)
        ]
        image_url = image_refs[0] if image_refs else None
        if flow == "motion_control":
            motion_photo_url = str(payload.get("motion_photo_url") or "")
            motion_video_url = str(payload.get("motion_video_url") or "")
            if not motion_photo_url:
                motion_photo_url = next((url for url in refs if not re.search(r"\.(mp4|mov|webm|m4v)(\?|#|$)", url, re.I)), "")
            if not motion_video_url:
                motion_video_url = next((url for url in refs if re.search(r"\.(mp4|mov|webm|m4v)(\?|#|$)", url, re.I)), "")
            if not motion_photo_url or not motion_video_url:
                return _json({"ok": False, "error": "motion_refs_required"}, status=400)
            result = await kling_service.generate_motion_control(
                image_url=motion_photo_url,
                video_urls=[motion_video_url],
                prompt=prompt,
                motion_direction=str(options.get("character_orientation") or "video"),
                keep_original_sound=bool(options.get("keep_original_sound", True)),
                mode=str(options.get("motion_quality") or ("1080p" if model == "v3_pro" else "720p")),
                aspect_ratio=aspect_ratio,
                webhook_url=callback_url,
            )
        elif model == "gemini_omni":
            video_refs = [
                url
                for url in refs
                if url.rsplit(".", 1)[-1].lower() in {"mp4", "mov", "webm", "m4v"}
            ][:1]
            image_refs = [url for url in refs if url not in video_refs]
            seed_value = options.get("seed") or payload.get("seed")
            try:
                seed = int(seed_value) if seed_value not in (None, "") else None
            except (TypeError, ValueError):
                seed = None
            result = await gemini_omni_service.generate_video(
                prompt=prompt,
                image_urls=image_refs,
                video_urls=video_refs,
                audio_ids=[
                    str(item)
                    for item in (payload.get("audio_ids") or options.get("audio_ids") or [])
                    if str(item).strip()
                ],
                character_ids=[
                    str(item)
                    for item in (payload.get("character_ids") or options.get("character_ids") or [])
                    if str(item).strip()
                ],
                duration=duration,
                aspect_ratio=aspect_ratio,
                resolution=str(options.get("resolution") or payload.get("resolution") or "720p"),
                seed=seed,
                callback_url=callback_url,
            )
        elif model in {"wan_27_t2v", "wan_27_i2v", "wan_27_r2v", "wan_27_videoedit"}:
            seed_value = options.get("seed", payload.get("seed"))
            try:
                wan_seed = int(seed_value) if seed_value not in (None, "") else None
            except (TypeError, ValueError):
                wan_seed = None
            result = await kling_service.generate_video(
                prompt=prompt,
                model=model,
                duration=duration,
                aspect_ratio=aspect_ratio,
                webhook_url=callback_url,
                image_url=image_url,
                video_urls=video_refs,
                image_input=image_refs,
                negative_prompt=str(
                    options.get("negative_prompt")
                    or payload.get("negative_prompt")
                    or ""
                )
                or None,
                seedance_resolution=str(
                    options.get("resolution") or payload.get("resolution") or "1080p"
                ),
                wan_resolution=str(
                    options.get("resolution") or payload.get("resolution") or "1080p"
                ),
                wan_prompt_extend=bool(options.get("prompt_extend", True)),
                wan_watermark=bool(options.get("watermark", False)),
                wan_nsfw_checker=bool(options.get("nsfw_checker", True)),
                wan_audio_url=str(options.get("audio_url") or payload.get("audio_url") or "")
                or None,
                wan_driving_audio_url=str(
                    options.get("driving_audio_url")
                    or payload.get("driving_audio_url")
                    or ""
                )
                or None,
                wan_first_clip_url=str(
                    options.get("first_clip_url")
                    or payload.get("first_clip_url")
                    or ""
                )
                or None,
                wan_reference_voice=str(
                    options.get("reference_voice")
                    or payload.get("reference_voice")
                    or ""
                )
                or None,
                wan_reference_image=image_refs,
                wan_reference_video=video_refs,
                wan_reference_image_url=str(
                    options.get("reference_image")
                    or payload.get("reference_image")
                    or ""
                )
                or (image_refs[0] if image_refs else None),
                wan_seed=wan_seed,
            )
        elif model == "runway":
            result = await runway_service.generate_video(
                prompt,
                image_url=image_url,
                duration=duration,
                aspect_ratio=aspect_ratio,
                callback_url=callback_url,
            )
        elif model == "grok_imagine":
            result = await grok_service.generate_image_to_video(
                image_urls=refs[:7],
                prompt=prompt,
                mode=str(options.get("mode") or "normal"),
                duration=duration,
                resolution=str(options.get("resolution") or "720p"),
                aspect_ratio=aspect_ratio,
                nsfw_checker=bool(options.get("nsfw_checker", False)),
                callBackUrl=callback_url,
            )
        else:
            result = await kling_service.generate_video(
                prompt=prompt,
                model=model,
                duration=duration,
                aspect_ratio=aspect_ratio,
                webhook_url=callback_url,
                image_url=image_url,
                image_input=refs,
                generate_audio=bool(options.get("sound", payload.get("sound", True))),
            )
        task_id = str((result or {}).get("task_id") or "")
        usage_type = "video"
        task_type = "video"
    else:
        return _json({"ok": False, "error": "unknown_flow"}, status=400)

    if not task_id:
        return _json({"ok": False, "error": "provider_failed"}, status=502)

    charged, source, usage_id = await _charge_generation(
        telegram_id,
        usage_type=usage_type,
        model=model,
        task_id=task_id,
        cost=cost,
        metadata={"flow": flow, "model": model},
    )
    if not charged:
        return _json({"ok": False, "error": "insufficient_balance"}, status=402)

    await database.add_generation_task(
        user_id=user_row.id,
        telegram_id=telegram_id,
        task_id=task_id,
        type=task_type,
        preset_id=flow,
        model=model,
        duration=duration,
        aspect_ratio=aspect_ratio,
        prompt=prompt,
        cost=cost,
        reference_images=json.dumps(refs, ensure_ascii=False),
        billing_source=source,
        subscription_usage_id=usage_id,
    )
    return _json(
        {
            "ok": True,
            "task": await _query_one("SELECT * FROM generation_tasks WHERE task_id = ?", (task_id,)),
            "stats": await database.get_user_stats(telegram_id),
        }
    )


async def handle_tma_app_gpt55(request: web.Request) -> web.Response:
    user = await require_tma_user(request)
    telegram_id = _telegram_id(user)
    payload = await _read_json(request)
    message = str(payload.get("message") or "").strip()
    if not message:
        return _json({"ok": False, "error": "message_required"}, status=400)
    content = [{"type": "input_text", "text": message}]
    history = await database.get_gpt55_history(telegram_id, limit=20)
    answer = await gpt55_service.ask(content, history=history)
    if not answer:
        return _json({"ok": False, "error": "gpt_unavailable"}, status=502)
    await database.append_gpt55_history(telegram_id, content, answer)
    return _json({"ok": True, "answer": answer, "history": await database.get_gpt55_history(telegram_id, limit=20)})


async def handle_tma_app_gpt55_stream(request: web.Request) -> web.StreamResponse:
    user = await require_tma_user(request)
    telegram_id = _telegram_id(user)
    payload = await _read_json(request)
    message = str(payload.get("message") or "").strip()
    if not message:
        return _json({"ok": False, "error": "message_required"}, status=400)

    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)

    async def send_event(event: str, data: dict[str, Any]) -> None:
        payload_text = json.dumps(data, ensure_ascii=False, default=_json_default)
        await response.write(f"event: {event}\ndata: {payload_text}\n\n".encode("utf-8"))

    content = [{"type": "input_text", "text": message}]
    history = await database.get_gpt55_history(telegram_id, limit=20)
    answer_parts: list[str] = []
    try:
        async for delta in gpt55_service.stream(content, history=history):
            answer_parts.append(delta)
            await send_event("delta", {"delta": delta})

        answer = "".join(answer_parts).strip()
        if not answer:
            await send_event("error", {"error": "gpt_unavailable"})
            await response.write_eof()
            return response

        await database.append_gpt55_history(telegram_id, content, answer)
        await send_event(
            "done",
            {
                "answer": answer,
                "history": await database.get_gpt55_history(telegram_id, limit=20),
            },
        )
    except Exception as exc:
        logger.exception("TMA GPT 5.5 stream failed: %s", exc)
        await send_event("error", {"error": "gpt_unavailable"})
    await response.write_eof()
    return response


async def handle_tma_app_gpt55_clear(request: web.Request) -> web.Response:
    user = await require_tma_user(request)
    await database.clear_gpt55_history(_telegram_id(user))
    return _json({"ok": True, "history": []})


async def handle_tma_app_photo_to_prompt(request: web.Request) -> web.Response:
    user = await require_tma_user(request)
    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "file":
        return _json({"ok": False, "error": "file_required"}, status=400)
    filename = field.filename or "photo.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    if ext not in {"jpg", "jpeg", "png", "webp"}:
        return _json({"ok": False, "error": "bad_file_type"}, status=400)
    image_bytes = await field.read(decode=False)
    if len(image_bytes) > 12 * 1024 * 1024:
        return _json({"ok": False, "error": "file_too_large"}, status=400)
    prompt = await asyncio.to_thread(image_analyzer_service.analyze_image, image_bytes)
    prompt = re.sub(r"<[^>]*>", "", str(prompt or "")).strip()
    if not prompt or prompt.lower().startswith("ошибка анализа:"):
        return _json({"ok": False, "error": "analysis_failed"}, status=502)
    return _json(
        {
            "ok": True,
            "prompt": prompt,
            "stats": await database.get_user_stats(_telegram_id(user)),
        }
    )


async def handle_tma_app_prompt_builder(request: web.Request) -> web.Response:
    user = await require_tma_user(request)
    payload = await _read_json(request)
    idea = str(payload.get("idea") or payload.get("message") or "").strip()
    if len(idea) < 3:
        return _json({"ok": False, "error": "idea_required"}, status=400)
    task = (
        "Собери production-ready промпт для генерации изображения или видео. "
        "Ответь только готовым промптом без вступления. Сделай его конкретным, "
        "визуальным, с деталями композиции, света, стиля, камеры и качества. "
        f"Идея пользователя: {idea}"
    )
    answer = await gpt55_service.ask(
        [{"type": "input_text", "text": task}],
        history=[],
        reasoning_effort="medium",
        web_search=False,
    )
    if not answer:
        return _json({"ok": False, "error": "gpt_unavailable"}, status=502)
    await database.append_gpt55_history(
        _telegram_id(user),
        [{"type": "input_text", "text": idea}],
        answer,
    )
    return _json(
        {
            "ok": True,
            "prompt": answer,
            "history": await database.get_gpt55_history(_telegram_id(user), limit=20),
        }
    )


async def handle_tma_app_settings(request: web.Request) -> web.Response:
    user = await require_tma_user(request)
    telegram_id = _telegram_id(user)
    payload = await _read_json(request)
    allowed = {
        "preferred_model": payload.get("preferred_model"),
        "preferred_video_model": payload.get("preferred_video_model"),
        "preferred_i2v_model": payload.get("preferred_i2v_model"),
        "image_service": payload.get("image_service"),
    }
    await database.save_user_settings(telegram_id, **{k: v for k, v in allowed.items() if v is not None})
    return _json({"ok": True, "settings": await database.get_user_settings(telegram_id)})


async def handle_tma_app_promo(request: web.Request) -> web.Response:
    user = await require_tma_user(request)
    telegram_id = _telegram_id(user)
    payload = await _read_json(request)
    ok, reason, promo = await database.validate_promo_code(telegram_id, str(payload.get("code") or ""))
    if not ok:
        return _json({"ok": False, "error": reason}, status=400)
    if promo.get("promo_type") in {"bananas", "generation"}:
        marked, mark_reason = await database.mark_promo_code_used(
            telegram_id,
            promo["code"],
            order_id=f"tma:{promo['promo_type']}:{promo['code']}:{telegram_id}:{int(time.time())}",
        )
        if not marked:
            return _json({"ok": False, "error": mark_reason}, status=400)
        reward = int(promo.get("reward_credits") or 0)
        if promo["promo_type"] == "generation":
            credited = await database.add_free_generations(telegram_id, reward)
        else:
            credited = await database.add_credits_once(
                telegram_id,
                reward,
                reason="promo_bonus",
                external_id=f"tma_promo:{promo['code']}:{telegram_id}",
                metadata={"promo_code": promo["code"]},
            )
        return _json({"ok": True, "promo": promo, "credited": credited, "stats": await database.get_user_stats(telegram_id)})
    return _json({"ok": True, "promo": promo})


async def handle_tma_app_payment(request: web.Request) -> web.Response:
    user = await require_tma_user(request)
    telegram_id = _telegram_id(user)
    payload = await _read_json(request)
    package_id = str(payload.get("package_id") or "")
    provider = str(payload.get("provider") or config.payment_provider)
    recurring_requested = bool(payload.get("recurring"))
    package = await admin_package_config_service.get_package(package_id)
    if not package or package.get("hidden"):
        return _json({"ok": False, "error": "package_not_found"}, status=404)
    if provider not in {"tbank", "cryptobot"}:
        provider = config.payment_provider
    is_subscription = subscription_service.is_subscription_package(package)
    if recurring_requested and (provider != "tbank" or not is_subscription):
        return _json({"ok": False, "error": "recurring_not_available"}, status=400)

    promo = payload.get("promo") if isinstance(payload.get("promo"), dict) else {}
    promo_code = str(promo.get("code") or "")
    promo_discount_percent = int(promo.get("discount_percent") or 0)
    original_price_rub = int(package["price_rub"])
    amount_rub = original_price_rub
    if promo_code and promo_discount_percent:
        valid, reason, promo_row = await database.validate_promo_code(telegram_id, promo_code)
        if not valid:
            return _json({"ok": False, "error": reason}, status=400)
        promo_discount_percent = int(promo_row["discount_percent"])
        amount_rub = max(1, original_price_rub * (100 - promo_discount_percent) // 100)

    total_credits = int(package.get("credits") or 0) + int(package.get("bonus_credits") or 0)
    order_id = f"{telegram_id}_{int(time.time())}_{package_id}"
    success_url = config.MINI_APP_URL or f"{config.WEBHOOK_HOST.rstrip('/')}/miniapp"
    fail_url = success_url
    if provider == "cryptobot":
        result = await cryptobot_service.create_invoice(
            amount_rub=float(amount_rub),
            order_id=order_id,
            description=f"Покупка {total_credits} BoomCoin ({package['name']})",
            paid_btn_url=success_url,
        )
    else:
        result = await tbank_service.init_payment(
            amount=int(amount_rub * 100),
            order_id=order_id,
            description=f"Покупка {total_credits} BoomCoin ({package['name']})",
            customer_key=str(telegram_id),
            success_url=success_url,
            fail_url=fail_url,
            notification_url=config.tbank_notification_url,
            recurrent=recurring_requested,
        )
    payment_id = (result or {}).get("PaymentId") or (result or {}).get("payment_id")
    payment_url = (result or {}).get("PaymentURL") or (result or {}).get("PaymentUrl") or (result or {}).get("payment_url")
    if not result or not payment_id or not payment_url:
        return _json({"ok": False, "error": "payment_provider_failed", "provider_response": result}, status=502)

    user_row = await database.get_or_create_user(telegram_id)
    await database.create_transaction(
        order_id=order_id,
        user_id=user_row.id,
        payment_id=str(payment_id),
        provider=provider,
        credits=total_credits,
        amount_rub=float(amount_rub),
        original_amount_rub=float(original_price_rub),
        promo_code=promo_code or None,
        promo_discount_percent=promo_discount_percent,
        status="pending",
    )
    if recurring_requested:
        await database.upsert_recurring_subscription(
            telegram_id,
            provider="tbank",
            package_id=package_id,
            package_name=str(package["name"]),
            amount_rub=float(amount_rub),
            credits=total_credits,
            customer_key=str(telegram_id),
            status="pending",
        )
    return _json({"ok": True, "order_id": order_id, "payment_url": payment_url, "payment_id": str(payment_id)})


async def handle_tma_app_payment_check(request: web.Request) -> web.Response:
    user = await require_tma_user(request)
    telegram_id = _telegram_id(user)
    order_id = request.match_info["order_id"]
    transaction = await database.get_transaction_by_order(order_id)
    if not transaction:
        return _json({"ok": False, "error": "not_found"}, status=404)
    owner = await database.get_telegram_id_by_user_id(transaction.user_id)
    if int(owner or 0) != telegram_id:
        return _json({"ok": False, "error": "forbidden"}, status=403)
    provider_state = None
    if transaction.status != "completed":
        if transaction.provider == "cryptobot":
            invoice = await cryptobot_service.get_invoice(transaction.payment_id)
            paid = bool(invoice and invoice.get("status") == "paid")
            provider_state = invoice
        else:
            provider_state = await tbank_service.get_state(transaction.payment_id)
            paid = bool(provider_state and provider_state.get("Status") == "CONFIRMED")
        if paid:
            from bot.handlers.payments import _complete_transaction

            await _complete_transaction(order_id, payment_data=provider_state)
    updated = await database.get_transaction_by_order(order_id)
    payment = updated.__dict__ if updated else None
    return _json({"ok": True, "payment": payment, "stats": await database.get_user_stats(telegram_id)})


async def handle_tma_app_recurring_disable(request: web.Request) -> web.Response:
    user = await require_tma_user(request)
    telegram_id = _telegram_id(user)
    ok = await database.disable_recurring_subscription(telegram_id, reason="tma_user_disabled")
    return _json({"ok": ok, "recurring": await database.get_recurring_subscription(telegram_id)})


async def handle_tma_app_partner(request: web.Request) -> web.Response:
    user = await require_tma_user(request)
    telegram_id = _telegram_id(user)
    payload = await _read_json(request)
    action = str(payload.get("action") or "")
    if action == "accept":
        await database.accept_partner_agreement(telegram_id)
        from bot.database import generate_referral_code, update_user_referral_code

        user_row = await database.get_or_create_user(telegram_id)
        if not user_row.referral_code:
            await update_user_referral_code(telegram_id, await generate_referral_code())
    elif action == "convert":
        credits = int(payload.get("credits") or 0)
        result = await database.convert_partner_balance_to_credits(
            telegram_id,
            credits,
            config.PARTNER_RUB_PER_CREDIT,
        )
        if not result:
            return _json({"ok": False, "error": "convert_failed"}, status=400)
    elif action == "withdraw":
        withdrawal_id = await database.create_partner_withdrawal(
            telegram_id,
            float(payload.get("amount_rub") or 0),
            method=str(payload.get("method") or "card"),
            requisites=str(payload.get("requisites") or ""),
            recipient_name=str(payload.get("recipient_name") or ""),
            phone=str(payload.get("phone") or ""),
            card_mask=str(payload.get("card_mask") or "")[-4:],
        )
        if not withdrawal_id:
            return _json({"ok": False, "error": "withdrawal_failed"}, status=400)
    else:
        return _json({"ok": False, "error": "unknown_action"}, status=400)
    return _json(
        {
            "ok": True,
            "partner": await database.get_partner_overview(telegram_id),
            "withdrawals": await database.get_recent_partner_withdrawals(telegram_id, limit=10),
            "stats": await database.get_user_stats(telegram_id),
        }
    )


async def handle_tma_app_feed_action(request: web.Request) -> web.Response:
    user = await require_tma_user(request)
    telegram_id = _telegram_id(user)
    task_id = request.match_info["task_id"]
    payload = await _read_json(request)
    action = str(payload.get("action") or "")
    if action == "like":
        value = await database.like_feed_task(task_id, telegram_id)
        ok = value is not None
    elif action == "share":
        value = await database.increment_feed_share(task_id, telegram_id)
        ok = value is not None
    elif action == "publish":
        ok, reason = await database.share_task_to_feed(task_id, telegram_id)
        value = reason
    else:
        return _json({"ok": False, "error": "unknown_action"}, status=400)
    return _json({"ok": bool(ok), "value": value, "feed": await _feed(limit=60), "tasks": await _user_tasks(telegram_id)})


async def handle_tma_admin_bootstrap(request: web.Request) -> web.Response:
    user = await require_admin(request)
    limit = _production_limit(request)
    data = {
        "admin": user,
        "dashboard": await _dashboard(),
        "limits": {"mode": config.MINI_APP_MODE, "production_limit": limit, "max_limit": 5000},
        "users": [],
        "payments": [],
        "subscriptions": [],
        "recurring": [],
        "generations": [],
        "feed": [],
        "packages": [],
        "promos": [],
        "partners": [],
        "withdrawals": [],
        "referrals": {"config": {}, "payouts": []},
        "push": {"config": {}, "due_events": []},
        "system": {},
    }
    return _json({"ok": True, "data": data})


async def handle_tma_admin_users(request: web.Request) -> web.Response:
    await require_admin(request)
    return _json(
        {
            "ok": True,
            "users": await _users(
                request.query.get("search", ""),
                int(request.query.get("limit", "80")),
            ),
        }
    )


async def handle_tma_admin_user_action(request: web.Request) -> web.Response:
    admin = await require_admin(request)
    telegram_id = int(request.match_info["telegram_id"])
    payload = await _read_json(request)
    action = str(payload.get("action") or "")
    if action == "add_credits":
        amount = int(payload.get("amount") or 0)
        ok = amount > 0 and await database.add_credits(
            telegram_id,
            amount,
            reason="tma_admin_add",
            external_id=f"tma:{admin.get('id')}:add:{telegram_id}:{datetime.now().timestamp()}",
            metadata={"admin_id": admin.get("id")},
        )
    elif action == "deduct_credits":
        amount = int(payload.get("amount") or 0)
        ok = amount > 0 and await database.deduct_credits(
            telegram_id,
            amount,
            reason="tma_admin_deduct",
            external_id=f"tma:{admin.get('id')}:deduct:{telegram_id}:{datetime.now().timestamp()}",
            metadata={"admin_id": admin.get("id")},
        )
    elif action == "ban":
        ok = await database.set_user_banned(telegram_id, True)
    elif action == "unban":
        ok = await database.set_user_banned(telegram_id, False)
    else:
        return _json({"ok": False, "error": "unknown_action"}, status=400)
    stats = await database.get_user_stats(telegram_id)
    return _json({"ok": bool(ok), "user": stats})


async def handle_tma_admin_payment_action(request: web.Request) -> web.Response:
    await require_admin(request)
    order_id = request.match_info["order_id"]
    payload = await _read_json(request)
    action = str(payload.get("action") or "")
    transaction = await database.get_transaction_by_order(order_id)
    if transaction is None:
        return _json({"ok": False, "error": "not_found"}, status=404)

    provider_state = None
    if action == "mark_completed":
        from bot.handlers.payments import _complete_transaction

        ok = await _complete_transaction(order_id)
    elif action == "mark_failed":
        ok = await database.update_transaction_status(order_id, "failed")
    elif action == "mark_pending":
        ok = await database.update_transaction_status(order_id, "pending")
    elif action == "check_provider":
        if transaction.provider in {"tbank", "tbank_recurring"} and transaction.payment_id:
            provider_state = await tbank_service.get_state(transaction.payment_id)
            status = str(provider_state.get("Status") or "").lower() if provider_state else ""
            if status == "confirmed":
                from bot.handlers.payments import _complete_transaction

                await _complete_transaction(order_id, payment_data=provider_state)
            elif status in {"rejected", "cancelled", "canceled", "dead"}:
                await database.update_transaction_status(order_id, "failed")
            ok = True
        else:
            ok = False
    else:
        return _json({"ok": False, "error": "unknown_action"}, status=400)
    return _json(
        {
            "ok": bool(ok),
            "provider_state": provider_state,
            "payments": await _payments(_production_limit(request)),
        }
    )


async def handle_tma_admin_recurring_action(request: web.Request) -> web.Response:
    await require_admin(request)
    telegram_id = int(request.match_info["telegram_id"])
    payload = await _read_json(request)
    action = str(payload.get("action") or "disable")
    if action != "disable":
        return _json({"ok": False, "error": "unknown_action"}, status=400)
    ok = await database.disable_recurring_subscription(
        telegram_id,
        reason=str(payload.get("reason") or "tma_admin_disabled"),
    )
    return _json({"ok": ok, "recurring": await _recurring(_production_limit(request))})


async def handle_tma_admin_generation_action(request: web.Request) -> web.Response:
    await require_admin(request)
    task_id = request.match_info["task_id"]
    payload = await _read_json(request)
    action = str(payload.get("action") or "")
    task = await database.get_task_by_id(task_id)
    if task is None:
        return _json({"ok": False, "error": "not_found"}, status=404)
    if action == "refund":
        ok = await database.refund_generation_billing(task_id, reason="tma_admin_refund")
    elif action == "fail":
        ok = await database.fail_generation_task(task_id)
    elif action == "complete":
        result_url = str(payload.get("result_url") or task.result_url or "")
        if not result_url:
            return _json({"ok": False, "error": "result_url_required"}, status=400)
        ok = await database.complete_video_task(task_id, result_url)
    elif action == "publish_feed":
        ok, reason = await database.share_task_to_feed(task_id, int(task.telegram_id or 0))
        if not ok:
            return _json({"ok": False, "error": reason}, status=400)
    elif action == "remove_feed":
        ok = await database.remove_task_from_feed(task_id, int(task.telegram_id or 0))
    else:
        return _json({"ok": False, "error": "unknown_action"}, status=400)
    return _json({"ok": bool(ok), "generations": await _generations(_production_limit(request))})


async def handle_tma_admin_feed_action(request: web.Request) -> web.Response:
    await require_admin(request)
    task_id = request.match_info["task_id"]
    payload = await _read_json(request)
    action = str(payload.get("action") or "")
    if action == "like":
        value = await database.like_feed_task(task_id)
        ok = value is not None
    elif action == "share":
        value = await database.increment_feed_share(task_id)
        ok = value is not None
    elif action == "remove":
        task = await database.get_task_by_id(task_id)
        ok = bool(task and await database.remove_task_from_feed(task_id, int(task.telegram_id or 0)))
        value = None
    else:
        return _json({"ok": False, "error": "unknown_action"}, status=400)
    return _json({"ok": ok, "value": value, "feed": await _feed(min(_production_limit(request), 1000))})


async def handle_tma_admin_package_action(request: web.Request) -> web.Response:
    await require_admin(request)
    package_id = request.match_info["package_id"]
    payload = await _read_json(request)
    field = str(payload.get("field") or "")
    value = payload.get("value")
    service = admin_package_config_service
    if field in {"name", "kind", "period", "photo_limit_text", "video_limit_text"}:
        result = await service.set_text_field(package_id, field, str(value or ""))
    elif field == "price_rub":
        result = await service.set_price(package_id, int(value))
    elif field == "credits":
        result = await service.set_credits(package_id, int(value))
    elif field == "bonus_credits":
        result = await service.set_bonus(package_id, int(value))
    elif field == "subscription_days":
        result = await service.set_subscription_days(package_id, int(value))
    elif field == "image_limit":
        result = await service.set_image_limit(package_id, int(value))
    elif field == "video_limit":
        result = await service.set_video_limit(package_id, int(value))
    elif field in {"includes_pro", "priority"}:
        result = await service.set_bool_field(package_id, field, bool(value))
    elif field == "popular":
        result = await service.set_popular(package_id)
    elif field == "hidden":
        result = await service.set_hidden(package_id, bool(value))
    elif field == "discount_percent":
        result = await service.set_discount(package_id, int(value))
    else:
        return _json({"ok": False, "error": "unknown_field"}, status=400)
    return _json(
        {
            "ok": result.ok,
            "package": result.package,
            "error": result.error,
            "packages": await service.list_packages(include_hidden=True),
        },
        status=200 if result.ok else 400,
    )


async def handle_tma_admin_package_create(request: web.Request) -> web.Response:
    await require_admin(request)
    payload = await _read_json(request)
    result = await admin_package_config_service.create_package(payload)
    return _json(
        {
            "ok": result.ok,
            "package": result.package,
            "error": result.error,
            "packages": await admin_package_config_service.list_packages(include_hidden=True),
        },
        status=200 if result.ok else 400,
    )


async def handle_tma_admin_promos(request: web.Request) -> web.Response:
    admin = await require_admin(request)
    payload = await _read_json(request)
    expires_days = str(payload.get("expires_days") or "").strip()
    expires_at = None
    if expires_days:
        expires_at = (
            datetime.utcnow() + timedelta(days=max(1, int(expires_days)))
        ).isoformat(timespec="seconds")
    ok, result = await database.create_promo_code(
        code=str(payload.get("code") or ""),
        discount_percent=int(payload.get("discount_percent") or 0),
        max_uses=int(payload.get("max_uses") or 1),
        expires_at=expires_at,
        created_by=int(admin.get("id") or 0),
        promo_type=str(payload.get("promo_type") or "discount"),
        reward_credits=int(payload.get("reward_credits") or 0),
    )
    return _json(
        {
            "ok": ok,
            "result": result,
            "promos": await database.get_promo_codes(limit=60),
        },
        status=200 if ok else 400,
    )


async def handle_tma_admin_promo_action(request: web.Request) -> web.Response:
    await require_admin(request)
    code = request.match_info["code"]
    payload = await _read_json(request)
    if str(payload.get("action") or "deactivate") != "deactivate":
        return _json({"ok": False, "error": "unknown_action"}, status=400)
    ok = await database.deactivate_promo_code(code)
    return _json({"ok": ok, "promos": await database.get_promo_codes(limit=60)})


async def handle_tma_admin_referrals(request: web.Request) -> web.Response:
    await require_admin(request)
    payload = await _read_json(request)
    config_payload = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    if config_payload:
        await referral_admin_config_service.update_config(**config_payload)
    return _json({"ok": True, "referrals": await _referrals()})


async def handle_tma_admin_payout_action(request: web.Request) -> web.Response:
    await require_admin(request)
    payout_id = int(request.match_info["payout_id"])
    payload = await _read_json(request)
    status = str(payload.get("status") or "")
    comment = str(payload.get("comment") or "")
    if status not in {"pending", "paid", "frozen"}:
        return _json({"ok": False, "error": "bad_status"}, status=400)
    payout = await referral_admin_config_service.update_payout_status(
        payout_id,
        status,
        comment or None,
    )
    return _json({"ok": payout is not None, "referrals": await _referrals()})


async def handle_tma_admin_withdrawal_action(request: web.Request) -> web.Response:
    await require_admin(request)
    withdrawal_id = int(request.match_info["withdrawal_id"])
    payload = await _read_json(request)
    status = str(payload.get("status") or "")
    if status not in {"requested", "processing", "completed", "failed", "cancelled"}:
        return _json({"ok": False, "error": "bad_status"}, status=400)
    ok = await database.update_partner_withdrawal_status(
        withdrawal_id,
        status=status,
        status_title=str(payload.get("status_title") or status),
        error_message=str(payload.get("error_message") or "") or None,
    )
    return _json({"ok": ok, "withdrawals": await _withdrawals(_production_limit(request))})


async def handle_tma_admin_push(request: web.Request) -> web.Response:
    await require_admin(request)
    payload = await _read_json(request)
    if "enabled" in payload:
        await push_scenario_service.set_enabled(bool(payload.get("enabled")))
    if isinstance(payload.get("rules"), list):
        current = await push_scenario_service.get_config()
        raw = current.to_json()
        by_key = {str(item.get("key")): item for item in payload["rules"] if isinstance(item, dict)}
        for rule in raw["rules"]:
            if rule["key"] in by_key:
                rule.update(by_key[rule["key"]])
        await push_scenario_service.save_config(PushScenarioConfig.from_json(raw))
    return _json({"ok": True, "push": await _push()})


async def handle_tma_admin_broadcast(request: web.Request) -> web.Response:
    await require_admin(request)
    payload = await _read_json(request)
    text = str(payload.get("text") or "").strip()
    if not text:
        return _json({"ok": False, "error": "empty_text"}, status=400)
    try:
        requested_limit = int(payload.get("limit") or _production_limit(request))
    except (TypeError, ValueError):
        requested_limit = _production_limit(request)
    limit = max(1, min(requested_limit, _production_limit(request), 5000))
    users = await _users(limit=limit)
    bot = request.app.get("bot")
    if bot is None:
        return _json({"ok": False, "error": "bot_unavailable"}, status=503)
    sent = 0
    failed = 0
    for user in users:
        telegram_id = int(user.get("telegram_id") or 0)
        if not telegram_id or user.get("is_banned"):
            continue
        try:
            await bot.send_message(telegram_id, text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
    return _json({"ok": True, "sent": sent, "failed": failed})


async def handle_tma_admin_settings(request: web.Request) -> web.Response:
    await require_admin(request)
    payload = await _read_json(request)
    if "maintenance" in payload:
        await database.set_bot_setting(
            "maintenance_mode",
            "1" if bool(payload.get("maintenance")) else "0",
        )
    return _json({"ok": True, "dashboard": await _dashboard(), "system": await _system()})


async def handle_tma_admin_collections(request: web.Request) -> web.Response:
    await require_admin(request)
    name = request.match_info["name"]
    limit = _production_limit(request)
    if name == "users":
        return _json({"ok": True, "users": await _users(limit=limit)})
    if name == "payments":
        return _json({"ok": True, "payments": await _payments(limit)})
    if name == "subscriptions":
        return _json({"ok": True, "subscriptions": await _subscriptions(limit)})
    if name == "recurring":
        return _json({"ok": True, "recurring": await _recurring(limit)})
    if name == "generations":
        return _json({"ok": True, "generations": await _generations(limit)})
    if name == "feed":
        return _json({"ok": True, "feed": await _feed(min(limit, 1000))})
    if name == "packages":
        return _json({"ok": True, "packages": await admin_package_config_service.list_packages(include_hidden=True)})
    if name == "promos":
        return _json({"ok": True, "promos": await database.get_promo_codes(limit=limit)})
    if name == "partners":
        return _json({"ok": True, "partners": await _partners(request.query.get("search", ""), limit)})
    if name == "withdrawals":
        return _json({"ok": True, "withdrawals": await _withdrawals(limit)})
    if name == "referrals":
        return _json({"ok": True, "referrals": await _referrals()})
    if name == "push":
        return _json({"ok": True, "push": await _push()})
    if name == "system":
        return _json({"ok": True, "system": await _system()})
    return _json({"ok": False, "error": "unknown_collection"}, status=404)


async def handle_tma_index(request: web.Request) -> web.Response:
    index_path = Path("tma/dist/index.html")
    if not index_path.exists():
        return web.Response(
            text="Mini App is not built yet. Run: cd tma && npm run build",
            status=503,
            content_type="text/plain",
        )
    return web.FileResponse(
        index_path,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


async def handle_tma_media_proxy(request: web.Request) -> web.Response:
    """Прокси для медиа-файлов. Скачивает внешний URL и кэширует локально."""
    task_id = request.match_info.get("task_id", "")
    if not task_id:
        return web.Response(text="missing task_id", status=400)

    task = await database.get_task_by_id(task_id)
    if not task or not task.result_url:
        return web.Response(text="not found", status=404)

    url = task.result_url

    # Если уже локальный — сразу отдаём
    if url.startswith("/uploads/") or url.startswith("uploads/"):
        return web.HTTPFound(location=url)

    # Если это внешний URL — скачиваем на сервер
    from bot.services.media_storage import download_media

    stored_url, error = await download_media(task_id, url)
    if stored_url and stored_url != url:
        # Обновляем в БД
        await database.update_task_result_url(task_id, stored_url)
        return web.HTTPFound(location=stored_url)

    # Не удалось скачать — редиректим на оригинал (возможно ещё живой)
    return web.HTTPFound(location=url)


def setup_tma_routes(app: web.Application) -> None:
    app.router.add_get("/api/tma/app/bootstrap", handle_tma_app_bootstrap)
    app.router.add_get("/api/tma/app/ws", handle_tma_app_ws)
    app.router.add_post("/api/tma/app/upload", handle_tma_app_upload)
    app.router.add_post("/api/tma/app/generation", handle_tma_app_generation)
    app.router.add_post("/api/tma/app/gpt55", handle_tma_app_gpt55)
    app.router.add_post("/api/tma/app/gpt55/stream", handle_tma_app_gpt55_stream)
    app.router.add_post("/api/tma/app/gpt55/clear", handle_tma_app_gpt55_clear)
    app.router.add_post("/api/tma/app/photo-to-prompt", handle_tma_app_photo_to_prompt)
    app.router.add_post("/api/tma/app/prompt-builder", handle_tma_app_prompt_builder)
    app.router.add_post("/api/tma/app/settings", handle_tma_app_settings)
    app.router.add_post("/api/tma/app/promo", handle_tma_app_promo)
    app.router.add_post("/api/tma/app/payment", handle_tma_app_payment)
    app.router.add_post("/api/tma/app/payment/{order_id}/check", handle_tma_app_payment_check)
    app.router.add_post("/api/tma/app/recurring/disable", handle_tma_app_recurring_disable)
    app.router.add_post("/api/tma/app/partner", handle_tma_app_partner)
    app.router.add_post("/api/tma/app/feed/{task_id}/action", handle_tma_app_feed_action)
    app.router.add_get("/api/tma/app/media/{task_id}", handle_tma_media_proxy)

    app.router.add_get("/api/tma/admin/bootstrap", handle_tma_admin_bootstrap)
    app.router.add_get("/api/tma/admin/users", handle_tma_admin_users)
    app.router.add_post(
        "/api/tma/admin/users/{telegram_id}/action",
        handle_tma_admin_user_action,
    )
    app.router.add_post(
        "/api/tma/admin/payments/{order_id}/action",
        handle_tma_admin_payment_action,
    )
    app.router.add_post(
        "/api/tma/admin/recurring/{telegram_id}/action",
        handle_tma_admin_recurring_action,
    )
    app.router.add_post(
        "/api/tma/admin/generations/{task_id}/action",
        handle_tma_admin_generation_action,
    )
    app.router.add_post(
        "/api/tma/admin/feed/{task_id}/action",
        handle_tma_admin_feed_action,
    )
    app.router.add_post(
        "/api/tma/admin/packages/{package_id}",
        handle_tma_admin_package_action,
    )
    app.router.add_post("/api/tma/admin/promos", handle_tma_admin_promos)
    app.router.add_post("/api/tma/admin/packages", handle_tma_admin_package_create)
    app.router.add_post("/api/tma/admin/promos/{code}", handle_tma_admin_promo_action)
    app.router.add_post("/api/tma/admin/referrals", handle_tma_admin_referrals)
    app.router.add_post("/api/tma/admin/payouts/{payout_id}", handle_tma_admin_payout_action)
    app.router.add_post(
        "/api/tma/admin/withdrawals/{withdrawal_id}",
        handle_tma_admin_withdrawal_action,
    )
    app.router.add_post("/api/tma/admin/push", handle_tma_admin_push)
    app.router.add_post("/api/tma/admin/broadcast", handle_tma_admin_broadcast)
    app.router.add_post("/api/tma/admin/settings", handle_tma_admin_settings)
    app.router.add_get("/api/tma/admin/{name}", handle_tma_admin_collections)

    dist = Path("tma/dist")
    assets = dist / "assets"
    if assets.exists():
        app.router.add_static("/miniapp/assets/", path=assets, show_index=False)
    app.router.add_get("/miniapp", handle_tma_index)
    app.router.add_get("/miniapp/", handle_tma_index)
