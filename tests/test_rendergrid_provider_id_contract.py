from __future__ import annotations

import asyncio
import importlib
from unittest.mock import AsyncMock

import pytest

from bot.handlers.rendergrid_provider_id_compat import (
    install_rendergrid_provider_id_compat,
)
from bot.services.rendergrid_nano_banana_provider import RenderGridNanoBananaProvider

miniapp_module = importlib.import_module("bot.miniapp")
install_rendergrid_provider_id_compat()


class _FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return kwargs


def _provider() -> RenderGridNanoBananaProvider:
    return RenderGridNanoBananaProvider(
        api_key="rg_live_test",
        model_name="nano-banana-pro",
        base_url="https://api.rendergrid.test/api/public/v1",
        request_timeout_seconds=5,
        generation_timeout_seconds=30,
        poll_interval_seconds=0.1,
        max_retries=0,
    )


def test_rendergrid_creation_id_is_exposed_as_common_provider_task_id() -> None:
    provider = _provider()
    provider.client.generate_image = AsyncMock(
        return_value={"id": "rg-creation-123", "status": "queued"}
    )
    provider.client.wait_for_creation = AsyncMock(
        return_value={
            "id": "rg-creation-123",
            "status": "completed",
            "result_urls": ["https://cdn.example/result.png"],
        }
    )
    provider._download_result = AsyncMock(return_value=(b"png-bytes", "image/png"))

    result = asyncio.run(
        provider.generate_image("Create a portrait", "1:1", "2K", [], "png")
    )
    asyncio.run(provider.close())

    assert result is not None
    assert result["creation_id"] == "rg-creation-123"
    assert result["provider_task_id"] == "rg-creation-123"


def test_rendergrid_terminal_failure_keeps_creation_id_for_support() -> None:
    provider = _provider()
    provider.client.generate_image = AsyncMock(
        return_value={
            "id": "rg-creation-failed-123",
            "status": "failed",
            "error": "Provider could not complete this image",
        }
    )

    result = asyncio.run(
        provider.generate_image("Create a portrait", "1:1", "2K", [], "png")
    )
    asyncio.run(provider.close())

    assert result is not None
    assert result["error"] == "Provider could not complete this image"
    assert result["creation_id"] == "rg-creation-failed-123"
    assert result["provider_task_id"] == "rg-creation-failed-123"


@pytest.mark.asyncio
async def test_done_launch_shows_local_and_rendergrid_provider_ids_separately() -> None:
    bot = _FakeBot()

    await miniapp_module._notify_miniapp_image_task_queued(
        {"bot": bot},
        123,
        {
            "status": "done",
            "task_id": "img_local_123",
            "provider_task_id": "rg-creation-123",
        },
        img_service="banana_pro",
        img_ratio="9:16",
        unit_cost=2.5,
    )

    assert len(bot.messages) == 1
    text = bot.messages[0]["text"]
    assert "ID задачи: <code>img_local_123</code>" in text
    assert "ID провайдера: <code>rg-creation-123</code>" in text


@pytest.mark.asyncio
async def test_rendergrid_acceptance_is_persisted_before_background_polling(monkeypatch) -> None:
    import json

    from bot import database
    from bot.handlers import generation

    user = await database.get_or_create_user(505050)
    provider_task_id = "rg-creation-persisted"
    generate_image = AsyncMock(
        return_value={
            "task_id": provider_task_id,
            "provider_task_id": provider_task_id,
            "provider": "rendergrid",
            "provider_model": "nano-banana-pro",
            "provider_status": "queued",
        }
    )
    monkeypatch.setattr(
        generation.nano_banana_pro_service,
        "generate_image",
        generate_image,
    )
    created_ids: list[str] = []

    async def on_task_created(local_task_id: str) -> None:
        created_ids.append(local_task_id)

    result = await generation._start_image_generation_task(
        user=user,
        telegram_id=505050,
        img_service="banana_pro",
        prompt="Create a studio portrait",
        img_ratio="1:1",
        reference_images=[],
        unit_cost=1.5,
        img_quality="2K",
        on_task_created=on_task_created,
    )

    assert result["status"] == "queued"
    assert result["task_id"] == provider_task_id
    assert len(created_ids) == 1
    assert created_ids[0].startswith("img_")

    task = await database.get_task_by_id(provider_task_id)
    assert task is not None
    request_data = json.loads(task.request_data or "{}")
    assert request_data["provider"] == "rendergrid"
    assert request_data["provider_model"] == "nano-banana-pro"
    assert request_data["provider_task_id"] == provider_task_id
    assert provider_task_id in request_data["task_id_aliases"]
    assert created_ids[0] in request_data["task_id_aliases"]


