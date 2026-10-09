"""Per-viewer display adapters; never write personal prices into shared models.

Only authenticated endpoint code resolves an actor. Pure adapters accept an
explicit server-selected tariff and default to the ordinary public price.
"""
from __future__ import annotations

from typing import Any

from aiohttp import web

from bot.creator_tariff import (
    get_actor_tariff,
    resolve_video_quote,
    video_quality_rates,
)
from bot.model_capabilities import get_video_capability

_SEEDANCE_MODELS = {"seedance_2", "seedance_2_5"}


def price_video_model_metadata(
    metadata: dict[str, Any], *, tariff: str = "standard",
) -> dict[str, Any]:
    model = str(metadata.get("id") or "")
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
    # The quote service uses reference presence only. This marker is not a URL,
    # never leaves pricing, and cannot restore or disclose a private asset.
    references = ["repeat-video-reference"] if has_video_reference else []
    return {
        "pricing_quality": quality,
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
