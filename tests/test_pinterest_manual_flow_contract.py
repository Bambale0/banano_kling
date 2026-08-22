from __future__ import annotations

from pathlib import Path

import pytest

from bot.pinterest_trend_flow_contract import (
    MAX_PINTEREST_REFERENCES,
    _is_pinterest_prompt,
    _required_measurement,
    _strict_reference_urls,
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


def test_route_installs_strict_contract_before_all_trend_routes() -> None:
    routes = read("bot/handlers/trend_route_compat.py")
    contract = read("bot/pinterest_trend_flow_contract.py")
    install_position = routes.index("install_pinterest_trend_flow_contract()")
    pinterest_route_position = routes.index("setup_pinterest_trend_routes(app, root)")
    generic_route_position = routes.index("setup_trend_routes(app, root)")

    assert install_position < pinterest_route_position < generic_route_position
    assert "generic_trend_api.miniapp_run_trend = block_pinterest_on_generic_run" in contract
