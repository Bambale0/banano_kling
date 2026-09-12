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
