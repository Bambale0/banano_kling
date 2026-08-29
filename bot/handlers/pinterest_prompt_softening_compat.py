"""Keep Pinterest AI reference guidance subordinate to the creative request.

Pinterest needs explicit reference roles, but the provider must not receive a
long pseudo-system contract as the main creative prompt. This compatibility
layer keeps the user's/base Pinterest instruction first and reduces the role
rules to a short visual-reference hint.
"""

from __future__ import annotations

import importlib
import logging
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

PINTEREST_REFERENCE_GUIDANCE_MARKER = "PINTEREST_REFERENCE_GUIDANCE_V3"
_INSTALLED = False


def _measurement_text(height_cm: int | None, weight_kg: int | None) -> str:
    values: list[str] = []
    if height_cm is not None:
        values.append(f"height {height_cm} cm")
    if weight_kg is not None:
        values.append(f"weight {weight_kg} kg")
    return ", ".join(values) if values else "not provided"


def _soft_runtime_prompt(
    base_prompt: str,
    *,
    height_cm: int | None,
    weight_kg: int | None,
) -> str:
    """Build Pinterest scene-first guidance without a legalistic instruction wall."""

    from bot.pinterest_trend_flow_contract import PINTEREST_PROMPT_MARKER

    creative_prompt = str(base_prompt or "").strip()
    measurements = _measurement_text(height_cm, weight_kg)
    prefix = f"{creative_prompt}\n\n" if creative_prompt else ""
    return (
        f"{prefix}{PINTEREST_PROMPT_MARKER}\n"
        f"{PINTEREST_REFERENCE_GUIDANCE_MARKER}\n"
        "Reference guidance:\n"
        "- Image 1 = SCENE_REFERENCE. Use its visual setup: pose, composition, "
        "camera, clothing, lighting, background and mood. Natural adjustments are "
        "allowed when needed for the user's anatomy and likeness.\n"
        "- Image 2 = USER_IDENTITY_REFERENCE. This is the only identity anchor. "
        "Keep that person clearly recognizable, including their own face, apparent "
        "age, skin tone, hair color/length and natural build.\n"
        "- Images 3..N, when present, are extra likeness evidence only.\n"
        "- Create a new natural photograph of the user in the Pinterest visual "
        "setup. Do not copy or blend the scene person's identity.\n"
        f"- User measurements: {measurements}. Treat them only as an approximate "
        "body-scale hint.\n"
        "Return one coherent photorealistic image. Do not add UI, captions, a "
        "collage or a watermark unless the creative request explicitly asks for text."
    )


def _soft_provider_payload(
    prompt: str,
    image_input: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Reorder Pinterest refs for Nano Banana Pro with concise role guidance."""

    service = importlib.import_module("bot.services.nano_banana_pro_service")

    refs = list(image_input or [])
    raw_prompt = str(prompt or "")
    if (
        service.PINTEREST_PROMPT_MARKER not in raw_prompt
        or service.PINTEREST_PROVIDER_SAFE_MARKER in raw_prompt
        or len(refs) < 2
    ):
        return raw_prompt, refs

    scene_reference = refs[0]
    identity_reference = refs[1]
    base_prompt = raw_prompt.split(service.PINTEREST_PROMPT_MARKER, 1)[0].strip()
    measurement_line = service._pinterest_measurement_line(raw_prompt)
    prefix = f"{base_prompt}\n\n" if base_prompt else ""
    provider_prompt = (
        f"{prefix}{service.PINTEREST_PROMPT_MARKER}\n"
        f"{service.PINTEREST_PROVIDER_SAFE_MARKER}\n"
        f"{PINTEREST_REFERENCE_GUIDANCE_MARKER}\n"
        "Reference guidance for the two images sent to the provider:\n"
        "- Image 1 = USER_IDENTITY_REFERENCE. This is the only identity anchor. "
        "Keep this person recognizable and use their own facial features, age "
        "impression, skin tone, hair color/length and natural build.\n"
        "- Image 2 = SCENE_REFERENCE. Use its pose, composition, camera, clothing, "
        "lighting, background and overall photographic mood.\n"
        "- No Images 3..N are sent to the provider; extra user photos remain "
        "likeness evidence in internal metadata only.\n"
        "- Create a natural new photograph of the person from Image 1 in the visual "
        "setup of Image 2. Do not copy or blend the identity of the person in Image 2.\n"
        f"{measurement_line}\n"
        "Return one coherent photorealistic image without UI, collage or watermark."
    )
    logger.info(
        "Pinterest AI provider prompt softened: stored_refs=%s provider_refs=2",
        len(refs),
    )
    return provider_prompt, [identity_reference, scene_reference]


def _soft_legacy_provider_prompt(*, measurements: str = "not provided") -> str:
    """Keep old saved Pinterest runs compatible without replaying the old contract."""

    from bot.handlers import pinterest_flow_contract_compat as legacy

    return (
        f"{legacy._DISPLAY_PROMPT}\n\n"
        f"{PINTEREST_REFERENCE_GUIDANCE_MARKER}\n"
        "Reference guidance:\n"
        "- Image 1 = USER_IDENTITY_REFERENCE. Keep that person recognizable.\n"
        "- Image 2 = SCENE_REFERENCE. Use it for pose, composition, camera, clothing, "
        "lighting and background.\n"
        "- Create a natural new photo of the user in that visual setup without "
        "copying or blending the scene person's identity.\n"
        f"- User measurements: {measurements}. Treat them only as an approximate "
        "body-scale hint.\n"
        "Return one coherent photorealistic image without UI, collage or watermark."
    )


def install_pinterest_prompt_softening() -> None:
    """Install concise Pinterest prompts across current and legacy provider paths."""

    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from bot import pinterest_trend_api as pinterest_api
    from bot.handlers import pinterest_flow_contract_compat as legacy
    from bot.handlers import trend_route_compat

    banana_pro = importlib.import_module("bot.services.nano_banana_pro_service")
    original_legacy_detector = legacy._is_pinterest_prompt

    def detects_soft_pinterest_prompt(prompt: str | None) -> bool:
        return (
            PINTEREST_REFERENCE_GUIDANCE_MARKER in str(prompt or "")
            or original_legacy_detector(prompt)
        )

    legacy._is_pinterest_prompt = detects_soft_pinterest_prompt
    legacy._pinterest_provider_prompt = _soft_legacy_provider_prompt
    banana_pro._pinterest_provider_payload = _soft_provider_payload
    pinterest_api._augmented_prompt = _soft_runtime_prompt

    original_contract_installer = trend_route_compat.install_pinterest_trend_flow_contract

    @wraps(original_contract_installer)
    def install_contract_then_soften() -> Any:
        result = original_contract_installer()
        # The strict installer replaces pinterest_api._augmented_prompt. Put the
        # concise runtime prompt back after all validation/privacy hooks are set.
        pinterest_api._augmented_prompt = _soft_runtime_prompt
        banana_pro._pinterest_provider_payload = _soft_provider_payload
        legacy._pinterest_provider_prompt = _soft_legacy_provider_prompt
        legacy._is_pinterest_prompt = detects_soft_pinterest_prompt
        logger.info("Pinterest AI concise reference guidance installed")
        return result

    trend_route_compat.install_pinterest_trend_flow_contract = install_contract_then_soften
    trend_route_compat._pinterest_prompt_softening_installed = True
