import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import urlencode

from bot.trend_visibility import (
    sanitize_prompt_api_payload,
    sanitize_prompt_for_public,
    verified_telegram_id_from_init_data,
)


def _trend() -> dict:
    return {
        "id": 1126,
        "author_id": 10,
        "title": "Закрытый тренд",
        "description": "Публичное описание",
        "category": "video",
        "tags": ["trend", "trend-video"],
        "preview_url": "/uploads/trend.mp4",
        "prompt_text": "SECRET PROMPT",
        "model": "seedance_2",
        "generation_settings": {
            "kind": "video",
            "user_input": "photo",
            "model": "seedance_2",
            "ratio": "9:16",
            "duration": 10,
            "quality": "4K",
            "kling_negative_prompt": "SECRET NEGATIVE",
        },
    }


def _signed_init_data(telegram_id: int, bot_token: str) -> str:
    fields = {
        "auth_date": "1776200000",
        "query_id": "test-query",
        "user": json.dumps({"id": telegram_id, "first_name": "Test"}, separators=(",", ":")),
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


def test_public_trend_keeps_only_runner_metadata() -> None:
    payload = sanitize_prompt_for_public(_trend())
    assert payload is not None
    assert payload["prompt_text"] == ""
    assert payload["model"] is None
    assert payload["generation_settings"] == {"kind": "video", "ratio": "9:16"}
    assert payload["prompt_hidden"] is True
    assert payload["prompt_actions_allowed"] is False
    assert payload["title"] == "Закрытый тренд"
    assert payload["preview_url"] == "/uploads/trend.mp4"
    assert payload["tags"] == ["trend", "trend-video"]


def test_regular_prompt_stays_usable() -> None:
    prompt = {
        "id": 5,
        "tags": ["portrait"],
        "prompt_text": "visible prompt",
        "model": "banana_pro",
        "generation_settings": {},
    }
    assert sanitize_prompt_for_public(prompt) == prompt


def test_prompt_api_payload_redacts_lists_and_details() -> None:
    detail = sanitize_prompt_api_payload({"ok": True, "prompt": _trend(), "link": "x"})
    listing = sanitize_prompt_api_payload({"ok": True, "prompts": [_trend()]})

    assert detail["prompt"]["prompt_text"] == ""
    assert detail["prompt"]["generation_settings"] == {"kind": "video", "ratio": "9:16"}
    assert listing["prompts"][0]["model"] is None
    assert listing["prompts"][0]["generation_settings"] == {"kind": "video", "ratio": "9:16"}


def test_admin_bypass_requires_valid_telegram_signature() -> None:
    token = "123456:TEST_TOKEN"
    init_data = _signed_init_data(123456, token)
    assert verified_telegram_id_from_init_data(init_data, token) == 123456
    assert verified_telegram_id_from_init_data(init_data, "wrong-token") is None
    assert verified_telegram_id_from_init_data("user=%7B%22id%22%3A123456%7D", token) is None


def test_browser_auth_installs_prompt_privacy_middleware() -> None:
    source = Path("bot/browser_auth.py").read_text(encoding="utf-8")
    assert "trend_prompt_privacy_middleware" in source
    assert "verified_telegram_id_from_init_data(init_data, config.BOT_TOKEN)" in source
    assert "app.middlewares.append(trend_prompt_privacy_middleware)" in source
    assert 'response.headers["Cache-Control"] = "no-store"' in source


def test_prompt_privacy_middleware_does_not_consume_body_before_handler() -> None:
    source = Path("bot/browser_auth.py").read_text(encoding="utf-8")
    start = source.index("async def trend_prompt_privacy_middleware")
    end = source.index("\n\ndef setup_browser_auth_routes", start)
    middleware = source[start:end]

    handler_call = middleware.index("response = await handler(request)")
    json_read = middleware.index("body = await request.json()")
    assert handler_call < json_read
