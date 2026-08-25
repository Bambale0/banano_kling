"""Pinterest AI scene/identity provider contract compatibility layer.

Pinterest AI is not a normal image edit. The public product contract is:
scene/reference image first, user identity second. Banana Pro is more reliable
when the provider payload is identity first and scene second, and the generic
reference-edit guidance must not be appended because it tells the model to edit
and preserve the first uploaded image. This module patches the image launch path
without changing the regular image editor flow.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from bot import db as db_backend

logger = logging.getLogger(__name__)

StartImageTask = Callable[..., Awaitable[dict[str, Any]]]
ReferenceGuidance = Callable[[str, str, list[str]], str]
RestoreImageTask = Callable[..., Awaitable[tuple[bool, str | None]]]

_ORIGINAL_START_IMAGE_TASK: StartImageTask | None = None
_PATCHED_START_IMAGE_TASK: StartImageTask | None = None
_ORIGINAL_REFERENCE_GUIDANCE: ReferenceGuidance | None = None
_PATCHED_REFERENCE_GUIDANCE: ReferenceGuidance | None = None
_ORIGINAL_RESTORE_IMAGE_TASK: RestoreImageTask | None = None
_PATCHED_RESTORE_IMAGE_TASK: RestoreImageTask | None = None

_DISPLAY_PROMPT = (
    "Pinterest AI: сохранить внешность с ваших фото в выбранной сцене Pinterest."
)


def _is_pinterest_prompt(prompt: str | None) -> bool:
    text = str(prompt or "")
    if not text:
        return False
    normalized = text.lower()
    return (
        (
            "strict identity preservation contract" in normalized
            and "scene_reference" in normalized
            and "user_identity_reference" in normalized
        )
        or (
            "image 1 is the user_identity_reference" in normalized
            and "image 2 is the scene_reference" in normalized
        )
        or "pinterest scene identity contract" in normalized
    )


def _pinterest_provider_prompt(*, measurements: str = "not provided") -> str:
    return (
        "PINTEREST SCENE IDENTITY CONTRACT\n\n"
        "You are generating a NEW photorealistic image.\n\n"
        "Image 1 is the USER_IDENTITY_REFERENCE. Use Image 1 only for the "
        "person's face, identity, apparent age, skin tone, facial geometry, "
        "hairline, distinctive facial features, and recognizable likeness.\n\n"
        "Image 2 is the SCENE_REFERENCE. Use Image 2 only for the scene, pose, "
        "body placement, outfit concept, composition, lighting, camera angle, "
        "framing, background, and photographic mood.\n\n"
        "Create a new photo of the person from Image 1 placed naturally into the "
        "scene and composition of Image 2.\n\n"
        "Hard negative rules:\n"
        "- Do not preserve, copy, or reuse the person from Image 2.\n"
        "- Do not copy the face, hair, identity, ethnicity, apparent age, or skin "
        "tone from Image 2.\n"
        "- Do not return Image 1 unchanged.\n"
        "- Do not return Image 2 unchanged.\n"
        "- Do not use Image 1 as the composition, outfit, background, or pose.\n"
        "- Do not output a collage, comparison, screenshot, source image, UI, text, "
        "watermark, or split-screen.\n"
        "- Do not average the two identities. Identity from Image 1 always wins.\n\n"
        "Quality rules:\n"
        "- The result must look like a real new photograph, not an edit preview.\n"
        "- Keep face and body anatomy natural.\n"
        "- Keep the user recognizable from Image 1.\n"
        f"- User measurements: {measurements}. Use them only for realistic body scale; "
        "never render measurement text into the image.\n\n"
        "User requested details:\n"
        f"{_DISPLAY_PROMPT}"
    )


def _extract_measurements(prompt: str | None) -> str:
    text = str(prompt or "")
    marker = "- User measurements:"
    idx = text.find(marker)
    if idx == -1:
        return "not provided"
    tail = text[idx + len(marker):].strip()
    # Existing prompt ends the measurement sentence with a period.
    end = tail.find(".")
    if end != -1:
        tail = tail[:end].strip()
    return tail or "not provided"


async def _patch_pinterest_request_snapshot(
    *,
    user_id: int,
    result: dict[str, Any],
    original_references: list[str],
    provider_references: list[str],
    provider_prompt: str,
) -> None:
    candidates: list[str] = []
    for key in ("task_id", "local_task_id", "provider_task_id"):
        value = str(result.get(key) or "").strip()
        if value and value not in candidates:
            candidates.append(value)
    if not candidates:
        return

    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        row = None
        for candidate in candidates:
            cursor = await db.execute(
                "SELECT id, request_data FROM generation_tasks WHERE task_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
                (candidate, user_id),
            )
            row = await cursor.fetchone()
            if row:
                break
        if not row:
            logger.warning(
                "Pinterest metadata patch skipped: no task row for candidates=%s user_id=%s",
                candidates,
                user_id,
            )
            return

        request_data: dict[str, Any] = {}
        if row["request_data"]:
            try:
                request_data = json.loads(row["request_data"])
            except Exception:
                request_data = {}

        identity_evidence = original_references[2:]
        logical_roles = ["scene", "identity", *(["identity_evidence"] * len(identity_evidence))]
        request_data.update(
            {
                "flow": "pinterest_ai",
                "reference_contract": "pinterest_scene_identity",
                "scene_reference": original_references[0] if original_references else "",
                "identity_reference": original_references[1] if len(original_references) > 1 else "",
                "identity_evidence": identity_evidence,
                "reference_roles": logical_roles,
                "reference_images": original_references,
                "source_reference_images": original_references,
                "provider_reference_images": provider_references,
                "provider_reference_roles": ["identity", "scene"],
                "user_prompt": _DISPLAY_PROMPT,
                "display_prompt": _DISPLAY_PROMPT,
                "original_prompt": _DISPLAY_PROMPT,
                "provider_prompt": provider_prompt,
                "pinterest_provider_safe_refs": True,
                "generic_reference_guidance_disabled": True,
            }
        )
        # Do not expose provider-only guidance via generic prompt readers.
        if str(request_data.get("effective_prompt") or "").startswith("EDIT REQUEST"):
            request_data.pop("effective_prompt", None)

        await db.execute(
            """
            UPDATE generation_tasks
            SET prompt = ?,
                request_data = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                _DISPLAY_PROMPT,
                json.dumps(request_data, ensure_ascii=False),
                row["id"],
            ),
        )
        await db.commit()


