import pytest

from bot.services.seedream_service import SeedreamLiteService


@pytest.mark.asyncio
async def test_flux_2_image_to_image_uses_input_urls(monkeypatch):
    service = SeedreamLiteService(api_key="test-key")
    captured = {}

    async def fake_post(endpoint, payload):
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        return {"data": {"taskId": "task-flux-2"}}

    monkeypatch.setattr(service, "_post", fake_post)

    task_id = await service.create_task(
        model="flux-2/pro-image-to-image",
        prompt="polish product photo",
        image_urls=["https://example.com/ref.png"],
        aspect_ratio="1:1",
    )

    assert task_id == "task-flux-2"
    assert captured["endpoint"] == "/api/v1/jobs/createTask"
    assert captured["payload"]["input"]["input_urls"] == ["https://example.com/ref.png"]
    assert "image_urls" not in captured["payload"]["input"]


@pytest.mark.asyncio
async def test_seedream_5_lite_image_to_image_uses_image_urls(monkeypatch):
    service = SeedreamLiteService(api_key="test-key")
    captured = {}

    async def fake_post(endpoint, payload):
        captured["payload"] = payload
        return {"data": {"taskId": "task-seedream-5"}}

    monkeypatch.setattr(service, "_post", fake_post)

    task_id = await service.create_task(
        model="seedream/5-lite-image-to-image",
        prompt="keep composition, change style",
        image_urls=["https://example.com/ref.png"],
    )

    assert task_id == "task-seedream-5"
    assert captured["payload"]["input"]["image_urls"] == ["https://example.com/ref.png"]
    assert "input_urls" not in captured["payload"]["input"]
