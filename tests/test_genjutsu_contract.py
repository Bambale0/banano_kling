from uuid import uuid4

import pytest

from bot.genjutsu.contract import (
    CATALOG,
    PipelineError,
    billable_seconds,
    compile_plan,
    default_settings,
    provider_input,
    quote_plan,
    validate_settings,
)


def priced_settings():
    settings = default_settings()
    settings["prices"] = {
        "motion_transfer": {"480p": 2, "720p": 3, "1080p": 4},
        "object_swap": {"480p": 2, "720p": 3, "1080p": 4},
        "restyle": {"480p": 2, "720p": 3, "1080p": 4},
    }
    return settings


def assets(duration_ms=4_001):
    return {
        "source": {"id": "source", "kind": "video", "duration_ms": duration_ms, "width": 1280, "height": 720},
        "ref": {"id": "ref", "kind": "image"},
    }


def test_motion_transfer_1080_provider_payload_contains_only_documented_fields():
    raw = {
        "source_asset_id": "source",
        "variants": 1,
        "continuation": "automatic",
        "steps": [{
            "operation": "motion_transfer",
            "resolution": "1080p",
            "prompt": "Replace the actor",
            "preserve": "camera motion",
            "references": [{"asset_id": "ref", "role": "character", "label": "hero"}],
            "preset_id": None,
        }],
    }
    plan = compile_plan(raw, assets(), priced_settings())
    payload = provider_input(plan["steps"][0], "https://media.example/source.mp4", ["https://media.example/ref.png"])
    assert set(payload) == {"video_url", "image_urls", "prompt", "resolution"}
    assert payload["resolution"] == "1080p"
    assert payload["image_urls"] == ["https://media.example/ref.png"]
    assert "Image 1: character - hero" in payload["prompt"]
    assert "Preserve: camera motion" in payload["prompt"]


def test_restyle_allows_zero_images_but_requires_available_uuid_preset():
    preset = str(uuid4())
    raw = {
        "source_asset_id": "source",
        "steps": [{
            "operation": "restyle",
            "resolution": "720p",
            "prompt": "",
            "preserve": "",
            "references": [],
            "preset_id": preset,
        }],
        "variants": 1,
        "continuation": "automatic",
    }
    plan = compile_plan(raw, assets(), priced_settings(), presets={preset})
    payload = provider_input(plan["steps"][0], "https://media.example/source.mp4", [])
    assert payload["preset_id"] == preset
    assert payload["image_urls"] == []

    with pytest.raises(PipelineError, match="preset_unavailable"):
        compile_plan(raw, assets(), priced_settings(), presets=set())


def test_quote_rounds_source_seconds_up_and_reserves_later_step_maximum():
    raw = {
        "source_asset_id": "source",
        "steps": [
            {
                "operation": "motion_transfer", "resolution": "720p", "prompt": "", "preserve": "",
                "references": [{"asset_id": "ref", "role": "character", "label": ""}], "preset_id": None,
            },
            {
                "operation": "object_swap", "resolution": "480p", "prompt": "", "preserve": "",
                "references": [{"asset_id": "ref", "role": "object", "label": ""}], "preset_id": None,
            },
        ],
        "variants": 2,
        "continuation": "automatic",
    }
    settings = priced_settings()
    plan = compile_plan(raw, assets(4_001), settings)
    quote = quote_plan(plan, assets(4_001), settings)
    first = quote["allocations"][0]
    second = quote["allocations"][1]
    assert quote["pricing_version"] == 2
    assert first["reference_seconds"] == 5
    assert first["generation_seconds"] == 5
    assert first["billable_seconds"] == 10
    assert first["reserved_credits"] == 30
    assert second["maximum_reserve"] is True
    assert second["reference_seconds"] == 30
    assert second["generation_seconds"] == 30
    assert second["billable_seconds"] == 60
    assert second["reserved_credits"] == 120
    assert quote["total_credits"] == (30 + 120) * 2



def test_billing_counts_video_reference_and_selected_generation_separately():
    assert billable_seconds(12_000, 8_000) == (12, 8, 20)
    assert billable_seconds(4_001, 8_001) == (5, 9, 14)


@pytest.mark.parametrize("bad_duration", [None, 0, -1, 5.5, True, "5000"])
def test_billing_rejects_invalid_or_missing_duration(bad_duration):
    with pytest.raises(PipelineError, match="invalid_video_duration"):
        billable_seconds(bad_duration, 8_000)
    with pytest.raises(PipelineError, match="invalid_video_duration"):
        billable_seconds(8_000, bad_duration)


