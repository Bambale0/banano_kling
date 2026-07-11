from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from typing import Any

from aiohttp import web

from bot import db as db_backend
from bot import internal_admin_api as base_api
from bot.config import config
from bot.internal_admin_user_commands import (
    CommandConflictError,
    CommandValidationError,
    _command_headers,
    _complete_command,
    _parse_command_payload,
    _reserve_command,
    internal_user_endpoint,
)

logger = logging.getLogger(__name__)

_ALLOWED_STATUSES = {
    "pending",
    "queued",
    "processing",
    "submitting",
    "completed",
    "failed",
}
_ALLOWED_TYPES = {"image", "video"}
_SENSITIVE_KEY_FRAGMENTS = (
    "token",
    "secret",
    "password",
    "authorization",
    "api_key",
    "apikey",
    "webhook",
    "callback",
)
_MAX_REQUEST_DEPTH = 5
_MAX_COLLECTION_ITEMS = 50
_MAX_STRING_LENGTH = 4000


def _service_envelope() -> dict[str, Any]:
    return base_api._service_envelope()


def _json_value(value: Any) -> Any:
    return base_api._json_value(value)


def _parse_operation_id(request: web.Request) -> int:
    raw_value = request.match_info.get("operation_id", "")
    try:
        operation_id = int(raw_value)
    except ValueError as exc:
        raise CommandValidationError("operation id must be an integer") from exc
    if operation_id <= 0:
        raise CommandValidationError("operation id must be positive")
    return operation_id


