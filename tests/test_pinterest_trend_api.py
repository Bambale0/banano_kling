import pytest

from bot.pinterest_trend_api import (
    _augmented_prompt,
    _measurement,
    _reference_urls,
    _validated_pinterest_url,
)
from bot.trend_api import TrendRunValidationError


def test_pinterest_url_accepts_only_expected_hosts():
    assert _validated_pinterest_url("https://www.pinterest.com/pin/123/") == (
        "https://www.pinterest.com/pin/123/"
    )
    assert _validated_pinterest_url("https://pin.it/abc123") == "https://pin.it/abc123"
    assert _validated_pinterest_url("https://i.pinimg.com/736x/a/b/c/photo.jpg").startswith(
        "https://i.pinimg.com/"
    )

    with pytest.raises(TrendRunValidationError):
        _validated_pinterest_url("https://evil.example/pinterest.com/pin/123")

    with pytest.raises(TrendRunValidationError):
        _validated_pinterest_url("file:///etc/passwd")


def test_pinterest_repeat_requires_exact_reference_then_user_photo():
    refs = _reference_urls(
        {
            "reference_urls": [
                "https://i.pinimg.com/reference.jpg",
                "https://tanyapi.chillcreative.ru/uploads/user.jpg",
            ]
        }
    )
    assert refs == (
        "https://i.pinimg.com/reference.jpg",
        "https://tanyapi.chillcreative.ru/uploads/user.jpg",
    )

    for invalid in ([], ["https://i.pinimg.com/reference.jpg"], ["a", "b", "c"]):
        with pytest.raises(TrendRunValidationError):
            _reference_urls({"reference_urls": invalid})


def test_measurements_are_optional_but_bounded():
    assert _measurement({}, "height_cm", minimum=120, maximum=230) is None
    assert _measurement({"height_cm": "165"}, "height_cm", minimum=120, maximum=230) == 165
    assert _measurement({"weight_kg": 55}, "weight_kg", minimum=30, maximum=250) == 55

    with pytest.raises(TrendRunValidationError):
        _measurement({"height_cm": 50}, "height_cm", minimum=120, maximum=230)
    with pytest.raises(TrendRunValidationError):
        _measurement({"weight_kg": "abc"}, "weight_kg", minimum=30, maximum=250)


def test_augmented_prompt_keeps_reference_roles_unambiguous():
    prompt = _augmented_prompt(
        "Create a realistic portrait.",
        height_cm=165,
        weight_kg=55,
    )

    assert "Input image 1 is the SOURCE / COMPOSITION REFERENCE" in prompt
    assert "Input image 2 is the USER / IDENTITY REFERENCE" in prompt
    assert "Do NOT copy the identity or face from image 1" in prompt
    assert "height 165 cm" in prompt
    assert "weight 55 kg" in prompt
    assert "never render the numbers or any text into the image" in prompt
