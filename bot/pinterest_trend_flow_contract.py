"""Strict product contract for the Pinterest repeat trend.

The Pinterest flow is intentionally different from ordinary one-tap trends:
users must provide a scene reference, their own identity photo, body
measurements, and explicitly confirm generation. Additional identity angles are
allowed to improve likeness but never trigger generation by themselves.

This module also isolates the Pinterest prompt from the generic Nano Banana
reference guidance. The generic editor assumes the first image is the identity
master, while Pinterest deliberately uses Image 1 as the scene master. Mixing
those contracts makes the provider copy the source person/composition instead
of recreating the scene with the user's identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from aiohttp import web

from bot import pinterest_trend_api as pinterest_api
from bot import trend_api as generic_trend_api
from bot.generation_context import (
    GenerationContextError,
    PrivacyPolicy,
    ensure_pinterest_reference_gate,
)
from bot.services.media_input_utils import _static_upload_hosts
from bot.trend_api import TrendRunValidationError

MIN_PINTEREST_REFERENCES = 2
MAX_PINTEREST_IDENTITY_ANGLES = 5
MAX_PINTEREST_REFERENCES = MIN_PINTEREST_REFERENCES + MAX_PINTEREST_IDENTITY_ANGLES
PINTEREST_PROMPT_MARKER = "PINTEREST_RECREATION_CONTRACT_V2"

_PRIVATE_TREND_REQUEST_KEYS = {
    "prompt",
    "effective_prompt",
    "source_url",
    "pinterest_url",
}


def _strict_reference_urls(body: dict[str, Any]) -> tuple[str, ...]:
    raw = body.get("reference_urls")
    if not isinstance(raw, list):
        raise TrendRunValidationError(
            "Для этого тренда нужны референс и ваше фото"
        )
    if not MIN_PINTEREST_REFERENCES <= len(raw) <= MAX_PINTEREST_REFERENCES:
        raise TrendRunValidationError(
            "Загрузите референс, ваше фото и при желании до 5 дополнительных ракурсов"
        )

    cleaned: list[str] = []
    for item in raw:
        url = str(item or "").strip()
        if not url:
            raise TrendRunValidationError("Дождитесь окончания загрузки всех фото")
        if url in cleaned:
            raise TrendRunValidationError("Не добавляйте одно и то же фото несколько раз")
        if url.startswith(("blob:", "data:", "file:")):
            raise TrendRunValidationError("Дождитесь окончания загрузки всех фото")
        if not url.startswith(("https://", "http://", "/uploads/")):
            raise TrendRunValidationError("Некорректная ссылка на фото")
        # External hosts (e.g. i.pinimg.com) reject datacenter fetches, which
        # made provider input randomly incomplete. Only our own uploads are
        # guaranteed fetchable by the provider.
        if not url.startswith("/uploads/"):
            parsed = urlparse(url)
            host = (parsed.hostname or "").strip().lower().lstrip(".")
            if host not in _static_upload_hosts():
                raise TrendRunValidationError(
                    "Загрузите фото файлом — ссылки на внешние сайты не поддерживаются"
                )
        cleaned.append(url)

    return tuple(cleaned)


def _required_measurement(
    body: dict[str, Any],
    key: str,
    *,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    raw = body.get(key)
    if raw in (None, ""):
        raise TrendRunValidationError(f"Укажите {label.lower()}")
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise TrendRunValidationError(f"{label} должен быть числом") from exc
    if value < minimum or value > maximum:
        raise TrendRunValidationError(f"{label} вне допустимого диапазона")
    return value


def _is_pinterest_prompt(prompt: Mapping[str, Any] | None) -> bool:
    if not prompt:
        return False
    tags = {
        str(tag or "").strip().lower()
        for tag in list(prompt.get("tags") or [])
        if str(tag or "").strip()
    }
    title = str(prompt.get("title") or "").strip().lower()
    return (
        "pinterest" in tags
        or "pinterest-repeat" in tags
        or "repeat-pinterest" in tags
        or "pinterest" in title
    )


def _build_pinterest_recreation_prompt(
    base_prompt: str,
    *,
    height_cm: int | None,
    weight_kg: int | None,
) -> str:
    """Build the provider prompt with explicit, non-overlapping reference roles."""

    measurements: list[str] = []
    if height_cm is not None:
        measurements.append(f"height {height_cm} cm")
    if weight_kg is not None:
        measurements.append(f"weight {weight_kg} kg")
    measurement_text = ", ".join(measurements) if measurements else "not provided"

    return (
        f"{base_prompt.strip()}\n\n"
        f"{PINTEREST_PROMPT_MARKER}\n"
        "REFERENCE ROLES — DO NOT SWAP THEM\n"
        "- Image 1 = USER_IDENTITY_REFERENCE. It is the primary identity master.\n"
        "- Image 2 = SCENE_REFERENCE. It is the master for the photographed setup, never for identity.\n"
        "- Images 3..N, when present, are ADDITIONAL_USER_IDENTITY_ANGLES of the SAME user. They only strengthen identity/body evidence.\n"
        "\n"
        "TASK — RE-PHOTOGRAPH, NOT EDIT\n"
        "- Take Image 2 (SCENE_REFERENCE) as the base frame and replace its person completely with the person from Image 1 (USER_IDENTITY_REFERENCE).\n"
        "- Do not preserve, retouch or lightly edit the person visible in Image 2: that person must not remain recognizable anywhere in the output.\n"
        "\n"
        "SCENE_REFERENCE LOCK — MATCH THESE ATTRIBUTES 1:1\n"
        "- Recreate the exact pose and body geometry: head tilt, torso rotation, shoulder angle, arm position, hand placement, leg position and weight distribution.\n"
        "- Recreate the exact camera viewpoint: camera height, camera angle, perspective, subject distance, framing, crop and subject placement. Do not invent a new angle or crop.\n"
        "- Recreate the exact facial expression, gaze direction and mouth/eye expression from SCENE_REFERENCE. Do not invent a different expression.\n"
        "- Recreate the exact outfit and styling from SCENE_REFERENCE: garment types, silhouette, colors, layers, fabric appearance, accessories and visible details. Do not redesign or replace the clothing.\n"
        "- Recreate the hairstyle arrangement from SCENE_REFERENCE: parting, bangs/fringe, waves/curls, volume, tied/loose structure and styling.\n"
        "- Recreate the background, lighting direction, shadow pattern, scene geometry and photographic mood from SCENE_REFERENCE.\n"
        "\n"
        "USER IDENTITY LOCK\n"
        "- The final person must be the same recognizable person as USER_IDENTITY_REFERENCE and Images 3..N, not the person from SCENE_REFERENCE.\n"
        "- Preserve the user's facial geometry, face shape, jawline, cheekbones, forehead proportions, eyes, eye spacing, brows, nose, lips, ears, skin tone, apparent age, hairline and distinctive facial features.\n"
        "- Preserve the user's natural body build and proportions.\n"
        "- Preserve the USER's real hair length and hair color/shade. Adapt the SCENE_REFERENCE hairstyle arrangement to the user's real length and color instead of copying the source person's hair identity.\n"
        f"- User measurements: {measurement_text}. Use them only as body-scale evidence; never render these numbers or measurement text.\n"
        "- Images 3..N must never override pose, camera, framing, expression, clothing, hairstyle arrangement, background or lighting from SCENE_REFERENCE.\n"
        "\n"
        "PARTIAL TRANSFER GUARD\n"
        "- Partial identity transfer is invalid. Do not take ONLY hair color, hair length or body cues from USER_IDENTITY_REFERENCE while keeping the SCENE_REFERENCE person's face.\n"
        "- Every identity attribute must come from the user together: facial structure, face geometry, skin tone, apparent age, hair color and hair length.\n"
        "- If the hair color differs between SCENE_REFERENCE and the user, render the user's hair color on the user's head shape adapted to the scene styling.\n"
        "- Do not copy person from scene reference.\n"
        "- Do not replace identity. Keep facial structure unchanged.\n"
        "\n"
        "CONFLICT PRIORITY\n"
        "- Pose/camera/framing/expression/clothing/hairstyle arrangement/scene always come from SCENE_REFERENCE.\n"
        "- Face/identity/body build/hair length/hair color always come from USER identity images.\n"
        "- Never average, blend or morph the source person's identity with the user's identity.\n"
        "\n"
        "SOURCE-COPY GUARD\n"
        "- Returning SCENE_REFERENCE unchanged or nearly unchanged is an invalid result.\n"
        "- Do not reuse the source person's face. Replace the person identity with the user while preserving the source setup exactly.\n"
        "- The result should look as if the USER was genuinely photographed in the exact source pose, camera angle, expression, outfit and scene.\n"
        "\n"
        "OUTPUT PRIVACY\n"
        "- Produce the image only. Do not output prompt text, explanations, URLs, source attribution, metadata, captions, watermarks, collages, split screens or UI text.\n"
        "- Prefer faithful 1:1 recreation over artistic reinterpretation."
    )


def _is_pinterest_runtime_prompt(prompt: str | None) -> bool:
    return PINTEREST_PROMPT_MARKER in str(prompt or "")


def _private_trend_task_kwargs(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed when persisting curated trend recipes.

    The provider still receives the full runtime prompt. Only the database copy
    is redacted, so Telegram webhook/history code cannot accidentally expose a
    paid trend recipe later.
    """

    clean = dict(kwargs)
    if str(clean.get("action_type") or "").strip().lower() != "trend":
        return clean

    marker_present = PINTEREST_PROMPT_MARKER in str(clean.get("prompt") or "")
    clean["prompt"] = ""
    request_data = clean.get("request_data")
    if isinstance(request_data, Mapping):
        private_request = dict(request_data)
        marker_present = marker_present or any(
            PINTEREST_PROMPT_MARKER in str(private_request.get(key) or "")
            for key in ("prompt", "effective_prompt")
        )
        for key in _PRIVATE_TREND_REQUEST_KEYS:
            private_request.pop(key, None)
        if marker_present:
            # Internal-only role metadata for retry/debugging. It is stripped
            # from every public payload by trend_task_privacy sanitizers.
            # Provider order is identity-first, scene-last for nano-banana-pro.
            references = private_request.get("reference_images")
            if isinstance(references, list) and references:
                private_request["reference_roles"] = [
                    *("identity" for _ in references[:-1]),
                    "scene",
                ]
        private_request["prompt_hidden"] = True
        private_request["prompt_actions_allowed"] = False
        clean["request_data"] = private_request
    return clean


