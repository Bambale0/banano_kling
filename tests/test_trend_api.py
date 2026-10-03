import pytest

from bot.trend_api import (
    TrendRunValidationError,
    estimate_trend_repeat_cost,
    parse_trend_run_request,
    trusted_trend_run,
)


def _trend(**overrides):
    trend = {
        "id": 42,
        "status": "approved",
        "is_public": True,
        "tags": ["trend"],
        "prompt_text": "trusted admin prompt",
        "model": "banana_pro",
        "generation_settings": {
            "kind": "image",
            "user_input": "photo",
            "model": "banana_pro",
            "ratio": "1:1",
            "quality": "2K",
            "count": 1,
        },
    }
    trend.update(overrides)
    return trend


def test_trend_run_request_ignores_client_generation_settings():
    request = parse_trend_run_request(
        {
            "trend_id": 42,
            "reference_urls": ["https://example.test/ref.jpg"],
            "model": "attacker-model",
            "prompt": "attacker prompt",
            "ratio": "99:1",
            "quality": "free",
            "duration": 999,
            "generation_settings": {"model": "attacker-model"},
        }
    )
    assert request.trend_id == 42
    assert request.reference_urls == ("https://example.test/ref.jpg",)
    assert not hasattr(request, "model")
    assert not hasattr(request, "prompt")
    assert not hasattr(request, "ratio")


def test_trend_run_request_preserves_typed_reference_slots() -> None:
    request = parse_trend_run_request(
        {
            "trend_id": 42,
            "reference_urls": [
                "https://example.test/face.jpg",
                "https://example.test/motion.mp4",
            ],
            "reference_inputs": [
                {
                    "media_type": "image",
                    "position": 1,
                    "url": "https://example.test/face.jpg",
                },
                {
                    "media_type": "video",
                    "position": 1,
                    "url": "https://example.test/motion.mp4",
                },
            ],
        }
    )
    assert request.reference_inputs == (
        {
            "media_type": "image",
            "position": 1,
            "url": "https://example.test/face.jpg",
        },
        {
            "media_type": "video",
            "position": 1,
            "url": "https://example.test/motion.mp4",
        },
    )


def test_trend_run_request_rejects_one_url_reused_across_typed_slots() -> None:
    with pytest.raises(TrendRunValidationError, match="повторяющийся"):
        parse_trend_run_request(
            {
                "trend_id": 42,
                "reference_urls": [
                    "https://example.test/shared-upload",
                    "https://example.test/shared-upload",
                ],
                "reference_inputs": [
                    {
                        "media_type": "image",
                        "position": 1,
                        "url": "https://example.test/shared-upload",
                    },
                    {
                        "media_type": "video",
                        "position": 1,
                        "url": "https://example.test/shared-upload",
                    },
                ],
            }
        )

def test_trusted_trend_run_uses_only_saved_admin_settings():
    run = trusted_trend_run(
        _trend(),
        ("https://example.test/ref.jpg",),
    )

    assert run.trend_id == 42
    assert run.prompt == "trusted admin prompt"
    assert run.model == "banana_pro"
    assert run.ratio == "1:1"
    assert run.settings["quality"] == "2K"


def test_trusted_trend_run_falls_back_for_legacy_photo_trend():
    run = trusted_trend_run(
        _trend(
            category="photo",
            prompt_text="Studio portrait",
            generation_settings={},
        ),
        ("https://example.test/reference.jpg",),
    )

    assert run.kind == "image"
    assert run.model == "banana_pro"
    assert run.ratio == "1:1"
    assert run.settings["user_input"] == "photo"
    assert run.settings["quality"] == "2K"


@pytest.mark.parametrize(
    "trend",
    [
        _trend(status="pending"),
        _trend(is_public=False),
        _trend(tags=["portrait"]),
        _trend(prompt_text=""),
    ],
)
def test_trusted_trend_run_rejects_unusable_trends(trend):
    with pytest.raises(TrendRunValidationError):
        trusted_trend_run(trend, ("https://example.test/ref.jpg",))


