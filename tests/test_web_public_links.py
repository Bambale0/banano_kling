"""Web-native profile/referral URLs must never require Telegram identity."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database, web_auth
from bot import db as db_backend


async def _web_identity(subject: str):
    response = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", subject, {
            "mode": "login", "source": None, "destination": "/login",
        })
    return response.cookies["nm_web_session"].value


def _server():
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    return TestClient(TestServer(app))


@pytest.mark.asyncio
async def test_independent_web_account_gets_stable_website_only_public_links(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    token = await _web_identity("first-website-user")
    async with _server() as client:
        async def read():
            response = await client.get("/mini-app/api/web-auth/public-links",
                                        headers={"Cookie": "nm_web_session=" + token})
            assert response.status == 200
            return await response.json()
        first = await read()
        second = await read()
        assert first == second
        code = first["code"]
        assert code.startswith("W") and 12 <= len(code) <= 20
        assert first["profile_link"] == (
            f"https://neuromixbot.com/mini-app/?web=1&profile={code}&ref={code}"
        )
        assert first["referral_link"] == f"https://neuromixbot.com/login?web=1&ref={code}"
        assert "t.me" not in str(first)
        unknown = await client.get("/mini-app/api/web-auth/public-links")
        assert unknown.status == 401
        public = await client.get("/mini-app/api/web-auth/public-profile?code=" + code)
        assert public.status == 200
        item = await public.json()
        assert item["code"] == code and item["display_name"] == "Автор NEUROMIX"
        assert "first-website-user" not in str(item)
        missing = await client.get("/mini-app/api/web-auth/public-profile?code=NO_SUCH_CODE")
        assert missing.status == 404


@pytest.mark.asyncio
async def test_linked_telegram_account_public_web_link_uses_existing_referral_code(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    legacy = await database.get_or_create_user(88776655)
    token = (await web_auth._complete_identity(
        SimpleNamespace(), "telegram", "88776655", {
            "mode": "login", "source": None, "destination": "/login",
        })).cookies["nm_web_session"].value
    async with _server() as client:
        response = await client.get("/mini-app/api/web-auth/public-links",
                                    headers={"Cookie": "nm_web_session=" + token})
        assert response.status == 200
        data = await response.json()
        assert data["code"] == legacy.referral_code
        assert "https://t.me/" not in data["profile_link"]
        public = await client.get("/mini-app/api/web-auth/public-profile?code=" + legacy.referral_code)
        assert public.status == 200


@pytest.mark.asyncio
async def test_website_referral_attribution_is_once_only_no_money_and_no_self_reference(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    owner_token = await _web_identity("inviter-web")
    invitee_token = await _web_identity("invitee-web")
    origin = {"Origin": "https://neuromixbot.com"}
    async with _server() as client:
        owner_links = await client.get("/mini-app/api/web-auth/public-links",
            headers={"Cookie": "nm_web_session=" + owner_token})
        code = (await owner_links.json())["code"]
        async def claim(token, code):
            response = await client.post("/mini-app/api/web-auth/referral/attach",
                json={"code": code},
                headers={**origin, "Cookie": "nm_web_session=" + token})
            return response.status, await response.json()
        self_claim = await claim(owner_token, code)
        assert self_claim[0] == 409
        first, replay = await asyncio.gather(
            claim(invitee_token, code), claim(invitee_token, code))
        assert first[0] == 200 and replay[0] == 200
        assert first[1]["attached"] or replay[1]["attached"]
        async with db_backend.connect() as db:
            rows = await (await db.execute("SELECT COUNT(*) FROM web_referral_attributions")).fetchone()
            assert rows[0] == 1
            # Signups record the invite, not a paid reward or balance entry.
            from bot.shared_accounts.wallet import WalletService
            account = await web_auth._session_account(
                SimpleNamespace(cookies={"nm_web_session": invitee_token}))
            assert (await WalletService("live").snapshot(account))["balance"]["available"] == "0.0000"


@pytest.mark.asyncio
async def test_expired_cookie_invalid_code_and_cross_origin_fail_closed(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    token = await _web_identity("bad-ref-web")
    async with _server() as client:
        for code in ("../admin", "https://evil.test", "x" * 90):
            response = await client.get("/mini-app/api/web-auth/public-profile",
                                        params={"code": code})
            assert response.status == 400
        anon = await client.post("/mini-app/api/web-auth/referral/attach",
                                 json={"code": "TEST_CODE"},
                                 headers={"Origin": "https://neuromixbot.com"})
        assert anon.status == 401
        wrong_origin = await client.post("/mini-app/api/web-auth/referral/attach",
            json={"code": "TEST_CODE"},
            headers={"Origin": "https://evil.test",
                     "Cookie": "nm_web_session=" + token})
        assert wrong_origin.status == 403



@pytest.mark.asyncio
async def test_web_invite_cannot_attach_after_invoice_creation(monkeypatch):
    from bot.web_commerce import ensure_web_payment_schema

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    inviter = await _web_identity("inviter-before-invoice")
    invited = await _web_identity("paid-before-invite")
    async with _server() as client:
        response = await client.get("/mini-app/api/web-auth/public-links",
            headers={"Cookie": "nm_web_session=" + inviter})
        code = (await response.json())["code"]
        account = await web_auth._session_account(
            SimpleNamespace(cookies={"nm_web_session": invited}))
        await ensure_web_payment_schema()
        async with db_backend.connect() as db:
            await db.execute(
                """INSERT INTO web_payment_orders
                   (order_id,account_id,request_key,package_id,amount_minor,credit_amount,
                    status,created_at_epoch,updated_at_epoch)
                   VALUES(?,?,?,?,?,?,'creating',?,?)""",
                ("web_" + "c" * 32, account, "existing-web-invoice-before-invite",
                 "mini", 25000, "250", 1, 1),
            )
            await db.commit()
        denied = await client.post("/mini-app/api/web-auth/referral/attach",
            json={"code": code},
            headers={"Origin": "https://neuromixbot.com",
                     "Cookie": "nm_web_session=" + invited})
        assert denied.status == 409
        assert (await denied.json())["error"] == "referral_after_activity"
        async with db_backend.connect() as db:
            count = await (await db.execute("SELECT COUNT(*) FROM web_referral_attributions")).fetchone()
        assert count[0] == 0
