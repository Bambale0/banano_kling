import pytest

from bot.keyboards import get_create_video_keyboard
from bot.services.kling_service import KlingService


@pytest.mark.asyncio
async def test_wan_27_i2v_payload_matches_kie_docs(monkeypatch):
    captured = {}
    service = KlingService(kie_key="test-key")

    async def fake_post(endpoint, payload):
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        return {"task_id": "task_wan_i2v", "status": "pending"}

    monkeypatch.setattr(service, "_kie_post", fake_post)

    result = await service.generate_video(
        prompt="slow cinematic camera push",
        model="wan_27_i2v",
        duration=5,
        aspect_ratio="16:9",
        image_url="https://example.com/start.png",
        wan_resolution="1080p",
        wan_prompt_extend=True,
        wan_watermark=False,
        webhook_url="https://example.com/webhook",
    )

    assert result["task_id"] == "task_wan_i2v"
    assert captured["endpoint"] == "/api/v1/jobs/createTask"
    assert captured["payload"]["model"] == "wan/2-7-image-to-video"
    assert captured["payload"]["callBackUrl"] == "https://example.com/webhook"

    input_data = captured["payload"]["input"]
    assert input_data["first_frame_url"] == "https://example.com/start.png"
    assert input_data["resolution"] == "1080p"
    assert input_data["duration"] == 5
    assert "ratio" not in input_data
    assert "aspect_ratio" not in input_data
    assert "nsfw_checker" not in input_data


@pytest.mark.asyncio
async def test_wan_27_t2v_payload_uses_ratio_field_from_kie_docs(monkeypatch):
    captured = {}
    service = KlingService(kie_key="test-key")

    async def fake_post(endpoint, payload):
        captured["payload"] = payload
        return {"task_id": "task_wan_t2v", "status": "pending"}

    monkeypatch.setattr(service, "_kie_post", fake_post)

    result = await service.generate_video(
        prompt="futuristic city at night",
        model="wan_27_t2v",
        duration=10,
        aspect_ratio="9:16",
        wan_resolution="720p",
    )

    assert result["task_id"] == "task_wan_t2v"
    assert captured["payload"]["model"] == "wan/2-7-text-to-video"
    input_data = captured["payload"]["input"]
    assert input_data["ratio"] == "9:16"
    assert "aspect_ratio" not in input_data


def test_wan_27_i2v_keyboard_does_not_show_ratio_buttons():
    kb = get_create_video_keyboard(
        current_v_type="imgtxt",
        current_model="wan_27_i2v",
        current_duration=5,
        current_ratio="16:9",
    )

    callback_data = [
        button.callback_data for row in kb.inline_keyboard for button in row
    ]
    assert not any(str(data).startswith("vratio_") for data in callback_data)