def install_pinterest_trend_flow_contract() -> None:
    """Install guards before Pinterest and generic trend routes are registered."""

    if getattr(pinterest_api, "_strict_manual_flow_installed", False):
        return

    from bot.handlers import generation as generation_module

    original_handler = pinterest_api.miniapp_run_pinterest_repeat
    original_generic_handler = generic_trend_api.miniapp_run_trend
    original_reference_guidance = generation_module._apply_reference_detail_preservation
    original_add_generation_task = generation_module.add_generation_task

    async def strict_manual_run(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise TrendRunValidationError("Некорректный запрос")
            if body.get("confirmed") is not True:
                raise TrendRunValidationError(
                    "Подтвердите генерацию кнопкой «Создать»"
                )
            _required_measurement(
                body,
                "height_cm",
                minimum=120,
                maximum=230,
                label="Рост",
            )
            _required_measurement(
                body,
                "weight_kg",
                minimum=30,
                maximum=250,
                label="Вес",
            )
            validated_urls = _strict_reference_urls(body)
        except TrendRunValidationError as error:
            return web.json_response({"ok": False, "error": str(error)}, status=400)
        except Exception:
            return web.json_response(
                {"ok": False, "error": "Некорректные параметры Pinterest-тренда"},
                status=400,
            )

        try:
            # Validation gate: scene exists, identity exists, roles valid,
            # privacy mode enabled. Runs before task creation and credit debit.
            ensure_pinterest_reference_gate(
                validated_urls,
                privacy_policy=PrivacyPolicy(
                    private_recipe=True,
                    hide_prompt=True,
                    allow_prompt_actions=False,
                    feed_prompt_visible=False,
                ),
            )
        except GenerationContextError as error:
            return web.json_response({"ok": False, "error": str(error)}, status=400)

        return await original_handler(request)

    async def block_pinterest_on_generic_run(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            if isinstance(body, dict):
                raw_trend_id = body.get("trend_id")
                if str(raw_trend_id or "").isdigit():
                    prompt = await generic_trend_api.get_prompt_by_id(
                        int(raw_trend_id),
                        approved_public_only=True,
                    )
                    if _is_pinterest_prompt(prompt):
                        return web.json_response(
                            {
                                "ok": False,
                                "error": (
                                    "Для Pinterest-тренда загрузите референс и ваше фото, "
                                    "укажите рост и вес и нажмите «Создать»"
                                ),
                            },
                            status=400,
                        )
        except Exception:
            # Preserve the ordinary generic handler's own validation/error mapping.
            pass
        return await original_generic_handler(request)

    def augmented_prompt(
        base_prompt: str,
        *,
        height_cm: int | None,
        weight_kg: int | None,
    ) -> str:
        return _build_pinterest_recreation_prompt(
            base_prompt,
            height_cm=height_cm,
            weight_kg=weight_kg,
        )

    def reference_guidance(
        img_service: str,
        prompt: str,
        reference_images: list[str],
    ) -> str:
        if _is_pinterest_runtime_prompt(prompt):
            # The Pinterest prompt already assigns every image a precise role.
            # The generic Banana guidance assumes Image 1 is the identity master
            # and therefore directly contradicts this workflow.
            return str(prompt or "").strip()
        return original_reference_guidance(img_service, prompt, reference_images)

    async def private_add_generation_task(*args, **kwargs):
        return await original_add_generation_task(
            *args,
            **_private_trend_task_kwargs(kwargs),
        )

    pinterest_api._reference_urls = _strict_reference_urls
    pinterest_api._augmented_prompt = augmented_prompt
    pinterest_api.miniapp_run_pinterest_repeat = strict_manual_run
    generic_trend_api.miniapp_run_trend = block_pinterest_on_generic_run
    generation_module._apply_reference_detail_preservation = reference_guidance
    generation_module.add_generation_task = private_add_generation_task
    pinterest_api._strict_manual_flow_installed = True
