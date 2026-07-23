"""Regression tests for Nano Banana 2 APIYI prompt parity."""

from bot.services.nano_banana_2_service import (
    _REFERENCE_ONLY_PROMPT,
    _normalize_apiyi_prompt,
)


def test_apiyi_plain_prompt_is_not_modified():
    prompt = "Create a natural editorial portrait with soft window light."

    normalized, stripped = _normalize_apiyi_prompt(prompt)

    assert normalized == prompt
    assert stripped is False


def test_apiyi_removes_legacy_reference_guidance_wrapper():
    prompt = (
        "EDIT REQUEST (highest priority): Change the background to a bright studio.\n\n"
        "Reference guidance: Same-person preservation is the highest priority. "
        "Preserve facial identity exactly."
    )

    normalized, stripped = _normalize_apiyi_prompt(prompt)

    assert normalized == "Change the background to a bright studio."
    assert stripped is True
    assert "Reference guidance" not in normalized
    assert "highest priority" not in normalized


def test_apiyi_removes_wrapper_even_with_appended_safety_text():
    prompt = (
        "EDIT REQUEST (highest priority): Keep a natural face and realistic skin.\n\n"
        "Reference guidance: preserve face geometry exactly.\n\n"
        "safe, non-explicit editorial image"
    )

    normalized, stripped = _normalize_apiyi_prompt(prompt)

    assert normalized == "Keep a natural face and realistic skin."
    assert stripped is True


def test_apiyi_reference_only_request_uses_short_neutral_instruction():
    normalized, stripped = _normalize_apiyi_prompt(
        "Reference guidance: preserve every facial detail exactly."
    )

    assert normalized == _REFERENCE_ONLY_PROMPT
    assert stripped is True
    assert "caricaturing" in normalized
    assert "smoothing" in normalized


def test_apiyi_empty_prompt_stays_empty():
    normalized, stripped = _normalize_apiyi_prompt("   ")

    assert normalized == ""
    assert stripped is False