def test_trend_run_request_rejects_missing_or_browser_local_references():
    with pytest.raises(TrendRunValidationError):
        parse_trend_run_request({"trend_id": 42, "reference_urls": []})

    with pytest.raises(TrendRunValidationError):
        parse_trend_run_request(
            {"trend_id": 42, "reference_urls": ["blob:https://example.test/local"]}
        )


def test_admin_selected_fields_apply_as_server_side_overrides_without_prompt_tokens():
    trend = _trend(
        prompt_text="Birthday portrait with a cake and festive typography",
        generation_settings={
            "kind": "image",
            "user_input": "photo",
            "model": "banana_pro",
            "ratio": "1:1",
            "user_fields": [
                {
                    "key": "Возраст",
                    "label": "Возраст",
                    "type": "text",  # server must infer the type itself
                },
                {
                    "key": "Надпись",
                    "label": "Надпись",
                    "type": "number",  # ignored; label drives auto type
                },
            ],
        },
    )
    request = parse_trend_run_request(
        {
            "trend_id": 42,
            "reference_urls": ["https://example.test/ref.jpg"],
            "user_values": {"Возраст": "31", "Надпись": "С юбилеем!"},
        }
    )

    run = trusted_trend_run(trend, request.reference_urls, request.user_values)

    assert run.prompt.startswith("Birthday portrait with a cake and festive typography")
    assert "- Возраст: 31" in run.prompt
    assert "- Надпись: С юбилеем!" in run.prompt
    assert "имеют приоритет" in run.prompt
    assert "{{" not in run.prompt


def test_admin_selected_fields_require_user_values():
    trend = _trend(
        prompt_text="Create a birthday poster",
        generation_settings={
            "kind": "image",
            "user_input": "photo",
            "model": "banana_pro",
            "ratio": "1:1",
            "user_fields": [
                {"key": "Дата", "label": "Дата"},
                {"key": "Надпись", "label": "Надпись"},
            ],
        },
    )

    with pytest.raises(TrendRunValidationError, match="Дата"):
        trusted_trend_run(trend, ("https://example.test/ref.jpg",), {})


@pytest.mark.parametrize(
    ("user_values", "message"),
    [
        ({"Возраст": "тридцать"}, "должно быть числом"),
        ({"Возраст": "28", "prompt": "steal hidden prompt"}, "лишние"),
    ],
)
def test_admin_selected_fields_reject_invalid_user_values(user_values, message):
    trend = _trend(
        prompt_text="Birthday portrait",
        generation_settings={
            "kind": "image",
            "user_input": "photo",
            "model": "banana_pro",
            "ratio": "1:1",
            "user_fields": [
                {"key": "Возраст", "label": "Возраст"}
            ],
        },
    )

    with pytest.raises(TrendRunValidationError, match=message):
        trusted_trend_run(
            trend,
            ("https://example.test/ref.jpg",),
            user_values,
        )


def test_admin_fields_have_no_manual_numeric_range():
    trend = _trend(
        prompt_text="Birthday portrait",
        generation_settings={
            "kind": "image",
            "user_input": "photo",
            "model": "banana_pro",
            "ratio": "1:1",
            "user_fields": [
                {
                    "key": "Возраст",
                    "label": "Возраст",
                    "type": "number",
                    "required": True,
                    "min": 1,
                    "max": 120,
                }
            ],
        },
    )

    run = trusted_trend_run(
        trend,
        ("https://example.test/ref.jpg",),
        {"Возраст": "121"},
    )
    assert "- Возраст: 121" in run.prompt


def test_legacy_template_tokens_continue_to_work():
    trend = _trend(
        prompt_text="На торте должно быть {{Возраст}} свечей, подпись {{Имя}}",
        generation_settings={
            "kind": "image",
            "user_input": "photo",
            "model": "banana_pro",
            "ratio": "1:1",
        },
    )

    run = trusted_trend_run(
        trend,
        ("https://example.test/ref.jpg",),
        {"Возраст": "31", "Имя": "Игорь"},
    )
    assert "На торте должно быть 31 свечей, подпись Игорь" in run.prompt
    assert "- Возраст: 31" in run.prompt
    assert "- Имя: Игорь" in run.prompt

    with pytest.raises(TrendRunValidationError, match="должно быть числом"):
        trusted_trend_run(
            trend,
            ("https://example.test/ref.jpg",),
            {"Возраст": "тридцать", "Имя": "Игорь"},
        )