def _parse_optional_positive_int(value: str | None, *, field: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise CommandValidationError(f"{field} must be an integer") from exc
    if parsed <= 0:
        raise CommandValidationError(f"{field} must be positive")
    return parsed


def _parse_request_data(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _sanitize_value(value: Any, *, depth: int = 0, key: str = "") -> Any:
    normalized_key = key.lower().replace("-", "_")
    if any(fragment in normalized_key for fragment in _SENSITIVE_KEY_FRAGMENTS):
        return "[redacted]"
    if depth >= _MAX_REQUEST_DEPTH:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:_MAX_STRING_LENGTH]
    if isinstance(value, Mapping):
        return {
            str(child_key): _sanitize_value(
                child_value,
                depth=depth + 1,
                key=str(child_key),
            )
            for child_key, child_value in list(value.items())[:_MAX_COLLECTION_ITEMS]
        }
    if isinstance(value, (list, tuple)):
        return [
            _sanitize_value(item, depth=depth + 1)
            for item in list(value)[:_MAX_COLLECTION_ITEMS]
        ]
    return str(value)[:_MAX_STRING_LENGTH]


def _operation_from_row(row: Mapping[str, Any], *, include_details: bool = False) -> dict[str, Any]:
    item = {
        "id": int(row["id"]),
        "task_id": str(row["task_id"]),
        "user_id": int(row["user_id"]),
        "telegram_id": int(row["telegram_id"]) if row["telegram_id"] else None,
        "username": row["username"] if "username" in row.keys() else None,
        "first_name": row["first_name"] if "first_name" in row.keys() else None,
        "last_name": row["last_name"] if "last_name" in row.keys() else None,
        "type": row["type"],
        "preset_id": row["preset_id"],
        "model": row["model"],
        "status": row["status"],
        "cost": int(row["cost"] or 0),
        "duration": row["duration"],
        "aspect_ratio": row["aspect_ratio"],
        "parent_generation_id": row["parent_generation_id"],
        "action_type": row["action_type"],
        "created_at": _json_value(row["created_at"]),
        "completed_at": _json_value(row["completed_at"]),
        "updated_at": _json_value(row["updated_at"]),
        "refunded_credits": int(row["refunded_credits"] or 0),
    }
    item["refundable_credits"] = max(item["cost"] - item["refunded_credits"], 0)
    if include_details:
        item.update(
            {
                "prompt": row["prompt"],
                "result_url": row["result_url"],
                "result_urls": _sanitize_value(_parse_result_urls(row["result_urls"])),
                "request": _sanitize_value(_parse_request_data(row["request_data"])),
            }
        )
    return item


def _parse_result_urls(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return [str(value)]
    if isinstance(parsed, list):
        return [str(item) for item in parsed if item]
    return [str(value)]


_OPERATION_SELECT = """
    SELECT
        gt.id,
        gt.task_id,
        gt.user_id,
        gt.telegram_id,
        u.username,
        u.first_name,
        u.last_name,
        gt.type,
        gt.preset_id,
        gt.model,
        gt.status,
        gt.cost,
        gt.duration,
        gt.aspect_ratio,
        gt.prompt,
        gt.result_url,
        gt.result_urls,
        gt.request_data,
        gt.parent_generation_id,
        gt.action_type,
        gt.created_at,
        gt.completed_at,
        gt.updated_at,
        COALESCE((
            SELECT SUM(e.amount)
            FROM internal_admin_operation_events e
            WHERE e.operation_id = gt.id
              AND e.event_type = 'credits.refund'
              AND e.status = 'success'
        ), 0) AS refunded_credits
    FROM generation_tasks gt
    JOIN users u ON u.id = gt.user_id
"""


async def _fetch_operation(operation_id: int, *, for_update: bool = False) -> Mapping[str, Any] | None:
    suffix = " FOR UPDATE OF gt, u" if for_update else ""
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            f"{_OPERATION_SELECT} WHERE gt.id = ?{suffix}",
            (operation_id,),
        )
        return await cursor.fetchone()


async def _fetch_operation_in_connection(
    connection: db_backend.Connection,
    operation_id: int,
    *,
    for_update: bool,
) -> Mapping[str, Any] | None:
    connection.row_factory = db_backend.Row
    suffix = " FOR UPDATE OF gt, u" if for_update else ""
    cursor = await connection.execute(
        f"{_OPERATION_SELECT} WHERE gt.id = ?{suffix}",
        (operation_id,),
    )
    return await cursor.fetchone()


async def _record_event(
    connection: db_backend.Connection,
    *,
    operation_id: int,
    event_type: str,
    status: str,
    actor_id: str | None,
    request_id: str | None,
    idempotency_key: str | None,
    amount: int | None = None,
    related_operation_id: int | None = None,
    details: Mapping[str, object] | None = None,
) -> None:
    await connection.execute(
        """
        INSERT INTO internal_admin_operation_events (
            operation_id, event_type, status, actor_type, actor_id,
            request_id, idempotency_key, amount, related_operation_id, details
        ) VALUES (?, ?, ?, 'admin', ?, ?, ?, ?, ?, CAST(? AS JSONB))
        """,
        (
            operation_id,
            event_type,
            status,
            actor_id,
            request_id,
            idempotency_key,
            amount,
            related_operation_id,
            json.dumps(dict(details or {}), ensure_ascii=False),
        ),
    )


def _require_confirmation(actual: Any, expected: str) -> None:
    if str(actual or "") != expected:
        raise CommandConflictError(f"confirmation must equal {expected}")


def _command_response(payload: dict[str, Any]) -> web.Response:
    status = int(payload.get("_http_status", 200))
    response_payload = {key: value for key, value in payload.items() if key != "_http_status"}
    return web.json_response(response_payload, status=status)


@internal_user_endpoint
async def operations_handler(request: web.Request) -> web.Response:
    if request.method != "GET":
        return web.json_response({"error": "method_not_allowed"}, status=405)

    limit = base_api._parse_page_limit(request)
    cursor_id = base_api.decode_cursor(request.query.get("cursor"))
    query = (request.query.get("query") or "").strip()
    if len(query) > 120:
        raise CommandValidationError("query is too long")

    status_filter = (request.query.get("status") or "").strip().lower()
    if status_filter and status_filter not in _ALLOWED_STATUSES:
        raise CommandValidationError("unsupported operation status")
    type_filter = (request.query.get("type") or "").strip().lower()
    if type_filter and type_filter not in _ALLOWED_TYPES:
        raise CommandValidationError("unsupported operation type")
    user_id = _parse_optional_positive_int(request.query.get("user_id"), field="user_id")

    clauses: list[str] = []
    parameters: list[Any] = []
    if cursor_id is not None:
        clauses.append("gt.id < ?")
        parameters.append(cursor_id)
    if query:
        pattern = f"%{query.lower()}%"
        clauses.append(
            "(CAST(gt.id AS TEXT) = ? OR LOWER(gt.task_id) LIKE ? "
            "OR CAST(gt.telegram_id AS TEXT) = ? OR LOWER(COALESCE(u.username, '')) LIKE ?)"
        )
        parameters.extend([query, pattern, query, pattern])
    if status_filter:
        clauses.append("LOWER(gt.status) = ?")
        parameters.append(status_filter)
    if type_filter:
        clauses.append("LOWER(gt.type) = ?")
        parameters.append(type_filter)
    if user_id is not None:
        clauses.append("gt.user_id = ?")
        parameters.append(user_id)

    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    parameters.append(limit + 1)
    rows = await base_api._fetch_all(
        f"{_OPERATION_SELECT}{where_sql} ORDER BY gt.id DESC LIMIT ?",
        tuple(parameters),
    )
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [_operation_from_row(row) for row in page_rows]
    next_cursor = (
        base_api.encode_cursor(int(page_rows[-1]["id"]))
        if has_more and page_rows
        else None
    )
    return web.json_response(
        {**_service_envelope(), "items": items, "next_cursor": next_cursor}
    )


@internal_user_endpoint
async def operation_detail_handler(request: web.Request) -> web.Response:
    operation_id = _parse_operation_id(request)
    row = await _fetch_operation(operation_id)
    if row is None:
        raise web.HTTPNotFound(text="operation_not_found")

    children = await base_api._fetch_all(
        """
        SELECT id, task_id, status, action_type, created_at, completed_at
        FROM generation_tasks
        WHERE parent_generation_id = ?
        ORDER BY id ASC
        """,
        (operation_id,),
    )
    return web.json_response(
        {
            **_service_envelope(),
            "data": _operation_from_row(row, include_details=True),
            "children": [
                {str(key): _json_value(child[key]) for key in child.keys()}
                for child in children
            ],
        }
    )


@internal_user_endpoint
async def operation_timeline_handler(request: web.Request) -> web.Response:
    operation_id = _parse_operation_id(request)
    row = await _fetch_operation(operation_id)
    if row is None:
        raise web.HTTPNotFound(text="operation_not_found")

    persisted = await base_api._fetch_all(
        """
        SELECT
            id, event_type, status, actor_type, actor_id, request_id,
            idempotency_key, amount, related_operation_id, details, created_at
        FROM internal_admin_operation_events
        WHERE operation_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (operation_id,),
    )
    items: list[dict[str, Any]] = [
        {
            "id": f"synthetic-created-{operation_id}",
            "event_type": "operation.created",
            "status": "success",
            "actor_type": "system",
            "actor_id": None,
            "request_id": None,
            "idempotency_key": None,
            "amount": None,
            "related_operation_id": row["parent_generation_id"],
            "details": {
                "task_id": row["task_id"],
                "type": row["type"],
                "model": row["model"],
                "action_type": row["action_type"],
            },
            "created_at": _json_value(row["created_at"]),
        }
    ]
    if row["completed_at"]:
        items.append(
            {
                "id": f"synthetic-final-{operation_id}",
                "event_type": "operation.finalized",
                "status": row["status"],
                "actor_type": "system",
                "actor_id": None,
                "request_id": None,
                "idempotency_key": None,
                "amount": None,
                "related_operation_id": None,
                "details": {},
                "created_at": _json_value(row["completed_at"]),
            }
        )
    for event in persisted:
        details = event["details"]
        if isinstance(details, str):
            details = _parse_request_data(details)
        items.append(
            {
                "id": int(event["id"]),
                "event_type": event["event_type"],
                "status": event["status"],
                "actor_type": event["actor_type"],
                "actor_id": event["actor_id"],
                "request_id": event["request_id"],
                "idempotency_key": event["idempotency_key"],
                "amount": event["amount"],
                "related_operation_id": event["related_operation_id"],
                "details": _sanitize_value(details or {}),
                "created_at": _json_value(event["created_at"]),
            }
        )
    items.sort(key=lambda item: str(item["created_at"] or ""))
    return web.json_response({**_service_envelope(), "items": items})


async def _operation_by_task_id(task_id: str) -> Mapping[str, Any] | None:
    rows = await base_api._fetch_all(
        f"{_OPERATION_SELECT} WHERE gt.task_id = ? ORDER BY gt.id DESC LIMIT 1",
        (task_id,),
    )
    return rows[0] if rows else None


async def _annotate_replay_child(
    child_id: int,
    *,
    source_operation_id: int,
    admin_user_id: str,
    request_id: str,
    idempotency_key: str,
    reason: str,
    comment: str | None,
) -> None:
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            "SELECT request_data FROM generation_tasks WHERE id = ? FOR UPDATE",
            (child_id,),
        )
        row = await cursor.fetchone()
        request_data = _parse_request_data(row["request_data"] if row else None)
        request_data["admin_replay"] = {
            "source_operation_id": source_operation_id,
            "admin_user_id": admin_user_id,
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            "reason": reason,
            "comment": comment,
        }
        await connection.execute(
            """
            UPDATE generation_tasks
            SET parent_generation_id = ?,
                action_type = 'admin_replay',
                request_data = CAST(? AS JSONB),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                source_operation_id,
                json.dumps(request_data, ensure_ascii=False),
                child_id,
            ),
        )
        await connection.commit()


