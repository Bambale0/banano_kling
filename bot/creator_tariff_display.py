"""Per-viewer display adapters; never write personal prices into shared models.

Only authenticated endpoint code resolves an actor. Pure adapters accept an
explicit server-selected tariff and default to the ordinary public price.
"""
from __future__ import annotations

from typing import Any

from aiohttp import web

from bot.creator_tariff import (
    get_actor_tariff,
    image_quality_rates,
    resolve_video_quote,
    video_quality_rates,
)
from bot.model_capabilities import get_video_capability

_SEEDANCE_MODELS = {"seedance_2", "seedance_2_5"}


def price_image_model_metadata(
    metadata: dict[str, Any], *, tariff: str = "standard",
) -> dict[str, Any]:
    model = str(metadata.get("id") or "")
    rates = image_quality_rates(model, tariff=tariff)
    if not rates:
        return dict(metadata)
    default_quality = "basic" if model == "seedream_5_pro" else "2K"
    return {
        **metadata,
        "cost": rates.get(default_quality, metadata.get("cost")),
        "quality_costs": rates,
    }


def price_video_model_metadata(
    metadata: dict[str, Any], *, tariff: str = "standard",
) -> dict[str, Any]:
    model = str(metadata.get("id") or "")
    if model in {'wan_3', 'wan_3_prime'}:
        from bot.services.preset_manager import preset_manager

        rates = video_quality_rates(model, tariff=tariff)
        if tariff != 'creator' or rates == preset_manager.get_video_quality_costs(model):
            return dict(metadata)
        totals = {
            quality: {
                str(duration): preset_manager._format_cost(rate * (30 if int(duration) == -1 else int(duration)))
                for duration in metadata.get('durations', [])
            }
            for quality, rate in rates.items()
        }
        default = totals.get('1080p') or totals.get('720p') or {}
        return {**metadata, 'costs': default, 'quality_costs': rates, 'quality_duration_costs': totals}
    if model not in _SEEDANCE_MODELS:
        return dict(metadata)
    rates = video_quality_rates(model, tariff=tariff)
    return {
        **metadata,
        "costs": {
            str(duration): resolve_video_quote(
                model, 5 if int(duration) == -1 else int(duration),
                "720p" if model == "seedance_2_5" else None, tariff=tariff,
            ).cost
            for duration in metadata.get("durations", [])
        },
        "quality_costs": rates,
        # Exact server-rounded totals avoid client/Python half-step differences
        # for freely configured per-second rates.
        "quality_duration_costs": {
            quality: {
                str(duration): resolve_video_quote(
                    model, 5 if int(duration) == -1 else int(duration), quality, tariff=tariff,
                ).cost
                for duration in metadata.get("durations", [])
            }
            for quality in rates
        },
    }


def video_repeat_price_metadata(
    model: str, quality: str, *, has_video_reference: bool, tariff: str = "standard",
) -> dict[str, Any]:
    capability = get_video_capability(model)
    if capability is None:
        return {}
    # Source duration is unknown until the final repeat references are resolved.
    # These base duration totals are not a final quote if a video is attached.
    references = []
    return {
        "pricing_quality": quality,
        "reference_seconds_pending": bool(has_video_reference),
        "duration_costs": {
            str(duration): resolve_video_quote(
                model, duration, quality, references, tariff=tariff,
            ).cost
            for duration in capability.durations
        },
    }


def _price_feed_card(card: dict[str, Any], *, tariff: str) -> dict[str, Any]:
    slots = card.get("repeat_reference_slots")
    model = str(card.get("model") or "")
    if model not in _SEEDANCE_MODELS or not isinstance(slots, dict) or not slots.get("available"):
        return dict(card)
    return {
        **card,
        "repeat_reference_slots": {
            **slots,
            **video_repeat_price_metadata(
                model, str(slots.get("pricing_quality") or "720p"),
                has_video_reference=bool(slots.get("videos")), tariff=tariff,
            ),
        },
    }


def price_feed_api_payload(
    payload: dict[str, Any], *, tariff: str = "standard",
) -> dict[str, Any]:
    """Requote public descriptors, preserving the historical generation debit."""
    result = dict(payload)
    if isinstance(payload.get("feed"), list):
        result["feed"] = [_price_feed_card(card, tariff=tariff) for card in payload["feed"]]
    if isinstance(payload.get("feed_item"), dict):
        result["feed_item"] = _price_feed_card(payload["feed_item"], tariff=tariff)
    return result


async def priced_feed_response(payload: dict[str, Any], telegram_id: int) -> web.Response:
    tariff = await get_actor_tariff(telegram_id)
    return web.json_response(
        price_feed_api_payload(payload, tariff=tariff),
        headers={"Cache-Control": "no-store"},
    )
