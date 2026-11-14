"""Seedream 5.5 prices from existing admin-managed price.json configuration.

Price cells correspond to keys in costs_reference.image_models, which are
exposed by the existing admin price-editing keyboard.
"""
from __future__ import annotations

import math

from bot.services.preset_manager import preset_manager

QUALITY_PRICE_KEYS = {"1K": "seedream_55_1k", "1.5K": "seedream_55_1_5k", "2K": "seedream_55_2k"}
INPUT_PRICE_KEY = "seedream_55_ref"
SEEDREAM55_KEYS = {"seedream_55", "seedream_55_layers"}


def _config_rates() -> dict:
    data = preset_manager.get_price_config()
    costs = data.get("costs_reference", {}).get("image_models", {})
    return costs if isinstance(costs, dict) else {}


def price_cells() -> dict[str, float]:
    rates = _config_rates()
    keys = [*QUALITY_PRICE_KEYS.values(), INPUT_PRICE_KEY]
    cells = {}
    for key in keys:
        value = rates.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"Seedream 5.5 price is missing or invalid: {key}")
        cells[key] = float(value)
    return cells


def quality_prices() -> dict[str, float]:
    cells = price_cells()
    return {quality: cells[key] for quality, key in QUALITY_PRICE_KEYS.items()}


def input_image_price() -> float:
    return price_cells()[INPUT_PRICE_KEY]


def image_generation_cost(
    model: str, quality: str, *, reference_count: int = 0, max_images: int = 30,
) -> float:
    if model not in SEEDREAM55_KEYS:
        raise ValueError("Not a Seedream 5.5 model")
    rates = quality_prices()
    if quality not in rates and not (model == "seedream_55_layers" and quality == "auto"):
        raise ValueError("Unsupported Seedream 5.5 quality")
    if model == "seedream_55_layers":
        if reference_count != 1 or type(max_images) is not int or not 2 <= max_images <= 100:
            raise ValueError("Layers require one reference and 2–100 max images")
        # Worst-case reserve includes the composite image. Reconcile actual count after success.
        return round(max_images * rates.get(quality, rates["2K"]) + input_image_price(), 3)
    if type(reference_count) is not int or not 0 <= reference_count <= 10:
        raise ValueError("Unsupported Seedream 5.5 reference count")
    return round(rates[quality] + reference_count * input_image_price(), 3)
