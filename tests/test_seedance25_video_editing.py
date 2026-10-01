"""Regression coverage at Seedance public launch and provider-validation seams."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bot.handlers import seedance_25_fullstack as fullstack
from bot.handlers import seedance_25_public_release as public
from bot.handlers.miniapp_video_continuity_compat import enrich_video_repeat_body
from bot.video_generation_contract import normalize_video_request


@pytest.fixture(autouse=True)
def isolated_database():
    """Launch dependencies are mocked; no real database is required."""
    yield


def state_data(**overrides):
    return dict(seedance25_scenario="multimodal", v_duration=12, v_ratio="16:9",
                v_reference_videos=["https://example.test/source.mp4"],
                seedance25_video_editing=True, **overrides)


@pytest.mark.asyncio
async def test_admin_telegram_edit_persists_effective_provider_settings():
    state = SimpleNamespace(get_data=AsyncMock(return_value=state_data()), clear=AsyncMock())
    message = SimpleNamespace(from_user=SimpleNamespace(id=123), answer=AsyncMock())
    message.answer.return_value = SimpleNamespace(delete=AsyncMock())
    with patch.object(public.config, "is_admin", return_value=True), \
         patch.object(fullstack, "_validate_seedance_sources", AsyncMock()), \
         patch.object(fullstack, "_validate_local_source", AsyncMock(return_value=12)), \
         patch.object(public, "_launch_provider", AsyncMock(return_value={"task_id": "test-edit"})) as launch, \
         patch.object(public.generation_module, "get_or_create_user", AsyncMock(return_value=SimpleNamespace(id=1))), \
         patch.object(public.generation_module, "add_generation_task", AsyncMock()) as store:
        await public._public_message_launch(message, state, "Edit the input video")
    payload = launch.call_args.args[0]
    assert (payload["duration"], payload["ratio"]) == (-1, "adaptive")
    assert store.call_args.kwargs["request_data"]["seedance25_video_editing"] is True
    assert store.call_args.kwargs["duration"] == -1


@pytest.mark.asyncio
@pytest.mark.parametrize("admin, flag, expected", [(True, True, 200), (False, True, 400), (True, "false", 400), (True, 1, 400), (True, None, 400)])
async def test_miniapp_edit_entitlement_and_effective_response(admin, flag, expected):
    from bot import miniapp
    body = state_data()
    body.update(seedance25_video_editing=flag, prompt="Edit the source video")
    request = SimpleNamespace(app={})
    user = SimpleNamespace(id=1, credits=100)
    with patch.object(miniapp, "_get_user_context", AsyncMock(return_value=(123, {"user": user}))), \
         patch.object(public.config, "is_admin", return_value=admin), \
         patch.object(fullstack, "_validate_seedance_sources", AsyncMock()), \
         patch.object(fullstack, "_validate_local_source", AsyncMock(return_value=12)), \
         patch.object(public, "_launch_provider", AsyncMock(return_value={"task_id": "test-edit"})) as launch, \
         patch.object(miniapp, "deduct_credits", AsyncMock()) as debit, \
         patch.object(miniapp, "get_or_create_user", AsyncMock(return_value=user)), \
         patch.object(public.generation_module, "add_generation_task", AsyncMock()) as store:
        response = await public._public_miniapp_generate(request, body)
    assert response.status == expected
    debit.assert_not_awaited()
    if expected != 200:
        launch.assert_not_awaited()
        store.assert_not_awaited()
    else:
        result = json.loads(response.body)
        assert (result["duration"], result["aspect_ratio"]) == (-1, "adaptive")


@pytest.mark.asyncio
@pytest.mark.parametrize("duration, editing, valid", [(3, True, False), (4, True, True), (30, True, True), (31, True, False), (3, False, True), (None, True, True)])
async def test_edit_source_duration_preserves_regular_reference_limits(duration, editing, valid):
    data = state_data()
    data["seedance25_video_editing"] = editing
    payload = public._scenario_payload(data, "Edit")
    with patch.object(fullstack, "_validate_seedance_sources", AsyncMock()), \
         patch.object(fullstack, "_validate_local_source", AsyncMock(return_value=duration)):
        if valid:
            await public._validate_public_payload(payload, is_admin=True)
        else:
            with pytest.raises(ValueError, match="4–30"):
                await public._validate_public_payload(payload, is_admin=True)


def test_normal_reference_settings_are_preserved():
    data = state_data()
    data["seedance25_video_editing"] = False
    payload = public._scenario_payload(data, "Use motion as reference")
    assert (payload["duration"], payload["ratio"]) == (12, "16:9")


@pytest.mark.asyncio
async def test_public_normal_reference_launch_keeps_selected_settings_and_charge():
    from bot import miniapp
    body = state_data()
    body.update(seedance25_video_editing=False, prompt="Use reference motion")
    user = SimpleNamespace(id=1, credits=100)
    with patch.object(miniapp, "_get_user_context", AsyncMock(return_value=(123, {"user": user}))), \
         patch.object(public.config, "is_admin", return_value=False), \
         patch.object(fullstack, "_validate_seedance_sources", AsyncMock()), \
         patch.object(public.preview_module, "_price_quote", return_value=96), \
         patch.object(miniapp, "check_can_afford", AsyncMock(return_value=True)), \
         patch.object(miniapp, "deduct_credits", AsyncMock()) as debit, \
         patch.object(miniapp, "get_or_create_user", AsyncMock(return_value=user)), \
         patch.object(public, "_launch_provider", AsyncMock(return_value={"task_id": "normal-test"})) as launch, \
         patch.object(public.generation_module, "add_generation_task", AsyncMock()) as store:
        response = await public._public_miniapp_generate(SimpleNamespace(app={}), body)
    assert response.status == 200
    debit.assert_awaited_once_with(123, 96)
    assert (launch.call_args.args[0]["duration"], launch.call_args.args[0]["ratio"]) == (12, "16:9")
    assert store.call_args.kwargs["request_data"]["seedance25_video_editing"] is False
    assert store.call_args.kwargs["request_data"]["charged_cost"] == 96


def test_repeat_contract_preserves_editing_intent():
    normalized = normalize_video_request(dict(state_data(), v_model="seedance_2_5"))
    assert normalized["seedance25_video_editing"] is True
    assert (normalized["v_duration"], normalized["v_ratio"]) == (-1, "adaptive")


def repeat_source():
    return {"model": "seedance_2_5", "duration": 12, "aspect_ratio": "16:9",
            "prompt": "Edit source", "request_data": state_data()}


def test_private_miniapp_repeat_restores_edit_intent_and_effective_settings():
    body = enrich_video_repeat_body({"source_feed_gen_id": 1}, repeat_source())
    assert body["seedance25_video_editing"] is True
    assert (body["v_duration"], body["v_ratio"]) == (-1, "adaptive")


@pytest.mark.parametrize("flag", [False, "false", 1])
def test_repeat_does_not_coerce_explicit_flag(flag):
    body = enrich_video_repeat_body({"source_feed_gen_id": 1, "seedance25_video_editing": flag}, repeat_source())
    assert body["seedance25_video_editing"] is flag
    assert (body["v_duration"], body["v_ratio"]) == (12, "16:9")


@pytest.mark.asyncio
async def test_public_repeat_of_admin_edit_is_denied_before_charge():
    from bot import miniapp
    body = enrich_video_repeat_body({"source_feed_gen_id": 1}, repeat_source())
    user = SimpleNamespace(id=2, credits=100)
    card = {"gen_type": "video", "model": "seedance_2_5"}
    with patch.object(miniapp, "_get_user_context", AsyncMock(return_value=(456, {"user": user}))), \
         patch.object(miniapp, "_get_repeat_source_card", AsyncMock(return_value=card)), \
         patch.object(public.config, "is_admin", return_value=False), \
         patch.object(public, "_launch_provider", AsyncMock()) as launch, \
         patch.object(miniapp, "deduct_credits", AsyncMock()) as debit:
        response = await public._public_miniapp_generate(SimpleNamespace(app={}), body)
    assert response.status == 400
    assert "только администратору" in json.loads(response.body)["error"]
    launch.assert_not_awaited()
    debit.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_telegram_edit_is_rejected_before_charge_or_provider():
    state = SimpleNamespace(get_data=AsyncMock(return_value=state_data()), clear=AsyncMock())
    message = SimpleNamespace(from_user=SimpleNamespace(id=123), answer=AsyncMock())
    with patch.object(public.config, "is_admin", return_value=False), \
         patch.object(public, "_launch_provider", AsyncMock()) as launch, \
         patch.object(public.generation_module, "deduct_credits", AsyncMock()) as debit:
        await public._public_message_launch(message, state, "Edit the video")
    launch.assert_not_awaited()
    debit.assert_not_awaited()
    assert "только администратору" in message.answer.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario, videos", [("text", []), ("multimodal", []), ("multimodal", ["https://example.test/a.mp4", "https://example.test/b.mp4"])])
async def test_edit_requires_exactly_one_video_and_multimodal(scenario, videos):
    data = state_data()
    data.update(seedance25_scenario=scenario, v_reference_videos=videos)
    with pytest.raises(ValueError, match="одно исходное видео"):
        await public._validate_public_payload(public._scenario_payload(data, "Edit"), is_admin=True)


@pytest.mark.parametrize("error, hinted", [
    ("Seedance identified your task as video editing. Issues: duration must be -1", True),
    ("duration is not valid", False),
    ("server unavailable", False),
])
def test_editing_failure_has_actionable_hint_without_retry(error, hinted):
    text = fullstack._seedance25_failure_text("test", code=422, fail_msg=error, request_data={"admin_free": True})
    assert ("Выберите режим «Редактировать видео»" in text) is hinted
    assert "Списаний не было" in text
