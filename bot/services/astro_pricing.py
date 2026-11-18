"""Admin-managed Astro service price catalog; never charges or reserves balance.

Astro is admin-only and reports currently have no billing integration.
Prices are catalogue configuration for future rollout, not an implicit debit.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal, InvalidOperation
from typing import Any

ASTRO_SERVICE_LABELS: dict[str, str] = {
    "natal": "Натальная карта",
    "compatibility": "Совместимость",
    "karma": "Кармический разбор",
    "year": "Годовой прогноз",
    "month": "Гороскоп на месяц",
    "solar": "Соляр",
    "lunar": "Лунный календарь",
}


def _validated_price(value: Any) -> int | float:
    """Enforce positive, finite banana prices with at most two decimals."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Astro price must be a number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Astro price must be finite and positive")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Invalid Astro price") from exc
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Astro price supports at most two fractional digits")
    return int(amount) if amount == amount.to_integral_value() else float(amount)


def validate_astro_service_prices(config: dict[str, Any]) -> None:
    """Validate optional service_prices.astro without requiring legacy migration."""
    services = config.get("service_prices", {})
    if not isinstance(services, dict):
        raise ValueError("service_prices must be an object")
    astro = services.get("astro", {})
    if not isinstance(astro, dict):
        raise ValueError("service_prices.astro must be an object")
    unknown = set(astro) - set(ASTRO_SERVICE_LABELS)
    if unknown:
        raise ValueError("Unknown Astro service price")
    for value in astro.values():
        _validated_price(value)


def get_astro_service_price(config: dict[str, Any], service_id: str) -> int | float | None:
    """Unset prices are None, never zero or an invented billable default."""
    if service_id not in ASTRO_SERVICE_LABELS:
        raise ValueError("Unknown Astro service")
    validate_astro_service_prices(config)
    return config.get("service_prices", {}).get("astro", {}).get(service_id)


async def update_astro_service_price(
    manager: Any, service_id: str, value: int | float,
    *, expected_old: int | float | None,
) -> int | float | None:
    """CAS write under the same lock as authenticated internal tariff publishing.

    Preserve all unrelated settings, use atomic fsync/rename, rollback on reload
    failures. No balances, generation jobs or pricing quotation are touched.
    """
    from bot import internal_admin_tariffs as tariffs

    if service_id not in ASTRO_SERVICE_LABELS:
        raise ValueError("Unknown Astro service")
    new_value = _validated_price(value)
    async with tariffs._publish_lock():
        path = manager.price_path
        old_bytes = path.read_bytes()
        config = json.loads(old_bytes)
        if not isinstance(config, dict):
            raise ValueError("Invalid price catalog")
        current = get_astro_service_price(config, service_id)
        if current != expected_old:
            raise ValueError("Astro price changed: reopen the editor")
        config.setdefault("service_prices", {}).setdefault("astro", {})[service_id] = new_value
        validate_astro_service_prices(config)
        new_bytes = json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        try:
            tariffs._atomic_write(path, new_bytes)
            if not manager.reload():
                raise RuntimeError("Astro price reload failed")
        except Exception:
            tariffs._atomic_write(path, old_bytes)
            manager.reload()
            raise
        return current
