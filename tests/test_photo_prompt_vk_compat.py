import pytest

from bot.services import photo_prompt_vk_compat


def test_apiyi_key_falls_back_to_existing_provider_keys(monkeypatch):
    monkeypatch.delenv("APIYI_API_KEY", raising=False)
    monkeypatch.setenv("NANO_BANANA_PRO_FALLBACK_API_KEY", "pro-key")
    monkeypatch.setenv("NANOBANANA2_FALLBACK_API_KEY", "lite-key")

    assert photo_prompt_vk_compat._apiyi_api_key() == "pro-key"


def test_apiyi_vision_defaults_to_gpt55_only(monkeypatch):
    monkeypatch.delenv("APIYI_VISION_MODEL", raising=False)
    monkeypatch.delenv("APIYI_VISION_FALLBACK_MODELS", raising=False)

    assert photo_prompt_vk_compat._configured_models() == ["gpt-5.5"]


@pytest.mark.asyncio
async def test_vk_wrapper_falls_back_to_original_service_without_apiyi_key(monkeypatch):
    monkeypatch.delenv("APIYI_API_KEY", raising=False)
    monkeypatch.delenv("NANO_BANANA_PRO_FALLBACK_API_KEY", raising=False)
    monkeypatch.delenv("NANOBANANA2_FALLBACK_API_KEY", raising=False)

    async def original_analyze_photo(**kwargs):
        return {"prompt_ru": "fallback prompt", "raw": {"kwargs": kwargs}}

    async def missing_apiyi_key(_image_url):
        raise RuntimeError(
            "APIYI_API_KEY is not configured; exact VK photo analysis is unavailable"
        )

    monkeypatch.setattr(
        photo_prompt_vk_compat,
        "analyze_photo_exactly_as_vk",
        missing_apiyi_key,
    )

    import bot.services.photo_prompt_service as module

    previous_installed = getattr(module, "_vk_photo_prompt_exact_installed", False)
    previous_analyze_photo = module.photo_prompt_service.analyze_photo
    try:
        module._vk_photo_prompt_exact_installed = False
        module.photo_prompt_service.analyze_photo = original_analyze_photo
        photo_prompt_vk_compat.install_vk_photo_prompt_instructions()

        result = await module.photo_prompt_service.analyze_photo(
            image_url="https://example.com/a.jpg"
        )

        assert result["prompt_ru"] == "fallback prompt"
        assert result["raw"]["kwargs"]["image_url"] == "https://example.com/a.jpg"
    finally:
        module.photo_prompt_service.analyze_photo = previous_analyze_photo
        module._vk_photo_prompt_exact_installed = previous_installed


@pytest.mark.asyncio
async def test_vk_wrapper_falls_back_to_original_service_after_apiyi_provider_error(monkeypatch):
    async def original_analyze_photo(**kwargs):
        return {"prompt_ru": "fallback after provider error", "raw": {"kwargs": kwargs}}

    async def provider_unavailable(_image_url):
        raise ValueError(
            "APIYI photo analysis failed for all configured models: "
            "APIYI vision error 503: no available channels"
        )

    monkeypatch.setattr(
        photo_prompt_vk_compat,
        "analyze_photo_exactly_as_vk",
        provider_unavailable,
    )

    import bot.services.photo_prompt_service as module

    previous_installed = getattr(module, "_vk_photo_prompt_exact_installed", False)
    previous_analyze_photo = module.photo_prompt_service.analyze_photo
    try:
        module._vk_photo_prompt_exact_installed = False
        module.photo_prompt_service.analyze_photo = original_analyze_photo
        photo_prompt_vk_compat.install_vk_photo_prompt_instructions()

        result = await module.photo_prompt_service.analyze_photo(
            image_url="https://example.com/a.jpg"
        )

        assert result["prompt_ru"] == "fallback after provider error"
    finally:
        module.photo_prompt_service.analyze_photo = previous_analyze_photo
        module._vk_photo_prompt_exact_installed = previous_installed