async def _replay_image(
    source: Mapping[str, Any],
    *,
    admin_user_id: str,
    request_id: str,
    idempotency_key: str,
    reason: str,
    comment: str | None,
) -> Mapping[str, Any]:
    from bot.database import get_or_create_user
    from bot.handlers.generation import (
        _available_reference_images,
        _source_reference_images_from_request,
        _start_image_generation_task,
    )

    request_data = _parse_request_data(source["request_data"])
    telegram_id = int(source["telegram_id"] or 0)
    if telegram_id <= 0:
        raise CommandValidationError("operation has no Telegram recipient")
    user = await get_or_create_user(telegram_id)
    references, missing = _available_reference_images(
        _source_reference_images_from_request(request_data)
    )
    if missing:
        raise CommandConflictError("source references are no longer available")

    result = await _start_image_generation_task(
        user=user,
        telegram_id=telegram_id,
        img_service=str(request_data.get("img_service") or source["model"] or "banana_pro"),
        prompt=str(request_data.get("prompt") or source["prompt"] or ""),
        img_ratio=str(request_data.get("img_ratio") or source["aspect_ratio"] or "1:1"),
        reference_images=references,
        unit_cost=0,
        img_quality=str(request_data.get("img_quality") or "2K"),
        img_nsfw_checker=bool(request_data.get("img_nsfw_checker", False)),
        nsfw_enabled=bool(request_data.get("nsfw_enabled", False)),
        callback_url=config.kie_notification_url if config.WEBHOOK_HOST else None,
        parent_generation_id=int(source["id"]),
        action_type="admin_replay",
    )
    task_id = str(result.get("task_id") or "")
    if not task_id:
        raise RuntimeError("image provider did not create a replay operation")
    child = await _operation_by_task_id(task_id)
    if child is None:
        raise RuntimeError("replay operation was not persisted")
    await _annotate_replay_child(
        int(child["id"]),
        source_operation_id=int(source["id"]),
        admin_user_id=admin_user_id,
        request_id=request_id,
        idempotency_key=idempotency_key,
        reason=reason,
        comment=comment,
    )
    refreshed = await _fetch_operation(int(child["id"]))
    if refreshed is None:
        raise RuntimeError("replay operation disappeared")
    return refreshed


