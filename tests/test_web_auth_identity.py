"""Persistent browser identities: real SQLite transactions, replay and linking."""
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database, db as db_backend, web_auth


def _flow(*, source=None, destination="/mini-app/?ref=ABC123"):
    return {"mode": "link" if source else "login",
            "source": source, "destination": destination}


@pytest.mark.asyncio
async def test_new_web_account_and_cookie_survive_reload():
    response = await web_auth._complete_identity(
        SimpleNamespace(), "google", "112233445566778899001", _flow(),
    )
    assert response.location == "/mini-app/?ref=ABC123"
    assert "nm_web_session" in response.cookies
    cookie = response.cookies["nm_web_session"]
    assert cookie["httponly"] and cookie["secure"] and cookie["samesite"] == "Lax"

    request = SimpleNamespace(cookies={"nm_web_session": cookie.value})
    account = await web_auth._session_account(request)
    assert account and len(account) == 32

    second = await web_auth._complete_identity(
        SimpleNamespace(), "google", "112233445566778899001", _flow(),
    )
    assert await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": second.cookies["nm_web_session"].value}),
    ) == account


@pytest.mark.asyncio
async def test_verified_other_provider_links_without_identity_replacement(monkeypatch):
    google = await web_auth._complete_identity(SimpleNamespace(), "google", "google-sub", _flow())
    google_account = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": google.cookies["nm_web_session"].value}),
    )
    async def source_session(request):
        return google_account
    monkeypatch.setattr(web_auth, "_session_account", source_session)
    linked = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "yandex-sub", _flow(source=google_account),
    )
    assert linked.location == "/login?linked=yandex"
    async with db_backend.connect() as db:
        rows = await (await db.execute(
            "SELECT provider, account_id FROM web_auth_identities ORDER BY provider",
        )).fetchall()
    assert [(r[0], r[1]) for r in rows] == [
        ("google", google_account), ("yandex", google_account),
    ]


@pytest.mark.asyncio
async def test_existing_provider_identity_cannot_be_stolen_via_link(monkeypatch):
    first = await web_auth._complete_identity(SimpleNamespace(), "yandex", "owner-sub", _flow())
    first_account = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": first.cookies["nm_web_session"].value}),
    )
    other = await web_auth._complete_identity(SimpleNamespace(), "google", "different-sub", _flow())
    second_account = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": other.cookies["nm_web_session"].value}),
    )
    assert first_account != second_account
    async def source_session(request):
        return second_account
    monkeypatch.setattr(web_auth, "_session_account", source_session)
    refused = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "owner-sub", _flow(source=second_account),
    )
    assert refused.location == "/login?error=already-linked"
    assert not refused.cookies
    async with db_backend.connect() as db:
        row = await (await db.execute(
            "SELECT account_id FROM web_auth_identities WHERE provider = ? AND subject = ?",
            ("yandex", "owner-sub"),
        )).fetchone()
    assert row[0] == first_account


@pytest.mark.asyncio
async def test_telegram_web_auth_uses_legacy_identity_without_synthetic_id():
    existing = await database.get_or_create_user(987654321)
    signed = await web_auth._complete_identity(
        SimpleNamespace(), "telegram", "987654321", _flow(),
    )
    account = await web_auth._session_account(SimpleNamespace(cookies={
        "nm_web_session": signed.cookies["nm_web_session"].value,
    }))
    async with db_backend.connect() as db:
        mapping = await (await db.execute(
            "SELECT account_id FROM shared_account_identities WHERE platform = ? AND external_id = ?",
            ("telegram", 987654321),
        )).fetchone()
        legacy = await (await db.execute(
            "SELECT legacy_user_id FROM shared_account_legacy_links WHERE source = ? AND account_id = ?",
            ("telegram", account),
        )).fetchone()
    assert mapping[0] == account
    assert legacy[0] == existing.id


@pytest.mark.asyncio
async def test_email_magic_ticket_is_one_time_and_expires():
    ticket = await web_auth._new_flow("email", "login", None, "test@example.com",
                                      "/mini-app/?ref=REF123")
    flow = await web_auth._consume_flow("email", ticket)
    assert flow["subject"] == "test@example.com"
    assert flow["destination"] == "/mini-app/?ref=REF123"
    assert await web_auth._consume_flow("email", ticket) is None


@pytest.mark.asyncio
async def test_email_magic_ticket_has_bounded_requests():
    for index in range(3):
        await web_auth._new_flow("email", "login", None, "test@example.com", "/mini-app/")
    with pytest.raises(ValueError, match="Too many"):
        await web_auth._new_flow("email", "login", None, "test@example.com", "/mini-app/")


@pytest.mark.asyncio
async def test_google_oauth_start_requires_state_cookie_and_pkce(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setenv("WEB_AUTH_GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("WEB_AUTH_GOOGLE_CLIENT_SECRET", "test-client-secret")
    app = web.Application()
    app.router.add_get("/mini-app/api/web-auth/start/{provider}", web_auth.oauth_start)
    async with TestClient(TestServer(app)) as client:
        response = await client.get(
            "/mini-app/api/web-auth/start/google?next=%2Fmini-app%2F%3Fref%3DTEST",
            allow_redirects=False,
        )
        assert response.status == 302
        parsed = urlsplit(response.headers["Location"])
        assert parsed.hostname == "accounts.google.com"
        params = parse_qs(parsed.query)
        assert params["response_type"] == ["code"]
        assert params["code_challenge_method"] == ["S256"]
        assert params["redirect_uri"] == [
            "https://neuromixbot.com/mini-app/api/web-auth/callback/google"
        ]
        assert len(params["state"][0]) == 43
        assert "nm_web_oauth_state" in response.cookies
        assert response.cookies["nm_web_oauth_state"]["httponly"]
        assert response.cookies["nm_web_oauth_state"]["secure"]


@pytest.mark.asyncio
async def test_email_same_email_never_silently_merges_google_account():
    google = await web_auth._complete_identity(SimpleNamespace(), "google", "google-email-sub", _flow())
    email = await web_auth._complete_identity(SimpleNamespace(), "email", "test@example.com", _flow())
    google_account = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": google.cookies["nm_web_session"].value}),
    )
    email_account = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": email.cookies["nm_web_session"].value}),
    )
    assert google_account != email_account