def install_pinterest_flow_contract_compat(generation_module: Any) -> None:
    """Install provider-safe Pinterest AI prompt/reference handling."""

    global _ORIGINAL_START_IMAGE_TASK, _PATCHED_START_IMAGE_TASK
    global _ORIGINAL_REFERENCE_GUIDANCE, _PATCHED_REFERENCE_GUIDANCE
    global _ORIGINAL_RESTORE_IMAGE_TASK, _PATCHED_RESTORE_IMAGE_TASK

    if _ORIGINAL_REFERENCE_GUIDANCE is None:
        _ORIGINAL_REFERENCE_GUIDANCE = generation_module._apply_reference_detail_preservation
    original_guidance = _ORIGINAL_REFERENCE_GUIDANCE

    if _PATCHED_REFERENCE_GUIDANCE is None:

        def pinterest_safe_reference_guidance(
            img_service: str,
            prompt: str,
            reference_images: list[str],
        ) -> str:
            if _is_pinterest_prompt(prompt):
                logger.info(
                    "Pinterest AI: generic Banana reference guidance bypassed for %s refs",
                    len(reference_images or []),
                )
                return prompt
            return original_guidance(img_service, prompt, reference_images)

        _PATCHED_REFERENCE_GUIDANCE = pinterest_safe_reference_guidance

    generation_module._apply_reference_detail_preservation = _PATCHED_REFERENCE_GUIDANCE

    if _ORIGINAL_START_IMAGE_TASK is None:
        _ORIGINAL_START_IMAGE_TASK = generation_module._start_image_generation_task
    original_start = _ORIGINAL_START_IMAGE_TASK

    if _PATCHED_START_IMAGE_TASK is None:

        async def pinterest_safe_start_image_generation_task(*args: Any, **kwargs: Any):
            prompt = str(kwargs.get("prompt") or "")
            references = [str(ref or "").strip() for ref in (kwargs.get("reference_images") or []) if str(ref or "").strip()]
            img_service = str(kwargs.get("img_service") or "")
            if (
                _is_pinterest_prompt(prompt)
                and img_service in {"banana_pro", "nanobanana", "banana_2", "nano-banana-2-lite"}
                and len(references) >= 2
            ):
                scene_reference = references[0]
                identity_reference = references[1]
                provider_references = [identity_reference, scene_reference]
                provider_prompt = _pinterest_provider_prompt(
                    measurements=_extract_measurements(prompt)
                )
                patched_kwargs = dict(kwargs)
                patched_kwargs["prompt"] = provider_prompt
                patched_kwargs["reference_images"] = provider_references
                logger.info(
                    "Pinterest AI: provider-safe payload task start img_service=%s logical_refs=%s provider_roles=%s",
                    img_service,
                    len(references),
                    ["identity", "scene"],
                )
                result = await original_start(*args, **patched_kwargs)
                try:
                    user = kwargs.get("user")
                    user_id = int(getattr(user, "id", 0) or 0)
                    if user_id:
                        await _patch_pinterest_request_snapshot(
                            user_id=user_id,
                            result=result or {},
                            original_references=references,
                            provider_references=provider_references,
                            provider_prompt=provider_prompt,
                        )
                except Exception:
                    logger.exception("Pinterest AI: failed to patch request snapshot")
                return result

            return await original_start(*args, **kwargs)

        _PATCHED_START_IMAGE_TASK = pinterest_safe_start_image_generation_task

    generation_module._start_image_generation_task = _PATCHED_START_IMAGE_TASK

    # Repeat screen compatibility: keep the provider prompt for execution but do
    # not display it as editable user text.
    if hasattr(generation_module, "_restore_image_task_to_state"):
        if _ORIGINAL_RESTORE_IMAGE_TASK is None:
            _ORIGINAL_RESTORE_IMAGE_TASK = generation_module._restore_image_task_to_state
        original_restore = _ORIGINAL_RESTORE_IMAGE_TASK

        if _PATCHED_RESTORE_IMAGE_TASK is None:

            async def pinterest_safe_restore_image_task_to_state(*args: Any, **kwargs: Any):
                result = await original_restore(*args, **kwargs)
                task = args[0] if args else kwargs.get("task")
                state = args[1] if len(args) > 1 else kwargs.get("state")
                if not task or state is None:
                    return result
                try:
                    request_data = json.loads(task.request_data) if getattr(task, "request_data", None) else {}
                except Exception:
                    request_data = {}
                if request_data.get("flow") == "pinterest_ai":
                    provider_prompt = str(request_data.get("provider_prompt") or request_data.get("prompt") or "")
                    if provider_prompt:
                        await state.update_data(
                            repeat_prompt=provider_prompt,
                            repeat_prompt_hidden=True,
                            repeat_display_prompt=request_data.get("display_prompt") or _DISPLAY_PROMPT,
                        )
                return result

            _PATCHED_RESTORE_IMAGE_TASK = pinterest_safe_restore_image_task_to_state

        generation_module._restore_image_task_to_state = _PATCHED_RESTORE_IMAGE_TASK

    logger.info("Pinterest AI flow contract compatibility installed")
