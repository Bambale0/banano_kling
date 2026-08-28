import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from bot.services.rendergrid_nano_banana_provider import (
    MIN_POLL_INTERVAL_SECONDS,
    RenderGridNanoBananaProvider,
    RenderGridProviderError,
)


def _provider(model: str = "nano-banana-2") -> RenderGridNanoBananaProvider:
    return RenderGridNanoBananaProvider(
        api_key="rg_live_test",
        model_name=model,
        base_url="https://api.rendergrid.test/api/public/v1",
        request_timeout_seconds=5,
        generation_timeout_seconds=30,
        poll_interval_seconds=0.1,
        max_retries=0,
    )


def test_rendergrid_payload_preserves_model_settings_and_reference_urls():
    provider = _provider("nano-banana-pro")
    payload = provider._build_payload(
        prompt="Put this person in a studio portrait",
        aspect_ratio="4:3",
        resolution="4K",
        references=["https://cdn.example/ref.png"],
    )

    assert payload["model"] == "nano-banana-pro"
    assert payload["aspect_ratio"] == "4:3"
    assert payload["resolution"] == "4K"
    assert payload["reference_images"] == ["https://cdn.example/ref.png"]
    assert "authoritative visual references" in payload["prompt"]
    assert "Put this person in a studio portrait" in payload["prompt"]


def test_rendergrid_auto_ratio_is_not_sent_to_provider():
    provider = _provider()
    payload = provider._build_payload(
        prompt="A cinematic fox portrait",
        aspect_ratio="auto",
        resolution="BASIC",
        references=[],
    )

    assert "aspect_ratio" not in payload
    assert payload["resolution"] == "2K"


def test_rendergrid_polling_never_goes_below_documented_floor():
    provider = _provider()
    assert provider.poll_interval_seconds == MIN_POLL_INTERVAL_SECONDS


def test_rendergrid_generate_returns_existing_bot_image_bytes_contract():
    provider = _provider("nano-banana-2")
    provider._request = AsyncMock(
        side_effect=[
            {"id": "creation-1", "status": "queued"},
            {
                "id": "creation-1",
                "status": "completed",
                "result_urls": ["https://cdn.example/result.png"],
            },
        ]
    )
    provider._download_result = AsyncMock(return_value=(b"png-bytes", "image/png"))

    async def run():
        original_sleep = asyncio.sleep

        async def no_wait(_delay):
            return None

        asyncio.sleep = no_wait
        try:
            return await provider.generate_image(
                "Create a portrait",
                "1:1",
                "2K",
                ["https://cdn.example/ref.png"],
                "png",
            )
        finally:
            asyncio.sleep = original_sleep
            await provider.close()

    result = asyncio.run(run())

    assert result is not None
    assert result["image_bytes"] == b"png-bytes"
    assert result["provider"] == "rendergrid"
    assert result["provider_model"] == "nano-banana-2"
    assert result["creation_id"] == "creation-1"
    assert result["retryable"] is False


def test_rendergrid_technical_failure_returns_none_for_kie_fallback():
    provider = _provider()
    provider._request = AsyncMock(
        side_effect=RenderGridProviderError("upstream unavailable", status=503)
    )

    result = asyncio.run(
        provider.generate_image("Create a portrait", "1:1", "2K", [], "png")
    )
    asyncio.run(provider.close())

    assert result is None


def test_rendergrid_policy_failure_is_terminal_not_provider_fallback():
    provider = _provider()
    provider._request = AsyncMock(
        side_effect=RenderGridProviderError(
            "content blocked by safety policy",
            status=400,
            code="SAFETY",
        )
    )

    result = asyncio.run(
        provider.generate_image("Create a portrait", "1:1", "2K", [], "png")
    )
    asyncio.run(provider.close())

    assert result is not None
    assert result["provider"] == "rendergrid"
    assert result["retryable"] is False


def test_nanobanana_wiring_is_internal_and_uses_kie_as_rendergrid_fallback():
    root = Path(__file__).resolve().parents[1]
    services_init = (root / "bot/services/__init__.py").read_text(encoding="utf-8")

    assert 'NANOBANANA_RENDERGRID_ENABLED' in services_init
    assert 'NANOBANANA2_RENDERGRID_ENABLED' in services_init
    assert 'NANOBANANAPRO_RENDERGRID_ENABLED' in services_init
    assert 'RENDERGRID_NANO_BANANA_2_MODEL' in services_init
    assert 'RENDERGRID_NANO_BANANA_PRO_MODEL' in services_init
    assert 'service.primary_provider = RenderGridNanoBananaProvider(' in services_init
    assert 'service.fallback_provider = kie_provider' in services_init

    # Provider migration is intentionally below the UI/handler layer.
    assert "bot/handlers" not in services_init
    assert "InlineKeyboard" not in services_init
