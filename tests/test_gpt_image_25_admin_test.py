from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bot.keyboards import get_main_menu_keyboard
from bot.services.gpt_image_25_service import GPTImage25Service


def _callbacks(markup) -> list[str]:
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]


def test_main_menu_test_button_is_visible_only_to_admin(monkeypatch):
    monkeypatch.setattr("bot.config.config.ADMIN_IDS_STR", "111,333")

    admin_callbacks = _callbacks(get_main_menu_keyboard(10, telegram_id=111))
    user_callbacks = _callbacks(get_main_menu_keyboard(10, telegram_id=222))
    unknown_callbacks = _callbacks(get_main_menu_keyboard(10))

    assert "admin_test_lab" in admin_callbacks
    assert "admin_test_lab" not in user_callbacks
    assert "admin_test_lab" not in unknown_callbacks


def test_gpt25_maps_all_four_kie_model_ids():
    assert GPTImage25Service.model_id("flare", has_references=False) == (
        "gpt-image-2-5-flare-text-to-image"
    )
    assert GPTImage25Service.model_id("flare", has_references=True) == (
        "gpt-image-2-5-flare-image-to-image"
    )
    assert GPTImage25Service.model_id("sunburst", has_references=False) == (
        "gpt-image-2-5-sunburst-text-to-image"
    )
    assert GPTImage25Service.model_id("sunburst", has_references=True) == (
        "gpt-image-2-5-sunburst-image-to-image"
    )


def test_gpt25_text_payload_covers_documented_parameters():
    payload = GPTImage25Service.build_payload(
        prompt="A product poster",
        variant="flare",
        aspect_ratio="27:16",
        resolution="4K",
    )

    assert payload == {
        "model": "gpt-image-2-5-flare-text-to-image",
        "input": {
            "prompt": "A product poster",
            "aspect_ratio": "27:16",
            "resolution": "4K",
        },
    }
    assert "background" not in payload["input"]


def test_gpt25_image_payload_supports_sixteen_unique_references_and_callback():
    refs = [f"https://cdn.example/ref-{index}.png" for index in range(16)]
    payload = GPTImage25Service.build_payload(
        prompt="Keep the subjects, change the location",
        variant="sunburst",
        input_urls=refs + [refs[0]],
        aspect_ratio="auto",
        resolution="2K",
        callback_url="https://example.test/kie/callback",
    )

    assert payload["model"] == "gpt-image-2-5-sunburst-image-to-image"
    assert payload["input"]["input_urls"] == refs
    assert len(payload["input"]["input_urls"]) == 16
    assert payload["input"]["resolution"] == "2K"
    assert payload["callBackUrl"] == "https://example.test/kie/callback"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("variant", "unknown"),
        ("aspect_ratio", "5:4"),
        ("resolution", "8K"),
    ],
)
def test_gpt25_rejects_undocumented_parameter_values(field: str, value: str):
    kwargs = {
        "prompt": "test",
        "variant": "flare",
        "aspect_ratio": "auto",
        "resolution": "1K",
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        GPTImage25Service.build_payload(**kwargs)


def test_gpt25_rejects_non_public_or_too_many_references():
    with pytest.raises(ValueError, match="public HTTP"):
        GPTImage25Service.build_payload(
            prompt="test",
            input_urls=["/tmp/private.png"],
        )

    with pytest.raises(ValueError, match="at most 16"):
        GPTImage25Service.build_payload(
            prompt="test",
            input_urls=[f"https://cdn.example/{index}.png" for index in range(17)],
        )


def test_gpt25_rejects_prompt_over_provider_limit():
    with pytest.raises(ValueError, match="20000"):
        GPTImage25Service.build_payload(prompt="x" * 20_001)


def test_gpt25_generate_uses_unified_kie_market_endpoint():
    async def run():
        service = GPTImage25Service(kie_key="test-key")
        service._kie_post = AsyncMock(
            return_value={"task_id": "task-25", "status": "pending"}
        )
        result = await service.generate(
            prompt="A cinematic cat",
            variant="flare",
            aspect_ratio="9:16",
            resolution="1K",
        )
        return service, result

    service, result = asyncio.run(run())
    assert result["task_id"] == "task-25"
    assert result["provider"] == "kie"
    assert result["provider_model"] == "gpt-image-2-5-flare-text-to-image"
    service._kie_post.assert_awaited_once()
    endpoint, payload = service._kie_post.await_args.args
    assert endpoint == "/api/v1/jobs/createTask"
    assert payload["model"] == "gpt-image-2-5-flare-text-to-image"


def test_gpt25_record_parser_handles_success_and_failure_contracts():
    async def run_success():
        service = GPTImage25Service(kie_key="test-key")
        service._kie_get = AsyncMock(
            return_value={
                "code": 200,
                "msg": "success",
                "data": {
                    "taskId": "task-success",
                    "model": "gpt-image-2-5-sunburst-image-to-image",
                    "state": "success",
                    "resultJson": json.dumps(
                        {"resultUrls": ["https://cdn.example/result.png"]}
                    ),
                    "creditsConsumed": 42,
                },
            }
        )
        return await service.get_task_record("task-success")

    success = asyncio.run(run_success())
    assert success["state"] == "success"
    assert success["result_urls"] == ["https://cdn.example/result.png"]
    assert success["credits_consumed"] == 42

    async def run_failure():
        service = GPTImage25Service(kie_key="test-key")
        service._kie_get = AsyncMock(
            return_value={
                "data": {
                    "taskId": "task-fail",
                    "state": "fail",
                    "failCode": "MODEL_ERROR",
                    "failMsg": "provider rejected the task",
                }
            }
        )
        return await service.get_task_record("task-fail")

    failure = asyncio.run(run_failure())
    assert failure["state"] == "fail"
    assert failure["error_code"] == "MODEL_ERROR"
    assert failure["error"] == "provider rejected the task"


def test_admin_test_handler_keeps_provider_key_server_side_and_has_no_billing():
    root = Path(__file__).resolve().parents[1]
    source = (root / "bot/handlers/admin_test_lab.py").read_text(encoding="utf-8")

    assert 'callback_data="admin_test_gpt25"' in source
    assert "config.is_admin" in source
    assert "KIE_AI_API_KEY" in source
    assert "gpt_image_25_service.generate" in source
    assert "MAX_INPUT_IMAGES" in source
    assert "wait_for_result" in source
    assert "deduct" not in source.lower()
    assert "update_user_credits" not in source
    assert "api_key=" not in source.lower()
