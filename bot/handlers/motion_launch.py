"""Authenticated Motion quote/launch; provider acceptance is never inferred from timeout."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math

from aiohttp import web

from bot.services.motion_launch_receipts import (
    MotionInsufficientCredits,
    MotionLaunchConflict,
    MotionLaunchReceipts,
    definitely_rejected_motion_result,
)
from bot.services.motion_quote import build_motion_quote

logger = logging.getLogger(__name__)


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _validated_quote(body: dict, telegram_id: int, api) -> dict:
    from bot.handlers.seedance_25_fullstack import _ffprobe, _probe_duration
    from bot.handlers.seedance_25_public_release import _identity_local_path

    image_url = str(body.get("motion_image_url") or "").strip()
    video_url = str(body.get("motion_video_url") or "").strip()
    if not image_url or not video_url:
        raise ValueError("Загрузите свои фото и видео движения")
    image_path = _identity_local_path(image_url, "image", telegram_id)
    video_path = _identity_local_path(video_url, "video", telegram_id)
    del image_path
    before_hash = await asyncio.to_thread(_file_sha256, video_path)
    metadata = await _ffprobe(video_path)
    measured = _probe_duration(metadata, "video")
    source_hash = await asyncio.to_thread(_file_sha256, video_path)
    if before_hash != source_hash:
        raise ValueError("Видео изменилось во время расчёта. Загрузите его заново.")
    model = str(body.get("motion_model") or "motion_control_v26")
    quality = str(body.get("motion_mode") or "720p")
    rates = api.preset_manager.get_video_quality_costs(model)
    raw_rate = rates.get(quality)
    try:
        rate = float("nan") if isinstance(raw_rate, bool) else float(raw_rate)
    except (TypeError, ValueError) as exc:
        raise ValueError("Администратор ещё не настроил ставку Motion") from exc
    return build_motion_quote(
        model=model, quality=quality, direction=str(body.get("motion_direction") or "video"),
        prompt=str(body.get("prompt") or "").strip()[:2500],
        image_url=image_url, video_url=video_url,
        source_sha256=source_hash,
        source_seconds=measured, rate=rate, admin_free=api.config.is_admin(telegram_id),
        format_cost=api.preset_manager._format_cost,
    )


async def quote_motion(request, api):
    try:
        body = await request.json()
        telegram_id, _ctx = await api._get_user_context(
            request.app, body.get("init_data", ""), body.get("start_param_fallback"))
        quote = await _validated_quote(body, telegram_id, api)
        return web.json_response({"ok": True, "quote": quote})
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001 - sanitized HTTP boundary
        return api._miniapp_error_response(exc, log_message="Motion quote failed")


def _pending(receipt_id: str):
    return web.json_response({
        "ok": False, "code": "motion_status_pending", "receipt_id": receipt_id,
        "error": "Исход запуска Motion ещё проверяется. Повторное списание и повторная отправка заблокированы.",
    }, status=409)


async def persist_accepted_motion(receipt: dict, quote: dict, api):
    telegram_id = int(receipt["telegram_id"])
    task_id = receipt["provider_task_id"]
    charge = float(receipt["charged_cost"])
    inserted = await api.add_generation_task(
        receipt["user_id"], telegram_id, task_id, "video", "miniapp_motion_control",
        model=quote["model"], duration=math.ceil(quote["output_seconds"]), aspect_ratio="1:1",
        prompt=quote["prompt"], cost=charge,
        request_data={
            "source": "miniapp", "v_type": "motion_control",
            "motion_launch_receipt_id": receipt["receipt_id"],
            "motion_image_url": quote["image_url"], "motion_video_url": quote["video_url"],
            "motion_mode": quote["quality"], "motion_direction": quote["direction"],
            "motion_quote": quote, "charged": charge > 0, "charged_cost": charge,
            "admin_free": quote["admin_free"], "refund_on_failure": charge > 0,
            "refund_claimed": False,
        }, provider_accepted=True,
    )
    from bot import db as db_backend

    if not inserted:
        from bot.database import get_generation_task_payload

        existing = await get_generation_task_payload(task_id, user_id=int(receipt["user_id"]))
        raw = existing.get("request_data") if existing else None
        metadata = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(metadata, dict) or metadata.get("motion_launch_receipt_id") != receipt["receipt_id"]:
            raise RuntimeError("Motion canonical binding does not match durable receipt")
    store = MotionLaunchReceipts(db_backend.connect, db_backend.Row)
    await store.mark_bound(receipt["receipt_id"], task_id)


async def _bind_accepted(receipt: dict, quote: dict, user, telegram_id: int, api):
    await persist_accepted_motion(receipt, quote, api)
    task_id = receipt["provider_task_id"]
    fresh_user = await api.get_or_create_user(telegram_id)
    canonical = await api.get_generation_task_payload(task_id, user_id=int(receipt["user_id"]))
    canonical_status = canonical.get("status") if canonical else "pending"
    return web.json_response({
        "ok": True, "status": "done" if canonical_status == "completed" else "failed" if canonical_status == "failed" else "queued",
        "saved_url": canonical.get("result_url") if canonical else None, "task_id": task_id, "credits": fresh_user.credits,
        "cost": quote["cost"], "duration": quote["output_seconds"],
        "model": quote["model"], "prompt_preview": quote["prompt"][:100],
        "model_label": "Kling 3.0 Motion Control" if quote["model"] == "motion_control_v30"
                       else "Kling 2.6 Motion Control",
    })


async def status_motion(request, api):
    try:
        from bot import db as db_backend

        body = await request.json()
        telegram_id, ctx = await api._get_user_context(
            request.app, body.get("init_data", ""), body.get("start_param_fallback"))
        store = MotionLaunchReceipts(db_backend.connect, db_backend.Row)
        await store.ensure_schema()
        receipt = await store.find(telegram_id, str(body.get("motion_request_id") or ""))
        if not receipt:
            return web.json_response({"ok": True, "status": "not_found"})
        if receipt["phase"] == "accepted" and receipt["provider_task_id"]:
            return await _bind_accepted(receipt, json.loads(receipt["recipe_json"]), ctx["user"], telegram_id, api)
        if receipt["phase"] in {"rejected", "provider_failed"}:
            return web.json_response({"ok": True, "status": "rejected", "refunded": bool(receipt["refunded"])})
        return _pending(receipt["receipt_id"])
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001 - status must never resubmit a provider request
        return api._miniapp_error_response(exc, log_message="Motion status recovery deferred")


async def recover_accepted_motion(limit: int = 20) -> int:
    from types import SimpleNamespace

    from bot import database
    from bot import db as db_backend

    store = MotionLaunchReceipts(db_backend.connect, db_backend.Row)
    await store.ensure_schema()
    recovered = 0
    for receipt in await store.unbound_accepted(limit):
        try:
            await persist_accepted_motion(receipt, json.loads(receipt["recipe_json"]),
                                          SimpleNamespace(add_generation_task=database.add_generation_task))
            recovered += 1
        except Exception as exc:  # noqa: BLE001 - durable accepted receipt retries without resubmission
            logger.error("Motion accepted binding deferred: receipt_id=%s provider_task_id=%s error_type=%s",
                         receipt["receipt_id"], receipt["provider_task_id"], type(exc).__name__)
    return recovered


async def generate_motion(request, api):
    receipt = None
    store = None
    try:
        from bot import db as db_backend
        from bot.services.kling_service import kling_service

        body = await request.json()
        telegram_id, ctx = await api._get_user_context(
            request.app, body.get("init_data", ""), body.get("start_param_fallback"))
        user = ctx["user"]
        request_key = str(body.get("motion_request_id") or "")
        store = MotionLaunchReceipts(db_backend.connect, db_backend.Row)
        await store.ensure_schema()
        receipt = await store.find(telegram_id, request_key)
        if receipt:
            quote = json.loads(receipt["recipe_json"])
            if body.get("motion_quote_hash") != quote["quote_hash"]:
                raise MotionLaunchConflict("Этот запуск уже связан с другой ценой и настройками")
        else:
            quote = await _validated_quote(body, telegram_id, api)
            if body.get("motion_quote_hash") != quote["quote_hash"]:
                return web.json_response({
                    "ok": False, "code": "motion_quote_changed",
                    "error": "Цена или исходное видео изменились. Проверьте обновлённый расчёт перед запуском.",
                    "quote": quote,
                }, status=409)
            receipt = await store.reserve(
                user_id=user.id, telegram_id=telegram_id, request_key=request_key, recipe=quote,
                cost=quote["cost"], admin_free=quote["admin_free"],
            )
        if receipt["phase"] == "accepted" and receipt["provider_task_id"]:
            return await _bind_accepted(receipt, quote, user, telegram_id, api)
        if not receipt["created"]:
            if receipt["phase"] == "rejected":
                return web.json_response({
                    "ok": False, "code": "motion_rejected", "error": "Запуск отклонён, списание возвращено. Создайте новый запуск.",
                }, status=400)
            return _pending(receipt["receipt_id"])

        callback_url = api.config.kie_notification_url if api.config.WEBHOOK_HOST else None
        result = await kling_service.generate_motion_control(
            image_url=quote["image_url"], video_urls=[quote["video_url"]], prompt=quote["prompt"],
            mode=quote["quality"], motion_direction=quote["direction"],
            motion_model="kling-3.0/motion-control" if quote["model"] == "motion_control_v30"
                         else "kling-2.6/motion-control", webhook_url=callback_url,
        )
        task_id = result.get("task_id") if isinstance(result, dict) else None
        if task_id:
            logger.info("Motion provider accepted: receipt_id=%s provider_task_id=%r",
                        receipt["receipt_id"], str(task_id))
            if not await store.accepted(receipt["receipt_id"], str(task_id)):
                return _pending(receipt["receipt_id"])
            receipt.update(phase="accepted", provider_task_id=str(task_id))
            return await _bind_accepted(receipt, quote, user, telegram_id, api)
        if definitely_rejected_motion_result(result):
            if not await store.rejected_and_refund(receipt["receipt_id"]):
                return _pending(receipt["receipt_id"])
            return web.json_response({
                "ok": False, "code": "motion_rejected",
                "error": "Провайдер отклонил запуск Motion. Списание возвращено.",
            }, status=400)
        await store.unknown(receipt["receipt_id"])
        return _pending(receipt["receipt_id"])
    except (MotionLaunchConflict, MotionInsufficientCredits, ValueError) as exc:
        if receipt and receipt.get("created"):
            return _pending(receipt["receipt_id"])
        return web.json_response({"ok": False, "code": "motion_not_reserved", "error": str(exc)}, status=409)
    except Exception as exc:  # noqa: BLE001 - never refund an unknown provider/persistence outcome
        logger.error("Motion launch unresolved: receipt_id=%s error_type=%s",
                     receipt.get("receipt_id") if receipt else None, type(exc).__name__)
        if receipt:
            return _pending(receipt["receipt_id"])
        return api._miniapp_error_response(exc, log_message="Motion launch failed before confirmed reservation")
