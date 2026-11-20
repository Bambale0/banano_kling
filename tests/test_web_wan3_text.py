"""Wan3 web text scenarios never invent pricing or Telegram accounts."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bot import web_generation
from bot.services.preset_manager import preset_manager
from bot.services.wan3_models import wan3_service_for_model


@pytest.mark.parametrize("model", ["wan_3_prime", "wan_3"])
def test_wan3_text_mode_requires_admin_quality_rate_and_exact_duration(monkeypatch, model):
    # Production may not yet have configured Wan3 rates. A missing rate must
    # disable the purchasing option, NOT fallback to an unrelated video price.
    monkeypatch.setattr(preset_manager, "get_video_quality_costs",
                        lambda m: {"720p": 2.25} if m == model else {})
    price = web_generation._price("video", model, 6, "720P")
    from bot.services.wan3_prime_lifecycle import _round_half_credit

    assert float(price) == _round_half_credit(6 * 2.25)
    with pytest.raises(ValueError):
        web_generation._price("video", model, 6, "480P")
    for payload in (
        {"duration": -1},
        {"wan_scenario": "text", "reference_ids": ["wr_" + "1" * 32]},
        {"video_reference_ids": ["wr_" + "2" * 32]},
        {"audio_reference_ids": ["wr_" + "3" * 32]},
    ):
        with pytest.raises(ValueError):
            web_generation._normalize_request({
                "model": model, "prompt": "Time-lapse of growing trees",
                "request_key": "wan3-text-mode-2026", **payload,
            })


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["wan_3_prime", "wan_3"])
async def test_wan3_text_provider_uses_prepared_existing_wire_contract(monkeypatch, model):
    service = wan3_service_for_model(model)
    mock_submit = AsyncMock(return_value={"task_id": "wan-task-created"})
    monkeypatch.setattr(service, "submit_prepared", mock_submit)
    task, rejected = await web_generation._submit_to_provider(
        "web_" + "b" * 32, {
            "model": model, "prompt": "A bird taking flight over water",
            "aspect_ratio": "16:9", "duration": 6,
            "quality": "720P", "reference_urls": [],
            "reference_video_urls": [], "reference_audio_urls": [],
        },
    )
    assert (task, rejected) == ("wan-task-created", False)
    mock_submit.assert_awaited_once()
    wire = mock_submit.await_args.args[0]
    assert wire["duration"] == 6
    assert wire["resolution"] == "720P"
    assert wire["aspect_ratio"] == "16:9"
    assert "telegram_id" not in wire and "user_id" not in wire


def test_wan3_catalog_can_be_safely_disabled_without_admin_rates(monkeypatch):
    monkeypatch.setattr(preset_manager, "get_video_quality_costs", lambda _: {})
    entries = {m["id"]: m for m in web_generation._models()}
    for model in ("wan_3", "wan_3_prime"):
        assert entries[model]["enabled"] is False
        assert entries[model]["unavailable_reason"]



@pytest.mark.parametrize("scenario,count", [
    ("first_frame", 1), ("first_last", 2), ("reference", 3),
])
def test_wan3_image_scenarios_require_exact_refs_and_live_resolution_rate(monkeypatch, scenario, count):
    monkeypatch.setattr(preset_manager, "get_video_quality_costs",
                        lambda _: {"720p": 2.25})
    refs = ["wr_" + f"{idx + 1:032x}" for idx in range(count)]
    payload = {
        "model": "wan_3", "prompt": "Sunset on coastal cliffs",
        "request_key": "wan3-images-scenario-2026",
        "wan_scenario": scenario, "reference_ids": refs,
        "duration": 6, "quality": "720P",
    }
    normalized = web_generation._normalize_request(payload)
    assert normalized["wan_scenario"] == scenario
    assert normalized["reference_ids"] == refs
    with pytest.raises(ValueError):
        web_generation._normalize_request({
            **payload, "reference_ids": refs[:-1] if scenario != "reference" else [],
        })


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,image_count,wire_keys", [
    ("first_frame", 1, ("first_frame_url",)),
    ("first_last", 2, ("first_frame_url", "last_frame_url")),
    ("reference", 3, ("reference_image_urls",)),
])
async def test_wan3_image_provider_prepares_explicit_recipe_without_telegram(
    monkeypatch, scenario, image_count, wire_keys,
):
    service = wan3_service_for_model("wan_3")
    prepare = AsyncMock(return_value={"scenario": scenario, "duration": "6"})
    submit = AsyncMock(return_value={"task_id": "wan3-verified-image"})
    monkeypatch.setattr(service, "prepare_request", prepare)
    monkeypatch.setattr(service, "submit_prepared", submit)
    urls = [f"https://neuromixbot.com/uploads/web_refs/owned-{i}.png"
            for i in range(image_count)]
    task, rejected = await web_generation._submit_to_provider(
        "web_" + "f" * 32, {
            "model": "wan_3", "prompt": "Clouds flying over a city",
            "wan_scenario": scenario, "duration": 6, "quality": "720P",
            "aspect_ratio": "16:9", "reference_urls": urls,
            "reference_video_urls": [], "reference_audio_urls": [],
        },
    )
    assert (task, rejected) == ("wan3-verified-image", False)
    kwargs = prepare.await_args.kwargs
    assert kwargs["scenario"] == scenario
    assert all(key in kwargs for key in wire_keys)
    assert "telegram_id" not in kwargs