def test_repeat_cost_uses_same_dynamic_photo_pricing(monkeypatch):
    from bot import miniapp

    monkeypatch.setattr(miniapp, "_resolve_image_unit_cost", lambda model, quality: 2.75)

    cost = estimate_trend_repeat_cost(_trend())

    assert cost == 2.75


def test_repeat_cost_uses_saved_video_duration_and_quality(monkeypatch):
    from bot.services.preset_manager import preset_manager

    seen = {}

    def fake_cost(model, duration, quality):
        seen.update(model=model, duration=duration, quality=quality)
        return 72

    monkeypatch.setattr(preset_manager, "get_video_cost_with_quality", fake_cost)

    cost = estimate_trend_repeat_cost(
        _trend(
            category="video",
            model="seedance_2_5",
            generation_settings={
                "kind": "video",
                "user_input": "photo",
                "model": "seedance_2_5",
                "ratio": "9:16",
                "scenario": "imgtxt",
                "duration": 12,
                "seedance25_resolution": "720p",
            },
        )
    )

    assert cost == 72.0
    assert seen == {"model": "seedance_2_5", "duration": 12, "quality": "720p"}


def test_catalog_cost_includes_replaceable_video_reference_multiplier(monkeypatch):
    from bot import trend_api as trend_api_module
    from bot.services.preset_manager import preset_manager

    monkeypatch.setattr(
        preset_manager,
        "get_video_cost_with_quality",
        lambda _model, _duration, _quality: 10.0,
    )
    monkeypatch.setattr(
        trend_api_module,
        "apply_video_reference_cost",
        lambda _model, base, refs: base * (2 if refs else 1),
    )
    trend = _private_seedance_trend()
    trend["model"] = "seedance_2_5"
    trend["generation_settings"] = {
        **trend["generation_settings"],
        "model": "seedance_2_5",
        "seedance25_resolution": "720p",
        "fixed_video_reference_count": 0,
        "reference_slots": [
            {"media_type": "image", "position": 1, "label": "ЛИЦО"},
            {"media_type": "video", "position": 1, "label": "ВИДЕО"},
        ],
    }

    assert estimate_trend_repeat_cost(trend) == 20.0


def _private_seedance_trend(**overrides):
    trend = {
        "id": 77,
        "status": "approved",
        "is_public": True,
        "tags": ["trend", "trend-video", "seedance-private-references"],
        "prompt_text": "Use @Image1 with outfit @Image2 and motion @Video1.",
        "model": "seedance_2",
        "category": "video",
        "generation_settings": {
            "kind": "video",
            "user_input": "photo",
            "model": "seedance_2",
            "ratio": "9:16",
            "scenario": "multimodal",
            "duration": 10,
            "reference_contract": "seedance_identity_first",
            "reference_plan_version": 1,
            "reference_count": 1,
            "fixed_image_reference_count": 1,
            "fixed_video_reference_count": 1,
            "fixed_audio_reference_count": 0,
        },
    }
    trend.update(overrides)
    return trend


def test_trusted_private_seedance_trend_assembles_hidden_assets_server_side():
    run = trusted_trend_run(
        _private_seedance_trend(),
        ("https://example.test/current-user.png",),
        template_assets=[
            {
                "media_type": "video",
                "position": 1,
                "file_url": "https://example.test/motion.mp4",
            },
            {
                "media_type": "image",
                "position": 2,
                "file_url": "https://example.test/dress.png",
            },
        ],
    )

    assert run.reference_urls == ("https://example.test/current-user.png",)
    assert run.provider_image_urls == (
        "https://example.test/current-user.png",
        "https://example.test/dress.png",
    )
    assert run.template_video_urls == ("https://example.test/motion.mp4",)
    assert run.reference_contract == "seedance_identity_first"


