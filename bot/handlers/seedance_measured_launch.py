"""Seedance 2 effective-recipe quote/launch adapter, shared across surfaces."""
from __future__ import annotations

import json

from aiohttp import web

from bot import database
from bot.config import config
from bot.services.seedance_quote_lifecycle import (
    claim_quote,
    prepare_quote,
    public_quote,
    receipt_store,
    submit_claimed_quote,
)
from bot.services.seedance_quote_receipts import InsufficientCredits, QuoteConflict


async def submit_seedance2(payload):
    from bot.services.seedance_service import seedance_service

    images = list(dict.fromkeys([url for url in [payload.get("image_url"), *payload["image_references"]] if url]))
    return await seedance_service.generate_video(
        prompt=payload["prompt"], duration=payload["duration"], aspect_ratio=payload["ratio"],
        resolution="720p", generate_audio=True, reference_image_urls=images or None,
        reference_video_urls=payload["video_references"],
        reference_audio_urls=payload.get("audio_references") or None,
        callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
    )


async def bind_seedance2(row):
    payload = json.loads(row["provider_json"])
    billing = json.loads(row["billing_json"])
    metadata = {
        "v_model": "seedance_2", "v_type": payload["generation_type"],
        "v_duration": payload["duration"], "v_ratio": payload["ratio"],
        "v_image_url": payload.get("image_url"), "reference_images": payload["image_references"],
        "reference_videos": payload["video_references"], "v_reference_videos": payload["video_references"],
        "reference_audios": payload.get("audio_references") or [],
        "user_prompt": payload["prompt"], "prompt": payload["prompt"],
        "source": payload.get("_launch_surface", "miniapp"), "seedance_quote_id": row["quote_id"],
        "billing_quote": billing, "charged": row["charged_cost"] > 0, "charged_cost": row["charged_cost"],
        "admin_free": billing["profile"] == "admin", "refund_on_failure": row["charged_cost"] > 0,
        "refund_claimed": False,
    }
    for key in ("source_feed_gen_id", "parent_generation_id", "action_type", "prompt_source_id",
                "reference_contract", "fixed_asset_counts", "video_repeat_contract_version", "trend_id", "prompt_hidden", "prompt_actions_allowed"):
        if payload.get(key) is not None:
            metadata[key] = payload[key]
    task_id = row["provider_task_id"]
    inserted = await database.add_generation_task(
        row["user_id"], row["telegram_id"], task_id, "video", "no_preset_video", model="seedance_2",
        duration=payload["duration"], aspect_ratio=payload["ratio"], prompt=payload["prompt"],
        cost=row["charged_cost"], request_data=metadata, provider_accepted=True,
        source_feed_gen_id=payload.get("source_feed_gen_id"), parent_generation_id=payload.get("parent_generation_id"),
        action_type=payload.get("action_type"),
    )
    if not inserted:
        task = await database.get_generation_task_payload(task_id, user_id=int(row["user_id"]))
        raw = task.get("request_data") if task else None
        current = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(current, dict) or current.get("seedance_quote_id") != row["quote_id"]:
            raise QuoteConflict("Seedance canonical task does not match receipt")
    await (await receipt_store()).mark_bound(row["quote_id"], task_id)
    if payload.get("trend_id"):
        from bot import trend_api
        await trend_api._record_trend_use(payload["trend_id"], row["user_id"], credits_spent=row["charged_cost"], repeat_task_id=task_id)
    if payload.get("source_feed_gen_id") and row["charged_cost"] > 0:
        import bot.miniapp as miniapp_module
        await miniapp_module.credit_feed_prompt_repeat(payload.get("parent_generation_id"), row["user_id"],
                                                        repeat_task_id=task_id, credits_spent=row["charged_cost"])


async def prepare_seedance2(telegram_id: int, payload: dict):
    from bot.services.seedance_reference_binding import missing_seedance_reference_tags
    from bot.services.seedance_service import seedance_service

    if not seedance_service.MIN_DURATION <= payload["duration"] <= seedance_service.MAX_DURATION:
        raise ValueError("Выберите поддерживаемую длительность результата")
    if payload["ratio"] not in seedance_service.SUPPORTED_RATIOS:
        raise ValueError("Выберите поддерживаемый формат видео")
    if not payload["prompt"].strip() or len(payload["prompt"]) > seedance_service.MAX_PROMPT_LENGTH:
        raise ValueError("Проверьте длину описания видео")
    missing = missing_seedance_reference_tags(payload["prompt"], image_count=len(payload["image_references"]),
        video_count=len(payload["video_references"]), audio_count=len(payload.get("audio_references") or []))
    if missing:
        raise ValueError("В описании указаны отсутствующие референсы")
    return await prepare_quote(telegram_id, "seedance_2", payload, video_key="video_references",
                               duration=payload["duration"], quality="720p")


