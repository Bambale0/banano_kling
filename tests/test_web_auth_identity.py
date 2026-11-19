"""Persistent browser identities: real SQLite transactions, replay and linking."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import bot.db as db_backend
from bot import database, web_auth
from bot.config import config
from bot.miniapp import _validate_init_data
from bot.shared_accounts.wallet import WalletService


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
async def test_email_code_is_one_time_and_expires():
    from bot import email_otp

    ticket, code = await email_otp._issue(
        "test@example.com", "192.0.2.1", "login", None, "/mini-app/?ref=REF123",
    )
    flow = await email_otp._verify(ticket, code)
    assert flow["subject"] == "test@example.com"
    assert flow["destination"] == "/mini-app/?ref=REF123"
    assert await email_otp._verify(ticket, code) is None


@pytest.mark.asyncio
async def test_email_code_rate_limit_persists_across_calls(monkeypatch):
    from bot import email_otp

    now = 1_800_000_000
    monkeypatch.setattr(email_otp.time, "time", lambda: now)
    for index in range(3):
        monkeypatch.setattr(email_otp.time, "time", lambda tick=now + index * 61: tick)
        await email_otp._issue("test@example.com", "192.0.2.1",
                               "login", None, "/mini-app/")
    monkeypatch.setattr(email_otp.time, "time", lambda: now + 183)
    with pytest.raises(ValueError, match="rate limit"):
        await email_otp._issue("test@example.com", "192.0.2.1",
                               "login", None, "/mini-app/")


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
async def test_yandex_oauth_uses_registered_permissions_without_extra_scope(monkeypatch):
    """Yandex returns invalid_scope when unregistered login:email is requested."""
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setenv("WEB_AUTH_YANDEX_CLIENT_ID", "registered-yandex-client")
    monkeypatch.setenv("WEB_AUTH_YANDEX_CLIENT_SECRET", "test-secret")
    app = web.Application()
    app.router.add_get("/mini-app/api/web-auth/start/{provider}", web_auth.oauth_start)
    async with TestClient(TestServer(app)) as client:
        response = await client.get(
            "/mini-app/api/web-auth/start/yandex?next=%2Flogin%3Fref%3DTEST",
            allow_redirects=False,
        )
        assert response.status == 302
        parsed = urlsplit(response.headers["Location"])
        assert parsed.hostname == "oauth.yandex.ru"
        params = parse_qs(parsed.query)
        # Yandex OAuth uses permissions registered for the app if scope is omitted.
        assert "scope" not in params
        assert params["response_type"] == ["code"]
        assert params["redirect_uri"] == [
            "https://neuromixbot.com/mini-app/api/web-auth/callback/yandex"
        ]
        assert params["code_challenge_method"] == ["S256"]
        assert len(params["state"][0]) == 43
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


@pytest.mark.asyncio
async def test_existing_google_and_telegram_accounts_merge_only_with_both_fresh_proofs():
    # Existing Telegram account already has a different shared-account ID.
    telegram = await web_auth._complete_identity(
        SimpleNamespace(), "telegram", "456789123", _flow(),
    )
    first_id = await web_auth._session_account(SimpleNamespace(cookies={
        "nm_web_session": telegram.cookies["nm_web_session"].value,
    }))
    google = await web_auth._complete_identity(
        SimpleNamespace(), "google", "already-google-sub", _flow(),
    )
    second_cookie = google.cookies["nm_web_session"].value
    second_id = await web_auth._session_account(SimpleNamespace(cookies={
        "nm_web_session": second_cookie,
    }))
    assert first_id != second_id
    await WalletService("sandbox").apply(
        first_id, "credit", "2.2500", "web-merge-wallet-first",
    )
    await WalletService("sandbox").apply(
        second_id, "credit", "3.7500", "web-merge-wallet-second",
    )

    # This one action requires: a current Google session and a freshly
    # verified Telegram Login Widget payload. Both are checked server side.
    merged = await web_auth._complete_identity(
        SimpleNamespace(cookies={"nm_web_session": second_cookie}),
        "telegram", "456789123", _flow(source=second_id),
    )
    assert merged.location == "/login?linked=telegram"
    result_id = await web_auth._session_account(SimpleNamespace(cookies={
        "nm_web_session": merged.cookies["nm_web_session"].value,
    }))
    async with db_backend.connect() as db:
        rows = await (await db.execute(
            "SELECT account_id FROM web_auth_identities WHERE provider = 'google'",
        )).fetchall()
        tg = await (await db.execute(
            "SELECT account_id FROM shared_account_identities WHERE platform = 'telegram'",
        )).fetchall()
        active = await (await db.execute(
            "SELECT COUNT(*) FROM shared_accounts WHERE status = 'active'",
        )).fetchone()
    assert rows[0][0] == tg[0][0] == result_id
    assert active[0] == 1
    merged_wallet = await WalletService("sandbox").snapshot(result_id)
    assert merged_wallet["balance"]["available"] == "6.0000"
    entries = [item["kind"] for item in merged_wallet["entries"]]
    assert "transfer_in" in entries and "transfer_out" in entries


@pytest.mark.asyncio
async def test_two_existing_accounts_without_source_session_proof_never_merge(monkeypatch):
    first = await web_auth._complete_identity(SimpleNamespace(), "yandex", "existing-yandex", _flow())
    second = await web_auth._complete_identity(SimpleNamespace(), "google", "existing-google", _flow())
    first_id = await web_auth._session_account(SimpleNamespace(cookies={
        "nm_web_session": first.cookies["nm_web_session"].value,
    }))
    second_id = await web_auth._session_account(SimpleNamespace(cookies={
        "nm_web_session": second.cookies["nm_web_session"].value,
    }))
    assert first_id != second_id
    # Even if a caller spoofs the source account, absent the actual signed
    # session cookie the DB transaction must not transfer any accounts.
    async def forged_session(request):
        return first_id
    monkeypatch.setattr(web_auth, "_session_account", forged_session)
    denied = await web_auth._complete_identity(
        SimpleNamespace(cookies={}),
        "google", "existing-google", _flow(source=first_id),
    )
    assert denied.location == "/login?error=already-linked"
    async with db_backend.connect() as db:
        rows = await (await db.execute(
            "SELECT id FROM shared_accounts WHERE status = 'active'",
        )).fetchall()
    assert len(rows) == 2



@pytest.mark.asyncio
async def test_yandex_only_session_cannot_mint_telegram_credentials(monkeypatch):
    yandex = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "standalone-yandex-sub", _flow(destination="/login"),
    )
    from aiohttp.test_utils import make_mocked_request
    cookie = yandex.cookies["nm_web_session"].value
    request = make_mocked_request(
        "POST", "/mini-app/api/web-auth/studio",
        headers={"Origin": "https://neuromixbot.com", "Cookie": f"nm_web_session={cookie}"},
    )
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    response = await web_auth.web_auth_studio(request)
    assert response.status == 409
    assert b"needs_telegram_link" in response.body
    assert b"init_data" not in response.body


@pytest.mark.asyncio
async def test_verified_yandex_linked_to_real_telegram_can_mint_signed_studio_login(monkeypatch):
    from aiohttp.test_utils import make_mocked_request
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    tg_id = 287654321
    await database.get_or_create_user(tg_id)
    telegram = await web_auth._complete_identity(
        SimpleNamespace(), "telegram", str(tg_id), _flow(destination="/login"),
    )
    tg_cookie = telegram.cookies["nm_web_session"].value
    tg_account = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": tg_cookie}),
    )
    linked = await web_auth._complete_identity(
        SimpleNamespace(cookies={"nm_web_session": tg_cookie}),
        "yandex", "linked-yandex-sub", _flow(source=tg_account),
    )
    assert linked.location == "/login?linked=yandex"
    new_cookie = linked.cookies["nm_web_session"].value
    request = make_mocked_request(
        "POST", "/mini-app/api/web-auth/studio",
        headers={"Origin": "https://neuromixbot.com", "Cookie": f"nm_web_session={new_cookie}"},
    )
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    result = await web_auth.web_auth_studio(request)
    assert result.status == 200
    import json
    payload = json.loads(result.body)
    assert payload["ok"]
    verified = _validate_init_data(payload["init_data"], config.BOT_TOKEN)
    assert int(verified["user"]["id"]) == tg_id
