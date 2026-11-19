"""Public HTTP seams: a verified web account is never a synthetic Telegram user."""

from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import web_auth
from bot.shared_accounts.wallet import WalletService


@pytest.mark.asyncio
async def test_yandex_only_user_can_open_independent_web_account_without_telegram():
    identity = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "registered-yandex-only", {
            "mode": "login", "source": None, "destination": "/login",
        },
    )
    cookie = identity.cookies["nm_web_session"].value
    account = await web_auth._session_account(SimpleNamespace(cookies={"nm_web_session": cookie}))
    assert account

    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        response = await client.get(
            "/mini-app/api/web-auth/account", headers={"Cookie": f"nm_web_session={cookie}"},
        )
        assert response.status == 200
        payload = await response.json()
        assert payload["ok"] is True
        assert payload["account_id"] == account
        assert payload["studio_mode"] == "web"
        assert payload["connected"] == ["yandex"]
        assert payload["balance"]["available"] == "0.0000"
        assert payload["telegram_linked"] is False
        assert payload["can_generate"] is False

    # A web-only user has no Telegram identity or legacy balance.
    assert (await WalletService("live").snapshot(account))["balance"]["available"] == "0.0000"


@pytest.mark.asyncio
async def test_independent_web_account_rejects_unsigned_and_revoked_cookies(monkeypatch):
    login = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "another-user", {
            "mode": "login", "source": None, "destination": "/login",
        },
    )
    cookie = login.cookies["nm_web_session"].value
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        anonymous = await client.get("/mini-app/api/web-auth/account")
        assert anonymous.status == 401

        logout = await client.post(
            "/mini-app/api/web-auth/logout",
            headers={"Cookie": f"nm_web_session={cookie}", "Origin": "http://127.0.0.1"},
        )
        # Origin validation must be enforced; a foreign origin cannot revoke a session.
        assert logout.status == 403

        session = SimpleNamespace(cookies={"nm_web_session": cookie})
        assert await web_auth._session_account(session) is not None

        revoked = await client.post(
            "/mini-app/api/web-auth/logout",
            headers={"Cookie": f"nm_web_session={cookie}", "Origin": "https://neuromixbot.com"},
        )
        assert revoked.status == 200
        assert (await revoked.json())["ok"] is True
        assert await web_auth._session_account(session) is None

        after_logout = await client.get(
            "/mini-app/api/web-auth/account",
            headers={"Cookie": f"nm_web_session={cookie}"},
        )
        assert after_logout.status == 401


@pytest.mark.asyncio
async def test_independent_web_wallet_never_reads_another_yandex_identity():
    async def make(subject: str):
        response = await web_auth._complete_identity(
            SimpleNamespace(), "yandex", subject, {
                "mode": "login", "source": None, "destination": "/login",
            },
        )
        cookie = response.cookies["nm_web_session"].value
        account = await web_auth._session_account(
            SimpleNamespace(cookies={"nm_web_session": cookie}),
        )
        return cookie, account

    first_cookie, first_id = await make("yandex-first")
    second_cookie, second_id = await make("yandex-second")
    assert first_id != second_id
    await WalletService("live").apply(first_id, "credit", "3.2500", "web-wallet-first")

    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        first = await client.get(
            "/mini-app/api/web-auth/account",
            headers={"Cookie": f"nm_web_session={first_cookie}"},
        )
        second = await client.get(
            "/mini-app/api/web-auth/account",
            headers={"Cookie": f"nm_web_session={second_cookie}"},
        )
        assert first.status == second.status == 200
        assert (await first.json())["balance"]["available"] == "3.2500"
        assert (await second.json())["balance"]["available"] == "0.0000"