async def _replay_video(
    source: Mapping[str, Any],
    *,
    admin_user_id: str,
    request_id: str,
    idempotency_key: str,
    reason: str,
    comment: str | None,
) -> Mapping[str, Any]:
    from bot.database import (
        _merge_task_id_aliases,
        add_generation_task,
        complete_video_task,
        get_or_create_user,
    )
    from bot.handlers.generation import (
        _available_reference_images,
        _build_gemini_omni_video_list,
        _collect_gemini_omni_image_urls,
        _collect_gemini_omni_video_urls,
        _validate_gemini_omni_video_inputs,
        get_max_video_references,
        normalize_reference_urls,
    )
    from bot.services import gemini_omni_service, kling_service, veo_service
    from bot.services.grok_service import grok_service
    from bot.services.seedance_service import seedance_service

    request_data = _parse_request_data(source["request_data"])
    telegram_id = int(source["telegram_id"] or 0)
    if telegram_id <= 0:
        raise CommandValidationError("operation has no Telegram recipient")
    user = await get_or_create_user(telegram_id)

    v_model = str(request_data.get("v_model") or source["model"] or "v3_std")
    v_type = str(request_data.get("v_type") or "text")
    prompt = str(request_data.get("user_prompt") or source["prompt"] or "")
    duration = int(request_data.get("v_duration") or source["duration"] or 5)
    aspect_ratio = str(request_data.get("v_ratio") or source["aspect_ratio"] or "16:9")
    image_url = request_data.get("v_image_url")
    reference_images, missing_images = _available_reference_images(
        list(request_data.get("reference_images") or [])
    )
    if missing_images:
        raise CommandConflictError("source image references are no longer available")
    reference_videos = normalize_reference_urls(
        request_data.get("v_reference_videos", []),
        max_count=get_max_video_references(v_model),
    )
    avatar_audio_url = request_data.get("avatar_audio_url")

    local_task_id = f"admvid_{uuid.uuid4().hex[:16]}"
    replay_snapshot = {
        **request_data,
        "source": "admin_replay",
        "v_type": v_type,
        "v_model": v_model,
        "user_prompt": prompt,
        "v_duration": duration,
        "v_ratio": aspect_ratio,
        "v_image_url": image_url,
        "reference_images": reference_images,
        "v_reference_videos": reference_videos or [],
        "admin_replay": {
            "source_operation_id": int(source["id"]),
            "admin_user_id": admin_user_id,
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            "reason": reason,
            "comment": comment,
        },
    }
    await add_generation_task(
        user.id,
        telegram_id,
        local_task_id,
        "video",
        str(source["preset_id"] or "admin_replay"),
        model=v_model,
        duration=duration,
        aspect_ratio=aspect_ratio,
        prompt=prompt,
        cost=0,
        request_data=replay_snapshot,
        parent_generation_id=int(source["id"]),
        action_type="admin_replay",
    )

    try:
        if v_model == "gemini_omni_video":
            omni_images = _collect_gemini_omni_image_urls(image_url, reference_images)
            omni_video_urls = _collect_gemini_omni_video_urls(reference_videos)
            validation_error = _validate_gemini_omni_video_inputs(
                image_urls=omni_images,
                video_urls=omni_video_urls,
                character_ids=request_data.get("omni_character_ids", []),
                audio_ids=request_data.get("omni_audio_ids", []),
            )
            if validation_error:
                raise CommandValidationError(validation_error)
            result = await gemini_omni_service.generate_video(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                resolution=str(request_data.get("omni_resolution") or "720p"),
                image_urls=omni_images or None,
                audio_ids=request_data.get("omni_audio_ids", []),
                video_list=_build_gemini_omni_video_list(omni_video_urls, duration) or None,
                character_ids=request_data.get("omni_character_ids", []),
                seed=request_data.get("omni_seed"),
                callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
            )
        elif v_model.startswith("veo3"):
            generation_type = str(
                request_data.get("veo_generation_type") or "TEXT_2_VIDEO"
            )
            veo_images: list[str] = []
            if image_url:
                veo_images.append(str(image_url))
            max_images = 2 if generation_type == "FIRST_AND_LAST_FRAMES_2_VIDEO" else 3
            for reference in reference_images:
                if reference not in veo_images:
                    veo_images.append(reference)
                if len(veo_images) >= max_images:
                    break
            result = await veo_service.generate_video(
                prompt=prompt,
                model=v_model,
                duration=duration,
                generation_type=generation_type,
                image_urls=veo_images or None,
                aspect_ratio=aspect_ratio,
                enable_translation=bool(request_data.get("veo_translation", True)),
                watermark=request_data.get("veo_watermark") or None,
                resolution=str(request_data.get("veo_resolution") or "720p"),
                seeds=request_data.get("veo_seed"),
                callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
            )
        elif v_model == "grok_imagine":
            if not image_url:
                raise CommandValidationError("Grok Imagine replay requires a source image")
            result = await grok_service.generate_image_to_video(
                image_urls=[str(image_url), *reference_images[:6]],
                prompt=prompt,
                mode=str(request_data.get("grok_mode") or "normal"),
                duration=duration,
                resolution="720p",
                aspect_ratio=aspect_ratio,
                callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
            )
        elif v_model == "grok_imagine_v15":
            if not image_url:
                raise CommandValidationError("Grok Imagine 1.5 replay requires a source image")
            result = await grok_service.generate_image_to_video_v15(
                image_urls=[str(image_url)],
                prompt=prompt,
                duration=duration,
                resolution=str(request_data.get("grok_resolution") or "480p"),
                aspect_ratio=aspect_ratio,
                callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
            )
        elif v_model == "seedance_2":
            seedance_refs = [str(image_url)] if image_url else []
            for reference in reference_images:
                if reference not in seedance_refs:
                    seedance_refs.append(reference)
            result = await seedance_service.generate_video(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                resolution="720p",
                generate_audio=True,
                first_frame_url=(
                    str(image_url)
                    if v_type == "imgtxt" and image_url and not seedance_refs[1:]
                    else None
                ),
                reference_image_urls=seedance_refs or None,
                reference_video_urls=reference_videos or None,
                callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
            )
        elif v_model in {"avatar_std", "avatar_pro"}:
            if not image_url or not avatar_audio_url:
                raise CommandValidationError("Kling Avatar replay requires image and audio")
            result = await kling_service.generate_video(
                prompt=prompt,
                model=v_model,
                duration=duration,
                aspect_ratio=aspect_ratio,
                image_url=str(image_url),
                video_urls=[str(avatar_audio_url)],
                webhook_url=config.kling_notification_url if config.WEBHOOK_HOST else None,
            )
        else:
            result = await kling_service.generate_video(
                prompt=prompt,
                model=v_model,
                duration=duration,
                aspect_ratio=aspect_ratio,
                image_url=str(image_url) if image_url else None,
                video_urls=reference_videos if v_type in {"video", "motion"} else None,
                image_input=reference_images if v_type != "imgtxt" else None,
                negative_prompt=request_data.get("kling_negative_prompt") or None,
                cfg_scale=float(request_data.get("kling_cfg_scale", 0.5)),
                webhook_url=config.kling_notification_url if config.WEBHOOK_HOST else None,
            )
    except Exception:
        await complete_video_task(local_task_id, None)
        raise

    provider_task_id = str(result.get("task_id") or "") if isinstance(result, dict) else ""
    if provider_task_id:
        replay_snapshot = _merge_task_id_aliases(
            replay_snapshot,
            local_task_id,
            provider_task_id,
        )
        async with db_backend.connect() as connection:
            await connection.execute(
                """
                UPDATE generation_tasks
                SET task_id = ?, request_data = CAST(? AS JSONB), updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ? AND id = (
                    SELECT id FROM generation_tasks WHERE task_id = ? ORDER BY id DESC LIMIT 1
                )
                """,
                (
                    provider_task_id,
                    json.dumps(replay_snapshot, ensure_ascii=False),
                    local_task_id,
                    local_task_id,
                ),
            )
            await connection.commit()
        child = await _operation_by_task_id(provider_task_id)
    else:
        result_url = None
        if isinstance(result, dict):
            result_url = result.get("video_url") or result.get("result_url")
        await complete_video_task(local_task_id, str(result_url) if result_url else None)
        child = await _operation_by_task_id(local_task_id)

    if child is None:
        raise RuntimeError("video replay operation was not persisted")
    return child


