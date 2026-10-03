import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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
async def test_kie_chatless_success_retains_result_without_telegram(
    isolated_database,
    monkeypatch,
):
    result_url = "https://cdn.example/chatless-result.png"
    user = await bot.database.get_or_create_user(
        123457,
        initial_telegram_chat_state="unavailable",
    )
    await bot.database.add_generation_task(
        user.id,
        user.telegram_id,
        "kie-chatless-success",
        "image",
        "miniapp_image",
        model="seedream_5_pro",
        request_data={"source": "miniapp"},
    )
    payload = {
        "code": 200,
        "data": {
            "taskId": "kie-chatless-success",
            "state": "success",
            "model": "seedream/5-pro-image-to-image",
            "resultJson": json.dumps({"resultUrls": [result_url]}),
        },
    }
    bot_instance = SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock())
    request = FakeRequest(payload, bot_instance)
    request["skip_kie_ai_secret_check"] = True
    monkeypatch.setattr(
        "bot.services.kie_webhook_verification.kie_market_service.get_task_status",
        AsyncMock(return_value=payload["data"]),
    )
    monkeypatch.setattr(
        main,
        "_persist_result_url_if_needed",
        AsyncMock(return_value=result_url),
    )

    response = await main.handle_kie_ai_webhook(request)

    task = await bot.database.get_task_by_id("kie-chatless-success")
    metadata = json.loads(task.request_data or "{}")
    assert response.status == 200
    assert task.status == "completed"
    assert task.result_url == result_url
    assert metadata["delivery_status"] == "unavailable"
    assert metadata["delivery_error"] == "chat_not_started"
    bot_instance.send_photo.assert_not_awaited()
    bot_instance.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_canonical_kie_terminal_error_stops_file_and_link_fallbacks(monkeypatch):
    result_url = "https://cdn.example/canonical-terminal.mp4"
    task = SimpleNamespace(
        id=45,
        task_id="canonical-kie-terminal",
        status="processing",
        user_id=10,
        type="video",
        model="kling/v3-pro",
        preset_id="no_preset_video",
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
        "data": {
            "taskId": task.task_id,
            "state": "success",
            "model": task.model,
            "resultJson": json.dumps({"resultUrls": [result_url]}),
        },
    }
    bot_instance = SimpleNamespace(
        send_video=AsyncMock(side_effect=RuntimeError("Bad Request: chat not found"))
    )
    request = FakeRequest(payload, bot_instance)
    request["skip_kie_ai_secret_check"] = True
    complete = AsyncMock(return_value=True)
    mark = AsyncMock(return_value=True)
    link = AsyncMock()
    download_session = MagicMock()
    monkeypatch.setattr(bot.database, "get_task_by_id", AsyncMock(return_value=task))
    monkeypatch.setattr(bot.database, "can_attempt_telegram_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(bot.database, "claim_task_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(bot.database, "complete_video_task", complete)
    monkeypatch.setattr(bot.database, "mark_task_delivery_status", mark)
    monkeypatch.setattr(bot.database, "store_task_result_ready", AsyncMock(return_value=True))
    monkeypatch.setattr(main, "_resolve_task_telegram_id", AsyncMock(return_value=654323))
    monkeypatch.setattr(main, "_persist_result_url_if_needed", AsyncMock(return_value=result_url))
    monkeypatch.setattr(main, "_send_plain_result_link", link)
    monkeypatch.setattr(main.aiohttp, "ClientSession", download_session)
    monkeypatch.setattr(
        "bot.services.kie_webhook_verification.kie_market_service.get_task_status",
        AsyncMock(return_value=payload["data"]),
    )

    response = await main.handle_kie_ai_webhook(request)

    assert response.status == 200
    complete.assert_awaited_once_with(task.task_id, result_url)
    mark.assert_awaited_once_with(task.task_id, "unavailable", error="chat_not_found")
    download_session.assert_not_called()
    link.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_prompt_followup_marks_chat_unavailable(monkeypatch):
    result_url = "https://cdn.example/followup-terminal.png"
    task = SimpleNamespace(
        id=46,
        task_id="canonical-followup-terminal",
        status="processing",
        user_id=11,
        type="image",
        model="seedream_5_pro",
        preset_id="no_preset",
        prompt="visible prompt",
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
        send_photo=AsyncMock(return_value=None),
        send_document=AsyncMock(return_value=None),
    )
    request = FakeRequest(payload, bot_instance)
    request["skip_kie_ai_secret_check"] = True
    mark_chat = AsyncMock(return_value=True)
    monkeypatch.setattr(bot.database, "get_task_by_id", AsyncMock(return_value=task))
    monkeypatch.setattr(bot.database, "can_attempt_telegram_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(bot.database, "claim_task_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(bot.database, "complete_video_task", AsyncMock(return_value=True))
    monkeypatch.setattr(bot.database, "mark_task_delivery_status", AsyncMock(return_value=True))
    monkeypatch.setattr(bot.database, "mark_telegram_chat_unavailable", mark_chat)
    monkeypatch.setattr(bot.database, "store_task_result_ready", AsyncMock(return_value=True))
    monkeypatch.setattr(main, "_resolve_task_telegram_id", AsyncMock(return_value=654324))
    monkeypatch.setattr(main, "_persist_result_url_if_needed", AsyncMock(return_value=result_url))
    monkeypatch.setattr(main, "_download_remote_bytes", AsyncMock(return_value=None))
    monkeypatch.setattr(
        main,
        "_send_used_prompt_message",
        AsyncMock(side_effect=RuntimeError("Bad Request: chat not found")),
    )
    monkeypatch.setattr(
        "bot.services.kie_webhook_verification.kie_market_service.get_task_status",
        AsyncMock(return_value=payload["data"]),
    )

    response = await main.handle_kie_ai_webhook(request)

    assert response.status == 200
    mark_chat.assert_awaited_once_with(654324)


@pytest.mark.asyncio
async def test_terminal_watchdog_notification_marks_chat_unavailable(monkeypatch):
    task = SimpleNamespace(
        task_id="watchdog-terminal",
        model="seedream_5_pro",
        type="image",
        cost=8,
        request_data="{}",
    )
    bot_instance = SimpleNamespace(
        send_message=AsyncMock(side_effect=RuntimeError("Bad Request: chat not found"))
    )
    mark_chat = AsyncMock(return_value=True)
    monkeypatch.setattr(bot.database, "get_task_by_id", AsyncMock(return_value=task))
    monkeypatch.setattr(bot.database, "can_attempt_telegram_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(bot.database, "mark_telegram_chat_unavailable", mark_chat)
    monkeypatch.setattr(main, "_resolve_task_telegram_id", AsyncMock(return_value=654325))

    notified = await main._notify_watchdog_failed_task(
        bot_instance,
        {"task_id": task.task_id},
    )

    assert notified is False
    mark_chat.assert_awaited_once_with(654325)


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


@pytest.mark.asyncio
async def test_kie_kling_terminal_error_stops_all_fallbacks(monkeypatch):
    result_url = "https://cdn.example/kling-terminal.mp4"
    task = SimpleNamespace(
        id=44,
        task_id="kie-kling-terminal",
        status="processing",
        user_id=9,
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
        send_video=AsyncMock(side_effect=RuntimeError("Bad Request: chat not found"))
    )
    request = FakeRequest(payload, bot_instance)
    complete = AsyncMock(return_value=True)
    mark = AsyncMock(return_value=True)
    file_fallback = AsyncMock(return_value=True)
    link_fallback = AsyncMock()
    monkeypatch.setattr(main.config, "REPLICATE_WEBHOOK_SECRET", "")
    monkeypatch.setattr(bot.database, "get_task_by_id", AsyncMock(return_value=task))
    monkeypatch.setattr(bot.database, "can_attempt_telegram_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(bot.database, "claim_task_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(bot.database, "complete_video_task", complete)
    monkeypatch.setattr(bot.database, "mark_task_delivery_status", mark)
    monkeypatch.setattr(bot.database, "store_task_result_ready", AsyncMock(return_value=True))
    monkeypatch.setattr(main, "_resolve_task_telegram_id", AsyncMock(return_value=654322))
    monkeypatch.setattr(main, "_persist_result_url_if_needed", AsyncMock(return_value=result_url))
    monkeypatch.setattr(main, "_send_video_file_from_url", file_fallback)
    monkeypatch.setattr(main, "_send_plain_result_link", link_fallback)

    response = await main.handle_kling_webhook(request)

    assert response.status == 200
    complete.assert_awaited_once_with(task.task_id, result_url)
    mark.assert_awaited_once_with(
        task.task_id,
        "unavailable",
        error="chat_not_found",
    )
    file_fallback.assert_not_awaited()
    link_fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_image_poller_chatless_success_and_failure_make_zero_telegram_calls(
    isolated_database,
    monkeypatch,
):
    from bot.services import task_watchdog

    monkeypatch.setattr(task_watchdog, "DATABASE_PATH", bot.database.DATABASE_PATH)
    user = await bot.database.get_or_create_user(
        123458,
        initial_telegram_chat_state="unavailable",
    )
    await bot.database.add_generation_task(
        user.id,
        user.telegram_id,
        "poller-chatless-success",
        "image",
        "miniapp_image",
        model="nano_banana_pro",
        request_data={"source": "miniapp"},
    )
    success_task = await bot.database.get_task_by_id("poller-chatless-success")
    bot_instance = SimpleNamespace(
        send_photo=AsyncMock(),
        send_document=AsyncMock(),
        send_message=AsyncMock(),
    )
    result_url = "https://cdn.example/poller-result.png"
    monkeypatch.setattr(
        main,
        "_persist_result_url_if_needed",
        AsyncMock(return_value=result_url),
    )

    assert await main._send_polled_nexus_image_result(
        bot_instance,
        success_task,
        result_url,
    )
    stored_success = await bot.database.get_task_by_id("poller-chatless-success")
    assert stored_success.status == "completed"
    assert stored_success.result_url == result_url

    await bot.database.add_generation_task(
        user.id,
        user.telegram_id,
        "poller-chatless-failure",
        "image",
        "miniapp_image",
        model="nano_banana_pro",
        cost=5,
        request_data={"source": "miniapp"},
    )
    failure_task = await bot.database.get_task_by_id("poller-chatless-failure")
    assert await main._fail_polled_nexus_image_task(
        bot_instance,
        failure_task,
        reason="provider failed",
    )
    stored_failure = await bot.database.get_task_by_id("poller-chatless-failure")
    assert stored_failure.status == "failed"
    bot_instance.send_photo.assert_not_awaited()
    bot_instance.send_document.assert_not_awaited()
    bot_instance.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_kie_motion_failure_uses_atomic_refund_marker_before_notification(
    isolated_database,
    monkeypatch,
):
    from bot.services import task_watchdog

    monkeypatch.setattr(task_watchdog, "DATABASE_PATH", bot.database.DATABASE_PATH)
    user = await bot.database.get_or_create_user(123456)
    await bot.database.add_generation_task(
        user.id,
        user.telegram_id,
        "motion-failed",
        "video",
        "no_preset_video",
        model="motion_control_v26",
        duration=5,
        aspect_ratio="1:1",
        prompt="motion",
        cost=15,
        request_data={"source": "telegram"},
    )
    async with bot.database.db_backend.connect(bot.database.DATABASE_PATH) as db:
        await db.execute("UPDATE users SET credits = 0 WHERE id = ?", (user.id,))
        await db.commit()

    payload = {
        "code": 501,
        "data": {
            "taskId": "motion-failed",
            "state": "fail",
            "failCode": "500",
            "failMsg": "internal error, please try again later.",
        },
    }
    bot_instance = SimpleNamespace(send_message=AsyncMock(return_value=None))
    request = FakeRequest(payload, bot_instance)

    response = await main.handle_kling_webhook(request)
    replay = await main.handle_kling_webhook(request)

    assert response.status == 200
    assert replay.status == 200
    assert bot_instance.send_message.await_count <= 1
    failed_task = await bot.database.get_task_by_id("motion-failed")
    request_data = json.loads(failed_task.request_data or "{}")
    assert failed_task.status == "failed"
    assert request_data["refund_claimed"] is True
    assert request_data["refund_state"] == "refunded"
    refreshed = await bot.database.get_or_create_user(user.telegram_id)
    assert refreshed.credits == 15

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
