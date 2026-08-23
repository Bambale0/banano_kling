from __future__ import annotations

from pathlib import Path

import pytest

from bot.pinterest_trend_flow_contract import (
    MAX_PINTEREST_REFERENCES,
    PINTEREST_PROMPT_MARKER,
    _build_pinterest_recreation_prompt,
    _is_pinterest_prompt,
    _private_trend_task_kwargs,
    _required_measurement,
    _strict_reference_urls,
    install_pinterest_trend_flow_contract,
)
from bot.trend_api import TrendRunValidationError

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_pinterest_frontend_never_autostarts_from_upload_handlers() -> None:
    runner = read("frontend/miniapp-v0/components/trend-runner-dialog.tsx")

    upload_slot = runner.split("const uploadIntoSlot", 1)[1].split(
        "const handlePhotos", 1
    )[0]
    upload_angles = runner.split("const uploadPinterestAngles", 1)[1].split(
        "const removeIdentityAngle", 1
    )[0]
    generate = runner.split("const handleGenerate", 1)[1].split(
        "const renderExactSlot", 1
    )[0]

    assert "runPinterestRepeatTrend" not in upload_slot
    assert "runPinterestRepeatTrend" not in upload_angles
    assert "runPinterestRepeatTrend" in generate
    assert "onClick={() => void handleGenerate()}" in runner


def test_pinterest_frontend_requires_primary_refs_height_and_weight() -> None:
    runner = read("frontend/miniapp-v0/components/trend-runner-dialog.tsx")

    assert "MAX_PINTEREST_ANGLES = 5" in runner
    assert "pinterestPrimaryReady && validHeight && validWeight" in runner
    assert "1–5 ракурсов одного человека" in runner
    assert "Рост и вес обязательны" in runner
    assert "Загрузка фото сама генерацию не запускает" in runner


def test_pinterest_client_sends_explicit_confirmation() -> None:
    client = read("frontend/miniapp-v0/lib/trend-api.ts")
    pinterest_run = client.split("export async function runPinterestRepeatTrend(", 1)[1].split(
        "export async function runTrend(", 1
    )[0]

    assert "payload.height_cm = options.heightCm" in pinterest_run
    assert "payload.weight_kg = options.weightKg" in pinterest_run
    assert "payload.confirmed = true" in pinterest_run


def test_backend_accepts_scene_user_and_up_to_five_identity_angles() -> None:
    urls = [
        f"https://example.com/{index}.jpg"
        for index in range(MAX_PINTEREST_REFERENCES)
    ]
    assert _strict_reference_urls({"reference_urls": urls}) == tuple(urls)


@pytest.mark.parametrize("count", [0, 1, MAX_PINTEREST_REFERENCES + 1])
def test_backend_rejects_wrong_reference_count(count: int) -> None:
    urls = [f"https://example.com/{index}.jpg" for index in range(count)]
    with pytest.raises(TrendRunValidationError):
        _strict_reference_urls({"reference_urls": urls})


def test_backend_requires_height_and_weight() -> None:
    with pytest.raises(TrendRunValidationError, match="Укажите рост"):
        _required_measurement(
            {}, "height_cm", minimum=120, maximum=230, label="Рост"
        )
    with pytest.raises(TrendRunValidationError, match="Укажите вес"):
        _required_measurement(
            {}, "weight_kg", minimum=30, maximum=250, label="Вес"
        )


def test_pinterest_prompt_is_recognized_for_legacy_generic_route_guard() -> None:
    assert _is_pinterest_prompt(
        {"title": "Anything", "tags": ["trend", "pinterest-repeat"]}
    )
    assert _is_pinterest_prompt(
        {"title": "Повтори фото с Pinterest", "tags": ["trend"]}
    )
    assert not _is_pinterest_prompt(
        {"title": "Обычный тренд", "tags": ["trend", "portrait"]}
    )


