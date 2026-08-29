from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_banana_resolution_prices_live_in_price_config() -> None:
    config = json.loads(_read("data/price.json"))
    costs = config["costs_reference"]

    assert costs["image_quality_costs"] == {"1K": 2.5, "2K": 5, "4K": 7}
    assert costs["image_models"]["nano-banana-pro"] == 5
    assert costs["image_models"]["banana_2"] == 5


def test_runtime_quality_pricing_is_config_driven() -> None:
    source = _read("bot/quality_pricing.py")

    assert "image_quality_costs" in source
    assert "refresh_quality_pricing" in source
    assert '"2K": 5' not in source
    assert '"4K": 7' not in source


def test_admin_has_resolution_tier_editor_and_refreshes_runtime() -> None:
    source = _read("bot/handlers/banana_resolution_pricing_compat.py")

    assert "admin_banana_quality_prices" in source
    assert "admin_banana_quality_1K" in source
    assert "admin_banana_quality_2K" in source
    assert "admin_banana_quality_4K" in source
    assert 'price_target="image_quality"' in source
    assert "refresh_quality_pricing" in source


def test_compat_is_installed_before_admin_router_is_exposed() -> None:
    source = _read("bot/handlers/__init__.py")

    assert "install_banana_resolution_pricing" in source
    assert "banana_resolution_pricing_router" in source
    assert source.index("install_banana_resolution_pricing") < source.index(
        "admin_router.include_router(admin_module.router)"
    )
