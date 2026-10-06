"""Seedance 2.5 character identity-transfer contract.

This is a provider-facing prompt contract, not marketing copy. It assigns a
single purpose to each multimodal reference so Seedance does not treat the
source video's actor as a competing identity reference.
"""
from __future__ import annotations

SEEDANCE_25_PROMPT_MAX_CHARS = 30_000
IDENTITY_ROLE_VERSION = "apix-v1"

MAX_IDENTITY_IMAGES = 3


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


def build_identity_transfer_prompt(user_prompt: str, *, image_count: int) -> str:
    """Build the tested role-separated prompt for one-to-three identity refs."""
    if image_count < 1 or image_count > MAX_IDENTITY_IMAGES:
        raise ValueError(
            f"Seedance Identity Transfer expects 1-{MAX_IDENTITY_IMAGES} identity photos"
        )

    if image_count == 1:
        identity_intro = (
            "@Image1 is the sole authoritative identity and appearance reference "
            "for the main person."
        )
        image_roles = "Use @Image1 as the identity anchor in every visible frame and angle."
        represented_by = "@Image1"
    else:
        extras = " and ".join(f"@Image{index}" for index in range(2, image_count + 1))
        identity_intro = (
            "@Image1 is the primary identity and appearance reference for the main person. "
            f"{extras} are additional identity references for the same person and must only "
            "reinforce the same identity across different head angles."
        )
        image_roles = (
            "Use @Image1 as the main identity anchor. "
            f"Use {extras} only to improve identity consistency during head turns and angle changes."
        )
        represented_by = ", ".join(f"@Image{index}" for index in range(1, image_count + 1))

    prompt = f"""\
{identity_intro}

@Video1 is only the reference for motion, body movement, performance, camera movement, framing, timing, background, lighting and scene continuity.

Replace only the main person in @Video1 with the person represented by {represented_by}.

Preserve the same facial identity throughout the whole video: facial shape, eye shape and color, nose, lips, jawline, skin tone, age, hairline, hair color, hairstyle and recognizability.

{image_roles}

Do not inherit, preserve, average, morph or blend the original person's facial identity from @Video1 with the identity from the image references.
Preserve all motion, pose, performance, camera work, framing, timing, environment, lighting and unrelated people from @Video1.
Do not redesign the scene or change unrelated subjects."""

    extra = str(user_prompt or "").strip()
    if extra:
        prompt += f"\n\nAdditional user instruction:\n{extra}"
    if len(prompt) > SEEDANCE_25_PROMPT_MAX_CHARS:
        raise ValueError("Seedance 2.5 Identity Transfer prompt must be at most 30,000 characters after reference-role instructions are added")
    return prompt
