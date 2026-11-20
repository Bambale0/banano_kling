
"""Native Telegram and browser logins must resolve one verified actor namespace.

This read-only access surface is not permission to migrate or combine wallets.
"""
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import db as db_backend
from bot import web_auth
from bot.browser_auth import _build_browser_init_data
from bot.config import config
from bot.shared_accounts.unified_actor import resolve_account_actor


def _native(tg_id: int) -> str:
    """Genuine Telegram-shaped signed initData, not a browser-issued bridge."""
    values = {
        "auth_date": str(int(time.time())),
        "query_id": "AA_VerifiedNativeLaunch",
        "user": json.dumps({"id": tg_id, "first_name": "Verified User"}),
    }
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


@pytest.mark.asyncio
async def test_yandex_only_session_resolves_shared_actor_without_telegram_or_legacy_money():
    login = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "unified-yandex-only",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    token = login.cookies["nm_web_session"].value
    actor = await resolve_account_actor(
        SimpleNamespace(cookies={"nm_web_session": token}),
    )
    assert actor.account_id
    assert actor.auth_channel == "web"
    assert actor.telegram_id is None
    assert actor.telegram_linked is False
    assert actor.wallet_authority == "web_live"
    assert actor.can_access_legacy_telegram_wallet is False


@pytest.mark.asyncio
async def test_valid_native_telegram_provisions_idempotent_account_without_minting_browser_sessions():
    tg_id = 876521113
    signed = _native(tg_id)
    actor = await resolve_account_actor(SimpleNamespace(cookies={}), init_data=signed)
    repeat = await resolve_account_actor(SimpleNamespace(cookies={}), init_data=signed)
    assert repeat == actor
    assert actor.auth_channel == "telegram"
    assert actor.telegram_id == tg_id
    assert actor.telegram_linked is True
    assert actor.wallet_authority == "telegram_legacy"
    assert actor.can_access_legacy_telegram_wallet is True
    assert len(actor.account_id) == 32
    async with db_backend.connect() as db:
        session_count = await (await db.execute(
            "SELECT COUNT(*) FROM shared_account_sessions WHERE account_id = ?",
            (actor.account_id,),
        )).fetchone()
    assert session_count[0] == 0


