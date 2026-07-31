import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from aiohttp import web

from bot.config import config

_LOGIN_MAX_AGE_SECONDS = 10 * 60
_BROWSER_SESSION_MAX_AGE_SECONDS = 24 * 60 * 60
_ALLOWED_LOGIN_FIELDS = {
    "id",
    "first_name",
    "last_name",
    "username",
    "photo_url",
    "auth_date",
}


def _normalized_login_payload(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise TypeError("Invalid Telegram login payload")

    payload: dict[str, str] = {}
    for key in _ALLOWED_LOGIN_FIELDS | {"hash"}:
        value = raw.get(key)
        if value is not None:
            payload[key] = str(value)
    return payload


def _verify_telegram_login(raw: Any, bot_token: str) -> dict[str, Any]:
    payload = _normalized_login_payload(raw)
    received_hash = payload.pop("hash", "")
    if not received_hash:
        raise ValueError("Missing Telegram login hash")

    try:
        auth_date = int(payload.get("auth_date", "0"))
        telegram_id = int(payload.get("id", "0"))
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid Telegram login payload") from error

    now = int(time.time())
    if telegram_id <= 0 or auth_date <= 0:
        raise ValueError("Invalid Telegram login payload")
    if auth_date > now + 60 or now - auth_date > _LOGIN_MAX_AGE_SECONDS:
        raise ValueError("Expired Telegram login")

    data_check_string = "\n".join(
        f"{key}={payload[key]}" for key in sorted(payload) if key in _ALLOWED_LOGIN_FIELDS
    )
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError("Invalid Telegram login signature")

    return {
        "id": telegram_id,
        "first_name": payload.get("first_name", ""),
        "last_name": payload.get("last_name", ""),
        "username": payload.get("username", ""),
        "photo_url": payload.get("photo_url", ""),
        "language_code": "ru",
    }


def _build_browser_init_data(user: dict[str, Any], bot_token: str) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": f"browser_{secrets.token_urlsafe(18)}",
        "user": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    fields["hash"] = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(fields)


async def browser_telegram_auth_config(request: web.Request) -> web.Response:
    try:
        bot = request.app["bot"]
        me = await bot.get_me()
        response = web.json_response(
            {
                "ok": True,
                "bot_username": str(me.username or "").lstrip("@"),
            }
        )
        response.headers["Cache-Control"] = "public, max-age=300"
        return response
    except Exception:  # noqa: BLE001 - transport failures must become a stable 503 response
        return web.json_response(
            {"ok": False, "error": "Telegram login is unavailable"},
            status=503,
            headers={"Cache-Control": "no-store"},
        )


async def browser_telegram_auth(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        telegram_auth = body.get("telegram_auth", body)
        user = _verify_telegram_login(telegram_auth, config.BOT_TOKEN)
        init_data = _build_browser_init_data(user, config.BOT_TOKEN)
        response = web.json_response(
            {
                "ok": True,
                "init_data": init_data,
                "expires_in": _BROWSER_SESSION_MAX_AGE_SECONDS,
            }
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        return web.json_response(
            {"ok": False, "error": str(error)},
            status=401,
            headers={"Cache-Control": "no-store"},
        )
    except Exception:  # noqa: BLE001 - unexpected auth failures must not leak internals
        return web.json_response(
            {"ok": False, "error": "Telegram login failed"},
            status=500,
            headers={"Cache-Control": "no-store"},
        )


def setup_browser_auth_routes(app: web.Application) -> None:
    miniapp_path = config.MINI_APP_PATH or "/mini-app"
    if not miniapp_path.startswith("/"):
        miniapp_path = f"/{miniapp_path}"
    miniapp_root = miniapp_path.rstrip("/")
    app.router.add_get(
        miniapp_root + "/api/browser-auth/config",
        browser_telegram_auth_config,
    )
    app.router.add_post(miniapp_root + "/api/browser-auth", browser_telegram_auth)
