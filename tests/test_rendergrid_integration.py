import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

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


def test_rendergrid_creation_id_is_encoded_as_single_path_segment():
    client = RenderGridClient(api_key="rg_live_test")
    client._request = AsyncMock(return_value={"id": "creation-1", "status": "queued"})

    result = asyncio.run(client.get_creation("../status?x=1"))

    assert result["status"] == "queued"
    client._request.assert_awaited_once_with(
        "GET",
        "/creations/..%2Fstatus%3Fx%3D1",
    )


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


def test_rendergrid_test_is_telegram_admin_only_and_wired_before_legacy_admin():
    root = Path(__file__).resolve().parents[1]
    handler = (root / "bot/handlers/rendergrid_test_compat.py").read_text(
        encoding="utf-8"
    )
    handlers_init = (root / "bot/handlers/__init__.py").read_text(
        encoding="utf-8"
    )

    assert 'text="🧪 RenderGrid TEST"' in handler
    assert 'callback_data="admin_rendergrid_test"' in handler
    assert "config.is_admin(user_id)" in handler
    assert 'callback.answer("⛔ Нет доступа"' in handler
    assert "rendergrid_client.get_balance()" in handler
    assert "rendergrid_client.list_models()" in handler
    assert "rendergrid_client.generate_image(payload)" in handler
    assert "rendergrid_client.get_creation(creation_id)" in handler
    assert "install_rendergrid_test_compat(admin_module)" in handlers_init
    assert "admin_router.include_router(rendergrid_test_router)" in handlers_init
    assert handlers_init.index("admin_router.include_router(rendergrid_test_router)") < handlers_init.index(
        "admin_router.include_router(admin_module.router)"
    )


def test_rendergrid_test_branch_does_not_depend_on_miniapp_proxy():
    root = Path(__file__).resolve().parents[1]
    handler = (root / "bot/handlers/rendergrid_test_compat.py").read_text(
        encoding="utf-8"
    )
    feed_routes = (root / "bot/feed_reference_media.py").read_text(
        encoding="utf-8"
    )

    assert "miniapp" not in handler.lower()
    assert "rendergrid" not in feed_routes.lower()
    assert not (root / "bot/rendergrid_admin_api.py").exists()
    assert not (root / "frontend/miniapp-v0/lib/rendergrid-api.ts").exists()
    assert not (
        root / "frontend/miniapp-v0/components/tabs/rendergrid-test-tab.tsx"
    ).exists()
