"""Actual account-native provider adapter dispatch contracts.

Every model advertised as enabled must call exactly one underlying existing
provider adapter with a valid task ID. No synthetic Telegram user is involved.
"""
from __future__ import annotations

import importlib
from unittest.mock import AsyncMock

import pytest

from bot import miniapp, web_generation
from bot.services.kling_service import KlingService

_CASES = (
    ("flux_pro", "bot.services.gpt_image_service", "gpt_image_service", "generate_image", False),
    ("nano-banana-2-lite", "bot.services.kie_market_service", "kie_market_service",
     "create_nano_banana_2_lite_task", True),
    ("seedream_55", "bot.services.seedream55_service", "seedream55_service",
     "generate_text_to_image", False),
    ("seedream_5_pro", "bot.services.seedream_service", "seedream_service",
     "generate_text_to_image", False),
    ("banana_pro", "bot.services.nano_banana_pro_service", "nano_banana_pro_service",
     "create_task", True),
    ("banana_2", "bot.services.nano_banana_2_service", "nano_banana_2_service",
     "create_task", True),
    ("seedream_edit", "bot.services.seedream_service", "seedream_service",
     "generate_image", False),
    ("wan_27", "bot.services.wan27_service", "wan27_service",
     "generate_image", False),
    ("grok_imagine_i2i", "bot.services.grok_service", "grok_service",
     "generate_image_to_image", False),
    ("grok_imagine", "bot.services.grok_service", "grok_service",
     "generate_image_to_video", False),
    ("grok_imagine_v15", "bot.services.grok_service", "grok_service",
     "generate_image_to_video_v15", False),
    ("seedance_2", "bot.services.seedance_service", "seedance_service",
     "generate_video", False),
    ("veo3_fast", "bot.services.veo_service", "veo_service",
     "generate_video", False),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("model,module_name,instance_name,method,returns_text", _CASES)
async def test_existing_provider_adapter_gets_billed_web_task_without_telegram(
    monkeypatch, model, module_name, instance_name, method, returns_text,
):
    module = importlib.import_module(module_name)
    provider = getattr(module, instance_name)
    fake = AsyncMock(return_value="provider-task-456" if returns_text else {
        "task_id": "provider-task-456", "status": "pending",
    })
    monkeypatch.setattr(provider, method, fake)
    media, meta = web_generation._model_meta(model)
    ratios = list(meta["ratios"])
    durations = list(meta.get("durations") or [5])
    references = (
        ["https://neuromixbot.com/uploads/web_refs/signed.png"]
        if model in {"seedream_edit", "grok_imagine_i2i", "grok_imagine", "grok_imagine_v15"}
        else []
    )
    payload = {
        "model": model, "media_type": media, "prompt": "Some beautiful scenery",
        "aspect_ratio": "1:1" if "1:1" in ratios else ratios[0],
        "duration": 5 if 5 in durations else durations[0],
        "quality": "2K" if "2K" in meta.get("qualities", []) else
                   (meta.get("qualities") or [""])[0],
        "reference_urls": references,
    }
    task_id, rejected = await web_generation._submit_to_provider(
        "web_" + "1" * 32, payload,
    )
    assert task_id == "provider-task-456", model
    assert rejected is False, model
    fake.assert_awaited_once()
    assert "telegram_id" not in fake.await_args.kwargs
    assert "user_id" not in fake.await_args.kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize("model,method", (
    ("v3_std", "generate_kling_3_video"),
    ("v3_pro", "generate_kling_3_video"),
    ("v26_pro", "generate_kling_25_turbo_video"),
))
async def test_kling_web_task_uses_its_real_adapter_not_telegram(monkeypatch, model, method):
    mock = AsyncMock(return_value={"task_id": "kling-task-999"})
    monkeypatch.setattr(KlingService, method, mock)
    payload = {
        "model": model, "media_type": "video",
        "prompt": "A moving landscape", "aspect_ratio": "16:9",
        "duration": 5, "reference_urls": [], "quality": "",
    }
    task_id, rejected = await web_generation._submit_to_provider(
        "web_" + "b" * 32, payload,
    )
    assert task_id == "kling-task-999"
    assert rejected is False
    mock.assert_awaited_once()
    assert "telegram_id" not in mock.await_args.kwargs


@pytest.mark.asyncio
async def test_kie_task_status_uses_authenticated_record_info(monkeypatch):
    mock = AsyncMock(return_value={
        "data": {"task_id": "provider-abc", "status": "success",
                 "output": "https://cdn.kie.ai/web-finished.png"},
    })
    monkeypatch.setattr(KlingService, "get_task_status", mock)
    state, url = await web_generation._provider_check(
        "web_" + "1" * 32, "provider-abc", "seedream_55",
    )
    assert state == "success"
    assert url == "https://cdn.kie.ai/web-finished.png"


def test_web_model_catalog_derived_from_public_tg_catalog_without_misleading_enabled_flags():
    source = {item["id"] for item in (*miniapp.IMAGE_MODELS, *miniapp.VIDEO_MODELS)}
    catalog = web_generation._models()
    enabled = {item["id"] for item in catalog if item["enabled"]}
    assert source == {item["id"] for item in catalog}
    implemented = web_generation._IMAGE_MODELS | web_generation._VIDEO_MODELS
    assert enabled.issubset(implemented)
    for row in catalog:
        if row["id"] in implemented and not row["enabled"]:
            assert row["unavailable_reason"]
            assert row["id"] in {"wan_3", "wan_3_prime"}
            # Configured admin Wan3 resolution rates are a strict
            # prerequisite; never enable the placeholder generic price.
            assert not web_generation.preset_manager.get_video_quality_costs(row["id"])
    assert "seedream_55_layers" in enabled  # Bounded ZIP + frozen-rate settlement.


@pytest.mark.asyncio
@pytest.mark.parametrize("model,method,media_key", (
    ("motion_control_v26", "generate_motion_control", "video_urls"),
    ("motion_control_v30", "generate_motion_control", "video_urls"),
    ("avatar_std", "generate_kling_ai_avatar", "audio_url"),
    ("avatar_pro", "generate_kling_ai_avatar", "audio_url"),
))
async def test_typed_media_provider_receives_owned_video_or_audio_references(
    monkeypatch, model, method, media_key,
):
    fake = AsyncMock(return_value={"task_id": "web-multimedia-confirmed"})
    monkeypatch.setattr(KlingService, method, fake)
    payload = {
        "model": model, "media_type": "video", "prompt": "Animate this person",
        "aspect_ratio": "1:1" if model != "motion_control_v30" else "motion",
        "duration": 5, "quality": "720p" if model.startswith("motion") else "",
        "reference_urls": ["https://neuromixbot.com/uploads/web_refs/image.png"],
        "reference_video_urls": ["https://neuromixbot.com/uploads/web_refs/motion.mp4"],
        "reference_audio_urls": ["https://neuromixbot.com/uploads/web_refs/voice.mp3"],
    }
    task_id, rejected = await web_generation._submit_to_provider(
        "web_" + "c" * 32, payload,
    )
    assert task_id == "web-multimedia-confirmed", model
    assert rejected is False, model
    fake.assert_awaited_once()
    kwargs = fake.await_args.kwargs
    assert kwargs["image_url"].endswith("/image.png")
    if media_key == "video_urls":
        assert kwargs["video_urls"] == ["https://neuromixbot.com/uploads/web_refs/motion.mp4"]
        assert kwargs["mode"] == "720p"
        assert kwargs["motion_model"] == model
    else:
        assert kwargs["audio_url"] == "https://neuromixbot.com/uploads/web_refs/voice.mp3"
        assert kwargs["model"] == (
            "kling/ai-avatar-standard" if model == "avatar_std" else "kling/ai-avatar-pro"
        )
    assert "telegram_id" not in kwargs
    assert "user_id" not in kwargs


def test_motion_control_quote_uses_quality_and_live_admin_rates(monkeypatch):
    provider_cost = []
    def price(model, duration, quality=None):
        provider_cost.append((model, duration, quality))
        return 15 if quality == "720p" else 27
    monkeypatch.setattr(web_generation.preset_manager, "get_video_cost_with_quality", price)
    assert web_generation._price("video", "motion_control_v26", 5, "720p") == "15"
    assert web_generation._price("video", "motion_control_v26", 5, "1080p") == "27"
    assert provider_cost == [
        ("motion_control_v26", 5, "720p"),
        ("motion_control_v26", 5, "1080p"),
    ]


@pytest.mark.parametrize("duration", [2, 10])
def test_veo_web_rejects_durations_that_provider_silently_changes(duration):
    with pytest.raises(ValueError):
        web_generation._normalize_request({
            "model": "veo3_fast", "prompt": "A mountain sunrise video",
            "aspect_ratio": "16:9", "duration": duration,
            "request_key": "veo-duration-quote-check-2026",
        })


def test_veo_web_limits_first_and_last_frames_to_two():
    with pytest.raises(ValueError):
        web_generation._normalize_request({
            "model": "veo3_fast", "prompt": "A cinematic first to last transition",
            "duration": 6, "aspect_ratio": "16:9",
            "reference_ids": [
                "wr_" + str(index) * 32 for index in range(1, 4)
            ],
            "request_key": "veo-frame-overflow-2026",
        })


def test_seedream_edit_rejects_reference_counts_that_service_would_truncate():
    with pytest.raises(ValueError):
        web_generation._normalize_request({
            "model": "seedream_edit", "prompt": "Edit the scene",
            "quality": "4K", "aspect_ratio": "1:1",
            "reference_ids": [
                "wr_" + str(index) * 32 for index in range(1, 7)
            ],
            "request_key": "seedream-edit-reference-cap-2026",
        })


@pytest.mark.asyncio
async def test_seedream_edit_4k_dispatches_provider_high_quality_not_basic(monkeypatch):
    import importlib
    from unittest.mock import AsyncMock

    provider = importlib.import_module("bot.services.seedream_service").seedream_service
    fake = AsyncMock(return_value={"task_id": "seedream-quality-4k"})
    monkeypatch.setattr(provider, "generate_image", fake)
    task, rejected = await web_generation._submit_to_provider(
        "web_" + "f" * 32,
        {"model": "seedream_edit", "prompt": "A portrait in autumn",
         "quality": "4K", "aspect_ratio": "1:1", "duration": 5,
         "reference_urls": ["https://neuromixbot.com/uploads/web_refs/owned.png"]},
    )
    assert (task, rejected) == ("seedream-quality-4k", False)
    assert fake.await_args.kwargs["quality"] == "high"


def test_seedream55_web_settings_match_provider_contract_and_never_silent_fallback():
    base = {
        "model": "seedream_55", "prompt": "Beautiful portrait with crisp lines",
        "aspect_ratio": "1:1", "quality": "2K",
        "request_key": "seedream55-web-settings-2026",
    }
    good = web_generation._normalize_request({
        **base, "output_format": "png",
        "background": "transparent", "nsfw_checker": True,
    })
    assert good["output_format"] == "png"
    assert good["background"] == "transparent"
    assert good["nsfw_checker"] is True
    for invalid in (
        {"output_format": "jpeg", "background": "transparent"},
        {"output_format": "png", "background": "not-a-background"},
        {"nsfw_checker": "true"},
        {"aspect_ratio": "auto"},
    ):
        with pytest.raises(ValueError):
            web_generation._normalize_request({**base, **invalid})
    with pytest.raises(ValueError):
        web_generation._normalize_request({
            **base, "model": "flux_pro", "background": "transparent",
        })


@pytest.mark.asyncio
async def test_seedream55_web_text_and_edit_send_all_checked_options(monkeypatch):
    import importlib
    from unittest.mock import AsyncMock

    provider = importlib.import_module("bot.services.seedream55_service").seedream55_service
    create = AsyncMock(return_value={"task_id": "seedream55-settings-ok"})
    edit = AsyncMock(return_value={"task_id": "seedream55-edited-ok"})
    monkeypatch.setattr(provider, "generate_text_to_image", create)
    monkeypatch.setattr(provider, "generate_image", edit)
    base = {
        "model": "seedream_55", "prompt": "Sunset portrait on transparent background",
        "quality": "1.5K", "duration": 5, "aspect_ratio": "1:1",
        "output_format": "png", "background": "transparent",
        "nsfw_checker": True,
    }
    task, rejected = await web_generation._submit_to_provider(
        "web_" + "a" * 32, {**base, "reference_urls": []},
    )
    assert (task, rejected) == ("seedream55-settings-ok", False)
    assert create.await_args.kwargs["output_format"] == "png"
    assert create.await_args.kwargs["background"] == "transparent"
    assert create.await_args.kwargs["nsfw_checker"] is True
    task, rejected = await web_generation._submit_to_provider(
        "web_" + "b" * 32, {
            **base, "reference_urls": [
                "https://neuromixbot.com/uploads/web_refs/owned.png",
            ],
        },
    )
    assert (task, rejected) == ("seedream55-edited-ok", False)
    assert edit.await_args.kwargs["output_format"] == "png"
    assert edit.await_args.kwargs["background"] == "transparent"
    assert edit.await_args.kwargs["nsfw_checker"] is True


@pytest.mark.parametrize("model,quality,duration", [
    ("grok_imagine_v15", "720p", 6),
    ("veo3_fast", "1080p", 6),
    ("veo3_fast", "4k", 8),
])
def test_video_web_quality_billing_uses_actual_admin_resolution_rate(model, quality, duration):
    from bot.services.preset_manager import preset_manager

    catalogue = {row["id"]: row for row in web_generation._models()}
    assert quality in catalogue[model]["qualities"]
    quoted = web_generation._price("video", model, duration, quality)
    official = preset_manager.get_video_cost_with_quality(model, duration, quality)
    assert float(quoted) == official


@pytest.mark.asyncio
@pytest.mark.parametrize("model,quality,method", [
    ("grok_imagine_v15", "720p", "generate_image_to_video_v15"),
    ("veo3_fast", "4k", "generate_video"),
])
async def test_video_quality_reaches_provider_not_silently_reduced(monkeypatch, model, quality, method):
    import importlib
    from unittest.mock import AsyncMock

    module = "bot.services.grok_service" if model.startswith("grok") else "bot.services.veo_service"
    attr = "grok_service" if model.startswith("grok") else "veo_service"
    provider = getattr(importlib.import_module(module), attr)
    fake = AsyncMock(return_value={"task_id": "rendering-task-2026"})
    monkeypatch.setattr(provider, method, fake)
    result, rejected = await web_generation._submit_to_provider(
        "web_" + "1" * 32, {
            "model": model, "prompt": "A city at sunset",
            "aspect_ratio": "16:9", "duration": 6,
            "quality": quality,
            "reference_urls": [
                "https://neuromixbot.com/uploads/web_refs/owned.png",
            ],
        },
    )
    assert result == "rendering-task-2026"
    assert rejected is False
    assert fake.await_args.kwargs["resolution"] == quality
