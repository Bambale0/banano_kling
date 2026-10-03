"""Provider results survive Telegram chat changes and delivery races."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database, main


class Request(dict):
    def __init__(self, payload, bot):
        super().__init__(skip_kie_ai_secret_check=True)
        self.payload = payload
        self.app = {"bot": bot}
        self.headers = {}
        self.query = {}

    async def json(self):
        return self.payload

    async def read(self):
        return json.dumps(self.payload).encode()


async def prepare_callback(monkeypatch, route="canonical"):
    user = await database.get_or_create_user(881001)
    task_id = f"durable-{route}"
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        task_id,
        "video",
        "miniapp_video",
        model="v3_pro",
        request_data={"source": "miniapp"},
    )
    url = "https://cdn.example/durable.mp4"
    canonical = {
        "taskId": task_id,
        "state": "success",
        "model": "kling/v3-pro",
        "resultJson": json.dumps({"resultUrls": [url]}),
    }
    payload = {"code": 200, "data": canonical}
    handler = main.handle_kie_ai_webhook
    if route == "kling":
        payload = {"code": 200, "taskId": task_id, "data": {"result_video_url": url}}
        handler = main.handle_kling_webhook
    elif route == "legacy":
        handler = main.handle_kling_webhook
    bot = SimpleNamespace(
        send_video=AsyncMock(),
        send_photo=AsyncMock(),
        send_message=AsyncMock(),
        send_document=AsyncMock(),
    )
    monkeypatch.setattr(main.config, "REPLICATE_WEBHOOK_SECRET", "")
    monkeypatch.setattr(
        "bot.services.kie_webhook_verification.kie_market_service.get_task_status",
        AsyncMock(return_value=canonical),
    )
    monkeypatch.setattr(
        main, "_persist_result_url_if_needed", AsyncMock(return_value=url)
    )
    monkeypatch.setattr(main, "_send_video_file_from_url", AsyncMock(return_value=True))
    monkeypatch.setattr(main, "_send_original_file", AsyncMock(return_value=True))
    monkeypatch.setattr(main, "_send_used_prompt_message", AsyncMock())
    return user, task_id, url, handler, Request(payload, bot)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["canonical", "kling", "legacy"])
async def test_start_before_success_recovers_legacy_unavailable_task(
    monkeypatch, route
):
    user, task_id, url, handler, request = await prepare_callback(monkeypatch, route)
    # Reproduce tasks poisoned by a pre-result start-notification failure.
    await database.mark_task_delivery_status(
        task_id, "unavailable", error="chat_not_found"
    )
    await database.mark_telegram_chat_available(user.telegram_id)

    assert (await handler(request)).status == 200
    task = await database.get_task_by_id(task_id)
    assert task.result_url == url
    assert task.status == "completed"
    assert json.loads(task.request_data)["delivery_status"] == "delivered"

    sends = request.app["bot"].send_video.await_count
    assert (await handler(request)).status == 200
    assert request.app["bot"].send_video.await_count == sends


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["canonical", "kling", "legacy"])
async def test_success_is_stored_before_active_delivery_lease_rejects_replay(
    monkeypatch, route
):
    _user, task_id, url, handler, request = await prepare_callback(monkeypatch, route)
    assert await database.claim_task_delivery(task_id)

    assert (await handler(request)).status == 200
    task = await database.get_task_by_id(task_id)
    assert task.result_url == url
    assert task.status == "completed"
    assert json.loads(task.request_data)["delivery_status"] == "delivering"
    request.app["bot"].send_video.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["canonical", "kling", "legacy"])
async def test_failed_result_storage_requests_provider_retry(monkeypatch, route):
    _user, _task_id, _url, handler, request = await prepare_callback(monkeypatch, route)
    monkeypatch.setattr(
        database, "store_task_result_ready", AsyncMock(return_value=False)
    )

    assert (await handler(request)).status == 503
    request.app["bot"].send_video.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["canonical", "kling", "legacy"])
async def test_success_without_resolved_chat_still_completes(monkeypatch, route):
    _user, task_id, url, handler, request = await prepare_callback(monkeypatch, route)
    monkeypatch.setattr(main, "_resolve_task_telegram_id", AsyncMock(return_value=None))
    assert (await handler(request)).status == 200
    task = await database.get_task_by_id(task_id)
    assert task.status == "completed"
    assert task.result_url == url
    request.app["bot"].send_video.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["canonical", "kling", "legacy"])
async def test_callback_before_start_is_durable_and_never_replays_history(
    monkeypatch, route
):
    user, task_id, url, handler, request = await prepare_callback(monkeypatch, route)
    await database.mark_telegram_chat_unavailable(user.telegram_id)
    assert (await handler(request)).status == 200
    task = await database.get_task_by_id(task_id)
    assert (task.status, task.result_url) == ("completed", url)
    assert json.loads(task.request_data)["delivery_status"] == "unavailable"
    await database.mark_telegram_chat_available(user.telegram_id)
    assert (await handler(request)).status == 200
    request.app["bot"].send_video.assert_not_awaited()
    request.app["bot"].send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_pending_result_is_visible_and_retried_without_provider(
    monkeypatch,
):
    import importlib

    miniapp = importlib.import_module("bot.miniapp")
    user, task_id, url, handler, request = await prepare_callback(monkeypatch)
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    assert await database.store_task_result_ready(task_id, url)
    await database.mark_task_delivery_status(task_id, "pending", error="timeout")
    tasks = await miniapp._fetch_recent_tasks(user.telegram_id)
    assert tasks[0]["status"] == "completed"
    assert tasks[0]["result_url"] == url
    lookup = AsyncMock(side_effect=RuntimeError("provider expired"))
    monkeypatch.setattr(
        "bot.services.kie_webhook_verification.kie_market_service.get_task_status",
        lookup,
    )
    assert (await handler(request)).status == 200
    lookup.assert_not_awaited()
    task = await database.get_task_by_id(task_id)
    assert json.loads(task.request_data)["delivery_status"] == "delivered"


@pytest.mark.asyncio
async def test_watchdog_retries_stored_success_without_provider_or_refund(monkeypatch):
    from bot.services import task_watchdog

    _user, task_id, url, _handler, _request = await prepare_callback(monkeypatch)
    monkeypatch.setattr(task_watchdog, "DATABASE_PATH", database.DATABASE_PATH)
    await database.store_task_result_ready(task_id, url)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE generation_tasks SET created_at = datetime('now', '-3 hours') WHERE task_id = ?",
            (task_id,),
        )
        await db.commit()
    lookup = AsyncMock(side_effect=RuntimeError("provider expired"))
    refund = AsyncMock()
    recovery = AsyncMock(return_value=True)
    monkeypatch.setattr(task_watchdog, "check_task_with_provider", lookup)
    monkeypatch.setattr(task_watchdog, "force_fail_task", refund)
    assert await task_watchdog.run_watchdog_cycle(on_completed=recovery) == 1
    recovery.assert_awaited_once()
    lookup.assert_not_awaited()
    refund.assert_not_awaited()
    assert (await database.get_task_by_id(task_id)).status == "completed"


@pytest.mark.asyncio
async def test_store_rereads_metadata_after_cas_race(monkeypatch):
    _user, task_id, url, _handler, _request = await prepare_callback(monkeypatch)
    original = database.get_task_by_id
    reads = 0

    async def race(lookup):
        nonlocal reads
        task = await original(lookup)
        reads += 1
        if reads == 1:
            # A delivery lease lands after the persistence attempt's snapshot.
            await database.claim_task_delivery(task_id)
        return task

    monkeypatch.setattr(database, "get_task_by_id", race)
    assert await database.store_task_result_ready(task_id, url)
    task = await original(task_id)
    assert (task.status, task.result_url) == ("completed", url)
    assert json.loads(task.request_data)["delivery_status"] == "delivering"
    assert not await database.claim_task_delivery(task_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["canonical", "kling", "legacy"])
async def test_failed_generation_is_never_reopened_or_retried(monkeypatch, route):
    _user, task_id, _url, handler, request = await prepare_callback(monkeypatch, route)
    await database.complete_video_task(task_id, "")
    assert (await handler(request)).status == 200
    assert (await database.get_task_by_id(task_id)).status == "failed"
    request.app["bot"].send_video.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_storage_preserves_single_delivery_claim(monkeypatch):
    import asyncio

    _user, task_id, url, _handler, _request = await prepare_callback(monkeypatch)
    assert all(
        await asyncio.gather(
            *(database.store_task_result_ready(task_id, url) for _ in range(4))
        )
    )
    claims = await asyncio.gather(
        *(database.claim_task_delivery(task_id) for _ in range(4))
    )
    assert claims.count(True) == 1
    await database.mark_task_delivery_status(task_id, "delivered")
    assert await database.store_task_result_ready(task_id, url)
    assert not await database.claim_task_delivery(task_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["generic", "legacy", "sensitive"])
async def test_late_kling_failure_cannot_refund_or_erase_saved_success(
    monkeypatch, kind
):
    _user, task_id, url, _handler, request = await prepare_callback(monkeypatch)
    await database.store_task_result_ready(task_id, url)
    await database.mark_task_delivery_status(task_id, "pending", error="timeout")
    payload = {"taskId": task_id, "status": "failed"}
    if kind == "legacy":
        payload = {
            "code": 501,
            "data": {"taskId": task_id, "state": "failed", "failCode": 500},
        }
    if kind == "sensitive":
        payload["error"] = "sensitive e005"
    refund = AsyncMock()
    monkeypatch.setattr(database, "add_credits", refund)
    assert (
        await main.handle_kling_webhook(Request(payload, request.app["bot"]))
    ).status == 200
    task = await database.get_task_by_id(task_id)
    assert (task.status, task.result_url) == ("completed", url)
    assert json.loads(task.request_data)["delivery_status"] == "pending"
    refund.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_completed_success_cannot_bypass_active_lease(monkeypatch):
    _user, task_id, url, _handler, request = await prepare_callback(monkeypatch)
    await database.store_task_result_ready(task_id, url)
    assert await database.claim_task_delivery(task_id)
    payload = {"taskId": task_id, "status": "succeeded", "output": url}
    assert (
        await main.handle_kling_webhook(Request(payload, request.app["bot"]))
    ).status == 200
    request.app["bot"].send_video.assert_not_awaited()
    assert (
        json.loads((await database.get_task_by_id(task_id)).request_data)[
            "delivery_status"
        ]
        == "delivering"
    )


@pytest.mark.asyncio
async def test_poller_saved_success_recovery_does_not_query_expired_provider(
    monkeypatch,
):
    from bot.services import nexus_task_poller

    _user, task_id, url, _handler, request = await prepare_callback(monkeypatch)
    monkeypatch.setattr(nexus_task_poller, "DATABASE_PATH", database.DATABASE_PATH)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE generation_tasks SET type = 'image', model = 'banana_pro', request_data = ? WHERE task_id = ?",
            (
                json.dumps({"provider": "rendergrid", "provider_task_id": task_id}),
                task_id,
            ),
        )
        await db.commit()
    await database.store_task_result_ready(task_id, url)
    tasks = await nexus_task_poller.get_pending_provider_image_tasks()
    assert [row["task_id"] for row in tasks] == [task_id]
    lookup = AsyncMock(side_effect=RuntimeError("provider result expired"))
    from bot.services.nano_banana_pro_service import nano_banana_pro_service

    monkeypatch.setattr(nano_banana_pro_service, "get_task_status", lookup)
    monkeypatch.setattr(main, "_download_remote_bytes", AsyncMock(return_value=None))
    await main._poll_single_image_provider_task(request.app["bot"], tasks[0])
    lookup.assert_not_awaited()
    task = await database.get_task_by_id(task_id)
    assert task.status == "completed"
    assert json.loads(task.request_data)["delivery_status"] == "delivered"
    assert not await nexus_task_poller.get_pending_provider_image_tasks()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["audio", "character"])
async def test_asset_success_is_durable_before_failed_telegram_send(monkeypatch, kind):
    _user, task_id, _url, handler, request = await prepare_callback(monkeypatch)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE generation_tasks SET type = ?, model = ? WHERE task_id = ?",
            (kind, f"gemini-omni-{kind}", task_id),
        )
        await db.commit()
    payload = {
        "taskId": task_id,
        "state": "success",
        "model": f"gemini-omni-{kind}",
        "audioId" if kind == "audio" else "characterId": "durable-asset-id",
    }
    monkeypatch.setattr(
        "bot.services.kie_webhook_verification.kie_market_service.get_task_status",
        AsyncMock(return_value=payload),
    )
    request.app["bot"].send_message.side_effect = TimeoutError("Telegram unavailable")
    await handler(request)
    task = await database.get_task_by_id(task_id)
    assert (task.status, task.result_url) == ("completed", "durable-asset-id")
    await database.mark_task_delivery_status(task_id, "pending")
    request.app["bot"].send_message.side_effect = None
    assert (await handler(request)).status == 200
    assert (
        json.loads((await database.get_task_by_id(task_id)).request_data)[
            "delivery_status"
        ]
        == "delivered"
    )


@pytest.mark.asyncio
async def test_final_canonical_lookup_never_retries_paid_generation_after_success(
    monkeypatch,
):
    from dataclasses import replace

    _user, task_id, url, handler, request = await prepare_callback(monkeypatch)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE generation_tasks SET type = 'image', model = 'seedream_5_pro' "
            "WHERE task_id = ?",
            (task_id,),
        )
        await db.commit()
    await database.store_task_result_ready(task_id, url)
    await database.mark_task_delivery_status(task_id, "pending", error="timeout")
    original_lookup = database.get_task_by_id
    completed = await original_lookup(task_id)
    processing = replace(
        completed, status="processing", result_url=None, request_data="{}"
    )
    # The verifier's two reads precede a concurrent success commit; the handler
    # receives the completed row on its own final lookup.
    lookup = AsyncMock(side_effect=[processing, processing, completed])
    monkeypatch.setattr(database, "get_task_by_id", lookup)
    monkeypatch.setattr(
        "bot.services.kie_webhook_verification.kie_market_service.get_task_status",
        AsyncMock(
            return_value={
                "taskId": task_id,
                "state": "failed",
                "failCode": 500,
                "failMsg": "timed out",
                "model": "seedream/5-pro-image-to-image",
            }
        ),
    )
    refund = AsyncMock()
    monkeypatch.setattr(database, "add_credits", refund)
    retry = AsyncMock(return_value="unexpected-paid-retry")
    monkeypatch.setattr(main, "_retry_transient_kie_image_failure", retry)

    assert (await handler(request)).status == 200
    assert lookup.await_count == 3
    retry.assert_not_awaited()
    refund.assert_not_awaited()
    request.app["bot"].send_message.assert_not_awaited()
    task = await original_lookup(task_id)
    assert (task.status, task.result_url) == ("completed", url)
    assert json.loads(task.request_data)["delivery_status"] == "pending"
