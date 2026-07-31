import hashlib
import hmac
import json
from urllib.parse import parse_qsl

import pytest

from bot.services import telegram_browser_auth_service as service


def test_signed_state_round_trip(monkeypatch):
    monkeypatch.setattr(service.config, "BOT_TOKEN", "test-token")
    value = service._encode_signed_payload({"state": "abc", "exp": 4_000_000_000})
    assert service._decode_signed_payload(value)["state"] == "abc"


def test_signed_state_rejects_tampering(monkeypatch):
    monkeypatch.setattr(service.config, "BOT_TOKEN", "test-token")
    value = service._encode_signed_payload({"state": "abc", "exp": 4_000_000_000})
    encoded, signature = value.split(".", 1)
    with pytest.raises(ValueError):
        service._decode_signed_payload(f"{encoded}x.{signature}")


def test_browser_init_data_matches_miniapp_hmac(monkeypatch):
    token = "123:abc"
    monkeypatch.setattr(service.config, "BOT_TOKEN", token)
    init_data = service._browser_init_data(
        {
            "id": 42,
            "first_name": "Browser",
            "last_name": "User",
            "username": "browser_user",
            "photo_url": "",
        },
        auth_date=1_900_000_000,
    )
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    their_hash = parsed.pop("hash")
    check = "\n".join(f"{key}={value}" for key, value in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    assert hmac.compare_digest(their_hash, expected)
    assert json.loads(parsed["user"])["id"] == 42


def test_claims_require_numeric_user_id():
    with pytest.raises(ValueError):
        service._claims_to_user({"sub": "opaque"})
