"""Regression: Telegram linking is not authorization for VK native full shell."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.shared_accounts import gateway
from bot.shared_accounts.actor import PlatformActor
from bot.shared_accounts.api import _vk_full_app_ready


def test_vk_readiness_requires_complete_server_native_adapter(monkeypatch):
    monkeypatch.setenv("VK_FULL_APP_PARITY_ENABLED", "1")
    request = SimpleNamespace(app=web.Application())
    assert _vk_full_app_ready(request, platform="vk", telegram_linked=True) is False
    assert _vk_full_app_ready(request, platform="vk", telegram_linked=False) is False
    assert _vk_full_app_ready(request, platform="telegram", telegram_linked=True) is True


@pytest.mark.asyncio
async def test_linked_vk_cannot_fall_through_to_telegram_legacy_with_unready_adapter(monkeypatch):
    monkeypatch.setenv("VK_FULL_APP_PARITY_ENABLED", "1")
    monkeypatch.setenv("VK_NATIVE_TASKS_ENABLED", "0")
    actor = PlatformActor(
        platform="vk", external_id=2001, shared_account_id="a" * 32,
        linked_platforms=("vk", "telegram"), linked_telegram_id=1001,
    )
    resolved = AsyncMock(return_value=actor)
    monkeypatch.setattr(gateway, "resolve_platform_actor", resolved)
    legacy = AsyncMock(return_value=web.json_response({"wallet": "telegram"}))
    app = web.Application(middlewares=[gateway.vk_miniapp_gateway("/mini-app")])
    app.router.add_post("/mini-app/api/bootstrap", legacy)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/mini-app/api/bootstrap", json={"init_data": "vk_session:valid"},
        )
        assert response.status == 503
        assert (await response.json())["error"] == "VK studio integration unavailable"
    legacy.assert_not_awaited()
    resolved.assert_awaited_once_with("valid", expected_platform="vk")
