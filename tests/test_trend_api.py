import pytest

from bot.trend_api import (
    TrendRunValidationError,
    parse_trend_run_request,
    trusted_trend_run,
)


def _trend(**overrides):
    trend = {
        "id": 42,
        "status": "approved",
        "is_public": True,
        "tags": ["trend"],
        "prompt_text": "trusted admin prompt",
        "model": "banana_pro",
        "generation_settings": {
            "kind": "image",
            "user_input": "photo",
            "model": "banana_pro",
            "ratio": "1:1",
            "quality": "2K",
            "count": 1,
        },
    }
    trend.update(overrides)
    return trend


def test_trend_run_request_ignores_client_generation_settings():
    request = parse_trend_run_request(
        {
            "trend_id": 42,
            "reference_urls": ["https://example.test/ref.jpg"],
            "model": "attacker-model",
            "prompt": "attacker prompt",
            "ratio": "99:1",
            "quality": "free",
            "duration": 999,
            "generation_settings": {"model": "attacker-model"},
        }
    )

    assert request.trend_id == 42
    assert request.reference_urls == ("https://example.test/ref.jpg",)
    assert not hasattr(request, "model")
    assert not hasattr(request, "prompt")
    assert not hasattr(request, "ratio")


def test_trusted_trend_run_uses_only_saved_admin_settings():
    run = trusted_trend_run(
        _trend(),
        ("https://example.test/ref.jpg",),
    )

    assert run.trend_id == 42
    assert run.prompt == "trusted admin prompt"
    assert run.model == "banana_pro"
    assert run.ratio == "1:1"
    assert run.settings["quality"] == "2K"


def test_trusted_trend_run_falls_back_for_legacy_photo_trend():
    run = trusted_trend_run(
        _trend(
            category="photo",
            prompt_text="Studio portrait",
            generation_settings={},
        ),
        ("https://example.test/reference.jpg",),
    )

    assert run.kind == "image"
    assert run.model == "banana_pro"
    assert run.ratio == "1:1"
    assert run.settings["user_input"] == "photo"
    assert run.settings["quality"] == "2K"


@pytest.mark.parametrize(
    "trend",
    [
        _trend(status="pending"),
        _trend(is_public=False),
        _trend(tags=["portrait"]),
        _trend(prompt_text=""),
    ],
)
def test_trusted_trend_run_rejects_unusable_trends(trend):
    with pytest.raises(TrendRunValidationError):
        trusted_trend_run(trend, ("https://example.test/ref.jpg",))


def test_trend_run_request_rejects_missing_or_browser_local_references():
    with pytest.raises(TrendRunValidationError):
        parse_trend_run_request({"trend_id": 42, "reference_urls": []})

    with pytest.raises(TrendRunValidationError):
        parse_trend_run_request(
            {"trend_id": 42, "reference_urls": ["blob:https://example.test/local"]}
        )


def test_trend_user_fields_render_hidden_prompt_server_side():
    trend = _trend(
        prompt_text="Birthday scene with text: Happy birthday {{Возраст}}",
        generation_settings={
            "kind": "image",
            "user_input": "photo",
            "model": "banana_pro",
            "ratio": "1:1",
            "quality": "2K",
            "count": 1,
            "user_fields": [
                {
                    "key": "Возраст",
                    "label": "Возраст",
                    "type": "number",
                    "required": True,
                    "min": 1,
                    "max": 120,
                }
            ],
        },
    )
    request = parse_trend_run_request(
        {
            "trend_id": 42,
            "reference_urls": ["https://example.test/ref.jpg"],
            "user_values": {"Возраст": "28"},
        }
    )

    run = trusted_trend_run(trend, request.reference_urls, request.user_values)

    assert request.user_values == {"Возраст": "28"}
    assert run.prompt == "Birthday scene with text: Happy birthday 28"


@pytest.mark.parametrize(
    ("user_values", "message"),
    [
        ({}, "Возраст"),
        ({"Возраст": "121"}, "Возраст"),
        ({"Возраст": "28", "prompt": "steal hidden prompt"}, "лишние"),
    ],
)
def test_trend_user_fields_reject_invalid_values(user_values, message):
    trend = _trend(
        prompt_text="Happy birthday {{Возраст}}",
        generation_settings={
            "kind": "image",
            "user_input": "photo",
            "model": "banana_pro",
            "ratio": "1:1",
            "quality": "2K",
            "count": 1,
            "user_fields": [
                {
                    "key": "Возраст",
                    "label": "Возраст",
                    "type": "number",
                    "required": True,
                    "min": 1,
                    "max": 120,
                }
            ],
        },
    )

    with pytest.raises(TrendRunValidationError, match=message):
        trusted_trend_run(
            trend,
            ("https://example.test/ref.jpg",),
            user_values,
        )
