"""Browser identity regression: redirect safety, provider gating and HTML contract."""

from pathlib import Path

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
    schema = (ROOT / "bot/shared_accounts/schema.py").read_text(encoding="utf-8")
    assert "web_auth_identities" in schema
    assert "PRIMARY KEY(provider, subject)" in schema
    assert "UNIQUE(account_id, provider)" in schema
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


def test_next_login_renders_only_configured_browser_providers_and_preserves_telegram():
    panel = (ROOT / "frontend/miniapp-v0/components/landing-login-panel.tsx").read_text(encoding="utf-8")
    assert 'BrowserProviderLogin' in panel
    assert 'providers?.yandex' in panel
    assert 'providers?.google' in panel
    assert 'providers?.email' in panel
    assert '/mini-app/api/web-auth/config' in panel
    assert '/mini-app/api/web-auth/start/yandex' in panel
    assert '/mini-app/api/web-auth/telegram' in panel
    assert 'LegacyTelegramWidget linkYandex' in panel
    assert '/mini-app/api/web-auth/studio' in panel
    assert 'studioUrlWithSession(session.init_data)' in panel
    assert 'TelegramOIDCLogin' in panel
    assert 'window.location.search' in panel
    assert "['Почта', 'Google', 'Яндекс ID']" not in panel


def test_existing_public_landing_and_nginx_are_not_overwritten_by_static_oauth():
    landing = (ROOT / "web/landing/index.html").read_text(encoding="utf-8")
    nginx = (ROOT / "ops/nginx/neuromixbot.com.conf").read_text(encoding="utf-8")
    publisher = (ROOT / "scripts/deploy_landing_local.sh").read_text(encoding="utf-8")
    assert 'href="/login"' in landing
    assert 'try_files /mini-app/login/index.html =404' in nginx
    assert '/login.html =404' not in nginx
    assert 'for path in /login /login/; do' in publisher


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
    async with TestServer(app) as server, TestClient(server) as client:
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
    async with TestServer(app) as server, TestClient(server) as client:
            resp = await client.post("/mini-app/api/web-auth/telegram",
                                     json={"telegram_auth": {"id": 12345}})
            assert resp.status == 403
            resp = await client.post("/mini-app/api/web-auth/telegram",
                                     headers={"Origin": "https://" + server.host},
                                     json={"telegram_auth": {"id": 12345}})
            assert resp.status == 403



def test_yandex_info_uses_oauth_authorization_scheme_not_google_bearer():
    src = (ROOT / "bot/web_auth.py").read_text(encoding="utf-8")
    assert 'profile_auth = "OAuth " if provider == "yandex" else "Bearer "' in src
    assert 'headers={"Authorization": profile_auth + access}' in src
