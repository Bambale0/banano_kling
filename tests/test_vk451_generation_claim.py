"""Signed VK claim reconciliation through the same BFF actor boundary."""
import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.shared_accounts import api, vk_native
from bot.shared_accounts.actor import PlatformActor

KEY = "vk_generation_reconcile_test_00001"


@pytest.mark.asyncio
async def test_hmac_reconciles_exact_native_actor_without_recipe_leak(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SECRET", "test-bff-hmac")
    payloads = []

    async def native(request):
        body = await request.read()
        path = request.path
        assert path == "/internal/v1/miniapp/users/2001/generations/claim"
        stamp = request.headers["X-Internal-Timestamp"]
        message = b"\n".join((stamp.encode(), b"POST", path.encode(), body))
        expected = hmac.new(b"test-bff-hmac", message, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(request.headers["X-Internal-Signature"], expected)
        payloads.append(json.loads(body))
        return web.json_response({
            "ok": True, "found": True, "task_id": 91, "task_type": "photo",
            "status": "processing", "cost": 2.5, "prompt": "PRIVATE TREND RECIPE",
        })

    service = web.Application()
    service.router.add_post("/internal/v1/miniapp/users/2001/generations/claim", native)
    async with TestClient(TestServer(service)) as client:
        monkeypatch.setenv("VK_NATIVE_INTERNAL_ORIGIN", f"http://127.0.0.1:{client.server.port}")
        result = await vk_native.fetch_native_vk_generation_claim(2001, KEY)
        assert result == {"ok": True, "found": True, "task_id": 91,
                          "task_type": "photo", "status": "processing", "cost": 2.5}
        assert payloads == [{"client_request_id": KEY}]
        with pytest.raises(ValueError):
            await vk_native.fetch_native_vk_generation_claim(2001, "bad")


@pytest.mark.asyncio
async def test_public_bff_claim_never_uses_tg_actor_or_accepts_owner_claim(monkeypatch):
    owner = PlatformActor(
        platform="vk", external_id=2001, shared_account_id="a" * 32,
        linked_platforms=("vk", "telegram"), linked_telegram_id=1001,
    )
    monkeypatch.setattr(api, "load_policy", AsyncMock(return_value=SimpleNamespace(enabled=True)))
    auth = AsyncMock(return_value=owner)
    query = AsyncMock(return_value={"ok": True, "found": True, "task_id": 91,
                                    "task_type": "photo", "status": "processing", "cost": 2.5})
    monkeypatch.setattr(api, "resolve_platform_actor", auth)
    monkeypatch.setattr(api, "fetch_native_vk_generation_claim", query)
    app = web.Application()
    app.router.add_post("/claim", api._guard(api.vk_generation_claim))
    async with TestClient(TestServer(app)) as client:
        good = await client.post("/claim", headers={"Authorization": "Bearer verified-session"},
                                 json={"client_request_id": KEY})
        assert good.status == 200
        assert (await good.json())["task_id"] == 91
        query.assert_awaited_once_with(2001, KEY)
        assert (await client.post("/claim", headers={"Authorization": "Bearer verified-session"},
                                  json={"client_request_id": KEY, "vk_user_id": 999})).status == 400
        assert query.await_count == 1
        auth.assert_awaited_with("verified-session", expected_platform="vk")
