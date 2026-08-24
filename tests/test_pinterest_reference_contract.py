"""Regression contract for the Pinterest person-into-scene reference flow.

Enforces the strict scene-first reference contract:

- Image 1 = SCENE_REFERENCE (composition, pose, camera, light, background,
                             wardrobe, atmosphere, facial expression, crop).
- Image 2 = USER_IDENTITY_REFERENCE (face, hair, age, body build,
                             individual features).
- Images 3..N = IDENTITY_EVIDENCE (improve likeness only; never source).

Identity-first reordering is forbidden. A Pinterest result must look like the
user was photographed inside the scene, never like an edited Pinterest photo,
a lookalike, or one of the uploaded identity images returned unchanged.
"""

from __future__ import annotations

from bot import pinterest_trend_api as pinterest_api
from bot.generation_context import ReferenceRole, resolve_pinterest_reference_roles
from bot.pinterest_trend_flow_contract import (
    PINTEREST_PROMPT_MARKER,
    _build_pinterest_recreation_prompt,
    _private_trend_task_kwargs,
)
from bot.trend_api import TrustedTrendRun

SCENE = "https://example.com/scene.jpg"
USER = "https://example.com/user.jpg"


def _reference_roles(urls: list[str]) -> list[str]:
    """Return compact role labels for the provider payload order."""
    ordered = resolve_pinterest_reference_roles(urls).ordered
    return [ref.role.value for ref in ordered]


def test_two_references_resolve_scene_then_identity() -> None:
    ordered = resolve_pinterest_reference_roles([SCENE, USER]).ordered
    assert [item.url for item in ordered] == [SCENE, USER]
    assert [item.role for item in ordered] == [
        ReferenceRole.SCENE,
        ReferenceRole.IDENTITY,
    ]
    assert _reference_roles([SCENE, USER]) == ["scene", "identity"]


def test_additional_identity_images_stay_after_identity_as_evidence() -> None:
    urls = [
        SCENE,
        USER,
        "https://example.com/extra1.jpg",
        "https://example.com/extra2.jpg",
    ]
    ordered = resolve_pinterest_reference_roles(urls).ordered
    assert [item.url for item in ordered] == urls
    assert [item.role for item in ordered] == [
        ReferenceRole.SCENE,
        ReferenceRole.IDENTITY,
        ReferenceRole.IDENTITY,
        ReferenceRole.IDENTITY,
    ]

    store = _private_trend_task_kwargs(
        {
            "action_type": "trend",
            "prompt": f"{PINTEREST_PROMPT_MARKER}\n...",
            "request_data": {"reference_images": list(urls)},
        }
    )
    assert store["request_data"]["reference_roles"] == [
        "scene",
        "identity",
        "identity_evidence",
        "identity_evidence",
    ]


def test_prompt_forbids_returning_scene_or_identity_unchanged() -> None:
    prompt = _build_pinterest_recreation_prompt(
        "Recreate the photograph.",
        height_cm=178,
        weight_kg=72,
    )

    assert "TASK — TRANSFER THE PERSON INTO THE SCENE, DO NOT EDIT THE SCENE PERSON" in prompt
    assert "Returning SCENE_REFERENCE unchanged or nearly unchanged is an invalid result" in prompt
    assert "IDENTITY EVIDENCE GUARD" in prompt
    assert "Additional identity images are evidence only. Never reproduce them." in prompt
    assert "Never use them as source composition." in prompt
    assert "Never return any uploaded reference image unchanged." in prompt
    assert "that person must not remain recognizable anywhere in the output" in prompt


def test_pinterest_runtime_prompt_is_scene_first() -> None:
    prompt = _build_pinterest_recreation_prompt(
        "Recreate the photograph.",
        height_cm=170,
        weight_kg=60,
    )
    assert prompt.index("Image 1 = SCENE_REFERENCE") < prompt.index(
        "Image 2 = USER_IDENTITY_REFERENCE"
    )


def _persisted_run(urls: list[str]) -> dict:
    return _private_trend_task_kwargs(
        {
            "action_type": "trend",
            "prompt": f"Recreate.\n\n{PINTEREST_PROMPT_MARKER}\n...",
            "request_data": {"reference_images": list(urls)},
        }
    )


def test_repeat_generation_preserves_scene_first_reference_roles() -> None:
    urls = [SCENE, USER, "https://example.com/angle1.jpg", "https://example.com/angle2.jpg"]
    first_run = _persisted_run(urls)
    history_roles = list(first_run["request_data"]["reference_roles"])

    repeat_run = _persisted_run(list(first_run["request_data"]["reference_images"]))
    assert repeat_run["request_data"]["reference_roles"] == history_roles
    assert repeat_run["request_data"]["reference_roles"] == [
        "scene",
        "identity",
        "identity_evidence",
        "identity_evidence",
    ]
    assert repeat_run["request_data"]["reference_images"] == urls


async def test_lock_pinterest_run_never_reorders_identity_first() -> None:
    stored = TrustedTrendRun(
        trend_id=7,
        kind="image",
        prompt="base",
        model="banana_2",
        ratio="1:1",
        reference_urls=(SCENE, USER, "https://example.com/angle1.jpg"),
        settings={"quality": "4K", "count": 3, "ratio": "1:1"},
    )
    locked = await pinterest_api._lock_pinterest_run(stored, height_cm=180, weight_kg=80)
    assert locked.reference_urls == (SCENE, USER, "https://example.com/angle1.jpg")
    assert locked.prompt.index("Image 1 = SCENE_REFERENCE") < locked.prompt.index(
        "Image 2 = USER_IDENTITY_REFERENCE"
    )