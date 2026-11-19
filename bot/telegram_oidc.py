"""Verified Telegram OIDC ID token flow used by the browser login page.

The official Telegram Login SDK returns an ID token. Never trust its decoded
user object: verify the JWT against Telegram JWKS, claims and browser nonce.
"""
import base64
import binascii
import json
import time
from typing import Any

import aiohttp
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_TELEGRAM_JWKS_URL = "https://oauth.telegram.org/.well-known/jwks.json"
_TELEGRAM_ISSUER = "https://oauth.telegram.org"
_JWKS_CACHE_SECONDS = 600
_JWKS_CACHE: dict[str, Any] = {"keys": None, "until": 0.0}


def _decode_b64url(value: str) -> bytes:
    if not value or len(value) > 16384 or not all(
        char in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
        for char in value
    ):
        raise ValueError("Invalid Telegram OIDC token")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _parse_id_token(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    if not isinstance(token, str) or len(token) > 16384:
        raise ValueError("Invalid Telegram OIDC token")
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid Telegram OIDC token")
    try:
        header = json.loads(_decode_b64url(parts[0]))
        claims = json.loads(_decode_b64url(parts[1]))
        signature = _decode_b64url(parts[2])
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ValueError("Invalid Telegram OIDC token") from exc
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise ValueError("Invalid Telegram OIDC token")
    return header, claims, (parts[0] + "." + parts[1]).encode("ascii"), signature


async def fetch_telegram_jwks() -> dict[str, Any]:
    """Fetch Telegram's signing keys (bounded request and 10-min positive cache)."""
    now = time.monotonic()
    if _JWKS_CACHE["keys"] is not None and now < _JWKS_CACHE["until"]:
        return _JWKS_CACHE["keys"]
    try:
        timeout = aiohttp.ClientTimeout(total=5, connect=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                _TELEGRAM_JWKS_URL,
                headers={"Accept": "application/json"},
                max_redirects=0,
            ) as response:
                response.raise_for_status()
                if int(response.headers.get("Content-Length", "0")) > 131072:
                    raise ValueError("Oversized Telegram signing key response")
                raw = await response.content.read(131073)
                if len(raw) > 131072:
                    raise ValueError("Oversized Telegram signing key response")
                payload = json.loads(raw)
                if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
                    raise ValueError("Invalid Telegram signing key response")
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise ConnectionError("Telegram verification unavailable") from exc
    _JWKS_CACHE.update(keys=payload, until=time.monotonic() + _JWKS_CACHE_SECONDS)
    return payload


def verify_telegram_id_token(
    token: str, *, client_id: str, nonce: str, jwks: dict[str, Any],
    now: int | None = None,
) -> dict[str, Any]:
    """Verify RS256 signature and claims; convert to the existing Telegram user shape."""
    header, claims, signed, signature = _parse_id_token(token)
    if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
        raise ValueError("Unsupported Telegram OIDC signing algorithm")
    keys = jwks.get("keys") if isinstance(jwks, dict) else None
    if not isinstance(keys, list):
        raise ValueError("Invalid Telegram signing keys")
    key = next((
        item for item in keys
        if isinstance(item, dict) and item.get("kty") == "RSA"
        and item.get("kid") == header["kid"]
        and item.get("use", "sig") == "sig"
        and item.get("alg", "RS256") == "RS256"
    ), None)
    if key is None:
        raise ValueError("Unknown Telegram OIDC signing key")
    try:
        modulus = int.from_bytes(_decode_b64url(key["n"]), "big")
        exponent = int.from_bytes(_decode_b64url(key["e"]), "big")
        if modulus.bit_length() < 2048 or modulus.bit_length() > 8192:
            raise ValueError("Invalid Telegram signing key")
        public_key = rsa.RSAPublicNumbers(exponent, modulus).public_key()
        public_key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
    except (KeyError, TypeError, ValueError, InvalidSignature, binascii.Error) as exc:
        raise ValueError("Invalid Telegram OIDC signature") from exc

    timestamp = int(time.time()) if now is None else now
    audience = claims.get("aud")
    aud_valid = client_id in audience if isinstance(audience, list) else audience == client_id
    if not (
        claims.get("iss") == _TELEGRAM_ISSUER
        and aud_valid
        and isinstance(claims.get("nonce"), str)
        and nonce
        and len(nonce) >= 24
        and claims["nonce"] == nonce
        and type(claims.get("exp")) is int
        and type(claims.get("iat")) is int
        and timestamp < claims["exp"] <= timestamp + 86400
        and timestamp - 600 <= claims["iat"] <= timestamp + 60
    ):
        raise ValueError("Invalid Telegram OIDC claims")
    try:
        telegram_id = int(claims["id"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("Invalid Telegram OIDC user") from exc
    if telegram_id <= 0 or str(telegram_id) != str(claims["id"]):
        raise ValueError("Invalid Telegram OIDC user")

    return {
        "id": telegram_id,
        "first_name": str(claims.get("given_name") or claims.get("name") or "")[:256],
        "last_name": str(claims.get("family_name") or "")[:256],
        "username": str(claims.get("preferred_username") or "")[:64],
        "photo_url": str(claims.get("picture") or "")[:1024],
        "language_code": "ru",
    }
