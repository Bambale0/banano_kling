import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from bot.handlers import miniapp_regression_safety as safety
from bot.services import partner_approval_service as approval_service


@pytest.mark.asyncio
async def test_partner_overview_historical_pending_preserves_links_and_open_access(monkeypatch):
    async def payload(_request):
        return {"init_data": "signed-init-data"}

    fake_miniapp = SimpleNamespace(
        _miniapp_payload=payload,
        _validate_init_data=lambda _raw, _token: {"user": {"id": 710001}},
    )
    monkeypatch.setattr(safety, "_get_miniapp_module", lambda: fake_miniapp)

    async def pending_state(_telegram_id):
        return {
            "status": "pending",
            "is_partner": False,
            "application_id": 42,
            "can_apply": False,
        }

    monkeypatch.setattr(
        approval_service,
        "get_partner_application_state",
        pending_state,
    )

    async def legacy_overview(_request):
        return web.json_response(
            {
                "ok": True,
                "is_partner": False,
                "status": "basic",
                "referral_link": "https://example.test/ref/OPEN_PARTNER",
                "referral_bot_link": "https://t.me/example?start=OPEN_PARTNER",
            }
        )

    response = await safety._partner_overview_with_approval(
        legacy_overview,
        SimpleNamespace(app={}),
    )
    body = json.loads(response.text)

    assert response.status == 200
    assert body["status"] == "partner"
    assert body["application_status"] == "approved"
    assert body["application_id"] == 42
    assert body["can_apply"] is False
    assert body["is_partner"] is True
    assert body["referral_link"].endswith("/OPEN_PARTNER")
    assert body["referral_bot_link"].endswith("=OPEN_PARTNER")


@pytest.mark.asyncio
async def test_partner_overview_approved_preserves_legacy_links(monkeypatch):
    async def payload(_request):
        return {"init_data": "signed-init-data"}

    fake_miniapp = SimpleNamespace(
        _miniapp_payload=payload,
        _validate_init_data=lambda _raw, _token: {"user": {"id": 710002}},
    )
    monkeypatch.setattr(safety, "_get_miniapp_module", lambda: fake_miniapp)

    async def approved_state(_telegram_id):
        return {
            "status": "approved",
            "is_partner": True,
            "application_id": None,
            "can_apply": False,
        }

    monkeypatch.setattr(
        approval_service,
        "get_partner_application_state",
        approved_state,
    )

    async def legacy_overview(_request):
        return web.json_response(
            {
                "ok": True,
                "is_partner": True,
                "status": "partner",
                "referral_link": "https://example.test/ref/ACTIVE",
                "referral_bot_link": "https://t.me/example?start=ACTIVE",
            }
        )

    response = await safety._partner_overview_with_approval(
        legacy_overview,
        SimpleNamespace(app={}),
    )
    body = json.loads(response.text)

    assert body["status"] == "partner"
    assert body["is_partner"] is True
    assert body["referral_link"].endswith("/ACTIVE")
    assert body["referral_bot_link"].endswith("=ACTIVE")


@pytest.mark.asyncio
async def test_stale_partner_apply_returns_open_access_without_notifications(monkeypatch):
    original_calls = 0
    notifications: list[tuple[object, int]] = []

    async def payload(_request):
        return {"init_data": "signed-init-data", "action": "partner_apply"}

    async def user_context(_app, _init_data, _start_param):
        return 710003, {"user": object()}

    fake_miniapp = SimpleNamespace(
        _miniapp_payload=payload,
        _get_user_context=user_context,
    )
    monkeypatch.setattr(safety, "_get_miniapp_module", lambda: fake_miniapp)

    async def submit(telegram_id, *, source):
        assert telegram_id == 710003
        assert source == "miniapp"
        return {
            "ok": True,
            "status": "approved",
            "application_id": 77,
            "created": False,
        }

    async def notify(bot, application_id):
        notifications.append((bot, application_id))

    monkeypatch.setattr(approval_service, "submit_partner_application", submit)
    monkeypatch.setattr(
        approval_service,
        "notify_admins_about_partner_application",
        notify,
    )

    async def legacy_action(_request):
        nonlocal original_calls
        original_calls += 1
        return web.json_response({"ok": True, "legacy": True})

    bot = object()
    response = await safety._partner_action_with_approval(
        legacy_action,
        SimpleNamespace(app={"bot": bot}),
    )
    body = json.loads(response.text)

    assert response.status == 200
    assert body == {
        "ok": True,
        "status": "approved",
        "application_id": 77,
        "created": False,
    }
    assert original_calls == 0
    assert notifications == []


@pytest.mark.asyncio
async def test_non_partner_action_keeps_legacy_miniapp_behavior(monkeypatch):
    async def payload(_request):
        return {"init_data": "signed-init-data", "action": "some_existing_action"}

    fake_miniapp = SimpleNamespace(_miniapp_payload=payload)
    monkeypatch.setattr(safety, "_get_miniapp_module", lambda: fake_miniapp)

    async def legacy_action(_request):
        return web.json_response({"ok": True, "legacy": "preserved"})

    response = await safety._partner_action_with_approval(
        legacy_action,
        SimpleNamespace(app={}),
    )
    assert json.loads(response.text) == {"ok": True, "legacy": "preserved"}


@pytest.mark.asyncio
async def test_stale_partner_apply_still_requires_telegram_auth(monkeypatch):
    from unittest.mock import AsyncMock

    async def payload(_request):
        return {"init_data": "invalid", "action": "partner_apply"}

    async def denied_context(*_args):
        raise ValueError("Invalid signature")

    fake_miniapp = SimpleNamespace(_miniapp_payload=payload, _get_user_context=denied_context)
    monkeypatch.setattr(safety, "_get_miniapp_module", lambda: fake_miniapp)
    submit = AsyncMock()
    monkeypatch.setattr(approval_service, "submit_partner_application", submit)
    response = await safety._partner_action_with_approval(AsyncMock(), SimpleNamespace(app={}))
    assert response.status == 401
    submit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 500])
async def test_partner_overview_keeps_original_auth_ban_and_error_responses(status):
    original_response = web.json_response({"ok": False}, status=status)

    async def original(_request):
        return original_response

    response = await safety._partner_overview_with_approval(original, SimpleNamespace(app={}))
    assert response is original_response


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/mini-app/api/partner-overview", "/mini-app/api/action"])
async def test_partner_routes_keep_outer_ban_guard(monkeypatch, path):
    from unittest.mock import AsyncMock

    denied = web.json_response({"ok": False, "code": "user_banned"}, status=403)
    monkeypatch.setattr(safety, "_banned_miniapp_response", AsyncMock(return_value=denied))
    original = AsyncMock()
    response = await safety._wrap_post_handler(path, original)(SimpleNamespace(app={}))
    assert response is denied
    original.assert_not_awaited()