@pytest.mark.asyncio
async def test_pending_provider_scanner_recovers_rendergrid_after_restart(monkeypatch) -> None:
    from bot import database
    from bot.services import nexus_task_poller

    monkeypatch.setattr(nexus_task_poller, "DATABASE_PATH", database.DATABASE_PATH)
    user_rg = await database.get_or_create_user(101)
    user_nexus = await database.get_or_create_user(202)
    user_kie = await database.get_or_create_user(303)

    for user_id, telegram_id, task_id, provider, provider_model in (
        (user_rg.id, 101, "rg-task", "rendergrid", "nano-banana-pro"),
        (user_nexus.id, 202, "nexus-task", "nexus", "nano-banana-2"),
        (user_kie.id, 303, "kie-task", "kie", "nano-banana-pro"),
    ):
        await database.add_generation_task(
            user_id,
            telegram_id,
            task_id,
            "image",
            "banana_pro",
            model="banana_pro",
            request_data={
                "provider": provider,
                "provider_model": provider_model,
                "provider_task_id": task_id,
            },
        )

    tasks = await nexus_task_poller.get_pending_provider_image_tasks(limit=10)

    assert {task["task_id"] for task in tasks} == {"rg-task", "nexus-task"}
    assert {task["request_data"]["provider"] for task in tasks} == {
        "rendergrid",
        "nexus",
    }


@pytest.mark.asyncio
async def test_pending_provider_scanner_does_not_starve_rendergrid_behind_unmanaged_tasks(
    monkeypatch,
) -> None:
    from bot import database
    from bot import db as db_backend
    from bot.services import nexus_task_poller

    monkeypatch.setattr(nexus_task_poller, "DATABASE_PATH", database.DATABASE_PATH)

    for index in range(6):
        user = await database.get_or_create_user(4000 + index)
        task_id = f"kie-crowd-{index}"
        await database.add_generation_task(
            user.id,
            4000 + index,
            task_id,
            "image",
            "seedream_5_pro",
            model="seedream_5_pro",
            request_data={
                "provider": "kie",
                "provider_model": "seedream/5-pro-image-to-image",
                "provider_task_id": task_id,
            },
        )

    rendergrid_user = await database.get_or_create_user(4999)
    await database.add_generation_task(
        rendergrid_user.id,
        4999,
        "rg-not-starved",
        "image",
        "banana_2",
        model="banana_2",
        request_data={
            "provider": "rendergrid",
            "provider_model": "nano-banana-2",
            "provider_task_id": "rg-not-starved",
        },
    )

    async with db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE generation_tasks SET updated_at = '2020-01-01 00:00:00' "
            "WHERE task_id LIKE 'kie-crowd-%'"
        )
        await db.execute(
            "UPDATE generation_tasks SET updated_at = '2030-01-01 00:00:00' "
            "WHERE task_id = 'rg-not-starved'"
        )
        await db.commit()

    tasks = await nexus_task_poller.get_pending_provider_image_tasks(limit=1)

    assert [task["task_id"] for task in tasks] == ["rg-not-starved"]


@pytest.mark.asyncio
async def test_image_provider_poller_delivers_completed_rendergrid_task(monkeypatch) -> None:
    from bot import database
    from bot import main as main_module
    from bot.services.nano_banana_pro_service import nano_banana_pro_service

    user = await database.get_or_create_user(606060)
    provider_task_id = "rg-poller-completed"
    await database.add_generation_task(
        user.id,
        606060,
        provider_task_id,
        "image",
        "banana_pro",
        model="banana_pro",
        request_data={
            "provider": "rendergrid",
            "provider_model": "nano-banana-pro",
            "provider_task_id": provider_task_id,
        },
    )

    provider = _provider()
    provider.get_completed_result = AsyncMock(
        return_value={"result_url": "https://cdn.example/rendergrid-done.png"}
    )
    monkeypatch.setattr(nano_banana_pro_service, "primary_provider", provider)
    monkeypatch.setattr(nano_banana_pro_service, "fallback_provider", None)
    monkeypatch.setattr(
        nano_banana_pro_service,
        "get_task_status",
        AsyncMock(
            return_value={
                "id": provider_task_id,
                "status": "completed",
                "result_urls": ["https://cdn.example/rendergrid-done.png"],
            }
        ),
    )
    deliver = AsyncMock(return_value=True)
    monkeypatch.setattr(main_module, "_send_polled_nexus_image_result", deliver)

    await main_module._poll_single_image_provider_task(
        object(),
        {
            "task_id": provider_task_id,
            "request_data": {
                "provider": "rendergrid",
                "provider_model": "nano-banana-pro",
                "provider_task_id": provider_task_id,
            },
        },
    )
    await provider.close()

    provider.get_completed_result.assert_awaited_once()
    deliver.assert_awaited_once()
    assert deliver.await_args.args[2] == "https://cdn.example/rendergrid-done.png"
    assert deliver.await_args.kwargs["provider_task_id"] == provider_task_id


