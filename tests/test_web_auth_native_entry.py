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


@pytest.mark.asyncio
async def test_web_referral_without_messenger_is_stable_and_attributed_only_on_new_signup(monkeypatch):
    from bot import db as db_backend

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    owner = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "verified-owner-subject",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    owner_cookie = owner.cookies["nm_web_session"].value
    owner_id = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": owner_cookie}),
    )
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        unauthenticated = await client.get("/mini-app/api/web-auth/referral")
        assert unauthenticated.status == 401
        response = await client.get(
            "/mini-app/api/web-auth/referral",
            headers={"Cookie": f"nm_web_session={owner_cookie}"},
        )
        assert response.status == 200
        first = await response.json()
        assert first["url"].startswith("https://neuromixbot.com/login?ref=NW")
        assert first["registrations"] == 0
        repeat = await client.get(
            "/mini-app/api/web-auth/referral",
            headers={"Cookie": f"nm_web_session={owner_cookie}"},
        )
        assert (await repeat.json()) == first

    referral_code = first["code"]
    invited = await web_auth._complete_identity(
        SimpleNamespace(), "google", "verified-invited-user",
        {"mode": "login", "source": None, "destination": f"/login?ref={referral_code}"},
    )
    invited_cookie = invited.cookies["nm_web_session"].value
    invited_id = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": invited_cookie}),
    )
    assert invited_id != owner_id
    # A later login with another parameter cannot steal existing attribution.
    await web_auth._complete_identity(
        SimpleNamespace(), "google", "verified-invited-user",
        {"mode": "login", "source": None, "destination": "/login?ref=NW0000000000000000"},
    )
    async with db_backend.connect() as db:
        rows = await (await db.execute(
            "SELECT referrer_account_id FROM web_referral_attributions WHERE referred_account_id = ?",
            (invited_id,),
        )).fetchall()
    assert [str(row[0]) for row in rows] == [owner_id]
    assert (await WalletService("live").snapshot(invited_id))["balance"]["available"] == "0.0000"

    async with TestClient(TestServer(app)) as client:
        check = await client.get(
            "/mini-app/api/web-auth/referral",
            headers={"Cookie": f"nm_web_session={owner_cookie}"},
        )
        assert (await check.json())["registrations"] == 1


@pytest.mark.asyncio
async def test_web_referral_rejects_unverified_unknown_codes():
    from bot import db as db_backend
    response = await web_auth._complete_identity(
        SimpleNamespace(), "email", "verified@example.com",
        {"mode": "login", "source": None, "destination": "/login?ref=NW1111111111111111"},
    )
    account_id = await web_auth._session_account(SimpleNamespace(cookies={
        "nm_web_session": response.cookies["nm_web_session"].value,
    }))
    async with db_backend.connect() as db:
        row = await (await db.execute(
            "SELECT referrer_account_id FROM web_referral_attributions WHERE referred_account_id = ?",
            (account_id,),
        )).fetchone()
    assert row is None

@pytest.mark.asyncio
async def test_telegram_oidc_link_requires_fresh_signed_proof_and_preserves_existing_web_id(monkeypatch):
    from bot import browser_auth, telegram_oidc

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(browser_auth, "_telegram_oidc_client_id", lambda: "123456")
    called = []
    async def fake_keys():
        return {"keys": []}
    def fake_verify(token, *, client_id, nonce, jwks):
        called.append((token, client_id, nonce))
        assert token == "signed-id-token" and client_id == "123456" and nonce == "fresh-nonce"
        return {"id": 456789777, "username": "testperson", "first_name": "Test"}
    monkeypatch.setattr(telegram_oidc, "fetch_telegram_jwks", fake_keys)
    monkeypatch.setattr(telegram_oidc, "verify_telegram_id_token", fake_verify)

    owner = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "owner-verifiable",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    owner_cookie = owner.cookies["nm_web_session"].value
    original = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": owner_cookie}),
    )
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    app.router.add_post("/mini-app/api/browser-auth/account", web_auth.telegram_oidc_login)
    url = "/mini-app/api/browser-auth/account"
    async with TestClient(TestServer(app)) as client:
        forged = await client.post(
            url, json={"id_token": "signed-id-token", "intent": "link"},
            headers={"Origin": "https://neuromixbot.com",
                     "Cookie": f"nm_web_session={owner_cookie}"},
        )
        assert forged.status == 401
        assert not called

        linked = await client.post(
            url, json={"id_token": "signed-id-token", "intent": "link"},
            headers={"Origin": "https://neuromixbot.com",
                     "Cookie": f"nm_web_session={owner_cookie}; nm_telegram_oidc_nonce=fresh-nonce"},
        )
        assert linked.status == 200
        result = await linked.json()
        assert result["ok"] is True
        assert result["redirect"] == "/login?linked=telegram"
        assert result["init_data"]
        assert "nm_web_session" in linked.cookies
        reauthenticated = await web_auth._session_account(SimpleNamespace(cookies={
            "nm_web_session": linked.cookies["nm_web_session"].value,
        }))
        assert reauthenticated == original

        second = await client.post(
            url, json={"id_token": "signed-id-token", "intent": "link"},
            headers={"Origin": "https://malicious.example",
                     "Cookie": f"nm_web_session={owner_cookie}; nm_telegram_oidc_nonce=fresh-nonce"},
        )
        assert second.status == 403
