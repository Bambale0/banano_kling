"""KIE's 2026-10-23 create rejection: frame tasks require adaptive ratio."""

import json
from unittest.mock import AsyncMock

import pytest

from bot import database, trend_api
from bot.handlers import seedance_25_public_release as public
from bot.handlers import trend_seedance_25_compat as compat
from bot.services.seedance_25_service import Seedance25Service
from tests.test_creator_tariff_seedance2 import actor  # noqa: F401
from tests.test_creator_tariff_seedance25 import launch_env  # noqa: F401

REJECTION = {
    "code": 422,
    "msg": "Seedance 2.5 first-frame and first-last-frame tasks only support adaptive aspect ratio",
    "data": None,
}


@pytest.mark.parametrize("last_frame", [None, "https://example.test/last.png"])
@pytest.mark.parametrize("ratio", ["9:16", "16:9", "adaptive"])
async def test_frame_adapter_accepts_stale_fixed_ratio(monkeypatch, last_frame, ratio):
    service = Seedance25Service(kie_key="test-key")
    sent = []

    async def provider(_path, payload):
        sent.append(payload)
        response = {"code": 200, "data": {"taskId": "frame-task"}}
        if payload["input"]["aspect_ratio"] != "adaptive":
            response = REJECTION
        return service._parse_kie_create_response(json.dumps(response))

    monkeypatch.setattr(service, "_kie_post", provider)
    result = await service.generate_video(
        prompt="Birthday scene",
        duration=8,
        aspect_ratio=ratio,
        first_frame_url="https://example.test/first.png",
        last_frame_url=last_frame,
    )
    assert result.get("task_id") == "frame-task", result
    assert result["aspect_ratio"] == "adaptive"
    assert len(sent) == 1
    assert sent[0]["input"]["first_frame_url"] == "https://example.test/first.png"
    assert "reference_image_urls" not in sent[0]["input"]


@pytest.mark.parametrize("surface", ["miniapp", "telegram"])
@pytest.mark.parametrize("scenario", ["first_frame", "first_last"])
async def test_public_frame_launch_persists_normalized_ratio(
    launch_env, surface, scenario  # noqa: F811
):
    from tests.test_creator_tariff_seedance25 import body, message, telegram_state

    data = body(
        seedance25_scenario=scenario,
        v_ratio="9:16",
        v_duration=8,
        seedance25_first_frame_url="https://example.test/first.png",
        seedance25_last_frame_url="https://example.test/last.png",
    )
    if surface == "miniapp":
        response = await public._public_miniapp_generate(launch_env.request, data)
        assert response.status == 200, response.body
        assert json.loads(response.body)["aspect_ratio"] == "adaptive"
    else:
        await public._public_message_launch(
            message(), telegram_state(data), data["prompt"]
        )
    assert public._launch_provider.await_args.args[0]["ratio"] == "adaptive"
    saved = public.generation_module.add_generation_task.await_args.kwargs
    assert saved["aspect_ratio"] == "adaptive"
    assert saved["request_data"]["aspect_ratio"] == "adaptive"


@pytest.mark.parametrize("scenario", ["first_frame", "first_last"])
def test_telegram_frame_keyboard_only_offers_adaptive(scenario):
    from bot.handlers.seedance_25_telegram_compat import _clear_seedance_keyboard

    keyboard = _clear_seedance_keyboard(
        {"seedance25_scenario": scenario, "v_ratio": "9:16"}
    )
    ratios = [
        b
        for row in keyboard.inline_keyboard
        for b in row
        if b.callback_data.startswith("s25_ratio_")
    ]
    assert [b.callback_data for b in ratios] == ["s25_ratio_adaptive"]
    assert "✅" in ratios[0].text


async def test_birthday_trend_sends_and_persists_effective_ratio(actor, monkeypatch):  # noqa: F811
    selected = trend_api.TrustedTrendRun(
        trend_id=2303,
        kind="video",
        prompt="Birthday scene",
        model="seedance_2_5",
        ratio="9:16",
        reference_urls=("https://example.test/face.png",),
        settings={"duration": 8, "seedance25_resolution": "720p"},
    )
    monkeypatch.setattr(trend_api, "_validate_uploaded_references", lambda *_args: None)
    monkeypatch.setattr(trend_api, "touch_saved_references", AsyncMock())
    monkeypatch.setattr(trend_api, "_record_trend_use", AsyncMock())
    monkeypatch.setattr(public.fullstack, "_validate_seedance_sources", AsyncMock())
    monkeypatch.setattr(public.seedance_25_service, "kie_key", "test-key")
    sent = []

    async def provider(_path, payload):
        sent.append(payload)
        response = {"code": 200, "data": {"taskId": "birthday-frame-task"}}
        if payload["input"]["aspect_ratio"] != "adaptive":
            response = REJECTION
        return public.seedance_25_service._parse_kie_create_response(
            json.dumps(response)
        )

    monkeypatch.setattr(public.seedance_25_service, "_kie_post", provider)
    response = await compat._run_seedance25_trend(
        telegram_id=123, user=actor.user, trend=selected
    )
    assert response.status == 200, response.body
    assert json.loads(response.body)["aspect_ratio"] == "adaptive"
    task = await database.get_task_by_id("birthday-frame-task")
    assert task.aspect_ratio == "adaptive"
    assert json.loads(task.request_data)["aspect_ratio"] == "adaptive"
    assert (await database.get_or_create_user(123)).credits == actor.initial - task.cost
    assert len(sent) == 1


async def test_rejection_diagnostics_never_log_private_provider_text(
    monkeypatch, caplog
):
    service = Seedance25Service(kie_key="test-key")
    private_prompt = "private template contents"
    monkeypatch.setattr(
        service,
        "_kie_post",
        AsyncMock(
            return_value={
                "error": "api_error",
                "status_code": 422,
                "message": REJECTION["msg"]
                + " "
                + private_prompt
                + " https://example.test/private.png",
            }
        ),
    )
    await service.generate_video(
        prompt=private_prompt, first_frame_url="https://example.test/private.png"
    )
    assert "frame_ratio_requires_adaptive" in caplog.text
    assert "provider_code=422" in caplog.text
    assert private_prompt not in caplog.text
    assert "private.png" not in caplog.text
