"""Ordinary Seedance 2 rates remain editable without rewriting legacy prices."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.creator_tariff import resolve_video_quote
from bot.creator_tariff_display import price_video_model_metadata
from bot.handlers import admin
from bot.services.preset_manager import preset_manager


@pytest.fixture
def ordinary_prices(monkeypatch):
    prices = deepcopy(preset_manager.get_price_config())
    prices["costs_reference"]["video_models"]["seedance_2"] = {
        "base": 20, "duration_costs": {"5": 20, "10": 40, "15": 60},
        "quality_costs": {"480p": 2, "720p": 5},
    }
    prices.pop("creator_tariff", None)
    monkeypatch.setattr(preset_manager, "_price_config", deepcopy(prices))
    monkeypatch.setattr(admin, "_read_price_config", preset_manager.get_price_config)
    monkeypatch.setattr(admin, "is_admin", lambda _uid: True)
    writes = []

    def save(value):
        writes.append(deepcopy(value))
        preset_manager._price_config = deepcopy(value)
        return True

    monkeypatch.setattr(preset_manager, "update_price_config", save)
    return prices, writes


@pytest.mark.parametrize("model", ["seedance_2", "seedance-2.0", "bytedance/seedance-2"])
@pytest.mark.parametrize("quality", [None, "", "   ", "720P", " 720p "])
def test_default_matches_actual_provider_resolution(ordinary_prices, model, quality):
    quote = resolve_video_quote(model, 5, quality)
    assert quote.cost == 25
    assert quote.charge_cost == 25
    assert quote.quality == "720p"


@pytest.mark.parametrize("field,new_rate,expected_default,expected_explicit", [
    ("q720p", 6, 30, 30),
    ("q480p", 7, 25, 35),
])
async def test_admin_save_prices_next_quote_and_preserves_every_other_value(
    ordinary_prices, field, new_rate, expected_default, expected_explicit,
):
    before, writes = ordinary_prices
    original_quote = resolve_video_quote("seedance_2", 5)
    state = SimpleNamespace(get_data=AsyncMock(return_value={
        "price_target": "video", "price_key": "seedance_2", "price_field": field,
        "current_price_value": before["costs_reference"]["video_models"]["seedance_2"]["quality_costs"][field[1:]],
        "return_to": "admin_video_model_seedance_2",
    }), clear=AsyncMock())
    message = SimpleNamespace(from_user=SimpleNamespace(id=999999999), text=str(new_rate), answer=AsyncMock())
    await admin.admin_process_price_value(message, state)
    assert "Цена обновлена" in message.answer.await_args.args[0]
    state.clear.assert_awaited_once()
    expected = deepcopy(before)
    expected["costs_reference"]["video_models"]["seedance_2"]["quality_costs"][field[1:]] = new_rate
    assert writes == [expected]
    assert preset_manager.get_price_config() == expected
    assert resolve_video_quote("seedance_2", 5).cost == expected_default
    assert resolve_video_quote("seedance_2", 5, field[1:]).cost == expected_explicit
    assert original_quote.cost == 25


@pytest.mark.parametrize("quality_costs", [{}, {"480p": 2}])
def test_missing_default_quality_keeps_legacy_duration_prices(ordinary_prices, quality_costs):
    preset_manager._price_config["costs_reference"]["video_models"]["seedance_2"]["quality_costs"] = quality_costs
    assert [resolve_video_quote("seedance_2", duration).cost for duration in (5, 10, 15)] == [20, 40, 60]


def test_refreshed_metadata_uses_current_rates_without_global_or_historical_mutation(ordinary_prices):
    metadata = {"id": "seedance_2", "durations": [5, 10, 15], "costs": {"5": 20}}
    before = deepcopy(metadata)
    old = price_video_model_metadata(metadata)
    preset_manager._price_config["costs_reference"]["video_models"]["seedance_2"]["quality_costs"]["720p"] = 6
    fresh = price_video_model_metadata(metadata)
    assert old["costs"] == {"5": 25, "10": 50, "15": 75}
    assert fresh["costs"] == {"5": 30, "10": 60, "15": 90}
    assert fresh["quality_duration_costs"]["720p"] == fresh["costs"]
    assert metadata == before
