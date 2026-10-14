"""#313: completed video delivery must never loop forever after a 413."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database, main
from bot.services import task_watchdog


class FakeRequest(dict):
    def __init__(self, payload, telegram_bot):
        super().__init__(skip_kie_ai_secret_check=True)
        self._payload = payload
        self.query = {}
        self.headers = {}
        self.app = {"bot": telegram_bot}
    async def json(self):
        return self._payload
    async def read(self):
        return json.dumps(self._payload).encode()


class FakeDownload:
    status = 200
    def __init__(self):
        self.content = self
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        return False
    async def iter_chunked(self, _):
        yield b"sample video bytes"


class FakeSession:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        return False
    def get(self, _url, **_kwargs):
        return FakeDownload()


@pytest.mark.asyncio
async def test_successful_motion_video_413_sends_one_link_then_terminates_recovery(
    isolated_database, monkeypatch,
):
    telegram_id = 1240051
    user = await database.get_or_create_user(telegram_id)
    task_id = "oversize-313-webhook"
    result_url = "https://cdn.example/result-313.mp4"
    await database.add_generation_task(
        user.id, telegram_id, task_id, "video", "no_preset_video",
        model="motion_control_v26",
        cost=0, duration=5, request_data={"source": "miniapp", "charged": False},
    )
    payload = {
        "code": 200,
        "data": {
            "taskId": task_id,
            "state": "success",
            "model": "motion_control_v26",
            "resultJson": json.dumps({"resultUrls": [result_url]}),
        },
    }
    bot = SimpleNamespace(
        send_video=AsyncMock(side_effect=[
            RuntimeError("Bad Request: failed to get HTTP URL content"),
            RuntimeError("HTTP Client says - Request Entity Too Large"),
        ]),
        send_message=AsyncMock(),
        get_chat=AsyncMock(),
    )
    req = FakeRequest(payload, bot)
    monkeypatch.setattr(
        "bot.services.kie_webhook_verification.kie_market_service.get_task_status",
        AsyncMock(return_value=payload["data"]),
    )
    monkeypatch.setattr(
        main, "_persist_result_url_if_needed", AsyncMock(return_value=result_url),
    )
    monkeypatch.setattr(main, "_resolve_task_telegram_id", AsyncMock(return_value=telegram_id))
    monkeypatch.setattr(
        database, "can_attempt_telegram_delivery", AsyncMock(return_value=True),
    )
    monkeypatch.setattr(main.aiohttp, "ClientSession", FakeSession)
    response = await main.handle_kie_ai_webhook(req)
    assert response.status == 200
    saved = await database.get_task_by_id(task_id)
    metadata = json.loads(saved.request_data or "{}")
    assert saved.status == "completed"
    assert saved.result_url == result_url
    assert bot.send_message.await_count == 1
    assert bot.send_video.await_count == 2
    assert metadata["delivery_link_sent"] is True
    assert metadata["delivery_status"] == "link_only"
    assert await database.claim_task_delivery(task_id) is False
    monkeypatch.setattr(task_watchdog, "DATABASE_PATH", database.DATABASE_PATH)
    stuck = await task_watchdog.get_stuck_tasks(minutes=0)
    assert not any(t["task_id"] == task_id for t in stuck)
    again = await main.handle_kie_ai_webhook(req)
    assert again.status == 200
    assert bot.send_video.await_count == 2
    assert bot.send_message.await_count == 1


@pytest.mark.asyncio
async def test_retry_budget_stops_unbounded_link_only_media_replays(
    isolated_database, monkeypatch,
):
    telegram_id = 1240052
    user = await database.get_or_create_user(telegram_id)
    task_id = "oversize-313-existing"
    await database.add_generation_task(
        user.id, telegram_id, task_id, "video", "no_preset_video",
        model="motion_control_v26", cost=0,
        request_data={
            "delivery_status": "pending", "delivery_link_sent": True,
            "delivery_attempts": 30, "charged": False,
        },
    )
    assert await database.mark_task_delivery_status(
        task_id, "pending", error="HTTP Client says - Request Entity Too Large",
    )
    task = await database.get_task_by_id(task_id)
    meta = json.loads(task.request_data or "{}")
    assert meta["delivery_status"] == "link_only"
    assert await database.claim_task_delivery(task_id) is False


@pytest.mark.asyncio
async def test_retry_budget_without_sent_link_leaves_completed_result_for_manual_review(
    isolated_database,
):
    user = await database.get_or_create_user(1240053)
    task_id = "oversize-313-no-link"
    await database.add_generation_task(
        user.id, user.telegram_id, task_id, "video", "no_preset_video",
        cost=0,
        request_data={"delivery_status": "pending", "delivery_attempts": 30, "charged": False},
    )
    assert await database.mark_task_delivery_status(
        task_id, "pending", error="repeated Telegram network failure",
    )
    meta = json.loads((await database.get_task_by_id(task_id)).request_data or "{}")
    assert meta["delivery_status"] == "uncertain"
    assert await database.claim_task_delivery(task_id) is False


def test_telegram_oversize_classifier_keeps_transient_rejections_retryable():
    from bot.services.delivery_state import telegram_media_too_large

    assert telegram_media_too_large("HTTP Client says - Request Entity Too Large")
    assert telegram_media_too_large("Bad Request: file is too big")
    assert telegram_media_too_large("HTTP 413")
    assert telegram_media_too_large("telegram_media_too_large")
    for message in ("Too Many Requests: retry after 5", "failed to get HTTP URL content",
                    "request timeout", "Bad Request: chat not found", "HTTP 500"):
        assert not telegram_media_too_large(message)


@pytest.mark.asyncio
async def test_legacy_high_attempt_task_is_reconciled_without_resending_media(
    isolated_database, monkeypatch,
):
    telegram_id = 1240054
    user = await database.get_or_create_user(telegram_id)
    task_id = "oversize-313-legacy-task"
    result_url = "https://cdn.example/legacy-result.mp4"
    await database.add_generation_task(
        user.id, telegram_id, task_id, "video", "no_preset_video",
        model="motion_control_v26", cost=0,
        request_data={
            "delivery_status": "pending", "delivery_link_sent": True,
            "delivery_attempts": 7835, "charged": False,
        },
    )
    assert await database.store_task_result_ready(task_id, result_url)
    assert await database.claim_task_delivery(task_id) is False
    task = await database.get_task_by_id(task_id)
    metadata = json.loads(task.request_data)
    assert task.status == "completed"
    assert task.result_url == result_url
    assert metadata["delivery_status"] == "link_only"
    assert metadata["delivery_attempts"] == 7835
    assert await database.claim_task_delivery(task_id) is False
    assert json.loads((await database.get_task_by_id(task_id)).request_data) == metadata
    monkeypatch.setattr(task_watchdog, "DATABASE_PATH", database.DATABASE_PATH)
    stuck = await task_watchdog.get_stuck_tasks(minutes=0)
    assert not any(t["task_id"] == task_id for t in stuck)


@pytest.mark.asyncio
async def test_transient_delivery_stays_retryable_below_budget(isolated_database):
    user = await database.get_or_create_user(1240055)
    task_id = "oversize-313-transient"
    await database.add_generation_task(
        user.id, user.telegram_id, task_id, "video", "no_preset_video",
        cost=0,
        request_data={"delivery_status": "pending", "delivery_attempts": 2},
    )
    assert await database.mark_task_delivery_status(
        task_id, "pending", error="Temporary Telegram timeout",
    )
    meta = json.loads((await database.get_task_by_id(task_id)).request_data)
    assert meta["delivery_status"] == "pending"
    assert await database.claim_task_delivery(task_id)
    meta = json.loads((await database.get_task_by_id(task_id)).request_data)
    assert meta["delivery_status"] == "delivering"


@pytest.mark.asyncio
async def test_terminal_link_only_cannot_be_overwritten_by_stale_pending_update(
    isolated_database,
):
    user = await database.get_or_create_user(1240056)
    task_id = "oversize-313-terminal-guard"
    await database.add_generation_task(
        user.id, user.telegram_id, task_id, "video", "no_preset_video",
        cost=0,
        request_data={"delivery_status": "pending", "delivery_link_sent": True},
    )
    assert await database.mark_task_delivery_status(
        task_id, "link_only", error="telegram_media_too_large",
    )
    assert not await database.mark_task_delivery_status(
        task_id, "pending", error="stale network error",
    )
    meta = json.loads((await database.get_task_by_id(task_id)).request_data)
    assert meta["delivery_status"] == "link_only"



@pytest.mark.asyncio
async def test_permanent_size_rejection_without_link_needs_manual_recovery_immediately(
    isolated_database,
):
    user = await database.get_or_create_user(1240057)
    task_id = "oversize-313-no-link-413"
    await database.add_generation_task(
        user.id, user.telegram_id, task_id, "video", "no_preset_video",
        cost=0, request_data={"delivery_status": "pending", "delivery_attempts": 1},
    )
    assert await database.mark_task_delivery_status(
        task_id, "pending", error="HTTP Client says - Request Entity Too Large",
    )
    task = await database.get_task_by_id(task_id)
    metadata = json.loads(task.request_data or "{}")
    assert metadata["delivery_status"] == "uncertain"
    assert metadata["delivery_attempts"] == 2
    assert await database.claim_task_delivery(task_id) is False