@pytest.mark.asyncio
async def test_image_provider_poller_refunds_and_notifies_failed_rendergrid_task(
    monkeypatch,
) -> None:
    from bot import database
    from bot import main as main_module
    from bot.services import task_watchdog
    from bot.services.nano_banana_2_service import nano_banana_2_service

    monkeypatch.setattr(task_watchdog, "DATABASE_PATH", database.DATABASE_PATH)

    telegram_id = 626262
    user = await database.get_or_create_user(telegram_id)
    provider_task_id = "rg-poller-failed"
    await database.add_generation_task(
        user.id,
        telegram_id,
        provider_task_id,
        "image",
        "banana_2",
        model="banana_2",
        cost=1.5,
        request_data={
            "provider": "rendergrid",
            "provider_model": "nano-banana-2",
            "provider_task_id": provider_task_id,
            "task_id_aliases": ["img_rendergrid_failed", provider_task_id],
        },
    )
    balance_before = float(await database.get_user_credits(telegram_id))
    monkeypatch.setattr(
        nano_banana_2_service,
        "get_task_status",
        AsyncMock(
            return_value={
                "id": provider_task_id,
                "status": "failed",
                "error": "Generation failed.",
            }
        ),
    )
    bot = AsyncMock()

    await main_module._poll_single_image_provider_task(
        bot,
        {
            "task_id": provider_task_id,
            "request_data": {
                "provider": "rendergrid",
                "provider_model": "nano-banana-2",
                "provider_task_id": provider_task_id,
            },
        },
    )

    task = await database.get_task_by_id(provider_task_id)
    assert task is not None
    assert task.status == "failed"
    balance_after = float(await database.get_user_credits(telegram_id))
    assert balance_after - balance_before == pytest.approx(1.5)
    bot.send_message.assert_awaited_once()
    text = bot.send_message.await_args.kwargs["text"]
    assert "img_rendergrid_failed" in text
    assert "Бананы за эту попытку уже возвращены." in text


@pytest.mark.asyncio
async def test_polled_failure_does_not_double_refund_after_watchdog_wins(
    monkeypatch,
) -> None:
    from bot import database
    from bot import main as main_module
    from bot.services import task_watchdog

    monkeypatch.setattr(task_watchdog, "DATABASE_PATH", database.DATABASE_PATH)

    telegram_id = 616161
    user = await database.get_or_create_user(telegram_id)
    provider_task_id = "rg-refund-race"
    await database.add_generation_task(
        user.id,
        telegram_id,
        provider_task_id,
        "image",
        "banana_2",
        model="banana_2",
        cost=1.5,
        request_data={
            "provider": "rendergrid",
            "provider_model": "nano-banana-2",
            "provider_task_id": provider_task_id,
        },
    )
    stale_task = await database.get_task_by_id(provider_task_id)
    assert stale_task is not None
    balance_before = float(await database.get_user_credits(telegram_id))

    assert await task_watchdog.force_fail_task(stale_task.id, user.id, 1.5) is True
    balance_after_watchdog = float(await database.get_user_credits(telegram_id))
    assert balance_after_watchdog - balance_before == pytest.approx(1.5)

    bot = AsyncMock()
    delivered = await main_module._fail_polled_nexus_image_task(
        bot,
        stale_task,
        provider_task_id=provider_task_id,
        service_name="Nano Banana 2",
        reason="RenderGrid generation failed",
    )

    balance_after_late_poller = float(await database.get_user_credits(telegram_id))
    assert balance_after_late_poller == pytest.approx(balance_after_watchdog)
    assert delivered is False
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_image_provider_poller_processes_batch_concurrently(monkeypatch) -> None:
    from bot import main as main_module
    from bot.services import nexus_task_poller

    tasks = [
        {"task_id": f"rg-concurrent-{index}", "request_data": {"provider": "rendergrid"}}
        for index in range(4)
    ]
    monkeypatch.setattr(nexus_task_poller, "NEXUS_POLL_BATCH_SIZE", len(tasks))
    monkeypatch.setattr(nexus_task_poller, "NEXUS_POLL_CONCURRENCY", len(tasks))
    monkeypatch.setattr(nexus_task_poller, "NEXUS_POLL_INTERVAL_SECONDS", 3600)
    monkeypatch.setattr(
        nexus_task_poller,
        "get_pending_provider_image_tasks",
        AsyncMock(return_value=tasks),
    )

    started: list[str] = []
    all_started = asyncio.Event()
    release = asyncio.Event()

    async def fake_poll(_bot, task_row):
        started.append(task_row["task_id"])
        if len(started) == len(tasks):
            all_started.set()
        await release.wait()

    monkeypatch.setattr(main_module, "_poll_single_image_provider_task", fake_poll)

    real_sleep = asyncio.sleep

    async def controlled_sleep(delay):
        if delay == 5:
            return
        await real_sleep(delay)

    monkeypatch.setattr(main_module.asyncio, "sleep", controlled_sleep)

    poller = asyncio.create_task(main_module._image_provider_poller_loop(object()))
    try:
        await asyncio.wait_for(all_started.wait(), timeout=1)
        assert set(started) == {task["task_id"] for task in tasks}
    finally:
        release.set()
        poller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await poller


