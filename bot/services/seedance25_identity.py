"""Direct Seedance character edits; no intermediate image generation.

A complete instruction naming both reference roles is the provider prompt,
not an addition to a hidden identity wrapper. Empty or short legacy wishes
use an audited, editable direct-edit template.
"""
from __future__ import annotations

import re
from string import Formatter

SEEDANCE_25_PROMPT_MAX_CHARS = 20_480
IDENTITY_ROLE_VERSION = "direct-edit-v1"
MAX_IDENTITY_IMAGES = 3
IDENTITY_TEMPLATE_SETTING = "seedance25_direct_edit_template"
MAX_TEMPLATE_CHARS = 8_000
DEFAULT_IDENTITY_TEMPLATE = (
    "Video edit: replace the main person's facial features and hair in @Video1 "
    "with the person shown in {identity_images}. All photos show the same person. "
    "Keep the original clothing, body pose, actions, expressions, objects, camera, "
    "timing, lighting and background from @Video1. Do not blend the original face "
    "with the new face."
)


def validate_identity_transfer_refs(*, images: list[str], videos: list[str], audio: list[str] | None = None,
                                    first_frame: str | None = None, last_frame: str | None = None) -> None:
    """Require one source video and one-to-three identity photos."""
    if audio or first_frame or last_frame:
        raise ValueError("Seedance Identity Transfer cannot use audio or first/last-frame inputs")
    if not images:
        raise ValueError("Seedance Identity Transfer requires at least one identity photo")
    if len(images) > MAX_IDENTITY_IMAGES:
        raise ValueError(
            f"Seedance Identity Transfer supports at most {MAX_IDENTITY_IMAGES} identity photos"
        )
    if len(videos) != 1:
        raise ValueError("Seedance Identity Transfer requires one source video")


def validate_identity_template(text: str) -> str:
    """Allow only the reference-list placeholder, never Python attribute lookup."""
    cleaned = str(text or "").strip()
    if not cleaned or len(cleaned) > MAX_TEMPLATE_CHARS:
        raise ValueError(f"Edit template must contain 1-{MAX_TEMPLATE_CHARS} characters")
    try:
        fields = list(Formatter().parse(cleaned))
    except ValueError as exc:
        raise ValueError("Invalid edit template placeholders") from exc
    for _, field, spec, conversion in fields:
        if field is not None and (field != "identity_images" or spec or conversion):
            raise ValueError("Only {identity_images} is allowed in the edit template")
    if not any(field == "identity_images" for _, field, _, _ in fields) or not re.search(r"@Video1(?!\w)", cleaned):
        raise ValueError("Edit template must include {identity_images} and @Video1")
    # Fixed extra image/audio tags would break one-photo launches. Additional
    # images must come from the validated placeholder, not combined ordinals.
    for kind, index in re.findall(r"@\s*(image|img|video|audio)\s*[_-]?\s*(\d+)(?!\w)", cleaned, re.IGNORECASE):
        if kind.lower() == "audio" or int(index) != 1:
            raise ValueError("Edit template refers to unavailable media; use {identity_images}")
    return cleaned


def _has_direct_reference_roles(prompt: str, *, image_count: int) -> bool:
    """Complete instructions name both inputs; old short wishes remain supported."""
    from bot.services.seedance_reference_binding import (
        canonicalize_seedance_reference_tags,
    )

    canonical = canonicalize_seedance_reference_tags(prompt, image_count=image_count, video_count=1)
    return bool(re.search(r"@Image1(?!\w)", canonical) and re.search(r"@Video1(?!\w)", canonical))


def build_identity_transfer_prompt(user_prompt: str, *, image_count: int,
                                   template: str | None = None) -> str:
    """Keep complete instructions intact; otherwise render the direct edit recipe."""
    if image_count < 1 or image_count > MAX_IDENTITY_IMAGES:
        raise ValueError(f"Seedance Identity Transfer expects 1-{MAX_IDENTITY_IMAGES} identity photos")
    prompt = str(user_prompt or "").strip()
    if not _has_direct_reference_roles(prompt, image_count=image_count):
        selected = DEFAULT_IDENTITY_TEMPLATE if template is None else validate_identity_template(template)
        direct = selected.format(identity_images=", ".join(f"@Image{i}" for i in range(1, image_count + 1)))
        prompt = direct + ("\n\n" + prompt if prompt else "")
    if len(prompt) > SEEDANCE_25_PROMPT_MAX_CHARS:
        raise ValueError(
            f"Seedance 2.5 direct edit prompt must be at most {SEEDANCE_25_PROMPT_MAX_CHARS} characters"
        )
    return prompt


async def get_identity_edit_template() -> str:
    from bot.database import get_bot_setting

    configured = await get_bot_setting(IDENTITY_TEMPLATE_SETTING, "")
    return validate_identity_template(configured) if configured else DEFAULT_IDENTITY_TEMPLATE


async def resolve_identity_transfer_prompt(user_prompt: str, *, image_count: int) -> str:
    """Resolve once before debit; custom instructions never need configuration."""
    if _has_direct_reference_roles(str(user_prompt or ""), image_count=image_count):
        return build_identity_transfer_prompt(user_prompt, image_count=image_count)
    template = await get_identity_edit_template()
    return build_identity_transfer_prompt(user_prompt, image_count=image_count, template=template)


async def save_identity_edit_template(text: str, *, admin_id: int) -> None:
    from bot.database import set_bot_setting

    cleaned = validate_identity_template(text)
    await set_bot_setting(IDENTITY_TEMPLATE_SETTING, cleaned, updated_by_telegram_id=admin_id)


async def reset_identity_edit_template(*, admin_id: int) -> None:
    from bot.database import set_bot_setting

    await set_bot_setting(IDENTITY_TEMPLATE_SETTING, "", updated_by_telegram_id=admin_id)
