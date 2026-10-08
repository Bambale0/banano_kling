"""Typed video callbacks use the consent-aware Mini App flow before billing."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database, miniapp
from bot.handlers import generation
from bot.handlers import miniapp_video_continuity_compat as continuity
from bot.handlers import seedance_25_telegram_compat as seedance
from bot.handlers import video_generation_compat as advanced


@pytest.mark.asyncio
@pytest.mark.parametrize("handler_name", ["generic", "advanced", "seedance"])
@pytest.mark.parametrize("child", [False, True])
@pytest.mark.parametrize("available", [False, True])
async def test_typed_video_callback_redirects_or_blocks_before_billing(
    monkeypatch, handler_name, child, available,
):
    model = "seedance_2_5" if handler_name == "seedance" else "seedance_2"
    grant = {"version": 1, "images": ["https://example.test/fixed.png"], "videos": []}
    source = {
        "id": 42, "user_id": 1, "type": "video", "model": model, "status": "completed",
        "prompt": "Synthetic hidden recipe", "feed_repeat_reference_selection": grant,
        "request_data": {"v_type": "imgtxt", "v_image_url": "https://example.test/fixed.png",
                         "seedance25_scenario": "first_frame"},
    }
    task = SimpleNamespace(
        id=84 if child else 42, task_id="callback-source", user_id=2 if child else 1,
        type="video", model=model, source_feed_gen_id=42 if child else None,
        feed_repeat_reference_selection=None if child else json.dumps(grant),
        request_data=json.dumps({"v_model": model, "video_repeat_contract_version": 1} if child else {"v_model": model}),
        prompt="Synthetic hidden recipe", cost=10, duration=5, aspect_ratio="9:16",
    )
    task_lookup = AsyncMock(return_value=task)
    user_lookup = AsyncMock(return_value=SimpleNamespace(id=2, credits=100))
    monkeypatch.setattr(generation, "get_task_by_id", task_lookup)
    monkeypatch.setattr(advanced, "get_task_by_id", task_lookup)
    monkeypatch.setattr(database, "get_or_create_user", user_lookup)
    monkeypatch.setattr(generation, "get_or_create_user", user_lookup)
    monkeypatch.setattr(advanced, "get_or_create_user", user_lookup)
    monkeypatch.setattr(continuity, "get_generation_task_payload", AsyncMock(return_value=source))
    monkeypatch.setattr(miniapp, "_get_repeat_source_card", AsyncMock(
        return_value={"id": 42, "gen_type": "video"} if available else None))
    debit = AsyncMock()
    launch = AsyncMock()
    monkeypatch.setattr(generation, "deduct_credits", debit)
    monkeypatch.setattr(advanced, "deduct_credits", debit)
    monkeypatch.setattr(generation, "run_no_preset_video_from_callback", launch)
    monkeypatch.setattr(advanced, "run_no_preset_video_from_callback", launch)
    monkeypatch.setattr("bot.keyboards._mini_app_url_with_start_param",
                        lambda value: "https://example.test/mini-app?startapp=" + value)
    message = SimpleNamespace(answer=AsyncMock())
    callback = SimpleNamespace(
        data="repeat_video_result_callback-source", from_user=SimpleNamespace(id=880202),
        message=message, answer=AsyncMock(),
    )
    state = SimpleNamespace(update_data=AsyncMock(), clear=AsyncMock())
    handler = {"generic": generation.quick_repeat_video_result,
               "advanced": advanced.repeat_advanced_video_result,
               "seedance": seedance.seedance25_repeat_video_result}[handler_name]
    await handler(callback, state)
    debit.assert_not_awaited()
    launch.assert_not_awaited()
    state.update_data.assert_not_awaited()
    if available:
        call = message.answer.await_args
        assert call is not None
        button = call.kwargs["reply_markup"].inline_keyboard[0][0]
        assert button.web_app.url == "https://example.test/mini-app?startapp=remix_42"
        assert "https://example.test/fixed.png" not in call.args[0]
        assert "Synthetic hidden recipe" not in call.args[0]
    else:
        callback.answer.assert_awaited()
        assert callback.answer.await_args.kwargs["show_alert"] is True
        message.answer.assert_not_awaited()