@pytest.mark.asyncio
async def test_polled_result_chat_unavailable_is_terminal_without_warning(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import bot.keyboards as keyboard_module
    from bot import database
    from bot import main as main_module

    task = SimpleNamespace(
        task_id="provider-unavailable",
        id=991,
        user_id=51,
        telegram_id=123456,
        model="banana_2",
        type="image",
        cost=1.5,
        aspect_ratio="1:1",
        request_data="{}",
    )
    monkeypatch.setattr(
        main_module,
        "_resolve_task_telegram_id",
        AsyncMock(return_value=123456),
    )
    monkeypatch.setattr(
        main_module,
        "_persist_result_url_if_needed",
        AsyncMock(return_value="https://assets.example/result.png"),
    )
    monkeypatch.setattr(main_module, "_extract_reference_image_urls", lambda _task: [])
    monkeypatch.setattr(
        main_module, "_download_remote_bytes", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        main_module, "_send_original_file", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        main_module,
        "_send_plain_result_link",
        AsyncMock(side_effect=RuntimeError("Bad Request: chat not found")),
    )
    monkeypatch.setattr(
        keyboard_module, "get_image_result_keyboard", lambda *_a, **_kw: None
    )
    monkeypatch.setattr(database, "store_task_result_ready", AsyncMock(return_value=True))
    monkeypatch.setattr(database, "claim_task_delivery", AsyncMock(return_value=True))
    complete = AsyncMock(return_value=True)
    mark = AsyncMock(return_value=True)
    monkeypatch.setattr(database, "complete_video_task", complete)
    monkeypatch.setattr(database, "mark_task_delivery_status", mark)

    bot = AsyncMock()
    bot.send_photo.side_effect = RuntimeError("Bad Request: chat not found")
    warnings = []
    monkeypatch.setattr(
        main_module.logger, "warning", lambda *args: warnings.append(args)
    )

    handled = await main_module._send_polled_nexus_image_result(
        bot,
        task,
        "https://provider.example/result.png",
        provider_task_id="provider-unavailable",
    )

    assert handled is True
    complete.assert_awaited_once()
    mark.assert_awaited_once_with(
        "provider-unavailable",
        "unavailable",
        error="chat_not_found",
    )
    assert warnings == []


@pytest.mark.asyncio
async def test_failed_task_chat_unavailable_does_not_emit_exception(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot import main as main_module
    from bot.services import task_watchdog

    task = SimpleNamespace(
        task_id="provider-failed-unavailable",
        id=992,
        user_id=52,
        telegram_id=123456,
        model="banana_2",
        type="image",
        cost=1.5,
        request_data="{}",
    )
    monkeypatch.setattr(task_watchdog, "force_fail_task", AsyncMock(return_value=True))
    monkeypatch.setattr(
        main_module,
        "_resolve_task_telegram_id",
        AsyncMock(return_value=123456),
    )
    infos = []
    exceptions = []
    monkeypatch.setattr(main_module.logger, "info", lambda *args: infos.append(args))
    monkeypatch.setattr(
        main_module.logger, "exception", lambda *args: exceptions.append(args)
    )

    bot = AsyncMock()
    bot.send_message.side_effect = RuntimeError("Bad Request: chat not found")

    delivered = await main_module._fail_polled_nexus_image_task(
        bot,
        task,
        provider_task_id="provider-failed-unavailable",
        reason="provider failed",
    )

    assert delivered is False
    assert any("chat_not_found" in str(item) for item in infos)
    assert exceptions == []
