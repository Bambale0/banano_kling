from __future__ import annotations

from pathlib import Path

from bot.handlers.pinterest_prompt_softening_compat import (
    PINTEREST_REFERENCE_GUIDANCE_MARKER,
    _soft_legacy_provider_prompt,
    _soft_provider_payload,
    _soft_runtime_prompt,
)
from bot.pinterest_trend_flow_contract import PINTEREST_PROMPT_MARKER
from bot.services.nano_banana_pro_service import PINTEREST_PROVIDER_SAFE_MARKER

ROOT = Path(__file__).resolve().parents[1]
SCENE = "https://example.com/scene.jpg"
USER = "https://example.com/user.jpg"
EXTRA = "https://example.com/extra.jpg"

_FORBIDDEN_LITERAL_CONTRACT_PHRASES = (
    "STRICT IDENTITY PRESERVATION CONTRACT",
    "TASK — TRANSFER THE PERSON INTO THE SCENE",
    "SCENE_REFERENCE LOCK",
    "USER IDENTITY LOCK",
    "PARTIAL TRANSFER GUARD",
    "SOURCE-COPY GUARD",
    "IDENTITY EVIDENCE GUARD",
    "invalid result",
    "exact pose and body geometry",
    "exact camera viewpoint",
    "DO NOT SWAP",
)


def _assert_not_legalistic(prompt: str) -> None:
    for phrase in _FORBIDDEN_LITERAL_CONTRACT_PHRASES:
        assert phrase not in prompt


def test_runtime_prompt_keeps_creative_request_first_and_guidance_secondary() -> None:
    creative = "Recreate the warm rooftop portrait with a candid editorial mood."
    prompt = _soft_runtime_prompt(creative, height_cm=168, weight_kg=57)

    assert prompt.startswith(creative)
    assert PINTEREST_PROMPT_MARKER in prompt
    assert PINTEREST_REFERENCE_GUIDANCE_MARKER in prompt
    assert "Image 1 = SCENE_REFERENCE" in prompt
    assert "Image 2 = USER_IDENTITY_REFERENCE" in prompt
    assert "height 168 cm" in prompt
    assert "weight 57 kg" in prompt
    _assert_not_legalistic(prompt)


def test_provider_prompt_reorders_refs_without_overpowering_creative_request() -> None:
    creative = "Recreate the rooftop portrait naturally."
    runtime_prompt = _soft_runtime_prompt(creative, height_cm=168, weight_kg=57)

    provider_prompt, provider_refs = _soft_provider_payload(
        runtime_prompt,
        [SCENE, USER, EXTRA],
    )

    assert provider_refs == [USER, SCENE]
    assert provider_prompt.startswith(creative)
    assert PINTEREST_PROVIDER_SAFE_MARKER in provider_prompt
    assert PINTEREST_REFERENCE_GUIDANCE_MARKER in provider_prompt
    assert "Image 1 = USER_IDENTITY_REFERENCE" in provider_prompt
    assert "Image 2 = SCENE_REFERENCE" in provider_prompt
    assert "No Images 3..N are sent to the provider" in provider_prompt
    _assert_not_legalistic(provider_prompt)


def test_provider_prompt_is_idempotent() -> None:
    runtime_prompt = _soft_runtime_prompt("Recreate naturally.", height_cm=170, weight_kg=60)
    first_prompt, first_refs = _soft_provider_payload(runtime_prompt, [SCENE, USER])
    second_prompt, second_refs = _soft_provider_payload(first_prompt, first_refs)

    assert second_prompt == first_prompt
    assert second_refs == first_refs


def test_non_pinterest_provider_request_is_unchanged() -> None:
    prompt = "Create a minimal product photo on a white background."
    refs = [USER, SCENE]

    provider_prompt, provider_refs = _soft_provider_payload(prompt, refs)

    assert provider_prompt == prompt
    assert provider_refs == refs


def test_legacy_pinterest_runs_also_drop_the_old_instruction_wall() -> None:
    prompt = _soft_legacy_provider_prompt(measurements="height 170 cm, weight 60 kg")

    assert prompt.startswith("Pinterest AI:")
    assert PINTEREST_REFERENCE_GUIDANCE_MARKER in prompt
    assert "Image 1 = USER_IDENTITY_REFERENCE" in prompt
    assert "Image 2 = SCENE_REFERENCE" in prompt
    _assert_not_legalistic(prompt)


def test_production_install_hook_is_wired_before_generation_routes() -> None:
    source = (ROOT / "bot/handlers/repeat_run_confirm_compat.py").read_text(encoding="utf-8")

    assert "install_pinterest_prompt_softening" in source
    assert "install_pinterest_prompt_softening()" in source
