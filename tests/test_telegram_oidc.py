"""Security regressions for Telegram OIDC one-tap browser authentication."""
import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from bot import browser_auth
from bot.telegram_oidc import verify_telegram_id_token

CLIENT_ID = "123456"
NONCE = "a_strong_nonce_bound_to_browser_cookie_123"
NOW = int(time.time())


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _issue_token(key, **claims_override):
    public_numbers = key.public_key().public_numbers()
    jwks = {"keys": [{
        "kid": "test-key", "kty": "RSA", "alg": "RS256",
        "n": _b64url(public_numbers.n.to_bytes(256, "big")),
        "e": _b64url(public_numbers.e.to_bytes(3, "big")),
    }]}
    claims = {
        "iss": "https://oauth.telegram.org", "aud": CLIENT_ID,
        "iat": NOW, "exp": NOW + 3600, "nonce": NONCE,
        "sub": "123456789", "id": 123456789,
        "given_name": "Игорь", "preferred_username": "igor_test",
    }
    claims.update(claims_override)
    header = {"alg": "RS256", "kid": "test-key", "typ": "JWT"}
    message = (
        _b64url(json.dumps(header, separators=(",", ":")).encode()) + "."
        + _b64url(json.dumps(claims, separators=(",", ":"), ensure_ascii=False).encode())
    ).encode("ascii")
    signature = key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    return message.decode() + "." + _b64url(signature), jwks


def test_oidc_valid_signature_yields_existing_telegram_identity(signing_key):
    token, jwks = _issue_token(signing_key)
    user = verify_telegram_id_token(
        token, client_id=CLIENT_ID, nonce=NONCE, jwks=jwks, now=NOW
    )
    assert user["id"] == 123456789
    assert user["first_name"] == "Игорь"
    assert user["username"] == "igor_test"
    assert "phone_number" not in user


@pytest.mark.parametrize("claim,wrong", [
    ("iss", "https://attacker.test"),
    ("aud", "123457"),
    ("nonce", "different_browser_nonce_123456"),
    ("iat", NOW - 3601),
    ("exp", NOW - 1),
    ("id", 0),
])
def test_oidc_rejects_invalid_claims(signing_key, claim, wrong):
    token, jwks = _issue_token(signing_key, **{claim: wrong})
    with pytest.raises(ValueError):
        verify_telegram_id_token(
            token, client_id=CLIENT_ID, nonce=NONCE, jwks=jwks, now=NOW
        )


def test_oidc_rejects_tampered_signature(signing_key):
    token, jwks = _issue_token(signing_key)
    parts = token.split(".")
    parts[1] = _b64url(b'{"iss":"https://oauth.telegram.org","id":999}')
    with pytest.raises(ValueError, match="signature"):
        verify_telegram_id_token(
            ".".join(parts), client_id=CLIENT_ID, nonce=NONCE, jwks=jwks, now=NOW
        )


def test_oidc_rejects_unknown_signing_key(signing_key):
    token, _ = _issue_token(signing_key)
    with pytest.raises(ValueError, match="signing key"):
        verify_telegram_id_token(
            token, client_id=CLIENT_ID, nonce=NONCE,
            jwks={"keys": []}, now=NOW,
        )


def test_oidc_rejects_malformed_jwt():
    with pytest.raises(ValueError):
        verify_telegram_id_token(
            "not-a-jwt", client_id=CLIENT_ID, nonce=NONCE,
            jwks={"keys": []}, now=NOW,
        )


@pytest.mark.asyncio
async def test_browser_oidc_login_requires_matching_nonce_cookie(monkeypatch, signing_key):
    token, jwks = _issue_token(signing_key)
    monkeypatch.setattr(browser_auth.config, "BOT_TOKEN", "123456:TEST_TOKEN")
    monkeypatch.setattr(browser_auth.config, "TELEGRAM_OIDC_CLIENT_ID", CLIENT_ID)

    async def get_keys():
        return jwks

    monkeypatch.setattr(browser_auth, "fetch_telegram_jwks", get_keys)

    class Request:
        def __init__(self, nonce):
            self.cookies = {browser_auth._OIDC_NONCE_COOKIE: nonce} if nonce else {}
        async def json(self):
            return {"id_token": token}

    rejected = await browser_auth.browser_telegram_auth(Request("wrong_nonce_but_correct_length_123"))
    assert rejected.status == 401
    assert "init_data" not in rejected.text
    accepted = await browser_auth.browser_telegram_auth(Request(NONCE))
    assert accepted.status == 200
    assert json.loads(accepted.text)["init_data"]
    assert "Max-Age=0" in accepted.headers["Set-Cookie"]