async def launch_seedance2(telegram_id: int, payload: dict, quote_id: str, quote_hash: str):
    row = await claim_quote(telegram_id, quote_id, quote_hash, payload)
    return await submit_claimed_quote(row, submit=submit_seedance2, bind=bind_seedance2)


async def response_for_receipt(row):
    if row["phase"] != "accepted":
        return web.json_response({"ok": False, "quote_id": row["quote_id"],
                                  "code": "video_rejected" if row["phase"] == "rejected" else "video_status_pending",
                                  "error": "Проверьте статус ранее отправленной задачи перед новым запуском"}, status=409)
    payload = json.loads(row["provider_json"])
    billing = json.loads(row["billing_json"])
    task = await database.get_generation_task_payload(row["provider_task_id"], user_id=int(row["user_id"]))
    user = await database.get_or_create_user(row["telegram_id"])
    status = task.get("status") if task else "pending"
    return web.json_response({"ok": True, "status": "done" if status == "completed" else "failed" if status == "failed" else "queued",
                              "task_id": row["provider_task_id"], "saved_url": task.get("result_url") if task else None,
                              "credits": user.credits, "cost": billing["cost"], "model_label": "Seedance 2.0",
                              "prompt_hidden": bool(payload.get("source_feed_gen_id") or payload.get("trend_id")),
                              "prompt_actions_allowed": not bool(payload.get("source_feed_gen_id") or payload.get("trend_id")),
                              "source_feed_gen_id": payload.get("source_feed_gen_id"), "model": "seedance_2",
                              "aspect_ratio": payload["ratio"], "duration": payload["duration"], "task_type": "video", "trend_id": payload.get("trend_id")})


async def miniapp_measured_seedance2(request, body, telegram_id, payload):
    from bot.handlers.miniapp_video_continuity_compat import (
        verify_video_repeat_before_charge,
    )

    payload["_repeat_guard"] = getattr(request, "_video_repeat_guard", None)
    permission_error = await verify_video_repeat_before_charge(request)
    if permission_error is not None:
        return permission_error
    try:
        if body.get("video_quote_only") is True:
            return web.json_response(public_quote(await prepare_seedance2(telegram_id, payload)))
        return await response_for_receipt(await launch_seedance2(
            telegram_id, payload, body.get("video_quote_id"), body.get("video_quote_hash")))
    except QuoteConflict as exc:
        return web.json_response({"ok": False, "code": "video_quote_changed", "error": str(exc)}, status=409)
    except InsufficientCredits as exc:
        return web.json_response({"ok": False, "code": "video_not_reserved", "error": str(exc)}, status=400)
    except ValueError as exc:
        return web.json_response({"ok": False, "code": "video_input_invalid", "error": str(exc)}, status=400)


def telegram_payload(data, prompt):
    from bot.services.seedance_reference_binding import (
        canonicalize_seedance_reference_tags,
    )
    from bot.services.seedance_service import seedance_service

    def urls(values, limit):
        return list(dict.fromkeys(str(value).strip() for value in values if str(value or "").strip()))[:limit]
    images = urls([data.get("v_image_url"), *data.get("reference_images", [])], seedance_service.MAX_REFERENCE_IMAGES)
    videos = urls(data.get("v_reference_videos", []), seedance_service.MAX_REFERENCE_VIDEOS)
    audio = urls(data.get("reference_audios", data.get("seedance_reference_audios", [])), seedance_service.MAX_REFERENCE_AUDIO)
    payload = {"prompt": canonicalize_seedance_reference_tags(prompt, image_count=len(images), video_count=len(videos), audio_count=len(audio)),
               "duration": int(data.get("v_duration", 5)), "ratio": data.get("v_ratio", "16:9"),
               "generation_type": data.get("v_type", "text"), "image_url": None,
               "image_references": images, "video_references": videos, "audio_references": audio,
               "_launch_surface": "telegram"}
    if data.get("seedance2_repeat_context"):
        payload["_repeat_context"] = data["seedance2_repeat_context"]
    return payload


