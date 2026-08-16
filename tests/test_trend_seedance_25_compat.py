import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import trend_seedance_25_compat as compat


@pytest.mark.asyncio
async def test_seedance25_video_trend_uses_dedicated_provider_runtime(monkeypatch) -> None:
    from bot import miniapp as miniapp_module
    import bot.trend_api as trend_api

    trend = SimpleNamespace(
        trend_id=55,
        model="seedance_2_5",
        prompt="cinematic orbit",
        ratio="16:9",
        reference_urls=("https://example.test/source.jpg",),
        settings={"duration": 5, "seedance25_resolution": "720p"},
    )
    user = SimpleNamespace(id=101, credits=100)

    monkeypatch.setattr(
        miniapp_module,
        "_find_video_model_meta",
        lambda model: {
            "id": model,
            "ratios": ["adaptive", "16:9"],
            "durations": [5, 6],
        },
    )
    monkeypatch.setattr(
        miniapp_module,
        "get_video_model_label",
        lambda _model: "Seedance 2.5",
    )
    monkeypatch.setattr(trend_api, "_validate_uploaded_references", lambda *_args: None)
    monkeypatch.setattr(trend_api, "touch_saved_references", AsyncMock())
    monkeypatch.setattr(trend_api, "_debit_for_generation", AsyncMock(return_value=(False, None)))
    monkeypatch.setattr(trend_api, "_record_trend_use", AsyncMock())
    monkeypatch.setattr(compat.public_release, "_validate_public_payload", AsyncMock())
    provider = AsyncMock(return_value={"task_id": "seedance-task-1"})
    monkeypatch.setattr(compat.public_release, "_launch_provider", provider)
    monkeypatch.setattr(
        compat.public_release,
        "_request_data",
        lambda payload, **_kwargs: {
            "seedance25_scenario": payload["scenario"],
            "reference_images": payload["image_urls"],
            "first_frame_url": payload["first_frame"],
        },
    )
    add_task = AsyncMock()
    monkeypatch.setattr(compat.generation_module, "add_generation_task", add_task)
    monkeypatch.setattr(
        compat.generation_module,
        "get_or_create_user",
        AsyncMock(return_value=SimpleNamespace(credits=95)),
    )

    response = await compat._run_seedance25_trend(
        telegram_id=123456,
        user=user,
        trend=trend,
    )
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["ok"] is True
    assert payload["task_id"] == "seedance-task-1"
    assert payload["model"] == "seedance_2_5"
    assert payload["trend_id"] == 55
    provider.assert_awaited_once()
    launched_payload = provider.await_args.args[0]
    assert launched_payload["scenario"] == "first_frame"
    assert launched_payload["first_frame"] == "https://example.test/source.jpg"
    add_task.assert_awaited_once()
