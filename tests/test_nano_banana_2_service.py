import pytest

from bot.image_models import normalize_image_options
from bot.services.nano_banana_2_service import NanoBanana2Service


@pytest.mark.asyncio
async def test_nano_banana_2_retries_lower_resolution_on_422(monkeypatch):
    service = NanoBanana2Service(api_key="test-key")
    payloads = []

    async def fake_post(endpoint, payload):
        payloads.append(payload)
        if len(payloads) == 1:
            return {"code": 422, "msg": "Validation Error", "data": None}
        return {"code": 200, "msg": "success", "data": {"taskId": "task-ok"}}

    monkeypatch.setattr(service, "_post", fake_post)

    task_id = await service.create_task(
        prompt="portrait",
        aspect_ratio="1:1",
        resolution="4K",
        output_format="png",
        callback_url="https://example.com/webhook",
    )

    assert task_id == "task-ok"
    assert [item["input"]["resolution"] for item in payloads] == ["4K", "2K"]
    assert payloads[1]["callBackUrl"] == "https://example.com/webhook"


def test_nano_banana_2_default_resolution_matches_kie_docs():
    options = normalize_image_options("banana_2")

    assert options["resolution"] == "1K"
