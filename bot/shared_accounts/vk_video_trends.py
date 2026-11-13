"""Strict bridge for basic VK-owned image-to-video editorial trend repeats.

This module does not own funds, expose an editor recipe, or invent a Telegram
identity. Native VK model catalog and quote remain the final capability and
pricing authorities. Complex video/audio/template recipes fail closed.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from bot.trend_api import TrustedTrendRun

_KEY_RE = re.compile(r"[A-Za-z0-9_-]{16,80}\Z")


def supports_native_vk_video_trend(trend: Mapping[str, Any]) -> bool:
    """Basic photo-reference video trends only. Never imply complete TG parity."""
    settings = trend.get("generation_settings")
    if not isinstance(settings, Mapping):
        return False
    duration = settings.get("duration")
    count = settings.get("count", 1)
    return (
        settings.get("kind") == "video"
        and settings.get("scenario") == "imgtxt"
        and settings.get("user_input") == "photo"
        and type(settings.get("model")) is str
        and bool(settings.get("model"))
        and type(settings.get("ratio")) is str
        and bool(settings.get("ratio"))
        and type(duration) is int and 1 <= duration <= 60
        and type(count) is int and count == 1
        and not settings.get("reference_contract")
        and not settings.get("genjutsu_recipe_id")
        and not settings.get("seedance25_video_editing")
    )


def build_native_video_trend_request(
    trusted: TrustedTrendRun,
    native_catalog: Mapping[str, Any],
    photo_urls: Sequence[str],
    *,
    key: str | None,
    quote_only: bool,
    expected_cost: int | float | None,
) -> dict[str, Any]:
    """Create a native VK submission using only the trusted server-side recipe.

    The user may supply owned media and declared variables, but cannot
    override model/prompt/duration/price. Caller verifies ownership of photo
    URLs before this function. No paid call occurs until validation passes.
    """
    if not isinstance(trusted, TrustedTrendRun) or trusted.kind != "video":
        raise ValueError("Unsupported VK trend type")
    settings = trusted.settings
    if not supports_native_vk_video_trend({"generation_settings": settings}):
        raise ValueError("Unsupported VK video trend recipe")
    if (
        trusted.reference_contract
        or trusted.template_image_urls or trusted.template_video_urls
        or trusted.template_audio_urls or trusted.assembled_image_urls
        or trusted.assembled_video_urls or trusted.assembled_audio_urls
        or trusted.provider_video_urls or trusted.provider_audio_urls
        or trusted.user_reference_inputs
        or trusted.model != settings["model"]
        or trusted.ratio != settings["ratio"]
        or not trusted.prompt or not trusted.prompt.strip()
    ):
        raise ValueError("VK trend requires unsupported protected inputs")
    if not isinstance(native_catalog, Mapping) or native_catalog.get("ok") is not True:
        raise ValueError("Native VK model catalog is unavailable")
    native_models = native_catalog.get("video_models")
    if not isinstance(native_models, list):
        raise ValueError("Native VK video model catalog is invalid")
    model = next((
        item for item in native_models
        if isinstance(item, Mapping) and item.get("id") == trusted.model
    ), None)
    if model is None:
        raise ValueError("VK worker does not support this video model")
    duration = settings["duration"]
    supported_durations = model.get("durations")
    allowed_scenarios = model.get("scenarios")
    ratios = model.get("ratios")
    max_photos = model.get("max_image_references")
    if (
        not isinstance(supported_durations, list)
        or duration not in supported_durations
        or type(duration) is not int
        or not isinstance(allowed_scenarios, list)
        or "imgtxt" not in allowed_scenarios
        or not isinstance(ratios, list) or trusted.ratio not in ratios
        or type(max_photos) is not int or max_photos < 1
        or not isinstance(photo_urls, (tuple, list))
        or not 1 <= len(photo_urls) <= max_photos
        or any(type(url) is not str or not url for url in photo_urls)
        or len(set(photo_urls)) != len(photo_urls)
    ):
        raise ValueError("VK video trend exceeds native model capabilities")
    payload: dict[str, Any] = {
        "model": trusted.model,
        "prompt": trusted.prompt,
        "aspect": trusted.ratio,
        "duration": duration,
        "reference_photos": list(photo_urls),
    }
    if quote_only is True:
        payload["quote_only"] = True
    else:
        if not isinstance(key, str) or _KEY_RE.fullmatch(key) is None:
            raise ValueError("VK trend needs a valid idempotency key")
        if (
            type(expected_cost) not in (int, float)
            or not math.isfinite(expected_cost) or expected_cost <= 0
        ):
            raise ValueError("VK trend needs a valid native quote")
        payload["client_request_id"] = key
        payload["expected_cost"] = expected_cost
    return payload