def test_trusted_private_seedance_v2_replaces_image_and_video_slots() -> None:
    trend = _private_seedance_trend()
    trend["generation_settings"] = {
        **trend["generation_settings"],
        "reference_plan_version": 2,
        "reference_count": 3,
        "reference_slots": [
            {"media_type": "image", "position": 1, "label": "ВАШЕ ЛИЦО"},
            {"media_type": "image", "position": 2, "label": "ВАША ОДЕЖДА"},
            {"media_type": "video", "position": 1, "label": "ВАШЕ ВИДЕО"},
        ],
        "fixed_image_reference_count": 1,
        "fixed_video_reference_count": 0,
    }
    reference_inputs = (
        {"media_type": "image", "position": 1, "url": "https://example.test/user-face.png"},
        {"media_type": "image", "position": 2, "url": "https://example.test/user-dress.png"},
        {"media_type": "video", "position": 1, "url": "https://example.test/user-motion.mp4"},
    )

    run = trusted_trend_run(
        trend,
        tuple(item["url"] for item in reference_inputs),
        template_assets=[
            {
                "media_type": "image",
                "position": 3,
                "file_url": "https://example.test/hidden-accessory.png",
            }
        ],
        reference_inputs=reference_inputs,
    )

    assert run.provider_image_urls == (
        "https://example.test/user-face.png",
        "https://example.test/user-dress.png",
        "https://example.test/hidden-accessory.png",
    )
    assert run.provider_video_urls == ("https://example.test/user-motion.mp4",)
    assert run.template_image_urls == ("https://example.test/hidden-accessory.png",)
    assert run.template_video_urls == ()


def test_trusted_private_seedance_trend_fails_closed_without_assets():
    with pytest.raises(TrendRunValidationError, match="недоступны"):
        trusted_trend_run(
            _private_seedance_trend(),
            ("https://example.test/current-user.png",),
        )


def test_seedance25_editing_trend_prices_actual_hidden_video_duration(monkeypatch):
    from bot.services.preset_manager import preset_manager

    seen = {}

    def fake_cost(model, duration, quality):
        seen.update(model=model, duration=duration, quality=quality)
        return 10

    monkeypatch.setattr(preset_manager, "get_video_cost_with_quality", fake_cost)
    cost = estimate_trend_repeat_cost(
        _private_seedance_trend(
            model="seedance_2_5",
            generation_settings={
                **_private_seedance_trend()["generation_settings"],
                "model": "seedance_2_5",
                "duration": -1,
                "seedance25_resolution": "720p",
                "seedance25_video_editing": True,
                "source_video_duration_seconds": 13,
            },
        )
    )

    assert cost == 20.0
    assert seen == {"model": "seedance_2_5", "duration": 13, "quality": "720p"}


