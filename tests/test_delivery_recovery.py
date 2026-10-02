import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import bot.database
from bot import main
from bot.services.delivery_state import is_terminal_telegram_delivery_error


def test_terminal_telegram_delivery_errors_are_not_retried_forever():
    assert is_terminal_telegram_delivery_error("Bad Request: chat not found")
    assert is_terminal_telegram_delivery_error("Forbidden: bot was blocked by the user")
    assert is_terminal_telegram_delivery_error("Bad Request: user is deactivated")


def test_transient_telegram_delivery_errors_remain_recoverable():
    assert not is_terminal_telegram_delivery_error(TimeoutError("request timeout"))
    assert not is_terminal_telegram_delivery_error("Too Many Requests: retry after 3")
    assert not is_terminal_telegram_delivery_error("network error")


class FakeRequest(dict):
    def __init__(self, payload: dict, bot_instance):
        super().__init__()
        self._payload = payload
        self.query = {}
        self.headers = {}
        self.app = {"bot": bot_instance}

    async def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    async def json(self) -> dict:
        return self._payload


@pytest.mark.asyncio
async def test_kie_success_link_fallback_stays_recoverable(monkeypatch):
    result_url = "https://tempfile.aiquickdraw.com/seedream5pro/result.png"
    task = SimpleNamespace(
        id=42,
        task_id="kie-media-pending",
        status="processing",
        user_id=7,
        type="image",
        model="seedream_5_pro",
        preset_id="no_preset",
        prompt="test prompt",
        cost=8,
        duration=None,
        aspect_ratio="1:1",
        source_feed_gen_id=None,
        is_public_feed=False,
        request_data="{}",
    )
    payload = {
        "code": 200,
        "data": {
            "taskId": task.task_id,
            "state": "success",
            "model": "seedream/5-pro-image-to-image",
            "resultJson": json.dumps({"resultUrls": [result_url]}),
        },
    }
    bot_instance = SimpleNamespace(
        send_photo=AsyncMock(
            side_effect=RuntimeError("failed to get HTTP URL content")
        )
    )
    request = FakeRequest(payload, bot_instance)
    request["skip_kie_ai_secret_check"] = True

    complete = AsyncMock(return_value=True)
    mark_delivery = AsyncMock(return_value=True)
    store_result = AsyncMock(return_value=True)
    monkeypatch.setattr(bot.database, "get_task_by_id", AsyncMock(return_value=task))
    monkeypatch.setattr(
        "bot.services.kie_webhook_verification.kie_market_service.get_task_status",
        AsyncMock(return_value=payload["data"]),
    )
    monkeypatch.setattr(bot.database, "claim_task_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(bot.database, "complete_video_task", complete)
    monkeypatch.setattr(bot.database, "mark_task_delivery_status", mark_delivery)
    monkeypatch.setattr(bot.database, "store_task_result_ready", store_result)
    monkeypatch.setattr(main, "_resolve_task_telegram_id", AsyncMock(return_value=123456))
    monkeypatch.setattr(
        main,
        "_persist_result_url_if_needed",
        AsyncMock(return_value=result_url),
    )
    monkeypatch.setattr(main, "_download_remote_bytes", AsyncMock(return_value=None))
    monkeypatch.setattr(main, "_send_original_file", AsyncMock(return_value=False))
    link_fallback = AsyncMock(return_value=None)
    monkeypatch.setattr(main, "_send_plain_result_link", link_fallback)

    response = await main.handle_kie_ai_webhook(request)

    assert response.status == 200
    complete.assert_not_awaited()
    store_result.assert_awaited_once_with(task.task_id, result_url)
    link_fallback.assert_awaited_once()
    statuses = [call.args[1] for call in mark_delivery.await_args_list]
    assert statuses == ["link_sent", "pending"]


@pytest.mark.asyncio
async def test_kie_kling_link_fallback_does_not_complete_task(monkeypatch):
    result_url = "https://tempfile.aiquickdraw.com/kling/result.mp4"
    task = SimpleNamespace(
        id=43,
        task_id="kie-kling-pending",
        status="processing",
        user_id=8,
        type="video",
        model="v3_pro",
        preset_id="no_preset",
        prompt="test video",
        cost=12,
        duration=5,
        aspect_ratio="16:9",
        source_feed_gen_id=None,
        is_public_feed=False,
        request_data="{}",
    )
    payload = {
        "code": 200,
        "taskId": task.task_id,
        "data": {"result_video_url": result_url},
    }
    bot_instance = SimpleNamespace(
        send_video=AsyncMock(
            side_effect=RuntimeError("failed to get HTTP URL content")
        )
    )
    request = FakeRequest(payload, bot_instance)

    complete = AsyncMock(return_value=True)
    mark_delivery = AsyncMock(return_value=True)
    store_result = AsyncMock(return_value=True)
    monkeypatch.setattr(main.config, "REPLICATE_WEBHOOK_SECRET", "")
    monkeypatch.setattr(bot.database, "get_task_by_id", AsyncMock(return_value=task))
    monkeypatch.setattr(bot.database, "claim_task_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(bot.database, "complete_video_task", complete)
    monkeypatch.setattr(bot.database, "mark_task_delivery_status", mark_delivery)
    monkeypatch.setattr(bot.database, "store_task_result_ready", store_result)
    monkeypatch.setattr(main, "_resolve_task_telegram_id", AsyncMock(return_value=654321))
    monkeypatch.setattr(
        main,
        "_persist_result_url_if_needed",
        AsyncMock(return_value=result_url),
    )
    monkeypatch.setattr(main, "_send_video_file_from_url", AsyncMock(return_value=False))
    link_fallback = AsyncMock(return_value=None)
    monkeypatch.setattr(main, "_send_plain_result_link", link_fallback)

    response = await main.handle_kling_webhook(request)

    assert response.status == 200
    complete.assert_not_awaited()
    store_result.assert_awaited_once_with(task.task_id, result_url)
    link_fallback.assert_awaited_once()
    statuses = [call.args[1] for call in mark_delivery.await_args_list]
    assert statuses == ["link_sent", "pending"]

def test_terminal_telegram_delivery_reason_is_structured():
    from bot.services.delivery_state import terminal_telegram_delivery_reason

    assert (
        terminal_telegram_delivery_reason("Bad Request: chat not found")
        == "chat_not_found"
    )
    assert (
        terminal_telegram_delivery_reason("Forbidden: bot was blocked by the user")
        == "bot_blocked"
    )
    assert (
        terminal_telegram_delivery_reason("Bad Request: user is deactivated")
        == "user_deactivated"
    )
    assert terminal_telegram_delivery_reason("network error") is None
