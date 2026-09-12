import json

import pytest

from bot.services import (
    photo_prompt_service as photo_prompt_module,
)
from bot.services import (
    photo_prompt_vk_compat as vk_compat,
)

EXPECTED_PROMPT = (
    "Составь подробный промпт для создания максимально похожего фото в Banana Pro. "
    "Сохрани все мелкие детали, лицо, одежду, позу, освещение, стиль, цвета. "
    "На русском языке."
)
EXPECTED_INSTRUCTIONS = (
    "Ты эксперт по промптам для генерации изображений. "
    "Отвечай только готовым промптом без вводных фраз."
)


def test_vk_payload_is_exact() -> None:
    payload = vk_compat.build_vk_photo_analysis_payload(
        model="gpt-5.4",
        image_url="data:image/jpeg;base64,abc",
    )

    assert payload == {
        "model": "gpt-5.4",
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": EXPECTED_PROMPT,
                    },
                    {
                        "type": "input_image",
                        "image_url": "data:image/jpeg;base64,abc",
                        "detail": "high",
                    },
                ],
            }
        ],
        "instructions": EXPECTED_INSTRUCTIONS,
        "max_output_tokens": 1200,
    }


def test_vk_default_model_chain_matches_vk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APIYI_VISION_MODEL", raising=False)
    monkeypatch.delenv("APIYI_VISION_FALLBACK_MODELS", raising=False)

    assert vk_compat._configured_models() == ["gpt-5.5"]


@pytest.mark.asyncio
async def test_exact_vk_request_is_sent_to_apiyi(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self) -> str:
            return json.dumps({"output_text": "точный готовый промпт"})

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    async def fake_inline_image_url(photo_url: str) -> str:
        assert photo_url == "https://telegram.local/photo.jpg"
        return "data:image/jpeg;base64,telegram"

    monkeypatch.setattr(vk_compat, "_inline_image_url", fake_inline_image_url)
    monkeypatch.setattr(vk_compat, "_apiyi_api_key", lambda: "apiyi-test-key")
    monkeypatch.setattr(vk_compat, "_apiyi_base_url", lambda: "https://api.apiyi.com/v1")
    monkeypatch.setattr(vk_compat, "_configured_models", lambda: ["gpt-5.4"])
    monkeypatch.setattr(vk_compat.aiohttp, "ClientSession", FakeSession)

    prompt, model = await vk_compat.analyze_photo_exactly_as_vk(
        "https://telegram.local/photo.jpg"
    )

    assert prompt == "точный готовый промпт"
    assert model == "gpt-5.4"
    assert captured["url"] == "https://api.apiyi.com/v1/responses"
    assert captured["headers"]["Authorization"] == "Bearer apiyi-test-key"
    assert captured["json"] == vk_compat.build_vk_photo_analysis_payload(
        model="gpt-5.4",
        image_url="data:image/jpeg;base64,telegram",
    )


@pytest.mark.asyncio
async def test_main_telegram_photo_service_uses_qwen38_not_legacy_vk_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    class FakeQwen:
        enabled = True
        model = "qwen/qwen3.8-max-0902"

        async def analyze_image(
            self,
            *,
            image_url: str,
            system_prompt: str,
            user_instruction: str,
        ) -> str:
            captured["image_url"] = image_url
            captured["system_prompt"] = system_prompt
            captured["user_instruction"] = user_instruction
            return json.dumps(
                {
                    "prompt_ru": "результат Qwen 3.8",
                    "prompt_en": "Qwen 3.8 result",
                    "negative_prompt": "blur",
                    "model_hint": "Nano Banana Pro",
                    "key_details": ["soft light"],
                },
                ensure_ascii=False,
            )

    async def legacy_vk_must_not_run(_image_url: str) -> tuple[str, str]:
        raise AssertionError("legacy VK/APIYI photo route must not run")

    monkeypatch.setattr(
        photo_prompt_module,
        "openrouter_qwen38_service",
        FakeQwen(),
    )
    monkeypatch.setattr(
        vk_compat,
        "analyze_photo_exactly_as_vk",
        legacy_vk_must_not_run,
    )

    result = await photo_prompt_module.photo_prompt_service.analyze_photo(
        image_url="/static/uploads/photo.jpg",
        preserve="сохранить детали",
        goal="сделать похожий кадр",
        user_note="мягкий свет",
    )

    assert result["prompt_ru"] == "результат Qwen 3.8"
    assert result["prompt_en"] == "Qwen 3.8 result"
    assert result["negative_prompt"] == "blur"
    assert captured["image_url"] == "/static/uploads/photo.jpg"
    assert "сделать похожий кадр" in captured["user_instruction"]
    assert "сохранить детали" in captured["user_instruction"]
    assert "мягкий свет" in captured["user_instruction"]


@pytest.mark.asyncio
async def test_legacy_vk_callback_is_routed_through_unified_qwen_analyzer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib
    from unittest.mock import AsyncMock

    image_analyzer = importlib.import_module("bot.handlers.image_analyzer")
    prompt_module = importlib.import_module("bot.services.prompt_analyzer_v2_service")
    analyze_prompt = AsyncMock(
        return_value={
            "prompt_ru": "Qwen legacy callback result",
            "prompt_en": "Qwen legacy callback result EN",
        }
    )
    monkeypatch.setattr(
        prompt_module.prompt_analyzer_v2_service,
        "analyze_prompt",
        analyze_prompt,
    )

    result = await image_analyzer._vk_analyze_photo(
        "https://example.test/reference.jpg"
    )

    assert result == "Qwen legacy callback result"
    analyze_prompt.assert_awaited_once()
    kwargs = analyze_prompt.await_args.kwargs
    assert kwargs["image_url"] == "https://example.test/reference.jpg"
    assert "подробный промпт" in kwargs["text"]
