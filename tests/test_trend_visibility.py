from pathlib import Path
from urllib.parse import urlencode
import json

from bot.trend_visibility import (
    sanitize_prompt_api_payload,
    sanitize_prompt_for_public,
    telegram_id_from_init_data,
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


def test_init_data_reader_extracts_telegram_user_id() -> None:
    init_data = urlencode({"user": json.dumps({"id": 123456, "first_name": "Test"})})
    assert telegram_id_from_init_data(init_data) == 123456
    assert telegram_id_from_init_data("broken") is None


def test_browser_auth_installs_prompt_privacy_middleware() -> None:
    source = Path("bot/browser_auth.py").read_text(encoding="utf-8")
    assert "trend_prompt_privacy_middleware" in source
    assert "app.middlewares.append(trend_prompt_privacy_middleware)" in source
    assert 'response.headers["Cache-Control"] = "no-store"' in source
