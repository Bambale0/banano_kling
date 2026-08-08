import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from bot.handlers import miniapp_regression_safety as safety
from bot.services import partner_approval_service as approval_service


@pytest.mark.asyncio
async def test_partner_overview_pending_strips_links_server_side(monkeypatch):
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
                "referral_link": "https://example.test/ref/SHOULD_NOT_LEAK",
                "referral_bot_link": "https://t.me/example?start=SHOULD_NOT_LEAK",
            }
        )

    response = await safety._partner_overview_with_approval(
        legacy_overview,
        SimpleNamespace(app={}),
    )
    body = json.loads(response.text)

    assert response.status == 200
    assert body["status"] == "pending"
    assert body["application_status"] == "pending"
    assert body["application_id"] == 42
    assert body["can_apply"] is False
    assert body["is_partner"] is False
    assert body["referral_link"] == ""
    assert body["referral_bot_link"] == ""


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
async def test_partner_apply_action_creates_application_without_legacy_dispatch(monkeypatch):
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
            "status": "pending",
            "application_id": 77,
            "created": True,
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
        "status": "pending",
        "application_id": 77,
        "created": True,
    }
    assert original_calls == 0
    assert notifications == [(bot, 77)]


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
