import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from bot.services.rendergrid_service import (
    MIN_CREATION_POLL_INTERVAL_SECONDS,
    REFERENCE_IDENTITY_INSTRUCTION,
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


def test_rendergrid_reference_generation_keeps_reference_and_locks_identity():
    client = RenderGridClient(api_key="rg_live_test")
    client._request = AsyncMock(return_value={"id": "creation-ref", "status": "queued"})
    reference_url = "https://tanyapi.chillcreative.ru/uploads/refs/image/admin/ref.png"

    result = asyncio.run(
        client.generate_image(
            {
                "model": "nano-banana-2",
                "prompt": "Put the same woman in a red evening dress",
                "aspect_ratio": "1:1",
                "reference_images": [reference_url],
            },
            idempotency_key="ref-request",
        )
    )

    assert result["id"] == "creation-ref"
    expected_prompt = (
        f"{REFERENCE_IDENTITY_INSTRUCTION}\n\n"
        "User request:\nPut the same woman in a red evening dress"
    )
    client._request.assert_awaited_once_with(
        "POST",
        "/images/generate",
        json_body={
            "model": "nano-banana-2",
            "prompt": expected_prompt,
            "aspect_ratio": "1:1",
            "reference_images": [reference_url],
        },
        idempotency_key="ref-request",
    )


def test_rendergrid_reference_generation_rejects_non_public_reference_path():
    client = RenderGridClient(api_key="rg_live_test")
    client._request = AsyncMock(return_value={"id": "should-not-run"})

    with pytest.raises(ValueError, match="public HTTP"):
        asyncio.run(
            client.generate_image(
                {
                    "model": "nano-banana-2",
                    "prompt": "Keep the same person",
                    "reference_images": ["static/uploads/ref.png"],
                }
            )
        )

    client._request.assert_not_awaited()


def test_rendergrid_creation_id_is_encoded_as_single_path_segment():
    client = RenderGridClient(api_key="rg_live_test")
    client._request = AsyncMock(return_value={"id": "creation-1", "status": "queued"})
    result = asyncio.run(client.get_creation("../status?x=1"))
    assert result["status"] == "queued"
    client._request.assert_awaited_once_with("GET", "/creations/..%2Fstatus%3Fx%3D1")


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
    client.get_creation = AsyncMock(side_effect=lambda _creation_id: next(responses))

    async def run_wait():
        sleep_mock = AsyncMock()
        with patch("bot.services.rendergrid_service.asyncio.sleep", new=sleep_mock):
            result = await client.wait_for_creation(
                "creation-1",
                timeout_seconds=60,
                poll_interval_seconds=0.1,
            )
            return result, sleep_mock

    result, sleep_mock = asyncio.run(run_wait())
    assert result["status"] == "completed"
    sleep_mock.assert_awaited_once_with(MIN_CREATION_POLL_INTERVAL_SECONDS)


def test_rendergrid_telegram_flow_is_creator_friendly_and_admin_only():
    root = Path(__file__).resolve().parents[1]
    handler = (root / "bot/handlers/rendergrid_test_compat.py").read_text(encoding="utf-8")

    assert 'text="🧪 RenderGrid TEST"' in handler
    assert 'Command("rendergrid")' in handler
    assert "config.is_admin(user_id)" in handler
    assert 'callback.answer("⛔ Нет доступа"' in handler

    assert "waiting_reference_photo" in handler
    assert "waiting_prompt" in handler
    assert "_save_reference_image_from_message" in handler
    assert 'callback_data="rg_choose_model"' in handler
    assert 'callback_data="rg_add_photo"' in handler
    assert 'callback_data="rg_set_prompt"' in handler
    assert 'callback_data="rg_generate"' in handler
    assert "rendergrid_client.list_models()" in handler
    assert 'payload["reference_images"] = [reference_url]' in handler
    assert "rendergrid_client.wait_for_creation" in handler
    assert "answer_photo(" in handler

    assert "waiting_generation_payload" not in handler
    assert "json.loads(" not in handler
    assert "Creation ID" not in handler
    assert "сыр" not in handler.lower()


def test_rendergrid_admin_keyboard_is_installed_after_trends_wrapper():
    root = Path(__file__).resolve().parents[1]
    handlers_init = (root / "bot/handlers/__init__.py").read_text(encoding="utf-8")
    handler = (root / "bot/handlers/rendergrid_test_compat.py").read_text(encoding="utf-8")

    assert handlers_init.count("install_rendergrid_test_compat(admin_module)") == 1
    assert handlers_init.index(
        "install_trends_compat(common_module, generation_module, admin_module)"
    ) < handlers_init.index("install_rendergrid_test_compat(admin_module)")
    assert "admin_router.include_router(rendergrid_test_router)" in handlers_init
    assert handlers_init.index("admin_router.include_router(rendergrid_test_router)") < handlers_init.index(
        "admin_router.include_router(admin_module.router)"
    )
    assert 'button.callback_data == "admin_rendergrid_test"' in handler
    assert "router.startup.register(_patch_on_startup)" in handler


def test_rendergrid_test_branch_does_not_depend_on_miniapp_proxy():
    root = Path(__file__).resolve().parents[1]
    handler = (root / "bot/handlers/rendergrid_test_compat.py").read_text(encoding="utf-8")
    feed_routes = (root / "bot/feed_reference_media.py").read_text(encoding="utf-8")

    assert "miniapp" not in handler.lower()
    assert "rendergrid" not in feed_routes.lower()
    assert not (root / "bot/rendergrid_admin_api.py").exists()
    assert not (root / "frontend/miniapp-v0/lib/rendergrid-api.ts").exists()
    assert not (root / "frontend/miniapp-v0/components/tabs/rendergrid-test-tab.tsx").exists()
