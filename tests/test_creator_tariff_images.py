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


@pytest.mark.asyncio
@pytest.mark.parametrize("tariff", ["standard", "creator"])
@pytest.mark.parametrize(
    ("model", "quality", "ordinary", "creator"),
    [
        ("banana_pro", "2K", 4.0, 1.25),
        ("banana_2", "4K", 5.0, 1.5),
        ("seedream_5_pro", "basic", 6.0, 1.75),
    ],
)
@pytest.mark.parametrize("historical", [0.0, 1.0, 100.0])
async def test_repeat_image_price_belongs_to_actor_not_source(
    creator_image_prices, monkeypatch, tariff, model, quality,
    ordinary, creator, historical,
):
    from bot.handlers import generation

    actor_tariff = AsyncMock(return_value=tariff)
    monkeypatch.setattr(generation, "get_actor_tariff", actor_tariff)
    cost = await generation._resolve_repeat_image_unit_cost(
        101, model, quality, historical,
    )
    assert cost == (creator if tariff == "creator" else ordinary)
    actor_tariff.assert_awaited_once_with(101)


@pytest.mark.asyncio
@pytest.mark.parametrize("tariff,expected", [("standard", 4.0), ("creator", 1.25)])
async def test_telegram_repeat_confirmation_debits_actor_price(
    creator_image_prices, monkeypatch, tariff, expected,
):
    import json

    from bot.handlers import generation

    task = SimpleNamespace(
        id=42, type="image", user_id=8, model="banana_pro", cost=1.0,
        aspect_ratio="1:1", prompt="Synthetic scene",
        request_data=json.dumps({"img_service": "banana_pro", "img_quality": "2K"}),
    )
    monkeypatch.setattr(generation, "_resolve_repeat_image_task",
                        AsyncMock(return_value=("source", task)))
    monkeypatch.setattr(generation, "get_or_create_user",
                        AsyncMock(return_value=SimpleNamespace(id=7, credits=100)))
    monkeypatch.setattr(generation, "generation_has_private_recipe", lambda _: False)
    monkeypatch.setattr(generation, "_image_repeat_private_context",
                        AsyncMock(return_value=([], None)))
    monkeypatch.setattr(generation, "validate_private_repeat_reference_access",
                        AsyncMock(return_value=True))
    monkeypatch.setattr(generation, "get_actor_tariff", AsyncMock(return_value=tariff))
    monkeypatch.setattr(generation.config, "is_admin", lambda _: False)
    monkeypatch.setattr(generation, "check_can_afford", AsyncMock(return_value=True))
    debit = AsyncMock(return_value=True)
    monkeypatch.setattr(generation, "deduct_credits", debit)
    launch = AsyncMock(return_value={"status": "queued", "task_id": "synthetic-repeat"})
    monkeypatch.setattr(generation, "_start_image_generation_task", launch)
    progress = SimpleNamespace(delete=AsyncMock(), edit_text=AsyncMock())
    callback = SimpleNamespace(
        data="repeat_run_confirm_source", from_user=SimpleNamespace(id=101),
        message=SimpleNamespace(answer=AsyncMock(return_value=progress)),
        answer=AsyncMock(),
    )

    await generation.quick_repeat_image_confirm(callback, SimpleNamespace())

    debit.assert_awaited_once_with(101, expected)
    assert launch.await_args.kwargs["unit_cost"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("tariff,expected", [("standard", 4.0), ("creator", 1.25)])
async def test_miniapp_remix_debits_actor_price_not_source(
    creator_image_prices, monkeypatch, tariff, expected,
):
    body = {"init_data": "signed", "gen_id": 42, "reference_images": []}
    card = {"id": 42, "gen_type": "image", "is_mine": False, "model": "banana_pro"}
    source = {
        "id": 42, "type": "image", "status": "completed", "is_public_feed": True,
        "prompt": "Synthetic scene", "cost": 1.0,
        "request_data": {"img_service": "banana_pro", "img_quality": "2K"},
    }
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(return_value=body))
    monkeypatch.setattr(miniapp, "_get_user_context",
                        AsyncMock(return_value=(101, {"user": SimpleNamespace(id=7, credits=100)})))
    monkeypatch.setattr(miniapp, "_get_feed_remix_source_card", AsyncMock(return_value=card))
    monkeypatch.setattr(miniapp, "get_generation_task_payload", AsyncMock(return_value=source))
    monkeypatch.setattr(creator_tariff_display, "get_actor_tariff", AsyncMock(return_value=tariff))
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _: False)
    monkeypatch.setattr(miniapp, "check_can_afford", AsyncMock(return_value=True))
    debit = AsyncMock(return_value=True)
    monkeypatch.setattr(miniapp, "deduct_credits", debit)
    monkeypatch.setattr(miniapp, "add_credits", AsyncMock())
    launch = AsyncMock(return_value={"status": "failed"})
    monkeypatch.setattr(miniapp, "_start_image_generation_task_lazy", launch)

    response = await miniapp.miniapp_feed_remix(SimpleNamespace(app={}))

    assert response.status == 500  # synthetic provider failure after pricing
    debit.assert_awaited_once_with(101, expected)
    assert launch.await_args.kwargs["unit_cost"] == expected
