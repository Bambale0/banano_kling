"""TDD for VK-only video trend repeat using native VK execution and wallet."""

import pytest

from bot.shared_accounts.vk_video_trends import (
    build_native_video_trend_request,
    supports_native_vk_video_trend,
)
from bot.trend_api import TrustedTrendRun


CATALOG = {
    "ok": True,
    "video_models": [{
        "id": "v3_std", "label": "Kling Standard",
        "ratios": ["16:9", "9:16"], "durations": [5, 6],
        "scenarios": ["text", "imgtxt"], "max_image_references": 2,
        "costs": {"5": 12, "6": 14},
    }],
}

SETTINGS = {
    "kind": "video", "model": "v3_std", "user_input": "photo",
    "scenario": "imgtxt", "ratio": "16:9", "duration": 5, "count": 1,
}


def _trusted(**patch):
    settings = dict(SETTINGS)
    settings.update(patch.pop("settings", {}))
    values = {
        "trend_id": 31, "kind": "video", "model": "v3_std",
        "ratio": "16:9", "prompt": "Two friendly foxes wave",
        "reference_urls": ("https://example.invalid/personal.jpg",),
        "settings": settings,
    }
    values.update(patch)
    return TrustedTrendRun(**values)


def _public_trend(settings=None):
    return {
        "generation_settings": dict(SETTINGS if settings is None else settings),
        "status": "approved", "is_public": True,
        "tags": ["trend"], "id": 31,
    }


def test_capability_checks_basic_video_and_rejects_unsupported_recipe():
    assert supports_native_vk_video_trend(_public_trend())
    for patch in (
        {"scenario": "text"}, {"count": 2},
        {"reference_contract": "private_assets_v2"},
        {"seedance25_video_editing": True},
        {"genjutsu_recipe_id": "secret"},
        {"user_input": "video"}, {"duration": 0},
        {"duration": "5"}, {"model": ""},
    ):
        assert not supports_native_vk_video_trend(
            _public_trend({**SETTINGS, **patch})
        )


def test_video_native_payload_server_owned_model_prompt_duration_and_refs():
    payload = build_native_video_trend_request(
        _trusted(),
        CATALOG,
        ["https://example.invalid/upload.jpg"],
        key="vk_0123456789abcdef0123456789abcdef",
        quote_only=False,
        expected_cost=12,
    )
    assert payload == {
        "model": "v3_std",
        "prompt": "Two friendly foxes wave",
        "aspect": "16:9",
        "duration": 5,
        "reference_photos": ["https://example.invalid/upload.jpg"],
        "client_request_id": "vk_0123456789abcdef0123456789abcdef",
        "expected_cost": 12,
    }


def test_quote_never_requires_client_cost_or_claim():
    payload = build_native_video_trend_request(
        _trusted(), CATALOG, ["https://example.invalid/upload.jpg"],
        key=None, quote_only=True, expected_cost=None,
    )
    assert payload["quote_only"] is True
    assert "client_request_id" not in payload
    assert "expected_cost" not in payload


@pytest.mark.parametrize("change", [
    {"kind": "image"},
    {"reference_contract": "seedance-assets"},
    {"template_image_urls": ("https://example.invalid/private.png",)},
    {"template_video_urls": ("https://example.invalid/private.mp4",)},
    {"assembled_video_urls": ("https://example.invalid/private.mp4",)},
    {"template_audio_urls": ("https://example.invalid/private.wav",)},
])
def test_rejects_foreign_recipe_or_hidden_assets(change):
    core = dict(change)
    settings_patch = {"reference_contract": core.pop("reference_contract")} if "reference_contract" in core else {}
    obj = _trusted(settings=settings_patch, **core)
    with pytest.raises(ValueError):
        build_native_video_trend_request(
            obj, CATALOG, ["https://example.invalid/personal.jpg"],
            key="vk_0123456789abcdef0123456789abcdef",
            quote_only=False, expected_cost=12,
        )


@pytest.mark.parametrize("model,refs", [
    ("not_native", ["https://example.invalid/1.jpg"]),
    ("v3_std", []),
    ("v3_std", ["https://example.invalid/1.jpg",
                "https://example.invalid/2.jpg",
                "https://example.invalid/3.jpg"]),
])
def test_native_catalog_and_reference_limits_are_authoritative(model, refs):
    obj = _trusted()
    if model != "v3_std":
        obj = _trusted(settings={"model": model})
    with pytest.raises(ValueError):
        build_native_video_trend_request(
            obj, CATALOG, refs, key="vk_0123456789abcdef0123456789abcdef",
            quote_only=False, expected_cost=12,
        )


def test_rejects_stale_duration_and_native_scenario_without_any_money_call():
    obj = _trusted(settings={"duration": 7})
    with pytest.raises(ValueError):
        build_native_video_trend_request(
            obj, CATALOG, ["https://example.invalid/one.jpg"],
            key=None, quote_only=True, expected_cost=None,
        )


def test_no_client_defined_idempotency_key_for_paid_video_is_rejected():
    with pytest.raises(ValueError):
        build_native_video_trend_request(
            _trusted(), CATALOG, ["https://example.invalid/one.jpg"],
            key="bad", quote_only=False, expected_cost=12,
        )
