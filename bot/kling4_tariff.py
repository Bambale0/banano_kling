"""Admin-managed nominal Kling 4 pricing over measured provider billing units."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any

from bot.services.kling4_contract import Kling4Error
from bot.services.preset_manager import preset_manager

MODEL_KEY = "kling_4"
CATEGORIES = ("reference", "keyframe", "video")
QUALITIES = ("720p", "1080p")
ADMIN_RATE_FIELDS = {
    "rr720": ("reference", "720p", "Reference 720p"),
    "rr1080": ("reference", "1080p", "Reference 1080p"),
    "kf720": ("keyframe", "720p", "Keyframe 720p"),
    "kf1080": ("keyframe", "1080p", "Keyframe 1080p"),
    "vr720": ("video", "720p", "Video reference 720p"),
    "vr1080": ("video", "1080p", "Video reference 1080p"),
}


class Kling4TariffNotConfigured(Kling4Error):
    """The admin has not published a complete retail tariff yet."""


def validate_kling4_model_config(
    model_config: Any, *, require_complete: bool = True
) -> dict[str, Any]:
    """Validate the Kling 4 block accepted by the existing tariff publisher."""
    if not isinstance(model_config, dict):
        raise TypeError("video_models.kling_4 must be an object")
    rates = model_config.get("billing_rates")
    if (
        not isinstance(rates, dict)
        or set(rates) - set(CATEGORIES)
        or (require_complete and set(rates) != set(CATEGORIES))
    ):
        raise ValueError(
            "video_models.kling_4.billing_rates must contain reference, keyframe and video"
        )
    normalized: dict[str, dict[str, float]] = {}
    for category in CATEGORIES:
        qualities = rates.get(category)
        if qualities is None and not require_complete:
            continue
        if (
            not isinstance(qualities, dict)
            or set(qualities) - set(QUALITIES)
            or (require_complete and set(qualities) != set(QUALITIES))
        ):
            raise ValueError(
                f"video_models.kling_4.billing_rates.{category} must contain 720p and 1080p"
            )
        normalized[category] = {}
        for quality in qualities:
            value = qualities[quality]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(
                    f"video_models.kling_4.billing_rates.{category}.{quality} must be a number"
                )
            number = float(value)
            if not math.isfinite(number) or number <= 0:
                raise ValueError(
                    f"video_models.kling_4.billing_rates.{category}.{quality} must be finite and positive"
                )
            normalized[category][quality] = number
    result = deepcopy(model_config)
    result["billing_rates"] = normalized
    return result


def _price_config() -> dict[str, Any]:
    value = preset_manager.get_price_config()
    return value if isinstance(value, dict) else {}


def admin_rate_rows(model_config: Any) -> list[tuple[str, str, str, str, Any]]:
    """Return the six stable admin fields even before a tariff exists."""
    rates = (
        model_config.get("billing_rates", {}) if isinstance(model_config, dict) else {}
    )
    def editable_value(category: str, quality: str) -> Any:
        group = rates.get(category, {})
        value = group.get(quality) if isinstance(group, dict) else None
        # The shared admin editor chooses integer vs. decimal parsing from the
        # current value's type. Kling rates are decimal per-second values even
        # when JSON happened to store a whole number such as 1.
        return (
            float(value)
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else value
        )

    return [
        (
            field,
            category,
            quality,
            label,
            editable_value(category, quality),
        )
        for field, (category, quality, label) in ADMIN_RATE_FIELDS.items()
    ]


def update_admin_rate(manager: Any, field: str, value: Any) -> Any:
    """Persist one admin UI cell and verify that the manager can read it back."""
    if field not in ADMIN_RATE_FIELDS:
        raise KeyError("kling4_rate")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("Kling 4 rate must be a number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("Kling 4 rate must be finite and positive")

    config = deepcopy(manager.get_price_config())
    models = config.setdefault("costs_reference", {}).setdefault("video_models", {})
    model = models.setdefault(MODEL_KEY, {})
    category, quality, _label = ADMIN_RATE_FIELDS[field]
    qualities = model.setdefault("billing_rates", {}).setdefault(category, {})
    old_value = qualities.get(quality)
    qualities[quality] = value
    if not manager.update_price_config(config):
        raise RuntimeError("price config reload failed")
    saved = manager.get_price_config()
    read_back = (
        saved.get("costs_reference", {})
        .get("video_models", {})
        .get(MODEL_KEY, {})
        .get("billing_rates", {})
        .get(category, {})
        .get(quality)
    )
    if read_back != value:
        raise RuntimeError("Kling 4 rate was not readable after save")
    return old_value


def nominal_admin_quote(
    provider_quote: dict[str, Any], *, price_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Price the exact measured provider category/quality/seconds for an admin."""
    config = price_config if price_config is not None else _price_config()
    model_config = (
        config.get("costs_reference", {}).get("video_models", {}).get(MODEL_KEY)
        if isinstance(config, dict)
        else None
    )
    if model_config is None:
        raise Kling4TariffNotConfigured(
            "Цена Kling 4 не настроена. Задайте тариф в админке."
        )
    try:
        model_config = validate_kling4_model_config(model_config)
    except (TypeError, ValueError) as exc:
        raise Kling4TariffNotConfigured(
            "Цена Kling 4 настроена частично. Проверьте тариф в админке."
        ) from exc

    category = str(provider_quote.get("tariff") or "").strip().lower()
    quality = str(provider_quote.get("resolution") or "").strip().lower()
    if category not in CATEGORIES or quality not in QUALITIES:
        raise Kling4Error("Не удалось определить тариф Kling 4.")
    try:
        seconds = Decimal(str(provider_quote["billed_seconds"]))
        rate = Decimal(str(model_config["billing_rates"][category][quality]))
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise Kling4Error("Не удалось рассчитать цену Kling 4.") from exc
    if not seconds.is_finite() or seconds <= 0:
        raise Kling4Error("Не удалось рассчитать тарифицируемые секунды Kling 4.")

    cost = float(preset_manager._format_cost(float(rate * seconds)))
    if not math.isfinite(cost) or cost <= 0:
        raise Kling4TariffNotConfigured(
            "Цена Kling 4 настроена частично. Проверьте тариф в админке."
        )
    revision_payload = {
        "model": MODEL_KEY,
        "billing_rates": model_config["billing_rates"],
    }
    revision = hashlib.sha256(
        json.dumps(
            revision_payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()[:16]
    return {
        "cost": cost,
        "charge_cost": 0.0,
        "profile": "admin",
        "retail_rate": str(rate),
        "retail_revision": revision,
        "credit_name": str(
            config.get("credit_name_plural") or config.get("credit_name") or ""
        ).strip(),
        "credit_emoji": str(config.get("credit_emoji") or "").strip(),
    }


def attach_nominal_admin_price(
    provider_quote: dict[str, Any], *, price_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Freeze nominal retail price into the launch quote and its hash."""
    payload = {
        key: value for key, value in provider_quote.items() if key != "quote_hash"
    }
    payload.update(nominal_admin_quote(payload, price_config=price_config))
    payload["admin_free"] = True
    payload["quote_hash"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    return payload


def format_admin_price(quote: dict[str, Any]) -> str:
    cost = float(quote["cost"])
    amount = f"{cost:g}"
    unit = " ".join(
        value
        for value in (
            str(quote.get("credit_emoji") or "").strip(),
            str(quote.get("credit_name") or "").strip(),
        )
        if value
    )
    return f"Цена: {amount} {unit}.\nДля администратора списание отключено."
