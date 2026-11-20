"""Server-minted legacy Telegram studio credentials must die with web logout."""
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import make_mocked_request

from bot import database, miniapp, web_auth
from bot.config import config


def _flow(*, source=None):
    return {"mode": "link" if source else "login", "source": source,
            "destination": "/login"}


@pytest.mark.asyncio
async def test_web_studio_credentials_revoke_with_cookie_and_prevent_wrong_telegram_owner(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    tg_id = 387654219
    await database.get_or_create_user(tg_id)
    origin = await web_auth._complete_identity(
        SimpleNamespace(), "telegram", str(tg_id), _flow(),
    )
    initial_cookie = origin.cookies["nm_web_session"].value
    account_id = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": initial_cookie}),
    )
    linked = await web_auth._complete_identity(
        SimpleNamespace(cookies={"nm_web_session": initial_cookie}),
        "yandex", "studio-session-bound-user", _flow(source=account_id),
    )
    cookie = linked.cookies["nm_web_session"].value
    request = make_mocked_request(
        "POST", "/mini-app/api/web-auth/studio",
        headers={"Origin": "https://neuromixbot.com",
                 "Cookie": "nm_web_session=" + cookie},
    )
    response = await web_auth.web_auth_studio(request)
    assert response.status == 200
    import json
    signed = json.loads(response.body)["init_data"]
    payload = miniapp._validate_init_data(signed, config.BOT_TOKEN)
    token_id = payload["query_id"]
    assert token_id.startswith("webstudio_")
    assert payload["user"]["id"] == tg_id
    await web_auth.verify_studio_bridge(token_id, tg_id)
    from bot.shared_accounts.unified_actor import resolve_account_actor
    signed_actor = await resolve_account_actor(
        SimpleNamespace(cookies={}), init_data=signed,
    )
    assert signed_actor.account_id == account_id
    assert signed_actor.auth_channel == "web"
    assert signed_actor.wallet_authority == "web_live"
    assert signed_actor.can_access_legacy_telegram_wallet is False
    with pytest.raises(PermissionError):
        await web_auth.verify_studio_bridge(token_id, tg_id + 1)

    logout = make_mocked_request(
        "POST", "/mini-app/api/web-auth/logout",
        headers={"Origin": "https://neuromixbot.com",
                 "Cookie": "nm_web_session=" + cookie},
    )
    assert (await web_auth.logout(logout)).status == 200

    # Both the new actor contract and old Mini App legacy handler must fail.
    with pytest.raises(PermissionError):
        await web_auth.verify_studio_bridge(token_id, tg_id)
    with pytest.raises(PermissionError):
        await miniapp._get_user_context({}, signed)
    with pytest.raises(PermissionError):
        await resolve_account_actor(
            SimpleNamespace(cookies={}), init_data=signed,
        )


@pytest.mark.asyncio
async def test_unregistered_webstudio_token_fails_even_with_valid_telegram_hmac():
    from bot.browser_auth import _build_browser_init_data

    synthetic = _build_browser_init_data(
        {"id": 387654221, "first_name": "Test"}, config.BOT_TOKEN,
        query_id_prefix="webstudio",
    )
    payload = miniapp._validate_init_data(synthetic, config.BOT_TOKEN)
    with pytest.raises(PermissionError):
        await web_auth.verify_studio_bridge(payload["query_id"], 387654221)


@pytest.mark.asyncio
async def test_studio_login_revocation_race_returns_401_not_internal_error(monkeypatch):
    owner = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "studio-race-cancel",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    cookie = owner.cookies["nm_web_session"].value
    tg_id = 387654227
    await database.get_or_create_user(tg_id)
    account = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": cookie}),
    )
    linked = await web_auth._complete_identity(
        SimpleNamespace(cookies={"nm_web_session": cookie}),
        "telegram", str(tg_id), _flow(source=account),
    )
    request = make_mocked_request(
        "POST", "/mini-app/api/web-auth/studio",
        headers={"Origin": "https://neuromixbot.com",
                 "Cookie": "nm_web_session=" + linked.cookies["nm_web_session"].value},
    )
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    async def revoked_between_check_and_mint(*args):
        raise PermissionError("Session revoked")
    monkeypatch.setattr(web_auth, "_mint_session_bound_studio_init_data",
                        revoked_between_check_and_mint)
    response = await web_auth.web_auth_studio(request)
    assert response.status == 401
    assert b"session_required" in response.body
