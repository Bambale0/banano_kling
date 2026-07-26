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

    assert vk_compat._configured_models() == ["gpt-5.4", "gpt-5.5", "gpt-4o"]


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
async def test_main_telegram_photo_service_uses_exact_vk_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_vk_analysis(image_url: str) -> tuple[str, str]:
        assert image_url == "/static/uploads/photo.jpg"
        return "результат ровно из VK-контракта", "gpt-5.4"

    monkeypatch.setattr(vk_compat, "analyze_photo_exactly_as_vk", fake_vk_analysis)

    result = await photo_prompt_module.photo_prompt_service.analyze_photo(
        image_url="/static/uploads/photo.jpg",
        preserve="это должно быть проигнорировано для точного VK режима",
        goal="это тоже должно быть проигнорировано",
        user_note="и подпись не меняет VK payload",
    )

    assert result["prompt_ru"] == "результат ровно из VK-контракта"
    assert result["prompt_en"] == ""
    assert result["negative_prompt"] == ""
    assert result["raw"]["analysis_contract"] == "vk_exact"
    assert result["raw"]["analysis_model"] == "gpt-5.4"
