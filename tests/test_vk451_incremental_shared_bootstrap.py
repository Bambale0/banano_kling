"""#451: signed native VK can bootstrap the SAME app API without full parity."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.shared_accounts import gateway
from bot.shared_accounts.actor import PlatformActor
from bot.shared_accounts.api import (
    _vk_full_app_ready,
    _vk_legacy_linked_studio_available,
)
from bot.shared_accounts.native_bootstrap import VkNativeAppAdapter

VK = PlatformActor(
    platform="vk", external_id=2001, shared_account_id="a" * 32,
    linked_platforms=("vk",), linked_telegram_id=None,
)
LINKED_VK = PlatformActor(
    platform="vk", external_id=2001, shared_account_id="b" * 32,
    linked_platforms=("vk", "telegram"), linked_telegram_id=3001,
)


async def _client_with_native_bootstrap(
    *, actor=VK, state=None, models=None, commerce=None,
):
    from bot.shared_accounts.native_bootstrap import VkNativeBootstrapService

    state_read = AsyncMock(return_value=state or {
        "registered": True, "is_blocked": False, "balance": 22,
        "tasks": [{"task_id": 17, "task_type": "photo", "model": "nano_banana_pro", "status": "completed",
                   "cost": 2, "created_at": "2026-11-14 00:00:00",
                   "result_url": "https://example.test/vk.jpg"}],
    })
    model_read = AsyncMock(return_value=models or {
        "ok": True, "photo_models": [], "video_models": [],
    })
    commerce_read = AsyncMock(return_value=commerce or {
        "ok": True, "registered": True, "balance": 23.5,
        "payment_packages": [], "payments": [], "referrals": {},
    })
    service = VkNativeBootstrapService(
        state_reader=state_read, model_reader=model_read,
        commerce_reader=commerce_read,
    )
    adapter = VkNativeAppAdapter(bootstrap=service)
    legacy = AsyncMock(return_value=web.json_response({
        "ok": True, "source": "telegram", "credits": 999,
    }))
    app = web.Application(middlewares=[gateway.vk_miniapp_gateway()])
    app["vk_full_app_adapter"] = adapter
    app.router.add_post("/mini-app/api/bootstrap", legacy)
    auth = AsyncMock(return_value=actor)
    return TestClient(TestServer(app)), auth, legacy, state_read, model_read, commerce_read


@pytest.mark.asyncio
async def test_partial_vk_bootstrap_read_uses_native_wallet_and_same_path_without_tg(monkeypatch):
    monkeypatch.setenv("VK_NATIVE_BOOTSTRAP_ENABLED", "1")
    monkeypatch.delenv("VK_FULL_APP_PARITY_ENABLED", raising=False)
    client, auth, legacy, state, models, commerce = await _client_with_native_bootstrap()
    monkeypatch.setattr(gateway, "resolve_platform_actor", auth)
    async with client:
        payload = {"init_data": "vk_session:valid-scoped-token"}
        response = await client.post("/mini-app/api/bootstrap", json=payload)
        assert response.status == 200, await response.text()
        result = await response.json()
        assert result["credits"] == 23.5
        assert result["recent_tasks"][0]["task_id"] == "vk:17"
        assert result["telegram_chat_available"] is False
        assert result["telegram_bot_start_required"] is False
        assert "telegram_id" not in result
        legacy.assert_not_awaited()
        auth.assert_awaited_once_with("valid-scoped-token", expected_platform="vk")
        state.assert_awaited_once_with(2001)
        models.assert_awaited_once_with(2001)
        commerce.assert_awaited_once_with(2001)
        # This is a single native read domain, NOT the full 10-domain common shell.
        request = SimpleNamespace(app=client.app)
        assert _vk_full_app_ready(request, platform="vk", telegram_linked=False) is False


@pytest.mark.asyncio
async def test_native_bootstrap_feature_gate_off_rejects_vk_without_legacy_fallback(monkeypatch):
    monkeypatch.delenv("VK_NATIVE_BOOTSTRAP_ENABLED", raising=False)
    monkeypatch.delenv("VK_FULL_APP_PARITY_ENABLED", raising=False)
    client, auth, legacy, *_ = await _client_with_native_bootstrap()
    monkeypatch.setattr(gateway, "resolve_platform_actor", auth)
    async with client:
        response = await client.post("/mini-app/api/bootstrap", json={
            "init_data": "vk_session:signed",
        })
        assert response.status == 503
        legacy.assert_not_awaited()
        auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_native_bootstrap_never_hijacks_telegram_route(monkeypatch):
    monkeypatch.setenv("VK_NATIVE_BOOTSTRAP_ENABLED", "1")
    client, auth, legacy, *_ = await _client_with_native_bootstrap()
    monkeypatch.setattr(gateway, "resolve_platform_actor", auth)
    async with client:
        response = await client.post("/mini-app/api/bootstrap", json={
            "init_data": "tg-hash=authenticated",
        })
        assert response.status == 200
        assert (await response.json())["source"] == "telegram"
        legacy.assert_awaited_once()
        auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_bootstrap_enforces_actor_not_caller_claims(monkeypatch):
    monkeypatch.setenv("VK_NATIVE_BOOTSTRAP_ENABLED", "1")
    client, auth, legacy, state, *_ = await _client_with_native_bootstrap()
    monkeypatch.setattr(gateway, "resolve_platform_actor", auth)
    async with client:
        for field in ("vk_user_id", "telegram_id", "user_id", "wallet_platform", "shared_account_id"):
            response = await client.post("/mini-app/api/bootstrap", json={
                "init_data": "vk_session:valid", field: 888,
            })
            assert response.status == 400
        response = await client.post("/mini-app/api/bootstrap", json={
            "init_data": "vk_session:valid",
        })
        assert response.status == 200
        state.assert_awaited_once_with(2001)
        legacy.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_bootstrap_linked_actor_still_uses_authoritative_vk_wallet(monkeypatch):
    monkeypatch.setenv("VK_NATIVE_BOOTSTRAP_ENABLED", "1")
    client, auth, legacy, state, _models, commerce = await _client_with_native_bootstrap(actor=LINKED_VK)
    monkeypatch.setattr(gateway, "resolve_platform_actor", auth)
    async with client:
        response = await client.post("/mini-app/api/bootstrap", json={
            "init_data": "vk_session:valid",
        })
        assert response.status == 200
        assert (await response.json())["credits"] == 23.5
        state.assert_awaited_once_with(2001)
        commerce.assert_awaited_once_with(2001)
        legacy.assert_not_awaited()
    # Voluntary TG linking alone does not unlock unsafe legacy studio.
    assert not _vk_legacy_linked_studio_available(platform="vk", telegram_linked=True)


@pytest.mark.asyncio
async def test_disabled_native_bootstrap_cannot_be_bypassed_by_header_or_url(monkeypatch):
    monkeypatch.delenv("VK_NATIVE_BOOTSTRAP_ENABLED", raising=False)
    client, auth, legacy, *_ = await _client_with_native_bootstrap()
    monkeypatch.setattr(gateway, "resolve_platform_actor", auth)
    async with client:
        response = await client.post("/mini-app/api/bootstrap", json={},
            headers={"X-Telegram-Init-Data": "vk_session:valid"})
        assert response.status == 503
        query = await client.post("/mini-app/api/bootstrap?ticket=vk_session:valid", json={})
        assert query.status == 400
        legacy.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_bootstrap_rejects_unsupported_api_without_unlocking_full_domain(monkeypatch):
    monkeypatch.setenv("VK_NATIVE_BOOTSTRAP_ENABLED", "1")
    client, auth, legacy, *_ = await _client_with_native_bootstrap()
    monkeypatch.setattr(gateway, "resolve_platform_actor", auth)
    client.app.router.add_post("/mini-app/api/credit", legacy)
    async with client:
        response = await client.post("/mini-app/api/credit", json={
            "init_data": "vk_session:valid",
        })
        # Unimplemented native domains must NEVER use legacy Telegram money.
        assert response.status in {403, 503}
        legacy.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_bootstrap_invalid_session_does_not_call_upstream(monkeypatch):
    from bot.shared_accounts.errors import AuthenticationError

    monkeypatch.setenv("VK_NATIVE_BOOTSTRAP_ENABLED", "1")
    client, auth, legacy, state, *_ = await _client_with_native_bootstrap()
    auth.side_effect = AuthenticationError("Expired")
    monkeypatch.setattr(gateway, "resolve_platform_actor", auth)
    async with client:
        response = await client.post("/mini-app/api/bootstrap", json={
            "init_data": "vk_session:invalid",
        })
        assert response.status == 401
        state.assert_not_awaited()
        legacy.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_bootstrap_upstream_failure_is_redacted_and_never_falls_back(monkeypatch):
    monkeypatch.setenv("VK_NATIVE_BOOTSTRAP_ENABLED", "1")
    client, auth, legacy, state, *_ = await _client_with_native_bootstrap()
    state.side_effect = RuntimeError("private upstream URL, secret and stack")
    monkeypatch.setattr(gateway, "resolve_platform_actor", auth)
    async with client:
        response = await client.post("/mini-app/api/bootstrap", json={
            "init_data": "vk_session:valid",
        })
        assert response.status == 503
        assert await response.json() == {
            "ok": False, "error": "Service temporarily unavailable",
        }
        legacy.assert_not_awaited()

@pytest.mark.asyncio
async def test_oversized_native_bootstrap_cannot_bypass_disabled_gateway(monkeypatch):
    monkeypatch.delenv("VK_NATIVE_BOOTSTRAP_ENABLED", raising=False)
    monkeypatch.delenv("VK_FULL_APP_PARITY_ENABLED", raising=False)
    client, auth, legacy, *_ = await _client_with_native_bootstrap()
    monkeypatch.setattr(gateway, "resolve_platform_actor", auth)
    async with client:
        payload = {"init_data": "vk_session:" + "a" * 200000}
        result = await client.post("/mini-app/api/bootstrap", json=payload)
        assert result.status == 413
        legacy.assert_not_awaited()
        auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_bootstrap_partial_adapter_refuses_nonpost_method_and_untrusted_keys(monkeypatch):
    monkeypatch.setenv("VK_NATIVE_BOOTSTRAP_ENABLED", "1")
    client, auth, legacy, state, *_ = await _client_with_native_bootstrap()
    monkeypatch.setattr(gateway, "resolve_platform_actor", auth)
    # Handler exists as post-only; GET on common bootstrap must not expose
    # an unauthenticated Telegram session or actor-controlled owner.
    client.app.router.add_get("/mini-app/api/bootstrap", legacy)
    async with client:
        response = await client.get(
            "/mini-app/api/bootstrap", headers={"X-Telegram-Init-Data": "vk_session:valid"},
        )
        assert response.status == 405
        legacy.assert_not_awaited()
        for forbidden in ("is_admin", "owner_key", "shared_account_id"):
            response = await client.post("/mini-app/api/bootstrap", json={
                "init_data": "vk_session:valid", forbidden: "spoof",
            })
            assert response.status == 400
        state.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_bootstrap_does_not_enable_photo_payment_or_other_domain(monkeypatch):
    monkeypatch.setenv("VK_NATIVE_BOOTSTRAP_ENABLED", "1")
    monkeypatch.setenv("VK_FULL_APP_PARITY_ENABLED", "1")
    client, auth, legacy, state, *_ = await _client_with_native_bootstrap()
    monkeypatch.setattr(gateway, "resolve_platform_actor", auth)
    client.app.router.add_post("/mini-app/api/image/generate", legacy)
    async with client:
        response = await client.post("/mini-app/api/image/generate", json={
            "init_data": "vk_session:valid",
            "model": "test",
        })
        assert response.status == 503
        legacy.assert_not_awaited()
        state.assert_not_awaited()