async def verify_telegram_repeat(telegram_id, payload):
    import hashlib

    context = payload.get("_repeat_context")
    if not context:
        return
    task = await database.get_task_by_id(context["task_id"])
    user = await database.get_or_create_user(telegram_id)
    if (not task or task.user_id != user.id or task.model != "seedance_2"
            or hashlib.sha256(str(task.request_data or "").encode()).hexdigest() != context["recipe_hash"]):
        raise QuoteConflict("Исходное видео изменилось. Откройте повтор заново")


async def prepare_telegram_seedance2(message, state, telegram_id, prompt):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    data = await state.get_data()
    payload = telegram_payload(data, prompt)
    await verify_telegram_repeat(telegram_id, payload)
    row = await prepare_seedance2(telegram_id, payload)
    quote = public_quote(row)
    await state.update_data(user_prompt=prompt, seedance2_pending_quote={
        "quote_id": row["quote_id"], "quote_hash": row["quote_hash"]})
    await message.answer(
        f"Вход: {quote['input_seconds']:g} с + результат: {quote['selected_output_seconds']:g} с\n"
        f"Цена: {quote['cost']:g} 🍌. Запустить?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="Запустить видео", callback_data=f"seedquote2:{row['quote_id']}")]]))


async def confirm_telegram_seedance2(callback, state):
    data = await state.get_data()
    pending = data.get("seedance2_pending_quote") or {}
    quote_id = callback.data.split(":", 1)[-1]
    if data.get("v_model") != "seedance_2" or pending.get("quote_id") != quote_id:
        await callback.answer("Расчёт устарел. Отправьте запрос заново", show_alert=True)
        return
    try:
        payload = telegram_payload(data, data.get("user_prompt", ""))
        await verify_telegram_repeat(callback.from_user.id, payload)
        row = await launch_seedance2(callback.from_user.id, payload, quote_id, pending.get("quote_hash"))
        await callback.answer("Видео принято" if row["phase"] == "accepted" else "Проверяем статус отправки", show_alert=True)
    except (QuoteConflict, InsufficientCredits, ValueError) as exc:
        await callback.answer(str(exc)[:190], show_alert=True)


def trend_metadata(trend):
    return {"trend_id": int(trend.trend_id), "action_type": "trend", "prompt_source_id": int(trend.trend_id),
            "reference_contract": trend.reference_contract or None, "prompt_hidden": True,
            "prompt_actions_allowed": False, "_launch_surface": "trend",
            "_authorized_video_sources": list(getattr(trend, "template_video_urls", ())),
            "fixed_asset_counts": {kind: len(getattr(trend, f"template_{kind}_urls", ())) for kind in ("image", "video", "audio")}}


async def run_measured_trend_seedance2(telegram_id, trend, duration, generation_type, context):
    from bot.services.seedance_reference_binding import (
        canonicalize_seedance_reference_tags,
    )

    images, videos, audio = list(trend.provider_image_urls), list(trend.provider_video_urls), list(trend.provider_audio_urls)
    payload = {"prompt": canonicalize_seedance_reference_tags(trend.prompt, image_count=len(images), video_count=len(videos), audio_count=len(audio)),
               "duration": duration, "ratio": trend.ratio, "generation_type": generation_type,
               "image_url": None, "image_references": images, "video_references": videos, "audio_references": audio,
               **trend_metadata(trend)}
    try:
        if context.get("video_quote_only") is True:
            return web.json_response(public_quote(await prepare_seedance2(telegram_id, payload)))
        return await response_for_receipt(await launch_seedance2(telegram_id, payload, context.get("video_quote_id"), context.get("video_quote_hash")))
    except (QuoteConflict, InsufficientCredits, ValueError) as exc:
        return web.json_response({"ok": False, "code": "video_quote_changed", "error": str(exc), "retry_same_request": False}, status=409)


async def run_measured_trend_seedance25(telegram_id, trend, payload, context):
    from bot.handlers import seedance_25_public_release as public_release

    payload.update(trend_metadata(trend))
    try:
        if context.get("video_quote_only") is True:
            return web.json_response(public_quote(await public_release._prepare_measured_quote(telegram_id, payload)))
        return await public_release._measured_miniapp_response(await public_release._launch_measured_seedance25(
            telegram_id, payload, context.get("video_quote_id"), context.get("video_quote_hash")))
    except (QuoteConflict, InsufficientCredits, ValueError) as exc:
        return web.json_response({"ok": False, "code": "video_quote_changed", "error": str(exc), "retry_same_request": False}, status=409)