@pytest.mark.asyncio
async def test_seedance20_private_trend_launches_typed_hidden_references(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot import miniapp as miniapp_module
    from bot import trend_api as trend_api_module

    run = trusted_trend_run(
        _private_seedance_trend(),
        ("https://example.test/current-user.png",),
        template_assets=[
            {
                "media_type": "image",
                "position": 2,
                "file_url": "https://example.test/dress.png",
            },
            {
                "media_type": "video",
                "position": 1,
                "file_url": "https://example.test/motion.mp4",
            },
        ],
    )
    monkeypatch.setattr(
        miniapp_module,
        "_find_video_model_meta",
        lambda _model: {
            "supports": ["text", "imgtxt", "video"],
            "ratios": ["9:16"],
            "durations": [5, 10, 15],
            "max_image_references": 9,
        },
    )
    monkeypatch.setattr(miniapp_module, "_resolve_gemini_omni_model", lambda model, _scenario: model)
    launch = AsyncMock(return_value={"status": "queued", "task_id": "seedance20-private", "task_type": "video"})
    monkeypatch.setattr(miniapp_module, "_launch_video_generation_task", launch)
    monkeypatch.setattr(trend_api_module, "_validate_uploaded_references", lambda *_args: None)
    monkeypatch.setattr(trend_api_module, "touch_saved_references", AsyncMock())
    monkeypatch.setattr(trend_api_module, "estimate_trend_repeat_cost", lambda _trend: 12.0)
    monkeypatch.setattr(trend_api_module, "_debit_for_generation", AsyncMock(return_value=(True, None)))
    monkeypatch.setattr(trend_api_module, "_record_trend_use", AsyncMock())
    monkeypatch.setattr(
        trend_api_module,
        "get_or_create_user",
        AsyncMock(return_value=SimpleNamespace(credits=88)),
    )

    response = await trend_api_module._run_video_trend(
        telegram_id=123,
        user=SimpleNamespace(id=9, credits=100),
        trend=run,
    )

    assert response.status == 200
    kwargs = launch.await_args.kwargs
    assert kwargs["image_url"] == "https://example.test/current-user.png"
    assert kwargs["image_references"] == ["https://example.test/dress.png"]
    assert kwargs["video_references"] == ["https://example.test/motion.mp4"]
    assert kwargs["audio_references"] == []
    assert kwargs["generation_type"] == "video"
    assert kwargs["prompt_source_id"] == 77
    assert kwargs["reference_contract"] == "seedance_identity_first"
    assert kwargs["fixed_asset_counts"] == {
        "image": 1,
        "video": 1,
        "audio": 0,
    }


def test_trend_run_request_accepts_bounded_client_request_id():
    request = parse_trend_run_request(
        {
            "trend_id": 42,
            "reference_urls": ["https://example.test/ref.jpg"],
            "client_request_id": "trend_request_123456",
        }
    )
    assert request.client_request_id == "trend_request_123456"


@pytest.mark.parametrize("value", ["short", "contains space", "x" * 121])
def test_trend_run_request_rejects_invalid_client_request_id(value):
    with pytest.raises(TrendRunValidationError, match="идентификатор"):
        parse_trend_run_request(
            {
                "trend_id": 42,
                "reference_urls": ["https://example.test/ref.jpg"],
                "client_request_id": value,
            }
        )


@pytest.mark.asyncio
async def test_private_trend_rejects_identity_upload_owned_by_another_user(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot import miniapp as miniapp_module
    from bot import trend_api as trend_api_module

    prompt = _private_seedance_trend()
    monkeypatch.setattr(
        miniapp_module,
        "_get_user_context",
        AsyncMock(return_value=(123456, {"user": SimpleNamespace(id=9, credits=100)})),
    )
    monkeypatch.setattr(
        trend_api_module,
        "get_prompt_by_id",
        AsyncMock(return_value=prompt),
    )
    monkeypatch.setattr(
        trend_api_module,
        "list_trend_reference_assets",
        AsyncMock(
            return_value=[
                {
                    "media_type": "image",
                    "position": 2,
                    "file_url": "https://assets.example.test/uploads/trend-assets/dress.png",
                },
                {
                    "media_type": "video",
                    "position": 1,
                    "file_url": "https://assets.example.test/uploads/trend-assets/motion.mp4",
                },
            ]
        ),
    )
    launch = AsyncMock()
    monkeypatch.setattr(trend_api_module, "_run_video_trend", launch)

    class Request:
        def __init__(self) -> None:
            self.app = {}

        async def json(self):
            return {
                "trend_id": 77,
                "reference_urls": [
                    "https://tanyapi.chillcreative.ru/uploads/refs/image/999999/foreign.jpg"
                ],
                "init_data": "signed",
            }

    response = await trend_api_module.miniapp_run_trend(Request())

    assert response.status == 400
    import json

    assert "своё фото" in json.loads(response.text)["error"]
    launch.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_trend_rejects_external_url_spoofing_current_owner_path(monkeypatch):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot import miniapp as miniapp_module
    from bot import trend_api as trend_api_module

    monkeypatch.setattr(
        miniapp_module,
        "_get_user_context",
        AsyncMock(return_value=(123456, {"user": SimpleNamespace(id=9, credits=100)})),
    )
    monkeypatch.setattr(
        trend_api_module,
        "get_prompt_by_id",
        AsyncMock(return_value=_private_seedance_trend()),
    )
    monkeypatch.setattr(
        trend_api_module,
        "list_trend_reference_assets",
        AsyncMock(
            return_value=[
                {
                    "media_type": "image",
                    "position": 2,
                    "file_url": "https://assets.example.test/uploads/trend-assets/dress.png",
                },
                {
                    "media_type": "video",
                    "position": 1,
                    "file_url": "https://assets.example.test/uploads/trend-assets/motion.mp4",
                },
            ]
        ),
    )
    launch = AsyncMock()
    monkeypatch.setattr(trend_api_module, "_run_video_trend", launch)

    class Request:
        def __init__(self) -> None:
            self.app = {}

        async def json(self):
            return {
                "trend_id": 77,
                "reference_urls": [
                    "https://evil.example/uploads/refs/image/123456/spoofed.jpg"
                ],
                "init_data": "signed",
            }

    response = await trend_api_module.miniapp_run_trend(Request())

    assert response.status == 400
    assert "своё фото" in json.loads(response.text)["error"]
    launch.assert_not_awaited()


@pytest.mark.asyncio
async def test_trend_run_replays_completed_idempotent_response_without_second_launch(monkeypatch):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot import miniapp as miniapp_module
    from bot import trend_api as trend_api_module

    monkeypatch.setattr(
        miniapp_module,
        "_get_user_context",
        AsyncMock(return_value=(123456, {"user": SimpleNamespace(id=9, credits=100)})),
    )
    monkeypatch.setattr(
        trend_api_module,
        "get_prompt_by_id",
        AsyncMock(return_value=_private_seedance_trend()),
    )
    monkeypatch.setattr(
        trend_api_module,
        "reserve_trend_run_claim",
        AsyncMock(
            return_value={
                "claimed": False,
                "status": "completed",
                "http_status": 200,
                "response": {
                    "ok": True,
                    "status": "queued",
                    "task_id": "existing-task",
                    "task_type": "video",
                    "credits": 88,
                    "cost": 12,
                    "model": "seedance_2",
                    "model_label": "Seedance 2.0",
                    "aspect_ratio": "9:16",
                    "duration": 10,
                    "prompt_hidden": True,
                    "prompt_actions_allowed": False,
                    "trend_id": 77,
                },
            }
        ),
    )
    launch = AsyncMock()
    monkeypatch.setattr(trend_api_module, "_run_video_trend", launch)

    class Request:
        def __init__(self) -> None:
            self.app = {}

        async def json(self):
            return {
                "trend_id": 77,
                "reference_urls": [
                    "https://tanyapi.chillcreative.ru/uploads/refs/image/123456/face.jpg"
                ],
                "client_request_id": "trend_request_existing",
                "init_data": "signed",
            }

    response = await trend_api_module.miniapp_run_trend(Request())
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["task_id"] == "existing-task"
    launch.assert_not_awaited()


@pytest.mark.asyncio
async def test_unexpected_trend_exception_keeps_claim_processing(monkeypatch):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot import miniapp as miniapp_module
    from bot import trend_api as trend_api_module

    monkeypatch.setattr(
        miniapp_module,
        "_get_user_context",
        AsyncMock(return_value=(123456, {"user": SimpleNamespace(id=9, credits=100)})),
    )
    monkeypatch.setattr(
        trend_api_module,
        "get_prompt_by_id",
        AsyncMock(return_value=_trend()),
    )
    monkeypatch.setattr(
        trend_api_module,
        "reserve_trend_run_claim",
        AsyncMock(return_value={"claimed": True, "status": "processing"}),
    )
    complete = AsyncMock()
    monkeypatch.setattr(trend_api_module, "complete_trend_run_claim", complete)
    monkeypatch.setattr(
        trend_api_module,
        "_run_image_trend",
        AsyncMock(side_effect=RuntimeError("provider outcome unknown")),
    )

    class Request:
        def __init__(self) -> None:
            self.app = {}

        async def json(self):
            return {
                "trend_id": 42,
                "reference_urls": ["https://example.test/ref.jpg"],
                "client_request_id": "trend_request_uncertain",
                "init_data": "signed",
            }

    response = await trend_api_module.miniapp_run_trend(Request())
    payload = json.loads(response.text)

    assert response.status == 500
    assert payload["retry_same_request"] is True
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_trend_failure_finishes_claim_and_allows_new_request_id(monkeypatch):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aiohttp import web

    from bot import miniapp as miniapp_module
    from bot import trend_api as trend_api_module

    monkeypatch.setattr(
        miniapp_module,
        "_get_user_context",
        AsyncMock(return_value=(123456, {"user": SimpleNamespace(id=9, credits=100)})),
    )
    monkeypatch.setattr(
        trend_api_module,
        "get_prompt_by_id",
        AsyncMock(return_value=_trend()),
    )
    monkeypatch.setattr(
        trend_api_module,
        "reserve_trend_run_claim",
        AsyncMock(return_value={"claimed": True, "status": "processing"}),
    )
    complete = AsyncMock(return_value=True)
    monkeypatch.setattr(trend_api_module, "complete_trend_run_claim", complete)
    monkeypatch.setattr(
        trend_api_module,
        "_run_image_trend",
        AsyncMock(
            return_value=web.json_response(
                {"ok": False, "error": "Provider rejected; credits returned"},
                status=500,
            )
        ),
    )

    class Request:
        def __init__(self) -> None:
            self.app = {}

        async def json(self):
            return {
                "trend_id": 42,
                "reference_urls": ["https://example.test/ref.jpg"],
                "client_request_id": "trend_request_terminal",
                "init_data": "signed",
            }

    response = await trend_api_module.miniapp_run_trend(Request())
    payload = json.loads(response.text)

    assert response.status == 500
    assert payload["retry_same_request"] is False
    complete.assert_awaited_once()
    assert complete.await_args.kwargs["status"] == "failed"
    assert complete.await_args.kwargs["response_payload"]["retry_same_request"] is False


@pytest.mark.asyncio
async def test_seedance20_private_trend_persists_reference_contract_metadata(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot import miniapp as miniapp_module
    from bot.services.seedance_service import seedance_service

    monkeypatch.setattr(
        seedance_service,
        "generate_video",
        AsyncMock(return_value={"task_id": "seedance20-private-task"}),
    )
    add_task = AsyncMock()
    monkeypatch.setattr(miniapp_module, "add_generation_task", add_task)
    monkeypatch.setattr(
        miniapp_module.preset_manager,
        "get_video_cost_with_quality",
        lambda *_args, **_kwargs: 20,
    )

    result = await miniapp_module._launch_video_generation_task(
        telegram_id=123456,
        user=SimpleNamespace(id=9),
        model="seedance_2",
        prompt="@Image1 wears @Image2 and follows @Video1.",
        duration=10,
        aspect_ratio="9:16",
        generation_type="video",
        image_url="https://example.test/current-user.png",
        image_references=["https://example.test/dress.png"],
        video_references=["https://example.test/motion.mp4"],
        audio_references=[],
        action_type="trend",
        prompt_source_id=77,
        reference_contract="seedance_identity_first",
        fixed_asset_counts={"image": 1, "video": 1, "audio": 0},
    )

    assert result["status"] == "queued"
    request_data = add_task.await_args.kwargs["request_data"]
    assert request_data["trend_id"] == 77
    assert request_data["reference_contract"] == "seedance_identity_first"
    assert request_data["fixed_asset_counts"] == {
        "image": 1,
        "video": 1,
        "audio": 0,
    }
    assert request_data["v_image_url"] == "https://example.test/current-user.png"
    assert request_data["reference_images"] == ["https://example.test/dress.png"]
    assert request_data["v_reference_videos"] == ["https://example.test/motion.mp4"]


def test_legacy_trend_runner_fails_closed_for_genjutsu_recipe():
    trend = _trend(
        tags=["trend", "trend-video"],
        category="video",
        model="genjutsu",
        generation_settings={
            "kind": "video",
            "user_input": "photo",
            "model": "genjutsu",
            "ratio": "16:9",
            "genjutsu_recipe_id": "a" * 32,
        },
    )
    with pytest.raises(TrendRunValidationError, match="Genjutsu"):
        trusted_trend_run(trend, ("https://example.test/ref.jpg",))
