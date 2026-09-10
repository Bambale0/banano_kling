import json
from unittest.mock import AsyncMock

import pytest

import bot.services.comet_qwen38_service as qwen_module
from bot.services.comet_qwen38_service import CometQwen38Service, _extract_chat_text


def test_extract_chat_text_reads_openai_compatible_choice() -> None:
    assert _extract_chat_text(
        {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
    ) == '{"ok": true}'


@pytest.mark.asyncio
async def test_qwen_image_uses_openai_multimodal_image_url(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self):
            return json.dumps(
                {"choices": [{"message": {"content": '{"prompt_ru":"ru","prompt_en":"en"}'}}]}
            )

    class FakeSession:
        def __init__(self, timeout):
            captured["timeout"] = timeout.total

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(qwen_module.aiohttp, "ClientSession", FakeSession)
    service = CometQwen38Service(
        api_key="secret-test-key",
        base_url="https://api.cometapi.com/v1",
        model="qwen3.8-max",
    )

    output = await service.analyze_image(
        image_url="https://example.test/photo.jpg",
        system_prompt="system",
        user_instruction="analyze image",
    )

    assert json.loads(output)["prompt_ru"] == "ru"
    assert captured["url"] == "https://api.cometapi.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-test-key"
    payload = captured["payload"]
    assert payload["model"] == "qwen3.8-max"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["messages"][1]["content"] == [
        {
            "type": "image_url",
            "image_url": {"url": "https://example.test/photo.jpg"},
        },
        {"type": "text", "text": "analyze image"},
    ]


@pytest.mark.asyncio
async def test_qwen_video_uses_native_video_url_and_configured_fps() -> None:
    service = CometQwen38Service(
        api_key="test-key",
        base_url="https://api.cometapi.com/v1",
        model="qwen3.8-max",
    )
    service._complete = AsyncMock(return_value='{"prompt_ru":"ru","prompt_en":"en"}')

    await service.analyze_video(
        video_url="https://example.test/clip.mp4",
        system_prompt="system",
        user_instruction="analyze video",
        fps=2,
    )

    content = service._complete.await_args.kwargs["user_content"]
    assert content == [
        {
            "type": "video_url",
            "video_url": {"url": "https://example.test/clip.mp4"},
            "fps": 2.0,
        },
        {"type": "text", "text": "analyze video"},
    ]


@pytest.mark.asyncio
async def test_qwen_retries_rate_limit_once(monkeypatch) -> None:
    responses = [
        (429, {"error": {"message": "rate limited"}}),
        (200, {"choices": [{"message": {"content": "{}"}}]}),
    ]
    calls = []

    class FakeResponse:
        def __init__(self, status, body):
            self.status = status
            self.body = body

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self):
            return json.dumps(self.body)

    class FakeSession:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, headers, json):
            calls.append(url)
            status, body = responses.pop(0)
            return FakeResponse(status, body)

    monkeypatch.setattr(qwen_module.aiohttp, "ClientSession", FakeSession)
    monkeypatch.setattr(qwen_module.asyncio, "sleep", AsyncMock())
    service = CometQwen38Service(api_key="test-key")
    service.max_attempts = 2

    result = await service.analyze_image(
        image_url="https://example.test/photo.jpg",
        system_prompt="system",
        user_instruction="analyze",
    )

    assert result == "{}"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_qwen_requires_api_key_before_network() -> None:
    service = CometQwen38Service(api_key="")
    with pytest.raises(RuntimeError, match="COMETAPI_KEY"):
        await service.analyze_image(
            image_url="https://example.test/photo.jpg",
            system_prompt="system",
            user_instruction="analyze",
        )
