import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from bot.config import config
from bot.main import handle_kie_ai_webhook, handle_kling_webhook


@pytest.mark.asyncio
async def test_handle_kling_webhook_accepts_ai_secret(monkeypatch):
    payload = {
        "id": "task123",
        "status": "succeeded",
        "output": "https://x.example/out.mp4",
    }
    body = json.dumps(payload).encode("utf-8")
    monkeypatch.setattr(config, "AI_WEBHOOK_SECRET", "expected")

    # Build a lightweight fake request object with just the attributes the handler uses
    class FakeReq:
        def __init__(self, body):
            self._body = body
            self.headers = {}
            self.query = {"secret": "expected"}

        async def read(self):
            return self._body

    req = FakeReq(body)

    resp = await handle_kling_webhook(req)
    assert resp.status == 200


@pytest.mark.asyncio
async def test_handle_kling_webhook_rejects_invalid_ai_secret(monkeypatch, caplog):
    payload = {
        "id": "task123",
        "status": "succeeded",
        "output": "https://x.example/out.mp4",
    }
    body = json.dumps(payload).encode("utf-8")
    monkeypatch.setattr(config, "AI_WEBHOOK_SECRET", "expected")

    class FakeReq:
        def __init__(self, body):
            self._body = body
            self.headers = {}
            self.query = {"secret": "wrong"}

        async def read(self):
            return self._body

    req = FakeReq(body)

    resp = await handle_kling_webhook(req)

    assert resp.status == 403
    assert "invalid AI webhook secret" in caplog.text


@pytest.mark.asyncio
async def test_kie_webhook_rejects_invalid_ai_secret(monkeypatch):
    monkeypatch.setattr(config, "AI_WEBHOOK_SECRET", "expected")
    body = json.dumps({"data": {"taskId": "task-processing", "state": "processing"}}).encode(
        "utf-8"
    )

    class FakeReq:
        headers = {}
        query = {}

        async def read(self):
            return body

    resp = await handle_kie_ai_webhook(FakeReq())

    assert resp.status == 403


@pytest.mark.asyncio
async def test_kie_processing_status_is_not_treated_as_failure(monkeypatch):
    monkeypatch.setattr(config, "AI_WEBHOOK_SECRET", "expected")

    import bot.database as database

    complete = AsyncMock()
    refund = AsyncMock()
    monkeypatch.setattr(database, "get_task_by_id", AsyncMock(return_value=None))
    monkeypatch.setattr(database, "get_telegram_id_by_user_id", AsyncMock())
    monkeypatch.setattr(database, "complete_video_task", complete)
    monkeypatch.setattr(database, "add_credits", refund)

    body = json.dumps(
        {"data": {"taskId": "task-processing", "state": "processing"}}
    ).encode("utf-8")

    class FakeReq:
        headers = {}
        query = {"secret": "expected"}

        async def read(self):
            return body

    resp = await handle_kie_ai_webhook(FakeReq())

    assert resp.status == 200
    complete.assert_not_awaited()
    refund.assert_not_awaited()


@pytest.mark.asyncio
async def test_kie_failure_persists_error_message(monkeypatch):
    monkeypatch.setattr(config, "AI_WEBHOOK_SECRET", "expected")

    import bot.database as database
    import bot.main as main
    from bot.services.reliability import runtime_reliability

    fail_task = AsyncMock()
    monkeypatch.setattr(
        database,
        "get_task_by_id",
        AsyncMock(return_value=SimpleNamespace(user_id=7, cost=2)),
    )
    monkeypatch.setattr(database, "get_telegram_id_by_user_id", AsyncMock(return_value=None))
    monkeypatch.setattr(database, "fail_generation_task", fail_task)
    monkeypatch.setattr(main, "refund_generation_billing", AsyncMock())
    monkeypatch.setattr(runtime_reliability, "mark_provider_event", AsyncMock(return_value=True))

    body = json.dumps(
        {
            "code": 200,
            "data": {
                "taskId": "task-failed",
                "model": "nano-banana-2",
                "state": "fail",
                "failCode": 422,
                "failMsg": "No result generated. Try a simpler prompt.",
            },
        }
    ).encode("utf-8")

    class FakeReq:
        headers = {}
        query = {"secret": "expected"}

        async def read(self):
            return body

    resp = await handle_kie_ai_webhook(FakeReq())

    assert resp.status == 200
    fail_task.assert_awaited_once_with(
        "task-failed",
        "422: No result generated. Try a simpler prompt.",
    )