def test_operation_specific_reference_roles_fail_closed():
    raw = {
        "source_asset_id": "source",
        "steps": [{
            "operation": "restyle", "resolution": "720p", "prompt": "", "preserve": "",
            "references": [{"asset_id": "ref", "role": "location", "label": "background"}],
            "preset_id": str(uuid4()),
        }],
        "variants": 1,
        "continuation": "automatic",
    }
    with pytest.raises(PipelineError, match="unsupported_reference_role"):
        compile_plan(raw, assets(), priced_settings())


def test_object_swap_rejects_source_below_documented_pixel_floor():
    raw = {
        "source_asset_id": "source",
        "steps": [{
            "operation": "object_swap", "resolution": "720p", "prompt": "", "preserve": "",
            "references": [{"asset_id": "ref", "role": "object", "label": ""}], "preset_id": None,
        }],
        "variants": 1,
        "continuation": "automatic",
    }
    media = assets()
    media["source"].update(width=640, height=480)
    with pytest.raises(PipelineError, match="source_resolution_too_low"):
        compile_plan(raw, media, priced_settings())


LIGHT_ENDPOINTS = {
    "motion_transfer_light": "higgsfield/genjutsu-light/motion-transfer/v1.0",
    "object_swap_light": "higgsfield/genjutsu-light/object-swap/v1.0",
}


def plan(operation, duration_ms=5_000):
    media = {
        "source": {"id": "source", "kind": "video", "duration_ms": duration_ms,
                   "width": 1280, "height": 720},
        "reference": {"id": "reference", "kind": "image"},
    }
    draft = {
        "source_asset_id": "source", "variants": 1, "continuation": "automatic",
        "steps": [{
            "operation": operation, "resolution": "720p",
            "prompt": "Replace the hero", "preserve": "camera",
            "references": [{"asset_id": "reference", "role": "character", "label": "hero"}],
            "preset_id": None,
        }],
    }
    return draft, media


@pytest.mark.parametrize("operation,endpoint", LIGHT_ENDPOINTS.items())
def test_light_catalog_uses_official_model_endpoints(operation, endpoint):
    caps = CATALOG[operation]
    assert caps["provider_path"] == endpoint
    assert caps["resolutions"] == ["480p", "720p", "1080p"]
    assert caps["minimum_video_ms"] == 4_000
    assert caps["maximum_video_ms"] == 15_000
    assert caps["min_images"] == 1

    draft, media = plan(operation, 15_000)
    compiled = compile_plan(draft, media, default_settings())
    payload = provider_input(
        compiled["steps"][0], "https://media.example/source.mp4",
        ["https://media.example/hero.png"],
    )
    assert set(payload) == {"video_url", "image_urls", "prompt", "resolution"}
    assert payload["resolution"] == "720p"
    assert payload["image_urls"] == ["https://media.example/hero.png"]

    draft, media = plan(operation, 15_001)
    with pytest.raises(PipelineError, match="invalid_video_duration"):
        compile_plan(draft, media, default_settings())


def test_persisted_legacy_prices_get_disabled_light_defaults():
    old = default_settings()
    old["prices"] = {
        operation: prices for operation, prices in old["prices"].items()
        if operation not in LIGHT_ENDPOINTS
    }
    old["prices"]["motion_transfer"]["720p"] = 9
    old["public_enabled"] = True
    old["verified_operations"] = ["motion_transfer"]

    migrated = validate_settings(old)
    assert migrated["public_enabled"] is True
    assert migrated["verified_operations"] == ["motion_transfer"]
    assert migrated["prices"]["motion_transfer"]["720p"] == 9
    for operation in LIGHT_ENDPOINTS:
        assert migrated["prices"][operation] == {
            "480p": None, "720p": None, "1080p": None,
        }


def test_existing_tariff_validation_remains_strict():
    old = default_settings()
    del old["prices"]["restyle"]
    with pytest.raises(PipelineError, match="invalid_prices"):
        validate_settings(old)


def test_light_quoted_separately_and_disabled_without_a_rate():
    draft, media = plan("motion_transfer_light")
    settings = default_settings()
    compiled = compile_plan(draft, media, settings)
    with pytest.raises(PipelineError, match="price_not_configured"):
        quote_plan(compiled, media, settings)

    settings["prices"]["motion_transfer_light"]["720p"] = 2
    quote = quote_plan(compiled, media, settings)
    assert quote["total_credits"] == 20
    assert quote["allocations"][0]["reference_seconds"] == 5
    assert quote["allocations"][0]["generation_seconds"] == 5
    assert settings["verified_operations"] == []
