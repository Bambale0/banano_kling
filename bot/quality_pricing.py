from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_QUALITY = "2K"
# Safe defaults for a clean install or malformed runtime config.
# Production values are admin-managed in data/price.json and take precedence.
_LEGACY_FALLBACK_COSTS = {"1K": 1.5, "2K": 1.5, "4K": 2.0}
QUALITY_COSTS: dict[str, float] = {}
QUALITY_LABELS: dict[str, str] = {}
SEEDREAM_5_PRO_QUALITY_COSTS = {
    "basic": 2,
    "BASIC": 2,
    "high": 2.5,
    "HIGH": 2.5,
}


def _price_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "price.json"


def _read_price_config() -> dict[str, Any]:
    try:
        with _price_path().open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalized_quality_costs(
    price_config: dict[str, Any] | None = None,
) -> dict[str, float]:
    config = price_config if isinstance(price_config, dict) else _read_price_config()
    raw = (
        config.get("costs_reference", {})
        .get("image_quality_costs", {})
        if isinstance(config, dict)
        else {}
    )
    if not isinstance(raw, dict):
        raw = {}

    normalized: dict[str, float] = {}
    for quality in ("1K", "2K", "4K"):
        value = raw.get(quality, _LEGACY_FALLBACK_COSTS[quality])
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            value = _LEGACY_FALLBACK_COSTS[quality]
        normalized[quality] = float(value)
    return normalized


def refresh_quality_pricing(
    price_config: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Reload Banana resolution tariffs while preserving imported dict references."""
    normalized = _normalized_quality_costs(price_config)

    QUALITY_COSTS.clear()
    for quality, cost in normalized.items():
        QUALITY_COSTS[quality] = cost
        QUALITY_COSTS[quality.lower()] = cost

    QUALITY_LABELS.clear()
    for quality in ("1K", "2K", "4K"):
        QUALITY_LABELS[quality] = f"{quality} качество — {QUALITY_COSTS[quality]:g} 🍌"

    return dict(normalized)


refresh_quality_pricing()