async def _run_replay(
    source: Mapping[str, Any],
    *,
    admin_user_id: str,
    request_id: str,
    idempotency_key: str,
    reason: str,
    comment: str | None,
) -> Mapping[str, Any]:
    operation_type = str(source["type"] or "").lower()
    if operation_type == "image":
        return await _replay_image(
            source,
            admin_user_id=admin_user_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            reason=reason,
            comment=comment,
        )
    if operation_type == "video":
        return await _replay_video(
            source,
            admin_user_id=admin_user_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            reason=reason,
            comment=comment,
        )
    raise CommandValidationError("operation type cannot be replayed")


@internal_user_endpoint
async def replay_operation_handler(request: web.Request) -> web.Response:
    operation_id = _parse_operation_id(request)
    payload = _parse_command_payload(request, require_amount=False)
    raw_payload = _parse_request_data(request.get("internal_body", b""))
    _require_confirmation(raw_payload.get("confirmation"), f"REPLAY {operation_id}")
    idempotency_key, admin_user_id, request_id = _command_headers(request)

    source = await _fetch_operation(operation_id)
    if source is None:
        raise web.HTTPNotFound(text="operation_not_found")

    async with db_backend.connect() as connection:
        existing = await _reserve_command(
            connection,
            idempotency_key=idempotency_key,
            action="operation.replay",
            user_id=operation_id,
            admin_user_id=admin_user_id,
            request_id=request_id,
            payload=payload,
        )
        if existing is not None:
            await connection.rollback()
            return _command_response(existing)
        await connection.commit()

    try:
        child = await _run_replay(
            source,
            admin_user_id=admin_user_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            reason=str(payload["reason"]),
            comment=payload.get("comment"),
        )
        response_payload = {
            **_service_envelope(),
            "data": _operation_from_row(child, include_details=True),
        }
        async with db_backend.connect() as connection:
            await _record_event(
                connection,
                operation_id=operation_id,
                event_type="operation.replay",
                status="success",
                actor_id=admin_user_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                related_operation_id=int(child["id"]),
                details={"reason": payload["reason"], "comment": payload.get("comment")},
            )
            await _record_event(
                connection,
                operation_id=int(child["id"]),
                event_type="operation.replayed_from",
                status="success",
                actor_id=admin_user_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                related_operation_id=operation_id,
                details={},
            )
            await _complete_command(
                connection,
                idempotency_key=idempotency_key,
                response_payload=response_payload,
            )
            await connection.commit()
        return web.json_response(response_payload)
    except Exception as exc:
        logger.exception("Administrative operation replay failed: operation_id=%s", operation_id)
        failure_payload = {
            **_service_envelope(),
            "error": "operation_replay_failed",
            "detail": str(exc)[:500],
            "_http_status": 409
            if isinstance(exc, (CommandValidationError, CommandConflictError))
            else 502,
        }
        async with db_backend.connect() as connection:
            await _record_event(
                connection,
                operation_id=operation_id,
                event_type="operation.replay",
                status="failed",
                actor_id=admin_user_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                details={
                    "reason": payload["reason"],
                    "comment": payload.get("comment"),
                    "error": type(exc).__name__,
                },
            )
            await _complete_command(
                connection,
                idempotency_key=idempotency_key,
                response_payload=failure_payload,
            )
            await connection.commit()
        return _command_response(failure_payload)


