from pathlib import Path

import pytest

from bot.services.builtin_trends import (
    PINTEREST_REPEAT_REFERENCE_HINT,
    PINTEREST_REPEAT_TREND_ID,
    ensure_builtin_image_model_capabilities,
    get_builtin_trend,
    pinterest_repeat_trend,
)
from bot.trend_api import TrendRunValidationError, trusted_trend_run


def test_builtin_pinterest_trend_has_strict_two_image_roles() -> None:
    trend = pinterest_repeat_trend()

    assert trend["id"] == PINTEREST_REPEAT_TREND_ID
    assert trend["title"] == "Повтори фото с Pinterest"
    assert trend["generation_settings"]["model"] == "banana_pro"
    assert trend["generation_settings"]["quality"] == "2K"
    assert trend["generation_settings"]["ratio"] == "auto"
    assert trend["generation_settings"]["required_reference_count"] == 2
    assert trend["generation_settings"]["reference_hint"] == PINTEREST_REPEAT_REFERENCE_HINT
    assert "IMAGE 1 is the TARGET PINTEREST REFERENCE" in trend["prompt_text"]
    assert "IMAGE 2 is the USER IDENTITY REFERENCE" in trend["prompt_text"]
    assert "Do not copy the face or identity of the person from IMAGE 1" in trend["prompt_text"]


def test_builtin_pinterest_trend_runs_only_with_two_ordered_references() -> None:
    run = trusted_trend_run(
        pinterest_repeat_trend(),
        (
            "https://example.test/pinterest-reference.jpg",
            "https://example.test/user-identity.jpg",
        ),
    )

    assert run.model == "banana_pro"
    assert run.ratio == "auto"
    assert run.reference_urls[0].endswith("pinterest-reference.jpg")
    assert run.reference_urls[1].endswith("user-identity.jpg")

    with pytest.raises(TrendRunValidationError, match="ровно 2 фото"):
        trusted_trend_run(
            pinterest_repeat_trend(),
            ("https://example.test/only-one.jpg",),
        )


def test_builtin_lookup_returns_copy_and_does_not_shadow_other_prompts() -> None:
    first = get_builtin_trend(PINTEREST_REPEAT_TREND_ID)
    second = get_builtin_trend(PINTEREST_REPEAT_TREND_ID)

    assert first is not None
    assert second is not None
    assert first is not second
    assert get_builtin_trend(42) is None


def test_builtin_enables_provider_supported_auto_ratio_for_banana_pro() -> None:
    image_models = (
        {"id": "banana_pro", "ratios": ["1:1", "3:4"]},
        {"id": "other", "ratios": ["1:1"]},
    )

    ensure_builtin_image_model_capabilities(image_models)
    ensure_builtin_image_model_capabilities(image_models)

    assert image_models[0]["ratios"] == ["1:1", "3:4", "auto"]
    assert image_models[1]["ratios"] == ["1:1"]


def test_catalog_and_runtime_install_builtin_pinterest_trend() -> None:
    catalog_source = Path("frontend/miniapp-v0/lib/builtin-trends.ts").read_text(
        encoding="utf-8"
    )
    trends_tab_source = Path(
        "frontend/miniapp-v0/components/tabs/trends-tab.tsx"
    ).read_text(encoding="utf-8")
    route_source = Path("bot/handlers/trend_route_compat.py").read_text(
        encoding="utf-8"
    )

    assert "Повтори фото с Pinterest" in catalog_source
    assert "required_reference_count: 2" in catalog_source
    assert "withBuiltinTrends(trends.filter(hasTrendTag))" in trends_tab_source
    assert "install_builtin_trend_runtime()" in route_source
