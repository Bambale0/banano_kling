"""Contract and compatibility regressions for official Higgsfield Genjutsu Light.

The public launch remains gated by verified operations and admin-configured rates.
"""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from bot.genjutsu.contract import (
    CATALOG,
    PipelineError,
    compile_plan,
    default_settings,
    provider_input,
    quote_plan,
    validate_settings,
)
from bot.genjutsu.provider import Higgsfield


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


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,endpoint", LIGHT_ENDPOINTS.items())
async def test_light_provider_submit_reuses_hardened_async_client(operation, endpoint):
    captured = []

    async def submit(request):
        captured.append((request.path, request.headers.get("Idempotency-Key"),
                         await request.json()))
        return web.json_response({
            "request_id": "req_light",
            "status_url": str(request.url.with_path("/requests/req_light/status")),
            "cancel_url": str(request.url.with_path("/requests/req_light/cancel")),
        })

    app = web.Application()
    app.router.add_post("/" + endpoint, submit)
    server = TestServer(app)
    await server.start_server()
    try:
        provider = Higgsfield(
            "server-secret", str(server.make_url("")).rstrip("/"),
            allow_insecure_for_tests=True,
        )
        draft, media = plan(operation)
        compiled = compile_plan(draft, media, default_settings())
        payload = provider_input(
            compiled["steps"][0], "https://media.example/source.mp4",
            ["https://media.example/hero.png"],
        )
        handle = await provider.submit(
            endpoint, payload, timeout=5, idempotency_key="light-intent-1234",
        )
        assert handle["request_id"] == "req_light"
        assert len(captured) == 1
        assert captured[0][0] == "/" + endpoint
        assert captured[0][1] == "light-intent-1234"
        assert set(captured[0][2]) == {"video_url", "image_urls", "prompt", "resolution"}
    finally:
        await server.close()
