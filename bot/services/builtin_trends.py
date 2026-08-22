from __future__ import annotations

from copy import deepcopy
from typing import Any

PINTEREST_REPEAT_TREND_ID = 900_000_001
PINTEREST_REPEAT_TREND_TITLE = "Повтори фото с Pinterest"
PINTEREST_REPEAT_REFERENCE_HINT = (
    "Фото 1 — референс Pinterest: композиция, поза, ракурс, одежда, фон и свет. "
    "Фото 2 — ваше фото: лицо и идентичность."
)

PINTEREST_REPEAT_PROMPT = """Use the two input images with strict, separate roles.

IMAGE 1 is the TARGET PINTEREST REFERENCE. Recreate IMAGE 1 as faithfully as possible: composition, framing, crop, camera angle, perspective, pose, body position, hand placement, clothing and styling, environment, background, props, lighting direction and softness, shadows, color palette, color grading, lens look, depth of field, and overall mood.

IMAGE 2 is the USER IDENTITY REFERENCE. Use IMAGE 2 only for the person's identity and recognizable facial features. The generated person must clearly be the same person as IMAGE 2. Preserve their face shape, eyes, eyebrows, nose, lips, skin tone, age range, and distinctive identity cues. Do not copy the face or identity of the person from IMAGE 1.

Final result: the scene should look like IMAGE 1 was recreated with the person from IMAGE 2 in it. Keep the pose, styling, clothing, scene, light, framing, and visual language from IMAGE 1 while preserving the user's identity from IMAGE 2. Maintain photorealistic anatomy, natural skin texture, correct hands and proportions. Do not create a collage, split screen, before/after layout, captions, logos, or watermarks."""


def pinterest_repeat_trend() -> dict[str, Any]:
    """Return the trusted server-side recipe for the built-in Pinterest trend."""

    return {
        "id": PINTEREST_REPEAT_TREND_ID,
        "author_id": 0,
        "title": PINTEREST_REPEAT_TREND_TITLE,
        "description": (
            "Повторяет композицию, позу, ракурс, стиль и свет Pinterest-референса, "
            "но переносит в кадр именно вашу внешность."
        ),
        "category": "photo",
        "prompt_text": PINTEREST_REPEAT_PROMPT,
        "preview_url": None,
        "model": "banana_pro",
        "tags": ["trend", "builtin-trend", "pinterest-repeat"],
        "generation_settings": {
            "kind": "image",
            "user_input": "photo",
            "model": "banana_pro",
            "ratio": "auto",
            "required_reference_count": 2,
            "reference_hint": PINTEREST_REPEAT_REFERENCE_HINT,
            "quality": "2K",
            "count": 1,
            "nsfw_checker": False,
            "nsfw_enabled": False,
        },
        "likes": 0,
        "uses_count": 0,
        "is_public": True,
        "status": "approved",
    }


def get_builtin_trend(prompt_id: int | str) -> dict[str, Any] | None:
    try:
        normalized_id = int(prompt_id)
    except (TypeError, ValueError):
        return None
    if normalized_id != PINTEREST_REPEAT_TREND_ID:
        return None
    return deepcopy(pinterest_repeat_trend())


def is_builtin_auto_ratio_trend(
    trend_id: int | str,
    *,
    model: str,
    ratio: str,
) -> bool:
    """Allow provider-supported auto sizing only for the built-in recipe."""

    try:
        normalized_id = int(trend_id)
    except (TypeError, ValueError):
        return False
    return (
        normalized_id == PINTEREST_REPEAT_TREND_ID
        and model == "banana_pro"
        and ratio == "auto"
    )


def install_builtin_trend_runtime() -> None:
    """Install built-in trend lookup without changing normal database prompts."""

    from bot import trend_api as trend_api_module

    if getattr(trend_api_module, "_builtin_trends_installed", False):
        return

    original_get_prompt_by_id = trend_api_module.get_prompt_by_id
    original_use_prompt = trend_api_module.use_prompt

    async def get_prompt_by_id_with_builtins(
        prompt_id: int,
        approved_public_only: bool = False,
    ) -> dict[str, Any] | None:
        builtin = get_builtin_trend(prompt_id)
        if builtin is not None:
            if approved_public_only and (
                builtin.get("status") != "approved" or not builtin.get("is_public")
            ):
                return None
            return builtin
        return await original_get_prompt_by_id(
            prompt_id,
            approved_public_only=approved_public_only,
        )

    async def use_prompt_with_builtins(
        prompt_id: int,
        user_id: int,
        *,
        credits_spent: float = 0.0,
    ) -> Any:
        if get_builtin_trend(prompt_id) is not None:
            return None
        return await original_use_prompt(
            prompt_id,
            user_id,
            credits_spent=credits_spent,
        )

    trend_api_module.get_prompt_by_id = get_prompt_by_id_with_builtins
    trend_api_module.use_prompt = use_prompt_with_builtins
    trend_api_module._builtin_trends_installed = True
