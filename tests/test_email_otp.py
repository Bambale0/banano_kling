"""Email OTP: HTTP boundary, Resend contract, concurrency and abuse controls."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import db as db_backend
from bot import email_otp, web_auth


@pytest.fixture
def email_config(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setenv("WEB_AUTH_EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("WEB_AUTH_RESEND_API_KEY", "test-secret-REPLACE")
    monkeypatch.setenv("WEB_AUTH_RESEND_FROM", "NEUROMIX <verify@neuromixbot.com>")
    monkeypatch.setenv("WEB_AUTH_EMAIL_CODE_SECRET", "test-otp-hmac-secret-keep-out-of-database")


@pytest.mark.asyncio
async def test_email_login_http_with_code_and_replay_rejected(email_config, monkeypatch):
    delivered = []

    async def fake_send(email, code, request_id):
        delivered.append((email, code, request_id))
        return "provider_message_id"

    monkeypatch.setattr(email_otp, "_deliver_code", fake_send)
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        headers = {"Origin": "https://neuromixbot.com"}
        sent = await client.post("/mini-app/api/web-auth/email/start",
                                 headers=headers,
                                 json={"email": " PERSON@EXAMPLE.COM ",
                                       "next": "/mini-app/?ref=SHARER1"})
        assert sent.status == 200
        started = await sent.json()
        ticket = started["challenge_id"]
        assert len(ticket) == 43
        assert started["expires_in"] == 600
        assert started["resend_after"] == 60
        assert delivered[0][0] == "person@example.com"
        assert delivered[0][2] == ticket
        assert len(delivered[0][1]) == 6 and delivered[0][1].isascii()

        async with db_backend.connect() as db:
            saved = await (await db.execute(
                "SELECT code_hash, email FROM web_auth_email_codes"
            )).fetchone()
        assert saved[1] == "person@example.com"
        assert saved[0] != delivered[0][1]
        assert delivered[0][1] not in repr(saved)

        wrong = await client.post("/mini-app/api/web-auth/email/verify",
                                  headers=headers,
                                  json={"challenge_id": ticket, "code": "999a99"})
        assert wrong.status == 401
        sent_at = await client.post("/mini-app/api/web-auth/email/verify",
                                    headers=headers,
                                    json={"challenge_id": ticket, "code": delivered[0][1]})
        assert sent_at.status == 200
        result = await sent_at.json()
        assert result["redirect"] == "/mini-app/?ref=SHARER1"
        assert "nm_web_session" in sent_at.cookies
        assert sent_at.cookies["nm_web_session"]["httponly"]
        assert sent_at.cookies["nm_web_session"]["secure"]
        assert await web_auth._session_account(SimpleNamespace(cookies={
            "nm_web_session": sent_at.cookies["nm_web_session"].value,
        }))

        again = await client.post("/mini-app/api/web-auth/email/verify",
                                  headers=headers,
                                  json={"challenge_id": ticket, "code": delivered[0][1]})
        assert again.status == 401


@pytest.mark.asyncio
async def test_wrong_code_lockout_after_five_attempts(email_config):
    ticket, code = await email_otp._issue("many@example.com", "192.0.2.3",
                                          "login", None, "/mini-app/")
    bad = "123456" if code != "123456" else "654321"
    for _ in range(5):
        assert await email_otp._verify(ticket, bad) is None
    assert await email_otp._verify(ticket, code) is None
    async with db_backend.connect() as db:
        record = await (await db.execute(
            "SELECT failed_attempts FROM web_auth_email_codes"
        )).fetchone()
    assert record[0] == 5


@pytest.mark.asyncio
async def test_code_expiration_and_resend_invalidates_previous(email_config, monkeypatch):
    now = 1_800_000_000
    monkeypatch.setattr(email_otp.time, "time", lambda: now)
    first_ticket, first_code = await email_otp._issue(
        "expire@example.com", "192.0.2.4", "login", None, "/mini-app/",
    )
    monkeypatch.setattr(email_otp.time, "time", lambda: now + 61)
    new_ticket, new_code = await email_otp._issue(
        "expire@example.com", "192.0.2.4", "login", None, "/mini-app/",
    )
    assert await email_otp._verify(first_ticket, first_code) is None
    assert (await email_otp._verify(new_ticket, new_code))["subject"] == "expire@example.com"
    monkeypatch.setattr(email_otp.time, "time", lambda: now + 662)
    assert await email_otp._verify(new_ticket, new_code) is None


@pytest.mark.asyncio
async def test_resend_cooldown_persists_and_ip_bucket_bounds_bulk_spam(email_config, monkeypatch):
    base = 1_800_000_000
    monkeypatch.setattr(email_otp.time, "time", lambda: base)
    await email_otp._issue("cooldown@example.com", "192.0.2.5",
                           "login", None, "/mini-app/")
    with pytest.raises(ValueError, match="rate limit"):
        await email_otp._issue("cooldown@example.com", "192.0.2.5",
                               "login", None, "/mini-app/")
    # Different addresses cannot bypass the per-IP quota.
    for i in range(email_otp._MAX_IP_SENDS - 1):
        await email_otp._issue(f"person{i}@example.com", "192.0.2.5",
                               "login", None, "/mini-app/")
    with pytest.raises(ValueError, match="rate limit"):
        await email_otp._issue("another@example.com", "192.0.2.5",
                               "login", None, "/mini-app/")


@pytest.mark.asyncio
async def test_only_authenticated_same_origin_can_link_email(email_config, monkeypatch):
    monkeypatch.setattr(email_otp, "_deliver_code", AsyncMock(return_value="provider_id"))
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        url = "/mini-app/api/web-auth/email/start"
        blocked = await client.post(url, json={"email": "person@example.com"})
        assert blocked.status == 403
        denied = await client.post(url, headers={"Origin": "https://neuromixbot.com"},
                                   json={"email": "person@example.com", "intent": "link"})
        assert denied.status == 401


@pytest.mark.asyncio
async def test_email_sending_service_requires_verified_config(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setenv("WEB_AUTH_EMAIL_PROVIDER", "resend")
    monkeypatch.delenv("WEB_AUTH_RESEND_API_KEY", raising=False)
    monkeypatch.setenv("WEB_AUTH_RESEND_FROM", "verify@neuromixbot.com")
    assert not email_otp.email_enabled()
    monkeypatch.setenv("WEB_AUTH_RESEND_API_KEY", "re_example")
    assert email_otp.email_enabled()
    monkeypatch.setenv("WEB_AUTH_EMAIL_PROVIDER", "smtp")
    assert not email_otp.email_enabled()
    monkeypatch.setenv("WEB_AUTH_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("WEB_AUTH_SMTP_FROM", "verify@example.com")
    assert email_otp.email_enabled()


@pytest.mark.asyncio
async def test_resend_request_uses_idempotency_key_and_never_logs_code(email_config, monkeypatch):
    calls = []

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def json(self, **_):
            return {"id": "provider-message-123"}

    class FakeSession:
        def __init__(self, **kwargs):
            assert kwargs["timeout"].total == 10

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def post(self, url, *, headers, json):
            calls.append((url, headers, json))
            return FakeResponse()

    monkeypatch.setattr(email_otp.aiohttp, "ClientSession", FakeSession)
    result = await email_otp._deliver_code("person@example.com", "001234", "opaque-challenge")
    assert result == "provider-message-123"
    url, headers, body = calls[0]
    assert url == "https://api.resend.com/emails"
    assert headers["Authorization"] == "Bearer test-secret-REPLACE"
    assert headers["Idempotency-Key"] == "neuromix-email-otp-opaque-challenge"
    assert body["to"] == ["person@example.com"]
    assert body["text"].count("001234") == 1
    assert "001234" not in headers["Idempotency-Key"]
    assert "001234" not in url


@pytest.mark.asyncio
async def test_parallel_code_claim_only_one_succeeds(email_config):
    import asyncio

    ticket, code = await email_otp._issue("race@example.com", "192.0.2.9",
                                          "login", None, "/mini-app/")
    first, second = await asyncio.gather(
        email_otp._verify(ticket, code), email_otp._verify(ticket, code),
    )
    assert sum(result is not None for result in (first, second)) == 1
