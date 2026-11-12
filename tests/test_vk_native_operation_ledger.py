"""Trusted backend relay for the native VK shared-operation ledger."""
import hashlib
import hmac
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.shared_accounts.errors import PreviewConflict
from bot.shared_accounts.vk_native import (
    NativeVkOperationNotFound,
    reserve_native_vk_operation,
    settle_native_vk_operation,
)
from bot.shared_accounts.wallet import InsufficientFunds

SECRET = "main-to-native-operation-secret"


@pytest.mark.asyncio
async def test_reserve_and_settle_sign_exact_owner_scoped_payload(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SECRET", SECRET)
    monkeypatch.setenv("VK_NATIVE_SHARED_OPERATIONS_ENABLED", "1")
    seen = []
    app = web.Application()

    async def operation(request):
        body = await request.read()
        stamp = request.headers["X-Internal-Timestamp"]
        expected = hmac.new(
            SECRET.encode(),
            b"\n".join([stamp.encode(), b"POST", request.path.encode(), body]),
            hashlib.sha256,
        ).hexdigest()
        assert hmac.compare_digest(request.headers["X-Internal-Signature"], expected)
        seen.append((request.path, json.loads(body)))
        status = "reserved" if request.path.endswith("/reserve") else "completed"
        return web.json_response({
            "ok": True,
            "status": status,
            "cost": 0.1,
            "balance": 9.9,
            "client_request_id": "sharedOperationKey0001",
        })

    app.router.add_post("/internal/v1/miniapp/users/2001/operations/reserve", operation)
    app.router.add_post("/internal/v1/miniapp/users/2001/operations/settle", operation)
    async with TestClient(TestServer(app)) as client:
        monkeypatch.setenv(
            "VK_NATIVE_INTERNAL_ORIGIN", f"http://127.0.0.1:{client.server.port}"
        )
        reserved = await reserve_native_vk_operation(2001, {
            "operation": "photo_prompt",
            "client_request_id": "sharedOperationKey0001",
            "request_hash": "a" * 64,
            "cost": 0.1,
            "correlation_id": "trace-photo-prompt-1",
        })
        settled = await settle_native_vk_operation(2001, {
            "client_request_id": "sharedOperationKey0001",
            "request_hash": "a" * 64,
            "action": "complete",
            "external_ref": "provider-task-1",
        })
    assert reserved["status"] == "reserved"
    assert settled["status"] == "completed"
    assert [path for path, _payload in seen] == [
        "/internal/v1/miniapp/users/2001/operations/reserve",
        "/internal/v1/miniapp/users/2001/operations/settle",
    ]
    assert all("user_id" not in payload for _path, payload in seen)


@pytest.mark.asyncio
async def test_operation_relay_is_default_off_and_rejects_nonlocal_origin(monkeypatch):
    monkeypatch.delenv("VK_NATIVE_SHARED_OPERATIONS_ENABLED", raising=False)
    with pytest.raises(PermissionError):
        await reserve_native_vk_operation(2001, {})
    monkeypatch.setenv("VK_NATIVE_SHARED_OPERATIONS_ENABLED", "1")
    monkeypatch.setenv("INTERNAL_API_SECRET", SECRET)
    monkeypatch.setenv("VK_NATIVE_INTERNAL_ORIGIN", "https://evil.example")
    with pytest.raises(RuntimeError):
        await reserve_native_vk_operation(2001, {})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, ValueError),
        (402, InsufficientFunds),
        (403, PermissionError),
        (404, NativeVkOperationNotFound),
        (409, PreviewConflict),
        (503, RuntimeError),
    ],
)
async def test_operation_relay_preserves_safe_actionable_failures(monkeypatch, status, error):
    monkeypatch.setenv("INTERNAL_API_SECRET", SECRET)
    monkeypatch.setenv("VK_NATIVE_SHARED_OPERATIONS_ENABLED", "1")
    app = web.Application()

    async def reject(_request):
        return web.json_response({"error": "private native diagnostic"}, status=status)

    app.router.add_post("/internal/v1/miniapp/users/2001/operations/reserve", reject)
    async with TestClient(TestServer(app)) as client:
        monkeypatch.setenv(
            "VK_NATIVE_INTERNAL_ORIGIN", f"http://127.0.0.1:{client.server.port}"
        )
        with pytest.raises(error):
            await reserve_native_vk_operation(2001, {})


@pytest.mark.asyncio
async def test_operation_relay_rejects_malformed_success(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SECRET", SECRET)
    monkeypatch.setenv("VK_NATIVE_SHARED_OPERATIONS_ENABLED", "1")
    app = web.Application()

    async def malformed(_request):
        return web.json_response({"ok": True, "status": "reserved"})

    app.router.add_post(
        "/internal/v1/miniapp/users/2001/operations/reserve",
        malformed,
    )
    async with TestClient(TestServer(app)) as client:
        monkeypatch.setenv(
            "VK_NATIVE_INTERNAL_ORIGIN", f"http://127.0.0.1:{client.server.port}"
        )
        with pytest.raises(RuntimeError, match="response invalid"):
            await reserve_native_vk_operation(2001, {})
