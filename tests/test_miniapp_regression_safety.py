import json
from types import SimpleNamespace

import pytest
from aiohttp import web

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

    monkeypatch.setattr(
        safety,
        "_get_miniapp_module",
        lambda: SimpleNamespace(
            _miniapp_payload=fake_payload,
            _get_user_context=fake_context,
        ),
    )
    monkeypatch.setattr(safety.config, "is_admin", lambda _telegram_id: False)

    response = await safety._secure_prompt_submit(
        fake_original,
        DummyRequest({"init_data": "signed", "tags": ["trend", "trend-video"]}),
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

    monkeypatch.setattr(
        safety,
        "_get_miniapp_module",
        lambda: SimpleNamespace(
            _miniapp_payload=fake_payload,
            _get_user_context=fake_context,
        ),
    )
    monkeypatch.setattr(safety.config, "is_admin", lambda telegram_id: telegram_id == 42)

    response = await safety._secure_prompt_submit(
        fake_original,
        DummyRequest({"init_data": "signed", "tags": ["Trend"]}),
    )

    assert response.status == 200
    assert json.loads(response.text)["prompt"]["id"] == 7


@pytest.mark.asyncio
async def test_ordinary_prompt_submission_is_not_admin_only(monkeypatch):
    async def fake_original(_request):
        return web.json_response({"ok": True, "prompt": {"id": 8}})

    async def fail_context(*_args, **_kwargs):
        raise AssertionError("Ordinary prompt must not require an admin lookup")

    async def fake_payload(request):
        return request._body

    monkeypatch.setattr(
        safety,
        "_get_miniapp_module",
        lambda: SimpleNamespace(
            _miniapp_payload=fake_payload,
            _get_user_context=fail_context,
        ),
    )

    response = await safety._secure_prompt_submit(
        fake_original,
        DummyRequest({"init_data": "signed", "tags": ["portrait"]}),
    )

    assert response.status == 200


@pytest.mark.asyncio
async def test_lava_payment_requires_real_customer_email():
    original_called = False

    async def fake_original(_request):
        nonlocal original_called
        original_called = True
        return web.json_response({"ok": True})

    response = await safety._secure_create_payment(
        fake_original,
        DummyRequest(
            {
                "provider": "lava",
                "customer_email": "buyer@example.com",
            }
        ),
    )

    assert response.status == 400
    assert original_called is False


@pytest.mark.asyncio
async def test_lava_payment_uses_and_saves_request_local_email(monkeypatch):
    saved = []

    async def fake_original(_request):
        return web.json_response(
            {
                "ok": True,
                "email": safety._REQUEST_LAVA_EMAIL.get(),
            }
        )

    async def fake_context(_app, _init_data, _fallback):
        return 42, {"user": SimpleNamespace(id=1)}

    async def fake_save(telegram_id, email):
        saved.append((telegram_id, email))
        return email

    monkeypatch.setattr(
        safety,
        "_get_miniapp_module",
        lambda: SimpleNamespace(_get_user_context=fake_context),
    )
    monkeypatch.setattr(safety, "_save_payment_email", fake_save)

    response = await safety._secure_create_payment(
        fake_original,
        DummyRequest(
            {
                "provider": "lava",
                "customer_email": "User2026@Gmail.com",
                "init_data": "signed",
            }
        ),
    )

    payload = json.loads(response.text)
    assert response.status == 200
    assert payload["email"] == "user2026@gmail.com"
    assert saved == [(42, "user2026@gmail.com")]
    assert safety._REQUEST_LAVA_EMAIL.get() is None


@pytest.mark.asyncio
async def test_lava_payment_reuses_saved_account_email(monkeypatch):
    async def fake_original(_request):
        return web.json_response(
            {
                "ok": True,
                "email": safety._REQUEST_LAVA_EMAIL.get(),
            }
        )

    async def fake_context(_app, _init_data, _fallback):
        return 77, {"user": SimpleNamespace(id=2)}

    async def fake_saved_email(telegram_id):
        assert telegram_id == 77
        return "saved@mail.ru"

    monkeypatch.setattr(
        safety,
        "_get_miniapp_module",
        lambda: SimpleNamespace(_get_user_context=fake_context),
    )
    monkeypatch.setattr(safety, "_get_saved_payment_email", fake_saved_email)

    response = await safety._secure_create_payment(
        fake_original,
        DummyRequest(
            {
                "provider": "lava",
                "customer_email": "",
                "init_data": "signed",
            }
        ),
    )

    assert response.status == 200
    assert json.loads(response.text)["email"] == "saved@mail.ru"
    assert safety._REQUEST_LAVA_EMAIL.get() is None


@pytest.mark.asyncio
async def test_lava_payment_without_submitted_or_saved_email_is_rejected(monkeypatch):
    original_called = False

    async def fake_original(_request):
        nonlocal original_called
        original_called = True
        return web.json_response({"ok": True})

    async def fake_context(_app, _init_data, _fallback):
        return 77, {"user": SimpleNamespace(id=2)}

    async def fake_saved_email(_telegram_id):
        return None

    monkeypatch.setattr(
        safety,
        "_get_miniapp_module",
        lambda: SimpleNamespace(_get_user_context=fake_context),
    )
    monkeypatch.setattr(safety, "_get_saved_payment_email", fake_saved_email)

    response = await safety._secure_create_payment(
        fake_original,
        DummyRequest(
            {
                "provider": "lava",
                "customer_email": "",
                "init_data": "signed",
            }
        ),
    )

    assert response.status == 400
    assert original_called is False


@pytest.mark.asyncio
async def test_bootstrap_returns_saved_payment_email(monkeypatch):
    async def fake_original(_request):
        return web.json_response(
            {
                "ok": True,
                "telegram_id": 88,
                "credits": 25,
            }
        )

    async def fake_saved_email(telegram_id):
        assert telegram_id == 88
        return "account@mail.ru"

    monkeypatch.setattr(safety, "_get_saved_payment_email", fake_saved_email)

    response = await safety._secure_bootstrap(fake_original, DummyRequest({}))
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["credits"] == 25
    assert payload["payment_email"] == "account@mail.ru"


@pytest.mark.asyncio
async def test_payment_email_schema_executes_postgres_do_block(monkeypatch):
    statements: list[str] = []

    class FakeDatabase:
        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return False

        async def execute(self, statement, _parameters=None):
            statements.append(statement)
            return SimpleNamespace(rowcount=0)

        async def commit(self):
            return None

    monkeypatch.setattr(safety, "_PAYMENT_EMAIL_SCHEMA_READY", False)
    monkeypatch.setattr(safety, "_PAYMENT_EMAIL_SCHEMA_LOCK", None)
    monkeypatch.setattr(safety.db_backend, "is_postgres", lambda: True)
    monkeypatch.setattr(safety.db_backend, "connect", lambda: FakeDatabase())

    await safety._ensure_payment_email_schema()

    assert len(statements) == 1
    normalized_statement = " ".join(statements[0].split())
    assert normalized_statement.startswith("DO $$")
    assert "ALTER TABLE users ADD COLUMN payment_email TEXT" in normalized_statement
    assert "WHEN duplicate_column THEN NULL" in normalized_statement
    assert safety._PAYMENT_EMAIL_SCHEMA_READY is True


@pytest.mark.asyncio
async def test_non_lava_payment_does_not_require_email():
    async def fake_original(_request):
        return web.json_response({"ok": True, "provider": "telegram_stars"})

    response = await safety._secure_create_payment(
        fake_original,
        DummyRequest({"provider": "telegram_stars"}),
    )

    assert response.status == 200


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


def test_route_wrapping_targets_all_trend_bootstrap_and_payment_endpoints():
    async def handler(_request):
        return web.json_response({"ok": True})

    assert safety._wrap_post_handler(
        "/mini-app/api/prompts/submit", handler
    ) is not handler
    assert safety._wrap_post_handler("/api/v1/prompts", handler) is not handler
    assert safety._wrap_post_handler(
        "/mini-app/api/bootstrap", handler
    ) is not handler
    assert safety._wrap_post_handler(
        "/mini-app/api/create-payment", handler
    ) is not handler
    assert safety._wrap_post_handler("/mini-app/api/feed", handler) is handler


def test_installation_is_import_safe_and_patches_route_registration():
    assert web.UrlDispatcher.add_post is safety._guarded_add_post
    assert safety._ORIGINAL_ADD_POST is not None
    assert safety._ORIGINAL_LAVA_CREATE_INVOICE is not None
