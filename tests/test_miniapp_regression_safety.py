import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from bot import miniapp
from bot.handlers import miniapp_regression_safety as safety


class DummyRequest:
    def __init__(self, body: dict):
        self._body = body
        self.app = {}

    async def json(self) -> dict:
        return self._body


@pytest.mark.asyncio
async def test_non_admin_cannot_publish_trend(monkeypatch):
    original_called = False

    async def fake_original(_request):
        nonlocal original_called
        original_called = True
        return web.json_response({"ok": True})

    async def fake_payload(request):
        return request._body

    async def fake_context(_app, _init_data, _fallback):
        return 100500, {"user": SimpleNamespace(id=1)}

    monkeypatch.setattr(safety, "_ORIGINAL_PROMPT_SUBMIT", fake_original)
    monkeypatch.setattr(
        safety,
        "_MINIAPP_MODULE",
        SimpleNamespace(
            _miniapp_payload=fake_payload,
            _get_user_context=fake_context,
        ),
    )
    monkeypatch.setattr(safety.config, "is_admin", lambda _telegram_id: False)

    response = await safety._secure_prompt_submit(
        DummyRequest({"init_data": "signed", "tags": ["trend", "trend-video"]})
    )

    assert response.status == 403
    assert original_called is False
    assert "только администратор" in json.loads(response.text)["error"]


@pytest.mark.asyncio
async def test_admin_can_publish_trend(monkeypatch):
    async def fake_original(_request):
        return web.json_response({"ok": True, "prompt": {"id": 7}})

    async def fake_payload(request):
        return request._body

    async def fake_context(_app, _init_data, _fallback):
        return 42, {"user": SimpleNamespace(id=1)}

    monkeypatch.setattr(safety, "_ORIGINAL_PROMPT_SUBMIT", fake_original)
    monkeypatch.setattr(
        safety,
        "_MINIAPP_MODULE",
        SimpleNamespace(
            _miniapp_payload=fake_payload,
            _get_user_context=fake_context,
        ),
    )
    monkeypatch.setattr(safety.config, "is_admin", lambda telegram_id: telegram_id == 42)

    response = await safety._secure_prompt_submit(
        DummyRequest({"init_data": "signed", "tags": ["Trend"]})
    )

    assert response.status == 200
    assert json.loads(response.text)["prompt"]["id"] == 7


@pytest.mark.asyncio
async def test_lava_payment_requires_real_customer_email(monkeypatch):
    original_called = False

    async def fake_original(_request):
        nonlocal original_called
        original_called = True
        return web.json_response({"ok": True})

    monkeypatch.setattr(safety, "_ORIGINAL_CREATE_PAYMENT", fake_original)

    response = await safety._secure_create_payment(
        DummyRequest(
            {
                "provider": "lava",
                "customer_email": "buyer@example.com",
            }
        )
    )

    assert response.status == 400
    assert original_called is False


@pytest.mark.asyncio
async def test_lava_payment_uses_request_local_email(monkeypatch):
    async def fake_original(_request):
        return web.json_response(
            {
                "ok": True,
                "email": safety._REQUEST_LAVA_EMAIL.get(),
            }
        )

    monkeypatch.setattr(safety, "_ORIGINAL_CREATE_PAYMENT", fake_original)

    response = await safety._secure_create_payment(
        DummyRequest(
            {
                "provider": "lava",
                "customer_email": "User2026@Gmail.com",
            }
        )
    )

    payload = json.loads(response.text)
    assert response.status == 200
    assert payload["email"] == "user2026@gmail.com"
    assert safety._REQUEST_LAVA_EMAIL.get() is None


@pytest.mark.asyncio
async def test_lava_create_invoice_replaces_config_placeholder(monkeypatch):
    captured = {}

    async def fake_create_invoice(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(safety, "_ORIGINAL_LAVA_CREATE_INVOICE", fake_create_invoice)
    token = safety._REQUEST_LAVA_EMAIL.set("real.customer@mail.ru")
    try:
        result = await safety._create_invoice_with_request_email(
            email="buyer@example.com",
            offer_id="offer",
            currency="RUB",
        )
    finally:
        safety._REQUEST_LAVA_EMAIL.reset(token)

    assert result["ok"] is True
    assert captured["kwargs"]["email"] == "real.customer@mail.ru"


def test_installation_replaces_miniapp_route_handlers():
    assert miniapp.miniapp_prompt_submit is safety._secure_prompt_submit
    assert miniapp.miniapp_create_payment is safety._secure_create_payment
