"""Run Seedance 2.5 trends through the dedicated Seedance runtime.

The generic trend launcher calls ``_launch_video_generation_task`` directly. That
helper predates Seedance 2.5, whose Mini App integration is an interception layer,
so a Seedance trend otherwise falls through to the Kling provider branch. Keep all
legacy trend models untouched and special-case only the dedicated Seedance model.
"""

from __future__ import annotations

from functools import wraps
from typing import Any

from aiohttp import web

from bot.config import config
from bot.seedance_trend_recipe import REFERENCE_CONTRACT
from bot.services.seedance_reference_binding import missing_seedance_reference_tags

from . import generation as generation_module
from . import seedance_25_public_release as public_release

MODEL_KEY = "seedance_2_5"


async def _run_seedance25_trend(
    *,
    telegram_id: int,
    user: Any,
    trend: Any,
) -> web.Response:
    import bot.miniapp as miniapp_module
    from bot import trend_api

    user_references = [
        str(value or "").strip()
        for value in trend.reference_urls
        if str(value or "").strip()
    ]
    references = [
        str(value or "").strip()
        for value in getattr(trend, "provider_image_urls", trend.reference_urls)
        if str(value or "").strip()
    ]
    video_references = [
        str(value or "").strip()
        for value in getattr(trend, "template_video_urls", ())
        if str(value or "").strip()
    ]
    audio_references = [
        str(value or "").strip()
        for value in getattr(trend, "template_audio_urls", ())
        if str(value or "").strip()
    ]
    if not references:
        raise trend_api.TrendRunValidationError("Для видео-тренда загрузите фото")

    trend_api._validate_uploaded_references(
        [*references, *video_references, *audio_references],
        miniapp_module,
    )
    await trend_api.touch_saved_references(telegram_id, user_references, kind="image")

    # Seedance 2.5 is exposed through the dedicated compatibility bootstrap and
    # is intentionally absent from the legacy VIDEO_MODELS registry. Using the
    # generic lookup here makes every curated Seedance 2.5 trend unavailable.
    model_meta = public_release._public_model_meta()

    supported_ratios = list(model_meta.get("ratios") or [])
    ratio = "adaptive" if bool(trend.settings.get("seedance25_video_editing", False)) else str(trend.ratio or "adaptive")
    if supported_ratios and ratio not in supported_ratios:
        ratio = "adaptive" if "adaptive" in supported_ratios else str(supported_ratios[0])

    supported_durations = [int(value) for value in model_meta.get("durations", []) if int(value) > 0]
    video_editing = bool(trend.settings.get("seedance25_video_editing", False))
    duration = -1 if video_editing else trend_api._int_setting(trend.settings, "duration", 5)
    if not video_editing and supported_durations and duration not in supported_durations:
        duration = min(supported_durations, key=lambda value: abs(value - duration))

    resolution = str(trend.settings.get("seedance25_resolution") or "720p").lower()
    if resolution not in {"480p", "720p"}:
        resolution = "720p"

    # Curated trends may bind uploaded photos explicitly in the prompt via
    # Seedance tags such as @Image1. In that case even a single photo must stay
    # in multimodal references; mapping it to first_frame leaves @Image1
    # unbound and KIE rejects the task before creation.
    reference_contract = str(getattr(trend, "reference_contract", "") or "")
    private_reference_run = reference_contract == REFERENCE_CONTRACT
    missing_without_images = missing_seedance_reference_tags(
        str(trend.prompt or ""),
        image_count=0,
        video_count=0,
        audio_count=0,
    )
    uses_image_binding = any(tag.startswith("@Image") for tag in missing_without_images)
    if private_reference_run:
        scenario = "multimodal"
        first_frame = None
        image_urls = references
    elif len(references) == 1 and not uses_image_binding:
        scenario = "first_frame"
        first_frame = references[0]
        image_urls = []
    else:
        scenario = "multimodal"
        first_frame = None
        image_urls = references

    payload = {
        "scenario": scenario,
        "prompt": str(trend.prompt or "").strip(),
        "duration": duration,
        "ratio": ratio,
        "resolution": resolution,
        "first_frame": first_frame,
        "last_frame": None,
        "image_urls": image_urls,
        "video_urls": video_references,
        "audio_urls": audio_references,
        "seedance25_video_editing": video_editing,
        "return_last_frame": bool(trend.settings.get("return_last_frame", False)),
        "generate_audio": bool(trend.settings.get("generate_audio", True)),
        "output_format": str(trend.settings.get("output_format") or "mp4").lower(),
        "web_search": bool(trend.settings.get("web_search", False)),
        "nsfw_checker": bool(trend.settings.get("nsfw_checker", False)),
    }

    is_admin = config.is_admin(telegram_id)
    try:
        await public_release._validate_public_payload(
            payload,
            is_admin=is_admin,
            trusted_trend=private_reference_run,
        )
    except ValueError as exc:
        raise trend_api.TrendRunValidationError(str(exc)) from exc

    cost = trend_api.estimate_trend_repeat_cost(trend)
    if cost is None:
        raise trend_api.TrendRunValidationError(
            "Не удалось определить стоимость Seedance 2.5 тренда"
        )
    debited, debit_error = await trend_api._debit_for_generation(telegram_id, user, cost)
    if debit_error is not None:
        return debit_error

    launched = False
    try:
        result = await public_release._launch_provider(payload)
        if not result or not result.get("task_id"):
            if debited:
                await generation_module.add_credits(telegram_id, cost)
            error = result.get("error") if isinstance(result, dict) else "provider response has no task_id"
            return web.json_response(
                {
                    "ok": False,
                    "error": f"Seedance 2.5 не запустила тренд: {error}. Бананы возвращены.",
                },
                status=502,
            )

        task_id = str(result["task_id"])
        request_data = public_release._request_data(
            payload,
            is_admin=is_admin,
            quote=cost,
            source="trend",
        )
        request_data.update(
            {
                "trend_id": int(trend.trend_id),
                "action_type": "trend",
                "prompt_source_id": int(trend.trend_id),
                "reference_contract": reference_contract or None,
                "fixed_asset_counts": {
                    "image": len(getattr(trend, "template_image_urls", ())),
                    "video": len(getattr(trend, "template_video_urls", ())),
                    "audio": len(getattr(trend, "template_audio_urls", ())),
                },
                "prompt_hidden": True,
                "prompt_actions_allowed": False,
            }
        )
        await generation_module.add_generation_task(
            user.id,
            telegram_id,
            task_id,
            "video",
            "miniapp_video",
            model=MODEL_KEY,
            duration=duration,
            aspect_ratio=ratio,
            prompt=payload["prompt"],
            cost=cost,
            request_data=request_data,
            action_type="trend",
        )
        launched = True

        await trend_api._record_trend_use(
            int(trend.trend_id),
            user.id,
            credits_spent=cost,
        )
        fresh_user = await generation_module.get_or_create_user(telegram_id)
        return web.json_response(
            {
                "ok": True,
                "status": "queued",
                "task_id": task_id,
                "task_type": "video",
                "saved_url": None,
                "credits": fresh_user.credits,
                "cost": cost,
                "model": MODEL_KEY,
                "model_label": miniapp_module.get_video_model_label(MODEL_KEY),
                "aspect_ratio": ratio,
                "duration": duration,
                "prompt_hidden": True,
                "prompt_actions_allowed": False,
                "trend_id": int(trend.trend_id),
            }
        )
    except Exception:
        if debited and not launched:
            await generation_module.add_credits(telegram_id, cost)
        raise


def install_trend_seedance_25_compat() -> None:
    from bot import trend_api

    if getattr(trend_api, "_seedance25_trend_compat_installed", False):
        return

    current_run_video_trend = trend_api._run_video_trend

    @wraps(current_run_video_trend)
    async def run_video_trend_with_seedance25(
        *,
        telegram_id: int,
        user: Any,
        trend: Any,
    ) -> web.Response:
        if str(trend.model or "").strip() != MODEL_KEY:
            return await current_run_video_trend(
                telegram_id=telegram_id,
                user=user,
                trend=trend,
            )
        return await _run_seedance25_trend(
            telegram_id=telegram_id,
            user=user,
            trend=trend,
        )

    trend_api._run_video_trend = run_video_trend_with_seedance25
    trend_api._seedance25_trend_compat_installed = True
