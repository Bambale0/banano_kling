"""VK Mini App sessions reuse the linked Telegram application identity."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import db as db_backend
from bot import miniapp
from bot.browser_auth import trend_prompt_privacy_middleware
from bot.miniapp import _get_user_context
from bot.shared_accounts.auth import VerifiedIdentity
from bot.shared_accounts.policy import save_policy
from bot.shared_accounts.schema import ensure_schema
from bot.shared_accounts.store import create_session

ADMIN = 999999999
VK_ADMIN = 2001


async def _policy():
    return await save_policy(
        ADMIN,
        {"enabled": True, "vk_app_id": 123, "vk_admin_ids": [VK_ADMIN]},
        0,
    )


async def _insert_legacy_user(telegram_id=ADMIN, credits=42.5):
    async with db_backend.connect() as db:
        await ensure_schema(db)
        await db.execute(
            "INSERT INTO users(telegram_id, credits, username, first_name, last_name, photo_url) VALUES (?, ?, ?, ?, ?, ?)",
            (telegram_id, credits, "linked_admin", "Таня", "Admin", "https://example.test/avatar.jpg"),
        )
        await db.commit()


async def _link_vk_to_telegram(policy):
    telegram, _, _ = await create_session(
        VerifiedIdentity("telegram", ADMIN), 3600, policy.revision
    )
    vk, _, _ = await create_session(
        VerifiedIdentity("vk", VK_ADMIN), 3600, policy.revision
    )
    async with db_backend.connect() as db:
        await db.execute(
            "UPDATE shared_account_identities SET account_id = ? WHERE platform = ? AND external_id = ?",
            (telegram.id, "vk", VK_ADMIN),
        )
        await db.execute(
            "UPDATE shared_accounts SET status = ?, merged_into = ? WHERE id = ?",
            ("merged", telegram.id, vk.id),
        )
        await db.commit()
    _, token, _ = await create_session(
        VerifiedIdentity("vk", VK_ADMIN), 3600, policy.revision
    )
    return token


async def test_vk_session_reuses_linked_user_balance_and_identity(isolated_database):
    await _insert_legacy_user()
    policy = await _policy()
    token = await _link_vk_to_telegram(policy)

    telegram_id, context = await _get_user_context(
        web.Application(), "vk_session:" + token
    )

    assert telegram_id == ADMIN
    assert context["platform"] == "vk"
    assert context["actor"].identity == VerifiedIdentity("vk", VK_ADMIN)
    assert context["actor"].owner_user_id == context["user"].id
    assert context["actor"].telegram_id == ADMIN
    assert context["platform_external_id"] == VK_ADMIN
    assert context["vk_app_id"] == 123
    assert context["payload"]["user"] == {
        "id": ADMIN, "username": "linked_admin", "first_name": "Таня",
        "last_name": "Admin", "photo_url": "https://example.test/avatar.jpg",
    }
    assert context["user"].telegram_id == ADMIN
    assert float(context["user"].credits) == 42.5


async def test_unlinked_vk_session_cannot_create_a_shadow_telegram_user(isolated_database):
    await _insert_legacy_user()
    policy = await _policy()
    _, token, _ = await create_session(
        VerifiedIdentity("vk", VK_ADMIN), 3600, policy.revision
    )

    with pytest.raises(ValueError, match="свяжите аккаунты"):
        await _get_user_context(web.Application(), "vk_session:" + token)

    async with db_backend.connect() as db:
        rows = await (await db.execute("SELECT telegram_id FROM users")).fetchall()
    assert [row[0] for row in rows] == [ADMIN]


async def test_vk_session_is_revoked_by_policy_revision(isolated_database):
    await _insert_legacy_user()
    policy = await _policy()
    token = await _link_vk_to_telegram(policy)
    await save_policy(ADMIN, {"launch_max_age_seconds": 601}, policy.revision)

    with pytest.raises(ValueError):
        await _get_user_context(web.Application(), "vk_session:" + token)


def test_vk_payment_contract_allows_only_lava():
    from bot.miniapp import vk_payment_provider_denied

    assert vk_payment_provider_denied({"platform": "vk"}, "lava_card") is None
    denied = vk_payment_provider_denied({"platform": "vk"}, "telegram_stars")
    assert denied is not None
    assert denied.status == 403
    assert vk_payment_provider_denied({"platform": "telegram"}, "telegram_stars") is None


async def test_vk_linked_admin_keeps_admin_trend_response(isolated_database):
    await _insert_legacy_user()
    policy = await _policy()
    token = await _link_vk_to_telegram(policy)
    app = web.Application(middlewares=[trend_prompt_privacy_middleware])
    app["trend_prompt_privacy_root"] = "/mini-app"

    async def raw_prompt(_request):
        return web.json_response({
            "ok": True,
            "prompts": [{
                "id": 1,
                "title": "Тренд",
                "description": "Описание",
                "prompt_text": "private recipe",
                "is_trend": True,
                "tags": ["trend"],
                "successful_runs_count": 7,
                "uses_count": 7,
            }],
        })

    app.router.add_post("/mini-app/api/prompts", raw_prompt)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/mini-app/api/prompts",
            json={"init_data": "vk_session:" + token},
        )
        assert response.status == 200
        prompt = (await response.json())["prompts"][0]
        assert prompt["successful_runs_count"] == 7
        assert prompt["uses_count"] == 7


async def test_vk_copy_trend_link_stays_inside_vk(monkeypatch):
    actor = SimpleNamespace(id=1, referral_code="VKCODE")
    monkeypatch.setattr(
        miniapp,
        "_get_user_context",
        AsyncMock(return_value=(ADMIN, {
            "platform": "vk",
            "vk_app_id": 54880352,
            "user": actor,
        })),
    )
    monkeypatch.setattr(
        miniapp,
        "get_prompt_by_id",
        AsyncMock(return_value={
            "id": 42,
            "status": "approved",
            "is_public": True,
            "author_id": 2,
            "prompt_text": "",
        }),
    )
    app = web.Application()
    app["bot"] = SimpleNamespace(
        get_me=AsyncMock(return_value=SimpleNamespace(username="fixture_bot"))
    )
    app.router.add_post("/mini-app/api/prompts/link", miniapp.miniapp_prompt_link)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/mini-app/api/prompts/link",
            json={"init_data": "vk_session:test", "prompt_id": 42},
        )
        assert response.status == 200
        payload = await response.json()
    assert payload["link"] == (
        "https://vk.com/app54880352#prompt_42_ref_VKCODE"
    )


async def test_vk_partner_links_stay_inside_vk(monkeypatch):
    actor = SimpleNamespace(referral_code="VKCODE", channel_url="")
    monkeypatch.setattr(
        miniapp,
        "_get_user_context",
        AsyncMock(return_value=(ADMIN, {
            "platform": "vk",
            "vk_app_id": 54880352,
            "user": actor,
        })),
    )
    monkeypatch.setattr(miniapp, "get_or_create_user", AsyncMock(return_value=actor))
    monkeypatch.setattr(
        miniapp,
        "get_partner_overview",
        AsyncMock(return_value={
            "is_partner": True,
            "percent": 40,
            "level2_percent": 0,
            "referrals_count": 2,
            "balance_rub": 0,
        }),
    )
    app = web.Application()
    app["bot"] = SimpleNamespace(
        get_me=AsyncMock(return_value=SimpleNamespace(username="fixture_bot"))
    )
    app.router.add_post("/mini-app/api/partner", miniapp.miniapp_partner_overview)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/mini-app/api/partner",
            json={"init_data": "vk_session:test"},
        )
        assert response.status == 200
        payload = await response.json()
    expected = "https://vk.com/app54880352#ref_VKCODE"
    assert payload["referral_link"] == expected
    assert payload["referral_bot_link"] == expected
