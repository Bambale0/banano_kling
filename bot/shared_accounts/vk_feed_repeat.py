"""VK-owned repeat of *public, explicitly visible* photo-feed recipes.

Feed publication IDs are not editorial trend IDs. The paid operation is
authorized by the signed VK actor, and is never a Telegram task or wallet.
Hidden prompts/media/creator-owned references never leave the backend.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .vk_trend_contract import NATIVE_IMAGE_MODELS

_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9_-]{16,80}\Z")


def native_vk_feed_repeat_model(card: Mapping[str, Any]) -> str | None:
    """Only publicly repeatable photo cards; require a visible author prompt.

    Privacy decisions come from database.get_feed_generation_card, which
    applies recipe_privacy_rows and the author's published prompt policy.
    """
    if (
        not isinstance(card, Mapping)
        or card.get("gen_type") != "image"
        or card.get("publication_scope") != "feed"
        or card.get("prompt_hidden") is not False
        or card.get("feed_prompt_visible") is not True
        or card.get("prompt_actions_allowed") is not True
        or card.get("media_unavailable") is not False
        or card.get("feed_blurred") is True
        or type(card.get("prompt")) is not str
        or not card["prompt"].strip()
    ):
        return None
    model = card.get("model")
    if type(model) is not str:
        return None
    return NATIVE_IMAGE_MODELS.get(model)


def build_vk_feed_repeat(
    card: Mapping[str, Any],
    catalog: Mapping[str, Any],
    verified_references: Sequence[str],
    *,
    quote_only: bool,
    client_request_id: str | None,
    expected_cost: float | None,
) -> dict[str, Any]:
    """Use the server-owned public source prompt, *new VK-owned* input photos.

    No source reference URLs are forwarded. The native worker validates
    model pricing and debits its authoritative SQLite ledger exactly once.
    """
    model_id = native_vk_feed_repeat_model(card)
    if model_id is None:
        raise ValueError("VK feed publication is unavailable for repeat")
    if not isinstance(catalog, Mapping) or catalog.get("ok") is not True:
        raise ValueError("Native VK model catalogue unavailable")
    models = catalog.get("photo_models")
    if not isinstance(models, list):
        raise TypeError("Native VK photo model catalogue invalid")
    model = next((item for item in models if isinstance(item, Mapping)
                  and item.get("id") == model_id), None)
    if model is None:
        raise ValueError("Native VK model unavailable")
    ratio = card.get("aspect_ratio")
    ratios = model.get("ratios")
    resolutions = model.get("resolutions")
    max_photos = model.get("max_references")
    if (
        type(ratio) is not str or not ratio
        or not isinstance(ratios, list) or ratio not in ratios
        or not isinstance(resolutions, list) or not resolutions
        or any(type(item) is not str or not item for item in resolutions)
        or type(max_photos) is not int or max_photos < 0
        or not isinstance(verified_references, (tuple, list))
        or len(verified_references) > max_photos
        or any(type(url) is not str or not url for url in verified_references)
        or len(set(verified_references)) != len(verified_references)
    ):
        raise ValueError("VK feed repeat exceeds native model capabilities")
    # Resolution is chosen from the authoritative live native catalogue,
    # never from Telegram request_data, client quote or a hardcoded price.
    result: dict[str, Any] = {
        "model": model_id,
        "prompt": card["prompt"].strip(),
        "aspect": ratio,
        "resolution": resolutions[0],
        "reference_photos": list(verified_references),
    }
    if quote_only is True:
        result["quote_only"] = True
    else:
        if type(client_request_id) is not str or _IDEMPOTENCY_KEY.fullmatch(client_request_id) is None:
            raise ValueError("Native VK feed repeat requires an idempotency key")
        if type(expected_cost) not in (int, float) or not math.isfinite(expected_cost) or expected_cost <= 0:
            raise ValueError("Native VK feed repeat requires the quoted price")
        result["client_request_id"] = client_request_id
        result["expected_cost"] = expected_cost
    return result
