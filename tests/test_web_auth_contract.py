"""Browser identity regression: redirect safety, provider gating and HTML contract."""
import asyncio
import hashlib
import os
import re
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import web_auth

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("destination", [
    "//evil.example/mini-app/", "https://evil.example/mini-app/",
    "/\\evil.example/", "/admin", "/api/payment", "/mini-app/#fragment",
    "/mini-app/\r\nLocation: https://evil.example", "javascript:alert(1)",
])
def test_login_blocks_external_and_unsafe_destinations(destination):
    assert web_auth._safe_next(destination) == "/mini-app/"


@pytest.mark.parametrize("destination", [
    "/mini-app/", "/mini-app/?ref=ABC123", "/login?linked=google",
])
def test_login_preserves_safe_local_destination(destination):
    assert web_auth._safe_next(destination) == destination


def test_oauth_providers_are_explicitly_configured(monkeypatch):
    monkeypatch.delenv("WEB_AUTH_PUBLIC_ORIGIN", raising=False)
    monkeypatch.setenv("WEB_AUTH_GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("WEB_AUTH_GOOGLE_CLIENT_SECRET", "secret")
    assert web_auth._credentials("google") == ("", "")
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    assert web_auth._credentials("google") == ("client", "secret")
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "http://neuromixbot.com")
    assert web_auth._credentials("google") == ("", "")
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://evil.com/path")
    assert web_auth._credentials("google") == ("", "")


def test_web_auth_isolated_from_legacy_telegram_ids():
    src = (ROOT / "bot/web_auth.py").read_text(encoding="utf-8")
    assert "web_auth_identities" in src
    assert "PRIMARY KEY(provider, subject)" in src
    assert "UNIQUE(account_id, provider)" in src
    assert "_verify_telegram_login" in src
    assert "shared_account_legacy_links" in src
    assert "AuthConflict" in src
    assert "web_auth_sessions" in src
    assert "_SESSION_COOKIE" in src
    assert "httponly=True, secure=True" in src
    assert 'samesite="Lax"' in src


def test_provider_urls_use_authorization_code_flow_and_pkce():
    google = web_auth._oauth_urls("google")
    yandex = web_auth._oauth_urls("yandex")
    assert google[0] == "https://accounts.google.com/o/oauth2/v2/auth"
    assert google[1] == "https://oauth2.googleapis.com/token"
    assert yandex[0] == "https://oauth.yandex.ru/authorize"
    assert yandex[2] == "https://login.yandex.ru/info"
    src = (ROOT / "bot/web_auth.py").read_text(encoding="utf-8")
    assert '"code_challenge_method": "S256"' in src
    assert '"code_verifier": flow["verifier"]' in src
    assert 'hmac.compare_digest(request.cookies.get(_STATE_COOKIE, ""), expected)' in src


def test_login_html_shows_four_methods_and_local_api_only():
    html = (ROOT / "web/landing/login.html").read_text(encoding="utf-8")
    for method in ("Google", "Яндекс", "Telegram", "Email"):
        assert method in html
    assert 'id="email-form"' in html
    assert 'id="status" role="status"' in html
    assert 'mode=()=>authenticated?"link":"login"' in html
    assert 'const ref=String(query.get("ref")' in html
    assert 'new URL(payload.redirect||next,window.location.origin)' in html
    assert 'window.location.assign(destination.pathname+destination.search+destination.hash)' in html
    assert "/mini-app/api/web-auth" in html
    assert "localStorage" not in html


def test_root_cta_keeps_web_attribution_and_login_is_deployed():
    landing = (ROOT / "web/landing/index.html").read_text(encoding="utf-8")
    nginx = (ROOT / "ops/nginx/neuromixbot.com.conf").read_text(encoding="utf-8")
    publisher = (ROOT / "scripts/deploy_landing_local.sh").read_text(encoding="utf-8")
    assert "link.setAttribute('href', next)" in landing
    assert "'/login?ref=' + encodeURIComponent(ref)" in landing
    for route in ("location = /login {", "location = /login/ {"):
        assert route in nginx
        assert route in publisher
    assert 'for file in index.html login.html robots.txt' in publisher
    assert 'if [[ -f "$BACKUP/login.html" ]]' in publisher
    assert 'for file in login robots.txt' in publisher


def test_web_auth_routes_are_registered_before_wildcard():
    browser = (ROOT / "bot/browser_auth.py").read_text(encoding="utf-8")
    assert "setup_web_auth_routes(app, miniapp_root)" in browser
    assert browser.index("setup_web_auth_routes(app, miniapp_root)") < browser.index("app.router.add_get(")


@pytest.mark.asyncio
async def test_public_config_flags_disabled_providers_without_secrets(monkeypatch):
    monkeypatch.delenv("WEB_AUTH_PUBLIC_ORIGIN", raising=False)
    monkeypatch.delenv("WEB_AUTH_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("WEB_AUTH_YANDEX_CLIENT_ID", raising=False)
    async def no_schema():
        return None
    async def no_session(request):
        return None
    monkeypatch.setattr(web_auth, "_ensure_tables", no_schema)
    monkeypatch.setattr(web_auth, "_session_account", no_session)
    app = web.Application()
    app.router.add_get("/mini-app/api/web-auth/config", web_auth.web_auth_config)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.get("/mini-app/api/web-auth/config")
            assert resp.status == 200
            value = await resp.json()
            assert value["authenticated"] is False
            assert value["providers"]["google"] is False
            assert value["providers"]["yandex"] is False
            assert value["providers"]["email"] is False
            assert value["providers"]["telegram"] is True


@pytest.mark.asyncio
async def test_telegram_endpoint_rejects_unsigned_identity_and_bad_origin(monkeypatch):
    monkeypatch.delenv("WEB_AUTH_PUBLIC_ORIGIN", raising=False)
    app = web.Application()
    app.router.add_post("/mini-app/api/web-auth/telegram", web_auth.telegram_login)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.post("/mini-app/api/web-auth/telegram",
                                     json={"telegram_auth": {"id": 12345}})
            assert resp.status == 403
            resp = await client.post("/mini-app/api/web-auth/telegram",
                                     headers={"Origin": "https://" + server.host},
                                     json={"telegram_auth": {"id": 12345}})
            assert resp.status == 403
