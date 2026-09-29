"""Trend sharing through signed HTTP requests and isolated persisted users."""
import hashlib
import hmac
import json
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database, miniapp
from bot.browser_auth import trend_prompt_privacy_middleware
from bot.config import config
from bot.services import partner_approval_service, referral_service


def signed_init_data(telegram_id, start_param=None):
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Test"}),
    }
    if start_param:
        fields["start_param"] = start_param
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture
async def sharing_client(monkeypatch):
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(referral_service, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(miniapp, "_mini_app_referral_last_attempt", {})
    monkeypatch.setattr(partner_approval_service, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(partner_approval_service, "_SCHEMA_READY", False)
    monkeypatch.setattr(partner_approval_service, "_SCHEMA_LOCK", None)
    partner_approval_service.install_partner_referral_approval_guard()
    monkeypatch.setattr(miniapp, "process_referral_click", referral_service.process_referral_click)
    for module_name in ("bot.handlers.trend_success_compat", "bot.trend_task_privacy"):
        module = sys.modules.get(module_name)
        if module is not None:
            monkeypatch.setattr(module, "DATABASE_PATH", database.DATABASE_PATH)
            if hasattr(module, "_SCHEMA_READY"):
                monkeypatch.setattr(module, "_SCHEMA_READY", False)
                monkeypatch.setattr(module, "_SCHEMA_LOCK", None)
    await database.set_channel_subscription_required(False)
    app = web.Application(middlewares=[trend_prompt_privacy_middleware])
    app["trend_prompt_privacy_root"] = "/mini-app"
    app["bot"] = SimpleNamespace(
        get_me=AsyncMock(return_value=SimpleNamespace(username="test_bot")),
        send_message=AsyncMock(),
    )
    app.router.add_post("/mini-app/api/prompts/link", miniapp.miniapp_prompt_link)
    app.router.add_get("/api/v1/prompts/{prompt_id}/link", miniapp.miniapp_prompt_link)
    async with TestClient(TestServer(app)) as client:
        yield client


async def public_trend():
    author = await database.get_or_create_user(81001)
    trend = await database.create_prompt(
        author_id=author.id, prompt_text="Private recipe", title="Shared trend",
        tags=["trend"], is_public=True,
    )
    await database.approve_prompt(trend["id"])
    return trend


@pytest.mark.asyncio
async def test_copy_link_uses_authenticated_sharer_not_author_or_client(sharing_client):
    trend = await public_trend()
    sharer = await database.get_or_create_user(81002)
    response = await sharing_client.post("/mini-app/api/prompts/link", json={
        "init_data": signed_init_data(sharer.telegram_id),
        "prompt_id": trend["id"], "referral_code": "SPOOF", "user_id": 81001,
    })
    assert response.status == 200
    result = await response.json()
    assert result["link"] == (
        f"https://t.me/test_bot?startapp=prompt_{trend['id']}_ref_{sharer.referral_code}"
    )
    assert result["prompt"]["prompt_text"] == ""
    assert response.headers["Cache-Control"] == "no-store"
    unchanged = await database.get_or_create_user(sharer.telegram_id)
    assert unchanged.referred_by is None
    assert unchanged.credits == sharer.credits


@pytest.mark.asyncio
@pytest.mark.parametrize("auth", ["", "user=forged&hash=bad"])
async def test_copy_link_rejects_unauthenticated_requests(sharing_client, auth):
    response = await sharing_client.post("/mini-app/api/prompts/link", json={
        "init_data": auth, "prompt_id": 1,
    })
    assert response.status >= 400
    assert "link" not in await response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["missing", "private", "deleted"])
async def test_copy_link_respects_template_access(sharing_client, unavailable):
    trend = await public_trend()
    if unavailable == "private":
        author = await database.get_or_create_user(81001)
        trend = await database.create_prompt(
            author_id=author.id, prompt_text="private", is_public=False,
        )
    elif unavailable == "deleted":
        await database.deactivate_prompt(trend["id"])
    response = await sharing_client.post("/mini-app/api/prompts/link", json={
        "init_data": signed_init_data(81002),
        "prompt_id": 999999 if unavailable == "missing" else trend["id"],
    })
    assert response.status in {403, 404}
    assert "link" not in await response.json()


@pytest.mark.asyncio
async def test_v1_link_alias_uses_authenticated_sharer(sharing_client):
    trend = await public_trend()
    sharer = await database.get_or_create_user(81002)
    response = await sharing_client.get(
        f"/api/v1/prompts/{trend['id']}/link",
        headers={"X-Telegram-Init-Data": signed_init_data(sharer.telegram_id)},
    )
    assert response.status == 200
    assert (await response.json())["link"].endswith(f"_ref_{sharer.referral_code}")


@pytest.mark.asyncio
async def test_combined_trend_link_attaches_once_and_preserves_first_referrer(sharing_client):
    trend = await public_trend()
    sharer = await database.get_or_create_user(81002)
    other = await database.get_or_create_user(81003)
    for partner in (sharer, other):
        application = await partner_approval_service.submit_partner_application(
            partner.telegram_id, source="telegram_bot",
        )
        approved = await partner_approval_service.review_partner_application(
            application["application_id"], approve=True, admin_telegram_id=999999999,
        )
        assert approved["ok"] is True
    start = f"prompt_{trend['id']}_ref_{sharer.referral_code}"
    for code in [start, start, f"prompt_{trend['id']}_ref_{other.referral_code}"]:
        response = await sharing_client.post("/mini-app/api/prompts/link", json={
            "init_data": signed_init_data(81004, code), "prompt_id": trend["id"],
        })
        assert response.status == 200
    visitor = await database.get_or_create_user(81004)
    assert visitor.referred_by == sharer.id
    stats = await database.get_referral_stats(sharer.telegram_id)
    assert stats["referrals_count"] == 1
    updated = await database.get_or_create_user(sharer.telegram_id)
    assert updated.referral_earned - sharer.referral_earned == database.PARTNER_INVITER_BONUS


@pytest.mark.asyncio
async def test_self_and_legacy_trend_links_do_not_attach(sharing_client):
    trend = await public_trend()
    sharer = await database.get_or_create_user(81002)
    application = await partner_approval_service.submit_partner_application(
        sharer.telegram_id, source="telegram_bot",
    )
    await partner_approval_service.review_partner_application(
        application["application_id"], approve=True, admin_telegram_id=999999999,
    )
    for start in [f"prompt_{trend['id']}", f"prompt_{trend['id']}_ref_{sharer.referral_code}"]:
        response = await sharing_client.post("/mini-app/api/prompts/link", json={
            "init_data": signed_init_data(sharer.telegram_id, start), "prompt_id": trend["id"],
        })
        assert response.status == 200
    updated = await database.get_or_create_user(sharer.telegram_id)
    assert updated.referred_by is None
    assert updated.referral_earned == sharer.referral_earned


def test_link_builder_preserves_plain_link_without_referral_code():
    from bot.miniapp_links import prompt_link

    assert prompt_link("test_bot", 42, None) == "https://t.me/test_bot?startapp=prompt_42"


@pytest.mark.asyncio
async def test_unapproved_sharer_link_does_not_bypass_partner_approval(sharing_client):
    trend = await public_trend()
    sharer = await database.get_or_create_user(81002)
    response = await sharing_client.post("/mini-app/api/prompts/link", json={
        "init_data": signed_init_data(81004, f"prompt_{trend['id']}_ref_{sharer.referral_code}"),
        "prompt_id": trend["id"],
    })
    assert response.status == 200
    visitor = await database.get_or_create_user(81004)
    assert visitor.referred_by is None
    updated = await database.get_or_create_user(sharer.telegram_id)
    assert updated.referral_earned == sharer.referral_earned
