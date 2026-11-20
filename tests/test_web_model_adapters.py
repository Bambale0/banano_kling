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
    assert len(enabled) == 16  # Explicitly tested adapters; update with new adapters.
    assert enabled == (
        web_generation._IMAGE_MODELS | web_generation._VIDEO_MODELS
    )
