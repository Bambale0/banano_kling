"""Independent Omni Video generation, quality pricing and reference safety."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bot import web_generation
from bot.services.gemini_omni_service import gemini_omni_service
from bot.services.preset_manager import preset_manager


def test_gemini_web_quote_uses_admin_resolution_rate_without_telegram():
    # The configured retail rate applies per billed output second.
    rates = preset_manager.get_video_quality_costs("gemini_omni")
    if not rates:
        pytest.skip("Gemini Omni admin price not configured")
    by_id = {item["id"]: item for item in web_generation._models()}
    assert by_id["gemini_omni"]["enabled"] is True
    assert by_id["gemini_omni"]["qualities"] == ["720p", "1080p", "4k"]
    for quality in ("720p", "1080p", "4k"):
        price = web_generation._price("video", "gemini_omni", 6, quality)
        assert float(price) == preset_manager.get_video_cost_with_quality(
            "gemini_omni", 6, quality,
        )


def test_gemini_browser_restricts_refs_to_supported_and_owned_image_urls_only():
    valid = web_generation._normalize_request({
        "model": "gemini_omni", "prompt": "Person crossing a rainy street",
        "request_key": "gemini-video-browser-2026",
        "duration": 6, "quality": "1080p", "aspect_ratio": "16:9",
        "reference_ids": ["wr_" + "1" * 32],
    })
    assert valid["quality"] == "1080p"
    assert valid["reference_ids"] == ["wr_" + "1" * 32]
    for extras in (
        {"quality": "12k"},
        {"video_reference_ids": ["wr_" + "2" * 32]},
        {"audio_reference_ids": ["wr_" + "2" * 32]},
        {"character_ids": ["some-id"]},
        {"audio_ids": ["some-id"]},
    ):
        with pytest.raises(ValueError):
            web_generation._normalize_request({
                "model": "gemini_omni", "prompt": "A long video",
                "request_key": "gemini-video-browser-2026", **extras,
            })


@pytest.mark.asyncio
async def test_gemini_web_provider_uses_existing_video_adapter_without_telegram(monkeypatch):
    fake = AsyncMock(return_value={"task_id": "kie-gemini-omni-123"})
    monkeypatch.setattr(gemini_omni_service, "generate_video", fake)
    task, rejected = await web_generation._submit_to_provider(
        "web_" + "a" * 32, {
            "model": "gemini_omni", "prompt": "A train going through forest",
            "duration": 6, "aspect_ratio": "16:9", "quality": "1080p",
            "reference_urls": ["https://neuromixbot.com/uploads/web_refs/one.png"],
        },
    )
    assert (task, rejected) == ("kie-gemini-omni-123", False)
    assert fake.await_args.kwargs["resolution"] == "1080p"
    assert fake.await_args.kwargs["image_urls"] == [
        "https://neuromixbot.com/uploads/web_refs/one.png"
    ]
    assert "telegram_id" not in fake.await_args.kwargs
    assert "audio_ids" not in fake.await_args.kwargs
    assert "character_ids" not in fake.await_args.kwargs
