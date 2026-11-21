"""Regression coverage for browser-bound /start Telegram confirmation.

No external Telegram requests or paid generation calls are made.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database, telegram_browser_approval as approval, web_auth
from bot import db as db_backend
from bot import browser_auth

ROOT = "/mini-app/api/web-auth/telegram-approval"
ORIGIN = "https://neuromixbot.com"


def _callback(challenge: str, *, telegram_id: int, approve: bool = True):
    message = SimpleNamespace(
        chat=SimpleNamespace(id=telegram_id, type="private"),
        edit_text=AsyncMock(),
    )
    return SimpleNamespace(
        from_user=SimpleNamespace(id=telegram_id),
        message=message,
        data="wba:" + ("yes:" if approve else "no:") + challenge,
        answer=AsyncMock(),
    )


@pytest.fixture
def approval_app(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setitem(browser_auth._BOT_USERNAME_CACHE, "value", "")
    monkeypatch.setitem(browser_auth._BOT_USERNAME_CACHE, "until", 0.0)
    app = web.Application()
    app["bot"] = SimpleNamespace(get_me=AsyncMock(
        return_value=SimpleNamespace(username="neuromix_test_bot"),
    ))
    web_auth.setup_web_auth_routes(app, "/mini-app")
    return app


async def _begin(client: TestClient, *, cookie: str = ""):
    headers = {"Origin": ORIGIN}
    if cookie:
        headers["Cookie"] = cookie
    response = await client.post(ROOT + "/start", json={}, headers=headers)
    body = await response.json()
    return response, body


def _browser_cookie(response):
    token = response.cookies[approval._COOKIE].value
    assert response.cookies[approval._COOKIE]["secure"]
    assert response.cookies[approval._COOKIE]["httponly"]
    assert response.cookies[approval._COOKIE]["samesite"] == "Lax"
    return approval._COOKIE + "=" + token


def _challenge(body):
    assert body["url"].startswith("https://t.me/neuromix_test_bot?start=auth_")
    value = parse_qs(urlsplit(body["url"]).query)["start"][0]
    assert value.startswith("auth_")
    assert len(value) < 64
    return value.removeprefix("auth_")


async def _status(client, request_id, cookie):
    response = await client.get(ROOT + "/status?id=" + request_id,
                                headers={"Cookie": cookie})
    return response.status, (await response.json())["status"]


async def _claim(client, request_id, cookie):
    return await client.post(ROOT + "/claim", json={"id": request_id},
                             headers={"Origin": ORIGIN, "Cookie": cookie})


@pytest.mark.asyncio
async def test_browser_confirmed_telegram_login_uses_real_legacy_owner_and_is_one_time(approval_app):
    await database.get_or_create_user(88442211)
    async with TestClient(TestServer(approval_app)) as client:
        response, body = await _begin(client)
        assert response.status == 200
        cookie = _browser_cookie(response)
        challenge = _challenge(body)
        assert len(body["confirmation_code"]) == 6
        assert await _status(client, body["id"], cookie) == (200, "pending")

        message = SimpleNamespace(
            chat=SimpleNamespace(type="private"),
            from_user=SimpleNamespace(id=88442211),
            answer=AsyncMock(),
        )
        await approval.send_confirmation(message, challenge)
        message.answer.assert_awaited_once()
        assert body["confirmation_code"] in message.answer.call_args.args[0]
        keyboard = message.answer.call_args.kwargs["reply_markup"]
        assert keyboard.inline_keyboard[0][0].callback_data == "wba:yes:" + challenge

        before = await _claim(client, body["id"], cookie)
        assert before.status == 409
        confirmed = _callback(challenge, telegram_id=88442211)
        await approval.decide(confirmed)
        confirmed.answer.assert_awaited_once()
        assert await _status(client, body["id"], cookie) == (200, "approved")

        result = await _claim(client, body["id"], cookie)
        assert result.status == 200
        assert (await result.json())["status"] == "authenticated"
        assert result.cookies["nm_web_session"]["httponly"]
        assert result.cookies["nm_web_session"]["secure"]
        account = await web_auth._session_account(SimpleNamespace(cookies={
            "nm_web_session": result.cookies["nm_web_session"].value,
        }))
        assert account
        assert await _status(client, body["id"], cookie) == (200, "consumed")
        replay = await _claim(client, body["id"], cookie)
        assert replay.status == 409

        async with db_backend.connect() as db:
            row = await (await db.execute(
                "SELECT account_id FROM shared_account_identities "
                "WHERE platform='telegram' AND external_id=?",
                (88442211,),
            )).fetchone()
            assert row[0] == account


@pytest.mark.asyncio
async def test_approval_cannot_be_claimed_by_another_browser_or_without_origin(approval_app):
    async with TestClient(TestServer(approval_app)) as client:
        response, body = await _begin(client)
        cookie = _browser_cookie(response)
        challenge = _challenge(body)
        await approval.decide(_callback(challenge, telegram_id=77001122))

        wrong_browser = approval._COOKIE + "=" + "a" * 43
        assert await _status(client, body["id"], wrong_browser) == (404, "not_found")
        wrong_claim = await _claim(client, body["id"], wrong_browser)
        assert wrong_claim.status == 409
        cross_origin = await client.post(ROOT + "/claim", json={"id": body["id"]},
                                         headers={"Cookie": cookie, "Origin": "https://evil.example"})
        assert cross_origin.status == 403
        assert await _status(client, body["id"], cookie) == (200, "approved")


@pytest.mark.asyncio
async def test_denial_and_cancel_never_create_browser_sessions(approval_app):
    async with TestClient(TestServer(approval_app)) as client:
        response, body = await _begin(client)
        cookie = _browser_cookie(response)
        challenge = _challenge(body)
        denied = _callback(challenge, telegram_id=665544, approve=False)
        await approval.decide(denied)
        assert await _status(client, body["id"], cookie) == (200, "denied")
        assert (await _claim(client, body["id"], cookie)).status == 409
        assert (await client.post(ROOT + "/cancel", json={"id": body["id"]},
                                  headers={"Cookie": cookie})).status == 403

        second_response, second = await _begin(client, cookie=cookie)
        assert second_response.status == 200
        cancelled = await client.post(ROOT + "/cancel", json={"id": second["id"]},
                                      headers={"Origin": ORIGIN, "Cookie": cookie})
        assert cancelled.status == 200
        assert await _status(client, second["id"], cookie) == (200, "denied")
        late = _callback(_challenge(second), telegram_id=665544)
        await approval.decide(late)
        assert await _status(client, second["id"], cookie) == (200, "denied")
        assert (await _claim(client, second["id"], cookie)).status == 409


@pytest.mark.asyncio
async def test_expired_and_replaced_request_cannot_be_approved(approval_app, monkeypatch):
    base = 1_800_000_000
    monkeypatch.setattr(approval.time, "time", lambda: base)
    async with TestClient(TestServer(approval_app)) as client:
        first, data = await _begin(client)
        cookie = _browser_cookie(first)
        challenge = _challenge(data)
        next_response, later = await _begin(client, cookie=cookie)
        assert next_response.status == 200
        assert await _status(client, data["id"], cookie) == (200, "denied")
        late_callback = _callback(challenge, telegram_id=223344)
        await approval.decide(late_callback)
        assert await _status(client, data["id"], cookie) == (200, "denied")

        monkeypatch.setattr(approval.time, "time", lambda: base + 301)
        assert await _status(client, later["id"], cookie) == (200, "expired")
        expired_callback = _callback(_challenge(later), telegram_id=223344)
        await approval.decide(expired_callback)
        assert (await _claim(client, later["id"], cookie)).status == 409


@pytest.mark.asyncio
async def test_concurrent_claims_only_one_web_session_is_minted(approval_app):
    await database.get_or_create_user(10101010)
    async with TestClient(TestServer(approval_app)) as client:
        response, body = await _begin(client)
        cookie = _browser_cookie(response)
        await approval.decide(_callback(_challenge(body), telegram_id=10101010))
        results = await asyncio.gather(
            _claim(client, body["id"], cookie),
            _claim(client, body["id"], cookie),
        )
        assert sorted(item.status for item in results) == [200, 409]
        for response in results:
            if response.status == 200:
                assert response.cookies["nm_web_session"]["httponly"]


@pytest.mark.asyncio
async def test_browser_start_is_rate_limited_per_cookie(approval_app):
    async with TestClient(TestServer(approval_app)) as client:
        first, _ = await _begin(client)
        cookie = _browser_cookie(first)
        for _ in range(approval._BROWSER_LIMIT - 1):
            response, _ = await _begin(client, cookie=cookie)
            assert response.status == 200
        blocked, payload = await _begin(client, cookie=cookie)
        assert blocked.status == 429
        assert payload["error"] == "rate_limited"
