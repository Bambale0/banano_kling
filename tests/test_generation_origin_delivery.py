"""A linked legacy Telegram identity must not choose a VK task's transport."""
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database, miniapp


@pytest.fixture
def main_module(monkeypatch):
    if sys.platform == "win32":
        # The unrelated Linux memory diagnostic is imported by bot.main.
        monkeypatch.setitem(sys.modules, "resource", SimpleNamespace(
            RUSAGE_SELF=0, getrusage=lambda _who: SimpleNamespace(ru_maxrss=0),
        ))
    from bot import main
    from bot.handlers import generation
    from bot.handlers.generation_started_ux_compat import install_generation_started_ux
    from bot.services import task_watchdog
    install_generation_started_ux(generation)
    monkeypatch.setattr(task_watchdog, "DATABASE_PATH", database.DATABASE_PATH)
    return main


@pytest.mark.asyncio
async def test_completed_vk_task_cannot_acquire_a_telegram_delivery_lease():
    user = await database.get_or_create_user(880021)
    await database.add_generation_task(
        user.id, 880021, "vk-origin-image", "image", "banana_pro",
        model="banana_pro", request_data={"origin_platform": "vk"},
    )
    assert await database.store_task_result_ready(
        "vk-origin-image", "https://example.test/result.png",
    )

    assert not await database.claim_task_delivery("vk-origin-image")
    task = await database.get_task_by_id("vk-origin-image")
    assert task.status == "completed"
    assert task.result_url == "https://example.test/result.png"
    metadata = json.loads(task.request_data)
    assert metadata["origin_platform"] == "vk"
    assert metadata["delivery_status"] == "available_in_app"
    assert metadata.get("delivery_attempts", 0) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "done"])
@pytest.mark.parametrize("origin_platform", ["telegram", "vk"])
async def test_image_http_uses_verified_origin_for_notifications(monkeypatch, main_module, status, origin_platform):
    user = SimpleNamespace(id=7, credits=10)
    bot = SimpleNamespace(send_message=AsyncMock(), send_document=AsyncMock(), get_chat=AsyncMock())
    body = {"init_data": "signed-vk-session", "prompt": "Synthetic portrait",
            "img_service": "banana_pro", "img_ratio": "9:16", "img_quality": "2K",
            "platform": "telegram" if origin_platform == "vk" else "vk"}

    class Request:
        def __init__(self):
            self.app = {"bot": bot}

        async def json(self):
            return body

    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(880021, {
        "user": user, "platform": origin_platform, "platform_external_id": 2001,
    })))
    monkeypatch.setattr(miniapp, "_resolve_actor_image_unit_cost", AsyncMock(return_value=1))
    monkeypatch.setattr(miniapp, "check_can_afford", AsyncMock(return_value=True))
    monkeypatch.setattr(miniapp, "deduct_credits", AsyncMock(return_value=True))
    monkeypatch.setattr(miniapp, "get_or_create_user", AsyncMock(return_value=user))
    monkeypatch.setattr(miniapp, "can_attempt_telegram_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(database, "can_attempt_telegram_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(miniapp, "mark_telegram_chat_available", AsyncMock())
    launch = AsyncMock(return_value={"status": status, "task_id": "vk-image-http",
                                    "saved_url": "https://example.test/result.png"})
    monkeypatch.setattr(miniapp, "_start_image_generation_task_lazy", launch)

    response = await miniapp.miniapp_generate_image(Request())
    assert response.status == 200, response.text
    assert launch.await_args.kwargs["origin_platform"] == origin_platform
    assert bot.send_message.await_count == (1 if origin_platform == "telegram" else 0)
    assert bot.send_document.await_count == (1 if origin_platform == "telegram" and status == "done" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [{}, {"origin_platform": "telegram"}])
async def test_legacy_and_telegram_tasks_keep_their_delivery_lease(metadata):
    user = await database.get_or_create_user(880021)
    await database.add_generation_task(
        user.id, 880021, "telegram-origin-image", "image", "banana_pro",
        model="banana_pro", request_data=metadata,
    )
    assert await database.store_task_result_ready("telegram-origin-image", "https://example.test/result.png")
    assert await database.claim_task_delivery("telegram-origin-image")


@pytest.mark.asyncio
@pytest.mark.parametrize("handler_name", ["handle_seedream_webhook", "handle_novita_webhook"])
async def test_legacy_image_callbacks_keep_vk_results_in_app(monkeypatch, main_module, handler_name):
    user = await database.get_or_create_user(880021)
    await database.add_generation_task(
        user.id, 880021, "vk-legacy-callback", "image", "no_preset",
        model="seedream_edit", request_data={"origin_platform": "vk"},
    )
    bot = SimpleNamespace(send_document=AsyncMock(), send_message=AsyncMock(), get_chat=AsyncMock())
    monkeypatch.setattr(main_module, "_persist_result_url_if_needed", AsyncMock(return_value="https://example.test/result.png"))
    app = web.Application()
    app["bot"] = bot
    app.router.add_post('/callback', getattr(main_module, handler_name))
    payload = {"event_type": "ASYNC_TASK_RESULT", "payload": {
        "task": {"task_id": "vk-legacy-callback", "status": "TASK_STATUS_SUCCEED", "task_type": "TXT_TO_IMG"},
        "images": [{"image_url": "https://example.test/result.png"}],
    }}
    async with TestClient(TestServer(app)) as client:
        response = await client.post('/callback', json=payload)
        assert response.status == 200
    task = await database.get_task_by_id("vk-legacy-callback")
    assert task.status == "completed"
    assert task.result_url == "https://example.test/result.png"
    assert json.loads(task.request_data)["delivery_status"] == "available_in_app"
    bot.send_document.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    bot.get_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_polled_vk_image_finishes_without_sending_to_linked_telegram(monkeypatch, main_module):
    main = main_module
    user = await database.get_or_create_user(880021)
    await database.add_generation_task(
        user.id, 880021, "vk-polled-image", "image", "banana_pro",
        model="banana_pro", request_data={"origin_platform": "vk"},
    )
    task = await database.get_task_by_id("vk-polled-image")
    bot = SimpleNamespace(send_photo=AsyncMock(), send_document=AsyncMock(),
                          send_message=AsyncMock(), get_chat=AsyncMock())
    monkeypatch.setattr(main, "_persist_result_url_if_needed", AsyncMock(
        return_value="https://example.test/result.png"))

    assert await main._send_polled_nexus_image_result(bot, task, "https://example.test/result.png")
    completed = await database.get_task_by_id("vk-polled-image")
    assert completed.status == "completed"
    assert completed.result_url == "https://example.test/result.png"
    assert json.loads(completed.request_data)["delivery_status"] == "available_in_app"
    bot.send_photo.assert_not_awaited()
    bot.send_document.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    bot.get_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_id_replacement_retains_the_verified_vk_origin(monkeypatch, main_module):
    from bot.handlers import generation

    user = await database.get_or_create_user(880021)
    monkeypatch.setattr(generation.nano_banana_pro_service, "generate_image", AsyncMock(return_value={
        "task_id": "vk-rendergrid-provider", "provider_task_id": "vk-rendergrid-provider",
        "provider": "rendergrid", "provider_model": "nano-banana-pro", "provider_status": "queued",
    }))
    result = await generation._start_image_generation_task(
        user=user, telegram_id=880021, img_service="banana_pro", prompt="Synthetic VK portrait",
        img_ratio="9:16", reference_images=[], unit_cost=0, img_quality="2K", origin_platform="vk",
    )
    assert result["status"] == "queued"
    task = await database.get_task_by_id(result["task_id"])
    metadata = json.loads(task.request_data)
    assert metadata["origin_platform"] == "vk"
    assert metadata["provider_task_id"] == "vk-rendergrid-provider"


@pytest.mark.asyncio
async def test_in_app_completion_replay_preserves_the_first_terminal_result():
    user = await database.get_or_create_user(880021)
    await database.add_generation_task(
        user.id, 880021, "vk-replayed-image", "image", "banana_pro",
        model="banana_pro", request_data={"origin_platform": "vk"},
    )
    assert await database.complete_task_in_app("vk-replayed-image", "https://example.test/original.png")
    assert await database.complete_task_in_app("vk-replayed-image", "https://example.test/changed.png")
    task = await database.get_task_by_id("vk-replayed-image")
    assert task.result_url == "https://example.test/original.png"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["success", "fail"])
