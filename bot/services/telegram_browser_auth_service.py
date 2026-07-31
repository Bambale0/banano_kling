from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import aiohttp
import jwt
from aiohttp import web

from bot.config import config

logger = logging.getLogger(__name__)

_AUTH_PREFIX = "/mini-app/api/browser-auth"
_AUTH_COOKIE = "banano_tg_oidc"
_AUTH_TTL_SECONDS = 10 * 60
_BROWSER_INIT_DATA_TTL_SECONDS = 24 * 60 * 60
_TELEGRAM_ISSUER = "https://oauth.telegram.org"
_TELEGRAM_AUTH_URL = f"{_TELEGRAM_ISSUER}/auth"
_TELEGRAM_TOKEN_URL = f"{_TELEGRAM_ISSUER}/token"
_TELEGRAM_JWKS_URL = f"{_TELEGRAM_ISSUER}/.well-known/jwks.json"
_ALLOWED_JWT_ALGORITHMS = ("RS256", "ES256")
_JWK_CLIENT = jwt.PyJWKClient(_TELEGRAM_JWKS_URL, cache_keys=True, lifespan=3600)


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _auth_signing_key() -> bytes:
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is required for Telegram browser login")
    return hmac.new(
        config.BOT_TOKEN.encode("utf-8"),
        b"banano-telegram-browser-auth-v1",
        hashlib.sha256,
    ).digest()


def _encode_signed_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded = _b64url_encode(raw)
    signature = hmac.new(_auth_signing_key(), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64url_encode(signature)}"


def _decode_signed_payload(value: str) -> dict[str, Any]:
    try:
        encoded, supplied_signature = value.split(".", 1)
        expected_signature = hmac.new(
            _auth_signing_key(), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(
            expected_signature,
            _b64url_decode(supplied_signature),
        ):
            raise ValueError("Invalid browser auth state signature")
        payload = json.loads(_b64url_decode(encoded))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid browser auth state") from exc

    if not isinstance(payload, dict):
        raise ValueError("Invalid browser auth state")
    if int(payload.get("exp") or 0) < int(time.time()):
        raise ValueError("Browser auth state expired")
    return payload


def _normalize_origin(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    port = parsed.port
    netloc = parsed.hostname.lower()
    if port and port != 443:
        netloc = f"{netloc}:{port}"
    return f"https://{netloc}"


def _configured_allowed_origins() -> set[str]:
    values = {
        _normalize_origin(item)
        for item in os.getenv("TELEGRAM_LOGIN_ALLOWED_ORIGINS", "").split(",")
    }
    mini_app_origin = _normalize_origin(config.MINI_APP_URL)
    if mini_app_origin:
        values.add(mini_app_origin)
    return {item for item in values if item}


def _validate_return_to(value: str) -> tuple[str, str]:
    parsed = urlparse(str(value or "").strip())
    origin = _normalize_origin(value)
    if not origin or origin not in _configured_allowed_origins():
        raise web.HTTPBadRequest(reason="Frontend origin is not allowed")

    path = parsed.path or "/mini-app/"
    if not path.startswith("/mini-app"):
        path = "/mini-app/"
    cleaned = urlunparse(("https", urlparse(origin).netloc, path, "", parsed.query, ""))
    return origin, cleaned


def _client_id() -> str:
    return os.getenv("TELEGRAM_LOGIN_CLIENT_ID", "").strip()


def _client_secret() -> str:
    return os.getenv("TELEGRAM_LOGIN_CLIENT_SECRET", "").strip()


def _ensure_enabled() -> tuple[str, str]:
    client_id = _client_id()
    client_secret = _client_secret()
    if not client_id or not client_secret:
        raise web.HTTPServiceUnavailable(reason="Telegram browser login is not configured")
    if not client_id.isdigit():
        raise web.HTTPInternalServerError(reason="Invalid TELEGRAM_LOGIN_CLIENT_ID")
    if not _configured_allowed_origins():
        raise web.HTTPInternalServerError(reason="No Telegram login origins configured")
    return client_id, client_secret


def _code_challenge(verifier: str) -> str:
    return _b64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())


def _browser_init_data(user: dict[str, Any], *, auth_date: int | None = None) -> str:
    created_at = int(auth_date or time.time())
    fields = {
        "auth_date": str(created_at),
        "query_id": f"browser_{secrets.token_urlsafe(16)}",
        "user": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret_key = hmac.new(
        b"WebAppData",
        config.BOT_TOKEN.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    fields["hash"] = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(fields)


def _claims_to_user(claims: dict[str, Any]) -> dict[str, Any]:
    raw_id = claims.get("id")
    try:
        telegram_id = int(raw_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Telegram ID token has no numeric user id") from exc
    if telegram_id <= 0:
        raise ValueError("Telegram ID token has invalid user id")

    given_name = str(claims.get("given_name") or "").strip()
    family_name = str(claims.get("family_name") or "").strip()
    full_name = str(claims.get("name") or "").strip()
    if not given_name and full_name:
        name_parts = full_name.split(maxsplit=1)
        given_name = name_parts[0]
        if len(name_parts) > 1 and not family_name:
            family_name = name_parts[1]

    return {
        "id": telegram_id,
        "first_name": given_name or "Пользователь",
        "last_name": family_name,
        "username": str(claims.get("preferred_username") or "").strip().lstrip("@"),
        "photo_url": str(claims.get("picture") or "").strip(),
        "allows_write_to_pm": False,
    }


async def _decode_id_token(id_token: str, *, client_id: str, nonce: str) -> dict[str, Any]:
    def verify() -> dict[str, Any]:
        signing_key = _JWK_CLIENT.get_signing_key_from_jwt(id_token)
        return jwt.decode(
            id_token,
            signing_key.key,
            algorithms=list(_ALLOWED_JWT_ALGORITHMS),
            audience=client_id,
            issuer=_TELEGRAM_ISSUER,
            leeway=30,
            options={
                "require": ["iss", "aud", "sub", "iat", "exp", "nonce"],
            },
        )

    claims = await asyncio.to_thread(verify)
    if not hmac.compare_digest(str(claims.get("nonce") or ""), nonce):
        raise ValueError("Telegram login nonce mismatch")
    return claims


async def _exchange_code(
    *,
    code: str,
    verifier: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
) -> str:
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            _TELEGRAM_TOKEN_URL,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {credentials}",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        ) as response:
            payload = await response.json(content_type=None)
            if response.status >= 400 or not isinstance(payload, dict):
                logger.warning("Telegram token exchange failed: status=%s", response.status)
                raise ValueError("Telegram authorization failed")

    id_token = str(payload.get("id_token") or "").strip()
    if not id_token:
        raise ValueError("Telegram did not return an ID token")
    return id_token


def _redirect_with_error(return_to: str, code: str = "telegram_login_failed") -> web.Response:
    parsed = urlparse(return_to)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["auth_error"] = code
    target = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(query), ""))
    response = web.HTTPFound(target)
    response.del_cookie(_AUTH_COOKIE, path=f"{_AUTH_PREFIX}/")
    return response


async def telegram_browser_auth_start(request: web.Request) -> web.Response:
    client_id, _client_secret_value = _ensure_enabled()
    origin, return_to = _validate_return_to(request.query.get("return_to", ""))
    redirect_uri = f"{origin}{_AUTH_PREFIX}/callback"

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    cookie_payload = _encode_signed_payload(
        {
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "redirect_uri": redirect_uri,
            "return_to": return_to,
            "exp": int(time.time()) + _AUTH_TTL_SECONDS,
        }
    )
    auth_url = f"{_TELEGRAM_AUTH_URL}?{urlencode({
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid profile',
        'state': state,
        'nonce': nonce,
        'code_challenge': _code_challenge(verifier),
        'code_challenge_method': 'S256',
    })}"
    response = web.HTTPFound(auth_url)
    response.set_cookie(
        _AUTH_COOKIE,
        cookie_payload,
        max_age=_AUTH_TTL_SECONDS,
        secure=True,
        httponly=True,
        samesite="Lax",
        path=f"{_AUTH_PREFIX}/",
    )
    return response


