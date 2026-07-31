import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

import pytest

from bot.browser_auth import _build_browser_init_data, _verify_telegram_login


def _signed_login_payload(bot_token: str, **overrides):
    payload = {
        "id": "123456789",
        "first_name": "Игорь",
        "last_name": "",
        "username": "igor_test",
        "photo_url": "https://example.test/avatar.jpg",
        "auth_date": str(int(time.time())),
    }
    payload.update({key: str(value) for key, value in overrides.items()})
    data_check_string = "\n".join(f"{key}={payload[key]}" for key in sorted(payload))
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    payload["hash"] = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return payload


def _validate_webapp_signature(init_data: str, bot_token: str):
    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = fields.pop("hash")
    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert hmac.compare_digest(expected_hash, received_hash)
    return fields


def test_browser_login_verifies_telegram_widget_signature():
    token = "123456:TEST_TOKEN"
    payload = _signed_login_payload(token)

    user = _verify_telegram_login(payload, token)

    assert user["id"] == 123456789
    assert user["first_name"] == "Игорь"
    assert user["username"] == "igor_test"


def test_browser_login_rejects_tampered_payload():
    token = "123456:TEST_TOKEN"
    payload = _signed_login_payload(token)
    payload["first_name"] = "Подмена"

    with pytest.raises(ValueError, match="Invalid Telegram login signature"):
        _verify_telegram_login(payload, token)


def test_browser_login_rejects_expired_payload():
    token = "123456:TEST_TOKEN"
    payload = _signed_login_payload(token, auth_date=int(time.time()) - 3600)

    with pytest.raises(ValueError, match="Expired Telegram login"):
        _verify_telegram_login(payload, token)


def test_browser_session_is_valid_webapp_init_data():
    token = "123456:TEST_TOKEN"
    user = _verify_telegram_login(_signed_login_payload(token), token)

    init_data = _build_browser_init_data(user, token)
    fields = _validate_webapp_signature(init_data, token)
    decoded_user = json.loads(fields["user"])

    assert decoded_user["id"] == 123456789
    assert decoded_user["first_name"] == "Игорь"
    assert fields["query_id"].startswith("browser_")