@internal_user_endpoint
async def refund_operation_handler(request: web.Request) -> web.Response:
    operation_id = _parse_operation_id(request)
    payload = _parse_command_payload(request, require_amount=True)
    amount = int(payload["amount"])
    if amount <= 0:
        raise CommandValidationError("refund amount must be positive")
    raw_payload = _parse_request_data(request.get("internal_body", b""))
    _require_confirmation(raw_payload.get("confirmation"), f"REFUND {amount}")
    idempotency_key, admin_user_id, request_id = _command_headers(request)

    async with db_backend.connect() as connection:
        existing = await _reserve_command(
            connection,
            idempotency_key=idempotency_key,
            action="operation.refund",
            user_id=operation_id,
            admin_user_id=admin_user_id,
            request_id=request_id,
            payload=payload,
        )
        if existing is not None:
            await connection.rollback()
            return _command_response(existing)

        operation = await _fetch_operation_in_connection(
            connection,
            operation_id,
            for_update=True,
        )
        if operation is None:
            await connection.rollback()
            raise web.HTTPNotFound(text="operation_not_found")
        original_cost = int(operation["cost"] or 0)
        refunded_before = int(operation["refunded_credits"] or 0)
        refundable = max(original_cost - refunded_before, 0)
        if original_cost <= 0:
            raise CommandConflictError("operation did not charge credits")
        if amount > refundable:
            raise CommandConflictError(
                f"refund exceeds remaining refundable credits ({refundable})"
            )

        await connection.execute(
            """
            UPDATE users
            SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (amount, int(operation["user_id"])),
        )
        await _record_event(
            connection,
            operation_id=operation_id,
            event_type="credits.refund",
            status="success",
            actor_id=admin_user_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            amount=amount,
            details={"reason": payload["reason"], "comment": payload.get("comment")},
        )
        balance_cursor = await connection.execute(
            "SELECT credits FROM users WHERE id = ?",
            (int(operation["user_id"]),),
        )
        balance_row = await balance_cursor.fetchone()
        refunded_total = refunded_before + amount
        response_payload = {
            **_service_envelope(),
            "data": {
                "operation_id": operation_id,
                "user_id": int(operation["user_id"]),
                "telegram_id": int(operation["telegram_id"]),
                "amount": amount,
                "balance": int(balance_row["credits"] if balance_row else 0),
                "refunded_total": refunded_total,
                "refundable_remaining": max(original_cost - refunded_total, 0),
            },
        }
        await _complete_command(
            connection,
            idempotency_key=idempotency_key,
            response_payload=response_payload,
        )
        await connection.commit()
    return web.json_response(response_payload)
