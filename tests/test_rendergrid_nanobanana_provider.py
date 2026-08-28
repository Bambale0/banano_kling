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


def test_rendergrid_payload_hands_references_to_verified_client():
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
    assert payload["prompt"] == "Put this person in a studio portrait"


def test_rendergrid_verified_client_uses_image_urls_and_preserves_user_prompt():
    provider = _provider("nano-banana-2")
    provider.client._request = AsyncMock(
        return_value={"id": "creation-ref", "status": "queued"}
    )
    reference_url = "https://cdn.example/ref.png"
    user_prompt = "Keep the same person"

    result = asyncio.run(
        provider.client.generate_image(
            {
                "model": "nano-banana-2",
                "prompt": user_prompt,
                "reference_images": [reference_url],
            },
            idempotency_key="external-ref",
        )
    )

    assert result["id"] == "creation-ref"
    sent = provider.client._request.await_args.kwargs["json_body"]
    assert sent["image_urls"] == [reference_url]
    assert "reference_images" not in sent
    assert sent["prompt"] == user_prompt
    assert "[REFERENCE IDENTITY LOCK]" not in sent["prompt"]
    assert "User request:" not in sent["prompt"]


def test_rendergrid_verified_client_uses_file_ids_for_local_uploads():
    provider = _provider("nano-banana-pro")
    provider.client._upload_local_reference = AsyncMock(return_value="file-ref-1")
    provider.client._request = AsyncMock(
        return_value={"id": "creation-local", "status": "queued"}
    )
    reference_url = "https://tanyapi.chillcreative.ru/uploads/ref.png"

    result = asyncio.run(
        provider.client.generate_image(
            {
                "model": "nano-banana-pro",
                "prompt": "Keep the same face",
                "reference_images": [reference_url],
            },
            idempotency_key="local-ref",
        )
    )

    assert result["id"] == "creation-local"
    provider.client._upload_local_reference.assert_awaited_once_with(reference_url)
    sent = provider.client._request.await_args.kwargs["json_body"]
    assert sent["image_file_ids"] == ["file-ref-1"]
    assert "image_urls" not in sent
    assert "reference_images" not in sent


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
    provider.client.generate_image = AsyncMock(
        return_value={"id": "creation-1", "status": "queued"}
    )
    provider.client.wait_for_creation = AsyncMock(
        return_value={
            "id": "creation-1",
            "status": "completed",
            "result_urls": ["https://cdn.example/result.png"],
        }
    )
    provider._download_result = AsyncMock(return_value=(b"png-bytes", "image/png"))

    result = asyncio.run(
        provider.generate_image(
            "Create a portrait",
            "1:1",
            "2K",
            ["https://cdn.example/ref.png"],
            "png",
        )
    )
    asyncio.run(provider.close())

    assert result is not None
    assert result["image_bytes"] == b"png-bytes"
    assert result["provider"] == "rendergrid"
    assert result["provider_model"] == "nano-banana-2"
    assert result["creation_id"] == "creation-1"
    assert result["retryable"] is False


def test_rendergrid_4k_validation_retries_lowercase_inside_rendergrid():
    provider = _provider("nano-banana-pro")
    provider.client.generate_image = AsyncMock(
        side_effect=[
            RenderGridProviderError("invalid resolution", status=422),
            {
                "id": "creation-4k",
                "status": "completed",
                "result_urls": ["https://cdn.example/result-4k.png"],
            },
        ]
    )
    provider._download_result = AsyncMock(return_value=(b"4k-bytes", "image/png"))

    result = asyncio.run(
        provider.generate_image("Create a portrait", "1:1", "4K", [], "png")
    )
    asyncio.run(provider.close())

    assert result is not None
    assert result["provider"] == "rendergrid"
    assert result["image_bytes"] == b"4k-bytes"
    assert provider.client.generate_image.await_count == 2
    first_payload = provider.client.generate_image.await_args_list[0].args[0]
    second_payload = provider.client.generate_image.await_args_list[1].args[0]
    assert first_payload["resolution"] == "4K"
    assert second_payload["resolution"] == "4k"


def test_rendergrid_4k_validation_failure_never_silently_switches_to_kie():
    provider = _provider("nano-banana-pro")
    provider.client.generate_image = AsyncMock(
        side_effect=[
            RenderGridProviderError("invalid resolution", status=422),
            RenderGridProviderError("invalid resolution", status=422),
        ]
    )

    result = asyncio.run(
        provider.generate_image("Create a portrait", "1:1", "4K", [], "png")
    )
    asyncio.run(provider.close())

    assert result is not None
    assert result["provider"] == "rendergrid"
    assert result["http_status"] == 422
    assert result["retryable"] is False
    assert provider.client.generate_image.await_count == 2


def test_rendergrid_technical_failure_returns_none_for_kie_fallback():
    provider = _provider()
    provider.client.generate_image = AsyncMock(
        side_effect=RenderGridProviderError("upstream unavailable", status=503)
    )

    result = asyncio.run(
        provider.generate_image("Create a portrait", "1:1", "2K", [], "png")
    )
    asyncio.run(provider.close())

    assert result is None


def test_rendergrid_request_validation_is_terminal_not_kie_fallback():
    provider = _provider()
    provider.client.generate_image = AsyncMock(
        side_effect=RenderGridProviderError("invalid request", status=422)
    )

    result = asyncio.run(
        provider.generate_image("Create a portrait", "1:1", "2K", [], "png")
    )
    asyncio.run(provider.close())

    assert result is not None
    assert result["provider"] == "rendergrid"
    assert result["http_status"] == 422
    assert result["retryable"] is False


def test_rendergrid_policy_failure_is_terminal_not_provider_fallback():
    provider = _provider()
    provider.client.generate_image = AsyncMock(
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

    assert "NANOBANANA_RENDERGRID_ENABLED" in services_init
    assert "NANOBANANA2_RENDERGRID_ENABLED" in services_init
    assert "NANOBANANAPRO_RENDERGRID_ENABLED" in services_init
    assert "RENDERGRID_NANO_BANANA_2_MODEL" in services_init
    assert "RENDERGRID_NANO_BANANA_PRO_MODEL" in services_init
    assert "service.primary_provider = RenderGridNanoBananaProvider(" in services_init
    assert "service.fallback_provider = kie_provider" in services_init

    # Provider migration stays below the UI/handler layer.
    assert "bot/handlers" not in services_init
    assert "InlineKeyboard" not in services_init