def test_runtime_prompt_assigns_non_overlapping_scene_and_identity_roles() -> None:
    prompt = _build_pinterest_recreation_prompt(
        "Recreate the photograph.",
        height_cm=165,
        weight_kg=48,
    )

    assert PINTEREST_PROMPT_MARKER in prompt
    assert "Image 1 = SCENE_REFERENCE" in prompt
    assert "Image 2 = USER_IDENTITY_REFERENCE" in prompt
    assert "Images 3..N" in prompt
    assert "exact pose and body geometry" in prompt
    assert "exact camera viewpoint" in prompt
    assert "exact facial expression" in prompt
    assert "exact outfit and styling" in prompt
    assert "hairstyle arrangement from SCENE_REFERENCE" in prompt
    assert "USER's real hair length and hair color/shade" in prompt
    assert "Returning SCENE_REFERENCE unchanged or nearly unchanged is an invalid result" in prompt
    assert "PARTIAL TRANSFER GUARD" in prompt
    assert (
        "Do not take ONLY hair color, hair length or body cues from "
        "USER_IDENTITY_REFERENCE while keeping the SCENE_REFERENCE person's face"
    ) in prompt
    assert "Do not copy person from scene reference." in prompt
    assert "Do not replace identity. Keep facial structure unchanged." in prompt
    assert "Do not output prompt text, explanations, URLs" in prompt
    assert "height 165 cm" in prompt
    assert "weight 48 kg" in prompt


def test_pinterest_runtime_bypasses_generic_first_image_identity_guidance() -> None:
    from bot.handlers import generation as generation_module

    install_pinterest_trend_flow_contract()
    prompt = _build_pinterest_recreation_prompt(
        "Recreate the photograph.",
        height_cm=170,
        weight_kg=60,
    )
    result = generation_module._apply_reference_detail_preservation(
        "banana_pro",
        prompt,
        ["https://example.com/scene.jpg", "https://example.com/user.jpg"],
    )

    assert result == prompt
    assert "first uploaded image only as the primary person identity reference" not in result


def test_trend_task_persistence_does_not_store_private_recipe() -> None:
    original = {
        "action_type": "trend",
        "prompt": "SECRET PINTEREST PROMPT",
        "request_data": {
            "prompt": "SECRET PINTEREST PROMPT",
            "effective_prompt": "SECRET PROVIDER PROMPT",
            "source_url": "https://pinterest.com/pin/secret",
            "pinterest_url": "https://pin.it/secret",
            "reference_images": ["https://example.com/source.jpg"],
            "provider_model": "nano-banana-pro",
        },
    }

    private = _private_trend_task_kwargs(original)

    assert private["prompt"] == ""
    assert "prompt" not in private["request_data"]
    assert "effective_prompt" not in private["request_data"]
    assert "source_url" not in private["request_data"]
    assert "pinterest_url" not in private["request_data"]
    assert private["request_data"]["reference_images"] == ["https://example.com/source.jpg"]
    assert private["request_data"]["provider_model"] == "nano-banana-pro"
    assert private["request_data"]["prompt_hidden"] is True
    assert private["request_data"]["prompt_actions_allowed"] is False


def test_trend_task_persistence_stores_internal_reference_roles_for_pinterest() -> None:
    original = {
        "action_type": "trend",
        "prompt": f"Recreate.\n\n{PINTEREST_PROMPT_MARKER}\n...",
        "request_data": {
            "prompt": "runtime copy",
            "effective_prompt": f"EDIT REQUEST: ... {PINTEREST_PROMPT_MARKER}",
            "reference_images": [
                "https://example.com/scene.jpg",
                "https://example.com/user.jpg",
                "https://example.com/angle.jpg",
            ],
        },
    }

    private = _private_trend_task_kwargs(original)

    assert private["request_data"]["reference_roles"] == [
        "scene",
        "identity",
        "identity",
    ]


def test_generic_trend_tasks_do_not_get_pinterest_reference_roles() -> None:
    original = {
        "action_type": "trend",
        "prompt": "Ordinary curated trend without pinterest marker",
        "request_data": {
            "reference_images": [
                "https://example.com/a.jpg",
                "https://example.com/b.jpg",
            ],
        },
    }

    private = _private_trend_task_kwargs(original)

    assert "reference_roles" not in private["request_data"]


def test_route_installs_strict_contract_before_all_trend_routes() -> None:
    routes = read("bot/handlers/trend_route_compat.py")
    contract = read("bot/pinterest_trend_flow_contract.py")
    install_position = routes.index("install_pinterest_trend_flow_contract()")
    pinterest_route_position = routes.index("setup_pinterest_trend_routes(app, root)")
    generic_route_position = routes.index("setup_trend_routes(app, root)")

    assert install_position < pinterest_route_position < generic_route_position
    assert "generic_trend_api.miniapp_run_trend = block_pinterest_on_generic_run" in contract
    assert "generation_module._apply_reference_detail_preservation = reference_guidance" in contract
    assert "generation_module.add_generation_task = private_add_generation_task" in contract
