from __future__ import annotations

import asyncio
import importlib
from unittest.mock import AsyncMock

import pytest

from bot.services.rendergrid_nano_banana_provider import RenderGridNanoBananaProvider

miniapp_module = importlib.import_module("bot.miniapp")


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