async def test_vk_image_callback_keeps_settlement_without_telegram(monkeypatch, main_module, state):
    from bot.services import kie_webhook_verification

    user = await database.get_or_create_user(880021)
    starting_balance = float(user.credits)
    await database.add_credits(880021, 3)
    assert await database.deduct_credits(880021, 1)
    await database.add_generation_task(
        user.id, 880021, "vk-callback-image", "image", "banana_pro",
        model="banana_pro", cost=1, request_data={"origin_platform": "vk"},
    )
    bot = SimpleNamespace(send_photo=AsyncMock(), send_document=AsyncMock(),
                          send_message=AsyncMock(), get_chat=AsyncMock())
    payload = {"code": 200, "data": {"taskId": "vk-callback-image", "state": state,
               "failCode": "422", "failMsg": "Invalid input image",
               "model": "nano-banana-pro", "resultJson": json.dumps({"resultUrls": ["https://example.test/result.png"]})}}
    monkeypatch.setattr(kie_webhook_verification, "canonical_kie_callback", AsyncMock(return_value=(payload, 200)))
    monkeypatch.setattr(main_module.config, "KIE_AI_WEBHOOK_SECRET", "synthetic-webhook-secret")
    monkeypatch.setattr(main_module, "_persist_result_url_if_needed", AsyncMock(return_value="https://example.test/result.png"))
    completed = AsyncMock(wraps=database.complete_video_task)
    monkeypatch.setattr(database, "complete_video_task", completed)
    app = web.Application()
    app["bot"] = bot
    app.router.add_post('/callback', main_module.handle_kie_ai_webhook)
    async with TestClient(TestServer(app)) as client:
        response = await client.post('/callback?secret=synthetic-webhook-secret', json=payload)
        assert response.status == 200
        repeated = await client.post('/callback?secret=synthetic-webhook-secret', json=payload)
        assert repeated.status == 200
    task = await database.get_task_by_id("vk-callback-image")
    if state == "success":
        completed.assert_awaited_once_with("vk-callback-image", "https://example.test/result.png")
        assert task.status == "completed"
        assert json.loads(task.request_data)["delivery_status"] == "available_in_app"
    else:
        completed.assert_not_awaited()
        assert task.status == "failed"
    fresh = await database.get_or_create_user(880021)
    assert float(fresh.credits) == starting_balance + (2 if state == "success" else 3)
    bot.send_photo.assert_not_awaited()
    bot.send_document.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    bot.get_chat.assert_not_awaited()
