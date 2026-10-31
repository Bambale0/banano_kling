"""Creator image pricing: optional admin-managed overrides with ordinary fallback."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import creator_tariff, creator_tariff_display, miniapp, trend_api
from bot.quality_pricing import refresh_quality_pricing
from bot.services.preset_manager import preset_manager


@pytest.fixture
def creator_image_prices(monkeypatch):
    original = deepcopy(preset_manager.get_price_config())
    prices = deepcopy(original)
    costs = prices.setdefault("costs_reference", {})
    costs["image_quality_costs"] = {"1K": 3.0, "2K": 4.0, "4K": 5.0}
    costs["seedream_5_pro_quality_costs"] = {"basic": 6.0, "high": 7.0}

    prices["creator_tariff"] = {
        "enabled": True,
        "video_models": {
            model: {
                "quality_costs": {quality: 2.0 for quality in qualities}
            }
            for model, qualities in creator_tariff._required_qualities().items()
        },
        "image_models": {
            "nano-banana-pro": {
                "quality_costs": {"1K": 1.0, "2K": 1.25, "4K": 1.5}
            },
            "banana_2": {
                "quality_costs": {"1K": 1.0, "2K": 1.25, "4K": 1.5}
            },
            "seedream_5_pro": {
                "quality_costs": {"basic": 1.75, "high": 2.25}
            },
        },
    }
    monkeypatch.setattr(preset_manager, "_price_config", prices)
    refresh_quality_pricing(prices)
    try:
        yield prices
    finally:
        refresh_quality_pricing(original)


@pytest.mark.parametrize(
    ("model", "quality", "expected"),
    [
        ("banana_pro", "1K", 1.0),
        ("nano-banana-pro", "4K", 1.5),
        ("banana_2", "2K", 1.25),
        ("seedream_5_pro", "basic", 1.75),
        ("seedream_5_pro", "high", 2.25),
    ],
)
def test_creator_image_rates_override_target_models(
    creator_image_prices, model, quality, expected
):
    assert creator_tariff.resolve_image_unit_cost(
        model, quality, tariff="creator"
    ) == expected


def test_creator_image_missing_cell_falls_back_to_ordinary_without_disabling_tariff(
    creator_image_prices,
):
    creator_image_prices["creator_tariff"]["image_models"]["nano-banana-pro"][
        "quality_costs"
    ].pop("4K")
    assert creator_tariff.creator_tariff_status()["configured"] is True
    assert creator_tariff.resolve_image_unit_cost(
        "banana_pro", "4K", tariff="creator"
    ) == 5.0
    assert creator_tariff.resolve_image_unit_cost(
        "banana_pro", "4K", tariff="standard"
    ) == 5.0


def test_creator_image_config_rejects_unknown_model_and_invalid_price(
    creator_image_prices,
):
    raw = deepcopy(creator_image_prices["creator_tariff"])
    raw["image_models"]["unknown"] = {"quality_costs": {"2K": 1}}
    with pytest.raises(ValueError):
        creator_tariff.validate_creator_tariff_config(raw)

    raw = deepcopy(creator_image_prices["creator_tariff"])
    raw["image_models"]["banana_2"]["quality_costs"]["2K"] = 0
    with pytest.raises(ValueError):
        creator_tariff.validate_creator_tariff_config(raw)


def test_creator_image_display_is_personalized_without_mutating_shared_metadata(
    creator_image_prices,
):
    banana = {
        "id": "banana_pro",
        "cost": 4.0,
        "quality_costs": {"1K": 3.0, "2K": 4.0, "4K": 5.0},
    }
    before = deepcopy(banana)
    priced = creator_tariff_display.price_image_model_metadata(banana, tariff="creator")
    assert priced["cost"] == 1.25
    assert priced["quality_costs"] == {"1K": 1.0, "2K": 1.25, "4K": 1.5}
    assert banana == before

    seedream = creator_tariff_display.price_image_model_metadata(
        {
            "id": "seedream_5_pro",
            "cost": 6.0,
            "quality_costs": {"basic": 6.0, "high": 7.0},
        },
        tariff="creator",
    )
    assert seedream["cost"] == 1.75
    assert seedream["quality_costs"] == {"basic": 1.75, "high": 2.25}


def test_miniapp_image_resolver_accepts_server_selected_creator_profile(
    creator_image_prices,
):
    assert miniapp._resolve_image_unit_cost(
        "banana_2", "2K", tariff="creator"
    ) == 1.25
    assert miniapp._resolve_image_unit_cost(
        "seedream_5_pro", "high", tariff="creator"
    ) == 2.25


def test_image_trend_repeat_cost_uses_authenticated_creator_profile(
    creator_image_prices,
):
    trend = {
        "id": 77,
        "model": "banana_pro",
        "generation_settings": {
            "kind": "image",
            "model": "banana_pro",
            "quality": "4K",
        },
    }
    assert trend_api.estimate_trend_repeat_cost(trend, tariff="creator") == 1.5
    assert trend_api.estimate_trend_repeat_cost(trend, tariff="standard") == 5.0

@pytest.mark.asyncio
async def test_miniapp_image_launch_debits_authenticated_creator_price(
    creator_image_prices, monkeypatch
):
    class Request:
        def __init__(self):
            self.app = {}
            self.body = {
                "init_data": "signed",
                "prompt": "creator image",
                "img_service": "banana_2",
                "img_quality": "2K",
                "img_ratio": "1:1",
            }

        async def json(self):
            return self.body

    user = SimpleNamespace(id=7, credits=100.0)
    monkeypatch.setattr(
        miniapp,
        "_get_user_context",
        AsyncMock(return_value=(101, {"user": user})),
    )
    tariff = AsyncMock(return_value="creator")
    monkeypatch.setattr(creator_tariff_display, "get_actor_tariff", tariff)
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _telegram_id: False)
    can_afford = AsyncMock(return_value=True)
    debit = AsyncMock(return_value=True)
    launch = AsyncMock(
        return_value={
            "status": "pending",
            "task_id": "creator-image-test",
            "task_type": "image",
        }
    )
    monkeypatch.setattr(miniapp, "check_can_afford", can_afford)
    monkeypatch.setattr(miniapp, "deduct_credits", debit)
    monkeypatch.setattr(miniapp, "_start_image_generation_task_lazy", launch)
    monkeypatch.setattr(
        miniapp,
        "_notify_miniapp_image_task_queued",
        AsyncMock(),
    )
    monkeypatch.setattr(
        miniapp,
        "_deliver_miniapp_direct_image_result",
        AsyncMock(),
    )
    monkeypatch.setattr(
        miniapp,
        "get_or_create_user",
        AsyncMock(return_value=SimpleNamespace(credits=98.75)),
    )

    response = await miniapp.miniapp_generate_image(Request())

    assert response.status == 200
    tariff.assert_awaited_once_with(101)
    can_afford.assert_awaited_once_with(101, 1.25)
    debit.assert_awaited_once_with(101, 1.25)
    assert launch.await_args.kwargs["unit_cost"] == 1.25



def test_legacy_nanobanana_alias_uses_nano_banana_pro_creator_rate(
    creator_image_prices,
):
    creator_image_prices["creator_tariff"]["image_models"]["nano-banana-pro"][
        "quality_costs"
    ]["2K"] = 1.25
    creator_image_prices["creator_tariff"]["image_models"]["banana_2"][
        "quality_costs"
    ]["2K"] = 9.0

    assert creator_tariff.resolve_image_unit_cost(
        "nanobanana", "2K", tariff="creator"
    ) == 1.25
