import pytest

from bot import pinterest_trend_api as pinterest_api
from bot.pinterest_trend_api import (
    _augmented_prompt,
    _lock_pinterest_run,
    _measurement,
    _reference_urls,
    _validated_pinterest_url,
)
from bot.trend_api import TrustedTrendRun, TrendRunValidationError


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

    with pytest.raises(TrendRunValidationError):
        _reference_urls(
            {
                "reference_urls": [
                    "https://i.pinimg.com/same.jpg",
                    "https://i.pinimg.com/same.jpg",
                ]
            }
        )


def test_measurements_are_optional_but_bounded():
    assert _measurement({}, "height_cm", minimum=120, maximum=230) is None
    assert _measurement({"height_cm": "165"}, "height_cm", minimum=120, maximum=230) == 165
    assert _measurement({"weight_kg": 55}, "weight_kg", minimum=30, maximum=250) == 55

    with pytest.raises(TrendRunValidationError):
        _measurement({"height_cm": 50}, "height_cm", minimum=120, maximum=230)
    with pytest.raises(TrendRunValidationError):
        _measurement({"weight_kg": "abc"}, "weight_kg", minimum=30, maximum=250)


def test_augmented_prompt_keeps_reference_roles_and_identity_unambiguous():
    prompt = _augmented_prompt(
        "Create a realistic portrait.",
        height_cm=165,
        weight_kg=55,
    )

    assert "Image 1 = SCENE_REFERENCE" in prompt
    assert "Image 2 = USER_IDENTITY_REFERENCE" in prompt
    assert "only identity anchor" in prompt
    assert "identity from USER_IDENTITY_REFERENCE always wins" in prompt
    assert "Do NOT copy the face, identity" in prompt
    assert "Do NOT beautify, redesign, replace, average, or blend" in prompt
    assert "Follow the requested transformation as literally as possible" in prompt
    assert "Prefer faithful execution over artistic reinterpretation" in prompt
    assert "height 165 cm" in prompt
    assert "weight 55 kg" in prompt
    assert "never render these numbers" in prompt


async def test_pinterest_run_is_hard_locked_to_banana_pro_2k():
    stored = TrustedTrendRun(
        trend_id=42,
        kind="image",
        prompt="admin changed prompt",
        model="seedream_edit",
        ratio="1:1",
        reference_urls=(
            "https://i.pinimg.com/reference.jpg",
            "https://tanyapi.chillcreative.ru/uploads/user.jpg",
        ),
        settings={"quality": "4K", "count": 3},
    )

    # No scene URL probe available: keep the configured default ratio.
    locked = await _lock_pinterest_run(stored, height_cm=175, weight_kg=78)

    assert locked.model == "banana_pro"
    assert locked.ratio == "9:16"
    assert locked.settings["ratio"] == "9:16"
    # Provider order is identity-first, scene-last for nano-banana-pro.
    assert locked.reference_urls == (
        "https://tanyapi.chillcreative.ru/uploads/user.jpg",
        "https://i.pinimg.com/reference.jpg",
    )
    assert locked.settings["quality"] == "2K"
    assert locked.settings["count"] == 1
    assert locked.settings["reference_count"] == 2
    assert locked.settings["reference_labels"] == ["РЕФЕРЕНС", "ТЫ"]
    assert "SCENE_REFERENCE" in locked.prompt
    assert "USER_IDENTITY_REFERENCE" in locked.prompt
    assert "height 175 cm" in locked.prompt
    assert "weight 78 kg" in locked.prompt
    assert "admin changed prompt" not in locked.prompt


async def test_lock_pinterest_run_matches_ratio_to_scene_reference(monkeypatch):
    async def fake_probe(url: str):
        assert url == "https://i.pinimg.com/reference.jpg"
        return 3000, 4000

    monkeypatch.setattr(pinterest_api, "probe_image_size", fake_probe)

    stored = TrustedTrendRun(
        trend_id=42,
        kind="image",
        prompt="base",
        model="banana_pro",
        ratio="9:16",
        reference_urls=(
            "https://i.pinimg.com/reference.jpg",
            "https://tanyapi.chillcreative.ru/uploads/user.jpg",
        ),
        settings={"quality": "2K", "count": 1},
    )

    locked = await _lock_pinterest_run(
        stored,
        height_cm=170,
        weight_kg=60,
        scene_url="https://i.pinimg.com/reference.jpg",
    )

    # A 3:4 source must stay 3:4 instead of being stretched to 9:16.
    assert locked.ratio == "3:4"
    assert locked.settings["ratio"] == "3:4"


async def test_lock_pinterest_run_keeps_ratio_when_probe_fails(monkeypatch):
    async def failing_probe(url: str):
        return None

    monkeypatch.setattr(pinterest_api, "probe_image_size", failing_probe)

    stored = TrustedTrendRun(
        trend_id=42,
        kind="image",
        prompt="base",
        model="banana_pro",
        ratio="9:16",
        reference_urls=(
            "https://i.pinimg.com/broken.jpg",
            "https://tanyapi.chillcreative.ru/uploads/user.jpg",
        ),
        settings={"quality": "2K", "count": 1},
    )

    locked = await _lock_pinterest_run(
        stored,
        height_cm=170,
        weight_kg=60,
        scene_url="https://i.pinimg.com/broken.jpg",
    )

    assert locked.ratio == "9:16"
