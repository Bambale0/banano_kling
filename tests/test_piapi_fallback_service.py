import pytest

from bot.services.piapi_fallback_service import PiapiFallbackService


class _FakeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return '{"data": {"task_id": "piapi-task-1"}}'


class _FakeSession:
    def __init__(self):
        self.closed = False
        self.calls = []

    def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse()


@pytest.mark.asyncio
async def test_piapi_image_fallback_payload_uses_task_api():
    session = _FakeSession()
    service = PiapiFallbackService(api_key="test-key", base_url="https://piapi.test")
    service._session = session

    result = await service.generate_image(
        provider_model="banana_pro",
        prompt="cat in cyberpunk city",
        aspect_ratio="9:16",
        image_urls=["https://example.com/ref.png"],
        callback_url="https://example.com/webhook",
    )

    assert result["task_id"] == "piapi-task-1"
    call = session.calls[0]
    assert call["url"] == "https://piapi.test/api/v1/task"
    assert call["headers"]["x-api-key"] == "test-key"
    assert call["json"]["model"] == "gemini"
    assert call["json"]["task_type"] == "nano-banana-pro"
    assert call["json"]["input"]["prompt"] == "cat in cyberpunk city"
    assert call["json"]["input"]["aspect_ratio"] == "9:16"
    assert call["json"]["config"]["webhook_config"]["endpoint"] == "https://example.com/webhook"


@pytest.mark.asyncio
async def test_piapi_video_fallback_payload_maps_unknown_to_kling():
    session = _FakeSession()
    service = PiapiFallbackService(api_key="test-key", base_url="https://piapi.test")
    service._session = session

    result = await service.generate_video(
        provider_model="unknown_video",
        prompt="slow camera push",
        duration=10,
        aspect_ratio="16:9",
        image_url="https://example.com/start.jpg",
    )

    assert result["task_id"] == "piapi-task-1"
    payload = session.calls[0]["json"]
    assert payload["model"] == "kling"
    assert payload["task_type"] == "video_generation"
    assert payload["input"]["model_name"] == "unknown_video"
    assert payload["input"]["image_url"] == "https://example.com/start.jpg"
