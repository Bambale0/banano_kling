"""Native Telegram profile bootstrap for existing verified browser identity linking."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import web_auth
from bot.config import config


def _signed(telegram_id=987654321, *, age=0, query_id="native_launch"):
    fields = {
        "auth_date": str(int(time.time()) - age),
        "query_id": query_id,
        "user": json.dumps({"id": telegram_id, "first_name": "Test"}, separators=(",", ":")),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    token = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(token, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.mark.asyncio
async def test_native_session_creates_verified_cookie_and_identifies_telegram(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    app = web.Application()
    app.router.add_post("/mini-app/api/web-auth/native-session", web_auth.native_telegram_session)
    app.router.add_get("/mini-app/api/web-auth/config", web_auth.web_auth_config)
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/mini-app/api/web-auth/native-session",
            json={"init_data": _signed()}, headers={"Origin": "https://neuromixbot.com"})
        assert response.status == 200
        cookie = response.cookies["nm_web_session"]
        assert cookie["httponly"] and cookie["secure"] and cookie["samesite"] == "Lax"
        value = await response.json()
        assert value["ok"] is True
        # aiohttp's test server runs over HTTP; Secure cookies need to be
        # passed explicitly to prove a persisted authenticated session.
        check = await client.get("/mini-app/api/web-auth/config",
            headers={"Cookie": f"nm_web_session={cookie.value}"})
        data = await check.json()
        assert data["authenticated"] is True
        assert "telegram" in data["connected"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation,expected", [
    ("no-origin", 403), ("forged", 401), ("browser", 403),
    ("webstudio", 403), ("old", 401),
])
async def test_native_session_rejects_unsigned_synthetic_or_expired(monkeypatch, mutation, expected):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    app = web.Application()
    app.router.add_post("/mini-app/api/web-auth/native-session", web_auth.native_telegram_session)
    original = _signed()
    data = (original[:-1] + "x") if mutation == "forged" else (
        _signed(age=90000) if mutation == "old" else (
            _signed(query_id="browser_synthetic") if mutation == "browser" else (
                _signed(query_id="webstudio_synthetic") if mutation == "webstudio" else original)))
    headers = {} if mutation == "no-origin" else {"Origin": "https://neuromixbot.com"}
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/mini-app/api/web-auth/native-session",
            json={"init_data": data}, headers=headers)
        assert response.status == expected
        assert "nm_web_session" not in response.cookies


@pytest.mark.asyncio
async def test_native_session_never_overwrites_different_web_owner(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    other = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "yandex-owner", {
            "mode": "login", "source": None, "destination": "/login",
        })
    cookie = other.cookies["nm_web_session"].value
    app = web.Application()
    app.router.add_post("/mini-app/api/web-auth/native-session", web_auth.native_telegram_session)
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/mini-app/api/web-auth/native-session",
            json={"init_data": _signed(987654322)},
            headers={"Origin": "https://neuromixbot.com",
                     "Cookie": f"nm_web_session={cookie}"})
        assert response.status == 409
        assert "nm_web_session" not in response.cookies



@pytest.mark.asyncio
async def test_linked_telegram_must_not_hide_existing_funded_web_wallet():
    from types import SimpleNamespace

    from bot.shared_accounts.wallet import WalletService

    signed = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "web-identity-has-credits", {
            "mode": "login", "source": None, "destination": "/login",
        })
    request = SimpleNamespace(cookies={
        "nm_web_session": signed.cookies["nm_web_session"].value,
    })
    owner = await web_auth._session_account(request)
    await WalletService("live").apply(owner, "credit", "13.0000", "opening-fixture-1")
    refused = await web_auth._complete_identity(request, "telegram", "111222333", {
        "mode": "link", "source": owner, "destination": "/login",
    })
    assert refused.location == "/login?error=financial-cutover-required"
    assert "nm_web_session" not in refused.cookies
    assert (await WalletService("live").snapshot(owner))["balance"]["available"] == "13.0000"


@pytest.mark.asyncio
async def test_empty_independent_web_account_can_link_verified_telegram():
    from types import SimpleNamespace

    signed = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "web-identity-no-credits", {
            "mode": "login", "source": None, "destination": "/login",
        })
    request = SimpleNamespace(cookies={
        "nm_web_session": signed.cookies["nm_web_session"].value,
    })
    owner = await web_auth._session_account(request)
    linked = await web_auth._complete_identity(request, "telegram", "111222334", {
        "mode": "link", "source": owner, "destination": "/login",
    })
    assert linked.location == "/login?linked=telegram"
    assert await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": linked.cookies["nm_web_session"].value})
    ) == owner


@pytest.mark.asyncio
async def test_queued_web_invoice_blocks_telegram_link_even_before_payment():
    from types import SimpleNamespace

    from bot import db as db_backend
    from bot.web_commerce import ensure_web_payment_schema

    signed = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "web-identity-with-queued-invoice", {
            "mode": "login", "source": None, "destination": "/login",
        })
    request = SimpleNamespace(cookies={"nm_web_session": signed.cookies["nm_web_session"].value})
    owner = await web_auth._session_account(request)
    await ensure_web_payment_schema()
    async with db_backend.connect() as db:
        await db.execute(
            """INSERT INTO web_payment_orders
               (order_id,account_id,request_key,package_id,amount_minor,credit_amount,
                status,created_at_epoch,updated_at_epoch)
               VALUES (?,?,?,?,?,?,'creating',?,?)""",
            ("web_" + "b"*32, owner, "email-link-queued-order-key", "mini", 25000, "250", 1, 1),
        )
        await db.commit()
    refused = await web_auth._complete_identity(request, "telegram", "111222335", {
        "mode": "link", "source": owner, "destination": "/login",
    })
    assert refused.location == "/login?error=financial-cutover-required"



@pytest.mark.asyncio
async def test_existing_web_account_with_funds_cannot_merge_into_telegram_source():
    """A second merge direction must not silently bury independent web funds."""
    from types import SimpleNamespace

    from bot import db as db_backend
    from bot.shared_accounts.wallet import WalletService

    telegram = await web_auth._complete_identity(
        SimpleNamespace(), "telegram", "888999111",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    telegram_request = SimpleNamespace(cookies={
        "nm_web_session": telegram.cookies["nm_web_session"].value,
    })
    telegram_owner = await web_auth._session_account(telegram_request)
    yandex = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "independent-yandex-funded",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    yandex_owner = await web_auth._session_account(SimpleNamespace(cookies={
        "nm_web_session": yandex.cookies["nm_web_session"].value,
    }))
    await WalletService("live").apply(yandex_owner, "credit", "9.0000", "merge-guard-credit")
    refused = await web_auth._complete_identity(
        telegram_request, "yandex", "independent-yandex-funded",
        {"mode": "link", "source": telegram_owner, "destination": "/login"},
    )
    assert refused.location == "/login?error=financial-cutover-required"
    assert "nm_web_session" not in refused.cookies
    assert (await WalletService("live").snapshot(yandex_owner))["balance"]["available"] == "9.0000"
    async with db_backend.connect() as db:
        owner = await (await db.execute(
            "SELECT account_id FROM web_auth_identities WHERE provider='yandex' AND subject=?",
            ("independent-yandex-funded",),
        )).fetchone()
    assert owner[0] == yandex_owner



@pytest.mark.asyncio
async def test_two_independent_web_owners_with_funds_cannot_hide_paid_history_on_merge():
    from types import SimpleNamespace

    from bot import db as db_backend
    from bot.shared_accounts.wallet import WalletService

    first = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "yandex-existing-independent",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    first_owner = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": first.cookies["nm_web_session"].value}))
    second = await web_auth._complete_identity(
        SimpleNamespace(), "google", "google-funded-independent",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    second_request = SimpleNamespace(cookies={
        "nm_web_session": second.cookies["nm_web_session"].value,
    })
    second_owner = await web_auth._session_account(second_request)
    await WalletService("live").apply(second_owner, "credit", "4.7500", "independent-merge-credit")
    refused = await web_auth._complete_identity(
        second_request, "yandex", "yandex-existing-independent",
        {"mode": "link", "source": second_owner, "destination": "/login"},
    )
    assert refused.location == "/login?error=financial-cutover-required"
    assert (await WalletService("live").snapshot(second_owner))["balance"]["available"] == "4.7500"
    async with db_backend.connect() as db:
        old = await (await db.execute(
            "SELECT account_id FROM web_auth_identities WHERE provider='yandex' AND subject=?",
            ("yandex-existing-independent",),
        )).fetchone()
    assert old[0] == first_owner



@pytest.mark.asyncio
async def test_checkout_revalidates_unlinked_owner_inside_transaction_after_auth_race(monkeypatch):
    """An identity change after the initial check must not create a Lava invoice."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot import db as db_backend
    from bot import web_commerce
    from bot.services.lava_service import lava_service

    login = await web_auth._complete_identity(
        SimpleNamespace(), "google", "web-checkout-identity-race",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    cookie = login.cookies["nm_web_session"].value
    owner = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": cookie}))
    async with db_backend.connect() as db:
        await db.execute(
            """INSERT INTO shared_account_identities(platform,external_id,account_id)
               VALUES('telegram',?,?)""", (884422556, owner),
        )
        await db.commit()
    monkeypatch.setattr("bot.shared_accounts.store.linked_platforms",
                        AsyncMock(return_value=[]))
    monkeypatch.setattr(web_commerce, "_enabled", lambda: True)
    monkeypatch.setattr(web_commerce, "_package",
                        lambda _: (10000, "100", "offer-synthetic", "Synthetic"))
    monkeypatch.setattr(lava_service, "api_key", "synthetic-key")
    create = AsyncMock(side_effect=AssertionError("must not submit provider invoice"))
    monkeypatch.setattr(lava_service, "create_invoice", create)
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/mini-app/api/web-auth/web-payments/create",
            json={"request_key": "identity-race-16-chars", "package_id": "mini",
                  "email": "buyer@example.test"},
            headers={"Origin": "https://neuromixbot.com",
                     "Cookie": "nm_web_session=" + cookie},
        )
        assert response.status == 409
        assert (await response.json())["code"] == "FINANCIAL_CUTOVER_REQUIRED"
    create.assert_not_awaited()