async def telegram_browser_auth_callback(request: web.Request) -> web.Response:
    raw_cookie = request.cookies.get(_AUTH_COOKIE, "")
    fallback_return_to = f"{_normalize_origin(config.MINI_APP_URL)}/mini-app/"
    try:
        state_payload = _decode_signed_payload(raw_cookie)
        return_to = str(state_payload["return_to"])
        if request.query.get("error"):
            return _redirect_with_error(return_to, "telegram_login_cancelled")

        supplied_state = str(request.query.get("state") or "")
        expected_state = str(state_payload.get("state") or "")
        if not supplied_state or not hmac.compare_digest(supplied_state, expected_state):
            raise ValueError("Telegram login state mismatch")

        code = str(request.query.get("code") or "").strip()
        if not code:
            raise ValueError("Telegram login code is missing")

        client_id, client_secret = _ensure_enabled()
        id_token = await _exchange_code(
            code=code,
            verifier=str(state_payload["verifier"]),
            redirect_uri=str(state_payload["redirect_uri"]),
            client_id=client_id,
            client_secret=client_secret,
        )
        claims = await _decode_id_token(
            id_token,
            client_id=client_id,
            nonce=str(state_payload["nonce"]),
        )
        user = _claims_to_user(claims)
        init_data = _browser_init_data(user)

        parsed = urlparse(return_to)
        fragment = urlencode(
            {
                "tgWebAppData": init_data,
                "tgWebAppVersion": "browser",
                "tgWebAppPlatform": "web",
            }
        )
        target = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, fragment))
        response = web.HTTPFound(target)
        response.del_cookie(_AUTH_COOKIE, path=f"{_AUTH_PREFIX}/")
        return response
    except Exception as exc:
        logger.warning("Telegram browser login failed: %s", exc)
        safe_return_to = fallback_return_to if fallback_return_to.startswith("https://") else "/mini-app/"
        return _redirect_with_error(safe_return_to)


async def telegram_browser_auth_config(request: web.Request) -> web.Response:
    enabled = bool(_client_id() and _client_secret() and _configured_allowed_origins())
    return web.json_response(
        {
            "ok": True,
            "enabled": enabled,
            "expires_in": _BROWSER_INIT_DATA_TTL_SECONDS,
        },
        headers={"Cache-Control": "no-store"},
    )


async def dispatch_telegram_browser_auth(request: web.Request) -> web.Response | None:
    """Handle browser-login endpoints before the Mini App API catch-all route."""
    if request.method != "GET":
        return None
    if request.path == f"{_AUTH_PREFIX}/config":
        return await telegram_browser_auth_config(request)
    if request.path == f"{_AUTH_PREFIX}/start":
        return await telegram_browser_auth_start(request)
    if request.path == f"{_AUTH_PREFIX}/callback":
        return await telegram_browser_auth_callback(request)
    return None