@pytest.mark.asyncio
async def test_web_then_verified_telegram_link_share_account_not_wallet_authority():
    browser = await web_auth._complete_identity(
        SimpleNamespace(), "google", "unified-google",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    token = browser.cookies["nm_web_session"].value
    request = SimpleNamespace(cookies={"nm_web_session": token})
    owner = await resolve_account_actor(request)
    tg_id = 876523991
    linked = await web_auth._complete_identity(
        request, "telegram", str(tg_id),
        {"mode": "link", "source": owner.account_id, "destination": "/login"},
    )
    assert "nm_web_session" in linked.cookies
    linked_web = await resolve_account_actor(SimpleNamespace(
        cookies={"nm_web_session": linked.cookies["nm_web_session"].value},
    ))
    native = await resolve_account_actor(
        SimpleNamespace(cookies={}), init_data=_native(tg_id),
    )
    assert linked_web.account_id == native.account_id == owner.account_id
    assert linked_web.telegram_linked is True
    assert linked_web.telegram_id is None  # OIDC link predates legacy users row
    assert linked_web.wallet_authority == "web_live"
    assert native.wallet_authority == "telegram_legacy"


@pytest.mark.asyncio
async def test_native_credential_never_reuses_unrelated_browser_cookie_identity():
    browser = await web_auth._complete_identity(
        SimpleNamespace(), "email", "unified-unrelated@example.org",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    cookie = browser.cookies["nm_web_session"].value
    web_actor = await resolve_account_actor(SimpleNamespace(cookies={
        "nm_web_session": cookie,
    }))
    native = await resolve_account_actor(
        SimpleNamespace(cookies={"nm_web_session": cookie}),
        init_data=_native(876527887),
    )
    assert native.account_id != web_actor.account_id
    assert native.auth_channel == "telegram"


@pytest.mark.asyncio
async def test_invalid_telegram_auth_and_revoked_browser_cookie_both_fail(monkeypatch):
    from bot.shared_accounts.errors import AuthenticationError

    with pytest.raises((AuthenticationError, ValueError)):
        await resolve_account_actor(
            SimpleNamespace(cookies={}), init_data="user=%7B%22id%22%3A1%7D&hash=bad",
        )
    login = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "unified-revoked",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    token = login.cookies["nm_web_session"].value
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        result = await client.post(
            "/mini-app/api/web-auth/logout",
            headers={"Origin": "https://neuromixbot.com",
                     "Cookie": "nm_web_session=" + token},
        )
        assert result.status == 200
    with pytest.raises(AuthenticationError):
        await resolve_account_actor(SimpleNamespace(cookies={
            "nm_web_session": token,
        }))


@pytest.mark.asyncio
async def test_unified_actor_api_requires_signed_proof_and_returns_source_authority(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    login = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "unified-http-user",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    token = login.cookies["nm_web_session"].value
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    url = "/mini-app/api/web-auth/actor"
    async with TestClient(TestServer(app)) as client:
        anonymous = await client.get(url)
        assert anonymous.status == 401
        browser = await client.get(url, headers={
            "Cookie": "nm_web_session=" + token,
        })
        assert browser.status == 200, await browser.text()
        payload = await browser.json()
        assert payload["auth_channel"] == "web"
        assert payload["wallet_authority"] == "web_live"
        assert payload["telegram_linked"] is False

        forged = await client.post(url, json={"init_data": _native(876523008)},
                                  headers={"Origin": "https://evil.example"})
        assert forged.status == 403
        signed = await client.post(url, json={"init_data": _native(876523008)},
                                   headers={"Origin": "https://neuromixbot.com"})
        assert signed.status == 200, await signed.text()
        data = await signed.json()
        assert data["auth_channel"] == "telegram"
        assert data["wallet_authority"] == "telegram_legacy"
        assert data["account_id"] != payload["account_id"]


@pytest.mark.asyncio
async def test_browser_minted_telegram_data_cannot_claim_native_wallet_without_live_link():
    from bot.shared_accounts.errors import AuthenticationError

    signed = _build_browser_init_data(
        {"id": 876525001, "first_name": "Signed browser"}, config.BOT_TOKEN,
    )
    # Unlike Telegram WebView credentials, browser_* query IDs are created by
    # this backend; logout must invalidate them through the browser cookie.
    with pytest.raises((AuthenticationError, PermissionError)):
        await resolve_account_actor(SimpleNamespace(cookies={}), init_data=signed)


@pytest.mark.asyncio
async def test_browser_bridge_stays_web_owned_and_revoked_cookie_dies(monkeypatch):
    from bot.shared_accounts.errors import AuthenticationError

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    owner = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "bridge-web-owner",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    cookie = owner.cookies["nm_web_session"].value
    request = SimpleNamespace(cookies={"nm_web_session": cookie})
    web_actor = await resolve_account_actor(request)
    tg_id = 876525007
    linked = await web_auth._complete_identity(
        request, "telegram", str(tg_id),
        {"mode": "link", "source": web_actor.account_id, "destination": "/login"},
    )
    cookie = linked.cookies["nm_web_session"].value
    signed = _build_browser_init_data(
        {"id": tg_id, "first_name": "Browser TG link"}, config.BOT_TOKEN,
    )
    linked_actor = await resolve_account_actor(
        SimpleNamespace(cookies={"nm_web_session": cookie}), init_data=signed,
    )
    assert linked_actor.account_id == web_actor.account_id
    assert linked_actor.auth_channel == "web"
    assert linked_actor.wallet_authority == "web_live"
    assert linked_actor.can_access_legacy_telegram_wallet is False

    another = await web_auth._complete_identity(
        SimpleNamespace(), "email", "bridge-other@example.org",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    with pytest.raises((AuthenticationError, PermissionError)):
        await resolve_account_actor(SimpleNamespace(cookies={
            "nm_web_session": another.cookies["nm_web_session"].value,
        }), init_data=signed)

    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        logout = await client.post(
            "/mini-app/api/web-auth/logout",
            headers={"Origin": "https://neuromixbot.com",
                     "Cookie": "nm_web_session=" + cookie},
        )
        assert logout.status == 200

    with pytest.raises((AuthenticationError, PermissionError)):
        await resolve_account_actor(
            SimpleNamespace(cookies={"nm_web_session": cookie}),
            init_data=signed,
        )


@pytest.mark.asyncio
async def test_concurrent_native_telegram_launches_claim_one_account_only():
    import asyncio

    signed = _native(876529133)
    actors = await asyncio.gather(*[
        resolve_account_actor(SimpleNamespace(cookies={}), init_data=signed)
        for _ in range(8)
    ])
    ids = {actor.account_id for actor in actors}
    assert len(ids) == 1
    async with db_backend.connect() as db:
        account_row = await (await db.execute(
            "SELECT COUNT(*) FROM shared_account_identities WHERE platform='telegram' AND external_id=?",
            (876529133,),
        )).fetchone()
    assert int(account_row[0]) == 1


@pytest.mark.asyncio
async def test_signed_browser_bridge_http_never_selects_legacy_telegram_wallet(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    owner = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "unified-bridge-http-user",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    cookie = owner.cookies["nm_web_session"].value
    account = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": cookie}),
    )
    tg_id = 876529191
    linked = await web_auth._complete_identity(
        SimpleNamespace(cookies={"nm_web_session": cookie}),
        "telegram", str(tg_id),
        {"mode": "link", "source": account, "destination": "/login"},
    )
    linked_cookie = linked.cookies["nm_web_session"].value
    signed = _build_browser_init_data(
        {"id": tg_id, "first_name": "Backend-signed browser"},
        config.BOT_TOKEN,
    )
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    url = "/mini-app/api/web-auth/actor"
    async with TestClient(TestServer(app)) as client:
        browser_signed_no_cookie = await client.post(
            url, json={"init_data": signed}, headers={
                "Origin": "https://neuromixbot.com",
            },
        )
        assert browser_signed_no_cookie.status == 401
        linked_response = await client.post(url, json={"init_data": signed}, headers={
            "Origin": "https://neuromixbot.com",
            "Cookie": "nm_web_session=" + linked_cookie,
        })
        assert linked_response.status == 200
        payload = await linked_response.json()
        assert payload["account_id"] == account
        assert payload["auth_channel"] == "web"
        assert payload["wallet_authority"] == "web_live"
        assert payload["telegram_linked"] is True
