import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import trend_seedance_25_compat as compat


@pytest.mark.asyncio
async def test_seedance25_video_trend_uses_dedicated_provider_runtime(monkeypatch) -> None:
    from bot import miniapp as miniapp_module
    from bot import trend_api

    trend = SimpleNamespace(
        trend_id=55,
        model="seedance_2_5",
        prompt="cinematic orbit",
        ratio="16:9",
        reference_urls=("https://example.test/source.jpg",),
        settings={"duration": 5, "seedance25_resolution": "720p"},
    )
    user = SimpleNamespace(id=101, credits=100)

    # Seedance 2.5 is injected into Mini App bootstrap dynamically and is not
    # part of the generic VIDEO_MODELS registry. Trend execution must therefore
    # use the dedicated Seedance metadata instead of treating it as unavailable.
    monkeypatch.setattr(miniapp_module, "_find_video_model_meta", lambda _model: None)
    monkeypatch.setattr(
        compat.public_release,
        "_public_model_meta",
        lambda: {
            "id": "seedance_2_5",
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


@pytest.mark.asyncio
async def test_seedance25_tagged_single_image_trend_uses_multimodal_binding(monkeypatch) -> None:
    from bot import miniapp as miniapp_module
    from bot import trend_api

    trend = SimpleNamespace(
        trend_id=1605,
        model="seedance_2_5",
        prompt="Animate @Image1 with a cinematic orbit",
        ratio="9:16",
        reference_urls=("https://example.test/source.jpg",),
        settings={"duration": 12, "seedance25_resolution": "720p"},
    )
    user = SimpleNamespace(id=101, credits=170)

    monkeypatch.setattr(
        compat.public_release,
        "_public_model_meta",
        lambda: {
            "id": "seedance_2_5",
            "ratios": ["adaptive", "9:16"],
            "durations": list(range(4, 31)),
        },
    )
    monkeypatch.setattr(
        miniapp_module,
        "get_video_model_label",
        lambda _model: "Seedance 2.5",
    )
    monkeypatch.setattr(trend_api, "_validate_uploaded_references", lambda *_args: None)
    monkeypatch.setattr(trend_api, "touch_saved_references", AsyncMock())
    monkeypatch.setattr(trend_api, "_debit_for_generation", AsyncMock(return_value=(True, None)))
    monkeypatch.setattr(trend_api, "_record_trend_use", AsyncMock())
    monkeypatch.setattr(compat.public_release, "_validate_public_payload", AsyncMock())
    provider = AsyncMock(return_value={"task_id": "seedance-trend-tagged"})
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
    monkeypatch.setattr(compat.generation_module, "add_generation_task", AsyncMock())
    monkeypatch.setattr(
        compat.generation_module,
        "get_or_create_user",
        AsyncMock(return_value=SimpleNamespace(credits=98)),
    )

    response = await compat._run_seedance25_trend(
        telegram_id=123456,
        user=user,
        trend=trend,
    )

    assert response.status == 200
    launched_payload = provider.await_args.args[0]
    assert launched_payload["scenario"] == "multimodal"
    assert launched_payload["first_frame"] is None
    assert launched_payload["image_urls"] == ["https://example.test/source.jpg"]


@pytest.mark.asyncio
async def test_seedance25_private_trend_keeps_user_identity_first_and_hidden_media_typed(monkeypatch) -> None:
    from bot import miniapp as miniapp_module
    from bot import trend_api

    trend = SimpleNamespace(
        trend_id=1701,
        model="seedance_2_5",
        prompt="Replace @Video1 person with @Image1 wearing @Image2.",
        ratio="adaptive",
        reference_urls=("https://example.test/user-face.jpg",),
        provider_image_urls=(
            "https://example.test/user-face.jpg",
            "https://example.test/dress.jpg",
        ),
        template_image_urls=("https://example.test/dress.jpg",),
        template_video_urls=("https://example.test/source.mp4",),
        template_audio_urls=(),
        reference_contract="seedance_identity_first",
        settings={
            "duration": -1,
            "seedance25_resolution": "720p",
            "seedance25_video_editing": True,
            "source_video_duration_seconds": 12,
        },
    )
    user = SimpleNamespace(id=101, credits=170)

    monkeypatch.setattr(
        compat.public_release,
        "_public_model_meta",
        lambda: {
            "id": "seedance_2_5",
            "ratios": ["adaptive", "9:16"],
            "durations": list(range(4, 31)),
        },
    )
    monkeypatch.setattr(miniapp_module, "get_video_model_label", lambda _model: "Seedance 2.5")
    monkeypatch.setattr(trend_api, "_validate_uploaded_references", lambda *_args: None)
    touch = AsyncMock()
    monkeypatch.setattr(trend_api, "touch_saved_references", touch)
    monkeypatch.setattr(trend_api, "_debit_for_generation", AsyncMock(return_value=(True, None)))
    monkeypatch.setattr(trend_api, "_record_trend_use", AsyncMock())
    monkeypatch.setattr(trend_api, "estimate_trend_repeat_cost", lambda _trend: 48.0)
    validate = AsyncMock()
    monkeypatch.setattr(compat.public_release, "_validate_public_payload", validate)
    provider = AsyncMock(return_value={"task_id": "seedance-private-edit"})
    monkeypatch.setattr(compat.public_release, "_launch_provider", provider)
    monkeypatch.setattr(
        compat.public_release,
        "_request_data",
        lambda payload, **_kwargs: {
            "seedance25_scenario": payload["scenario"],
            "reference_images": payload["image_urls"],
            "v_reference_videos": payload["video_urls"],
        },
    )
    add_task = AsyncMock()
    monkeypatch.setattr(compat.generation_module, "add_generation_task", add_task)
    monkeypatch.setattr(
        compat.generation_module,
        "get_or_create_user",
        AsyncMock(return_value=SimpleNamespace(credits=122)),
    )

    response = await compat._run_seedance25_trend(
        telegram_id=123456,
        user=user,
        trend=trend,
    )

    assert response.status == 200
    payload = provider.await_args.args[0]
    assert payload["scenario"] == "multimodal"
    assert payload["first_frame"] is None
    assert payload["image_urls"] == [
        "https://example.test/user-face.jpg",
        "https://example.test/dress.jpg",
    ]
    assert payload["video_urls"] == ["https://example.test/source.mp4"]
    assert payload["seedance25_video_editing"] is True
    assert payload["duration"] == -1
    assert payload["ratio"] == "adaptive"
    validate.assert_awaited_once_with(payload, is_admin=False, trusted_trend=True)
    touch.assert_awaited_once_with(
        123456,
        ["https://example.test/user-face.jpg"],
        kind="image",
    )
    request_data = add_task.await_args.kwargs["request_data"]
    assert request_data["reference_contract"] == "seedance_identity_first"
    assert request_data["fixed_asset_counts"] == {"image": 1, "video": 1, "audio": 0}


@pytest.mark.asyncio
async def test_seedance25_editing_rejects_replacement_video_with_price_changing_duration(
    monkeypatch,
) -> None:
    from bot import trend_api

    trend = trend_api.TrustedTrendRun(
        trend_id=1702,
        kind="video",
        prompt="Replace @Video1 person with @Image1.",
        model="seedance_2_5",
        ratio="adaptive",
        reference_urls=(
            "https://tanyapi.test/uploads/refs/image/123456/face.jpg",
            "https://tanyapi.test/uploads/refs/video/123456/replacement.mp4",
        ),
        settings={
            "duration": -1,
            "seedance25_resolution": "720p",
            "seedance25_video_editing": True,
            "source_video_duration_seconds": 12,
            "required_video_duration_seconds": 12,
        },
        user_reference_inputs=(
            {
                "media_type": "image",
                "position": 1,
                "url": "https://tanyapi.test/uploads/refs/image/123456/face.jpg",
            },
            {
                "media_type": "video",
                "position": 1,
                "url": "https://tanyapi.test/uploads/refs/video/123456/replacement.mp4",
            },
        ),
        assembled_image_urls=(
            "https://tanyapi.test/uploads/refs/image/123456/face.jpg",
        ),
        assembled_video_urls=(
            "https://tanyapi.test/uploads/refs/video/123456/replacement.mp4",
        ),
        reference_contract="seedance_identity_first",
    )
    monkeypatch.setattr(
        compat.public_release,
        "_public_model_meta",
        lambda: {"ratios": ["adaptive"], "durations": list(range(4, 31))},
    )
    monkeypatch.setattr(trend_api, "_validate_uploaded_references", lambda *_args: None)
    monkeypatch.setattr(trend_api, "touch_saved_references", AsyncMock())
    monkeypatch.setattr(compat.public_release, "_validate_public_payload", AsyncMock())
    from bot.handlers import seedance_25_fullstack as fullstack

    monkeypatch.setattr(fullstack, "_validate_local_source", AsyncMock(return_value=12.4))
    debit = AsyncMock()
    monkeypatch.setattr(trend_api, "_debit_for_generation", debit)

    with pytest.raises(trend_api.TrendRunValidationError, match="12 сек"):
        await compat._run_seedance25_trend(
            telegram_id=123456,
            user=SimpleNamespace(id=101, credits=170),
            trend=trend,
        )

    debit.assert_not_awaited()
