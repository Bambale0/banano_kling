import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web

from bot.rendergrid_admin_api import setup_rendergrid_admin_routes
from bot.services.rendergrid_service import (
    MIN_CREATION_POLL_INTERVAL_SECONDS,
    RenderGridClient,
)


def test_rendergrid_client_builds_server_side_auth_and_idempotency_headers():
    client = RenderGridClient(api_key="rg_live_test")

    headers = client._headers(idempotency_key="request-123")

    assert headers["Authorization"] == "Bearer rg_live_test"
    assert headers["Idempotency-Key"] == "request-123"
    assert headers["Content-Type"] == "application/json"


def test_rendergrid_generate_requires_model_and_prompt_before_network_call():
    client = RenderGridClient(api_key="rg_live_test")

    with pytest.raises(ValueError, match="model"):
        asyncio.run(client.generate_image({"prompt": "hello"}))

    with pytest.raises(ValueError, match="prompt"):
        asyncio.run(client.generate_image({"model": "nano-banana-2"}))


def test_rendergrid_wait_never_polls_faster_than_documented_minimum():
    client = RenderGridClient(api_key="rg_live_test")
    responses = iter(
        [
            {"id": "creation-1", "status": "queued"},
            {
                "id": "creation-1",
                "status": "completed",
                "result_urls": ["https://cdn.example/result.jpg"],
            },
        ]
    )
    client.get_creation = AsyncMock(
        side_effect=lambda _creation_id: next(responses)
    )

    async def run_wait():
        sleep_mock = AsyncMock()
        with patch(
            "bot.services.rendergrid_service.asyncio.sleep",
            new=sleep_mock,
        ):
            result = await client.wait_for_creation(
                "creation-1",
                timeout_seconds=60,
                poll_interval_seconds=0.1,
            )
            return result, sleep_mock

    result, sleep_mock = asyncio.run(run_wait())

    assert result["status"] == "completed"
    sleep_mock.assert_awaited_once_with(MIN_CREATION_POLL_INTERVAL_SECONDS)


def test_rendergrid_admin_routes_are_explicit_and_use_miniapp_api_prefix():
    app = web.Application()
    setup_rendergrid_admin_routes(app)

    paths = {resource.canonical for resource in app.router.resources()}

    root = "/mini-app/api/admin/rendergrid"
    assert f"{root}/health" in paths
    assert f"{root}/models" in paths
    assert f"{root}/balance" in paths
    assert f"{root}/images/generate" in paths
    assert f"{root}/creations/{{creation_id}}" in paths
    assert not any("{tail" in path for path in paths)


def test_rendergrid_test_button_and_screen_are_admin_gated():
    root = Path(__file__).resolve().parents[1]
    nav = (root / "frontend/miniapp-v0/components/tab-nav.tsx").read_text(
        encoding="utf-8"
    )
    content = (
        root / "frontend/miniapp-v0/components/tab-content.tsx"
    ).read_text(encoding="utf-8")
    backend_api = (root / "bot/rendergrid_admin_api.py").read_text(
        encoding="utf-8"
    )
    frontend_api = (
        root / "frontend/miniapp-v0/lib/rendergrid-api.ts"
    ).read_text(encoding="utf-8")

    assert "state.user?.isAdmin ? [...tabs, adminTestTab] : tabs" in nav
    assert "activeTab === 8 && !state.user?.isAdmin" in content
    assert "config.is_admin(telegram_id)" in backend_api
    assert "X-Telegram-Init-Data" in backend_api
    assert "getApiBasePath()" in frontend_api
    assert "/admin/rendergrid" in frontend_api
