"""Regression tests for Nano Banana 2/APIYI playground parity."""

from bot.services.nano_banana_2_service import (
    APIYI_MODEL,
    APIYI_SAFETY_SETTINGS,
    DEFAULT_APIYI_MODEL,
    _build_apiyi_payload,
    _extract_apiyi_failure,
    _is_policy_failure,
    _normalize_apiyi_prompt,
)


def test_apiyi_uses_ga_model_by_default():
    assert DEFAULT_APIYI_MODEL == "gemini-3.1-flash-image"
    assert APIYI_MODEL
    assert not APIYI_MODEL.endswith("-preview")


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


def test_apiyi_removes_bot_generated_variant_suffix():
    prompt = (
        "Make the hair long and the skin glossy.\n\n"
        "For this single output: Use a slightly different composition and camera crop only. "
        "Keep the referenced face exactly identical."
    )

    normalized, stripped = _normalize_apiyi_prompt(prompt)

    assert normalized == "Make the hair long and the skin glossy."
    assert stripped is True


def test_apiyi_reference_only_wrapper_adds_no_hidden_prompt():
    normalized, stripped = _normalize_apiyi_prompt(
        "Reference guidance: preserve every facial detail exactly."
    )

    assert normalized == ""
    assert stripped is True


def test_apiyi_payload_has_no_system_instruction_and_disables_configurable_filters():
    payload = _build_apiyi_payload(
        prompt="Change the hairstyle to long loose curls.",
        reference_parts=[
            {
                "inlineData": {
                    "mimeType": "image/png",
                    "data": "ZmFrZQ==",
                }
            }
        ],
        aspect_ratio="3:4",
        resolution="4K",
    )

    assert "systemInstruction" not in payload
    assert payload["contents"][0]["role"] == "user"
    assert payload["contents"][0]["parts"][0] == {
        "text": "Change the hairstyle to long loose curls."
    }
    assert payload["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]
    assert payload["generationConfig"]["imageConfig"] == {
        "aspectRatio": "3:4",
        "imageSize": "4K",
    }
    assert payload["safetySettings"] == APIYI_SAFETY_SETTINGS
    assert all(item["threshold"] == "OFF" for item in payload["safetySettings"])


def test_apiyi_extracts_candidate_safety_reason():
    reason, ratings = _extract_apiyi_failure(
        {
            "candidates": [
                {
                    "finishReason": "IMAGE_SAFETY",
                    "safetyRatings": [
                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT"}
                    ],
                }
            ]
        }
    )

    assert reason == "IMAGE_SAFETY"
    assert len(ratings) == 1
    assert _is_policy_failure(reason) is True


def test_apiyi_extracts_prompt_block_reason():
    reason, _ratings = _extract_apiyi_failure(
        {"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}}
    )

    assert reason == "PROHIBITED_CONTENT"
    assert _is_policy_failure(reason) is True


def test_unknown_no_image_reason_is_retryable():
    assert _is_policy_failure("STOP") is False
    assert _is_policy_failure("") is False
