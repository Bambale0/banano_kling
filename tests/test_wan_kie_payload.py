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
        end_image_url="https://example.com/end.png",
        wan_resolution="1080p",
        wan_prompt_extend=True,
        wan_watermark=False,
        wan_nsfw_checker=True,
        wan_first_clip_url="https://example.com/guide.mp4",
        wan_driving_audio_url="https://example.com/audio.wav",
        wan_seed=42,
        webhook_url="https://example.com/webhook",
    )

    assert result["task_id"] == "task_wan_i2v"
    assert captured["endpoint"] == "/api/v1/jobs/createTask"
    assert captured["payload"]["model"] == "wan/2-7-image-to-video"
    assert captured["payload"]["callBackUrl"] == "https://example.com/webhook"

    input_data = captured["payload"]["input"]
    assert input_data["first_frame_url"] == "https://example.com/start.png"
    assert input_data["last_frame_url"] == "https://example.com/end.png"
    assert input_data["first_clip_url"] == "https://example.com/guide.mp4"
    assert input_data["driving_audio_url"] == "https://example.com/audio.wav"
    assert input_data["resolution"] == "1080p"
    assert input_data["duration"] == 5
    assert input_data["seed"] == 42
    assert input_data["nsfw_checker"] is True
    assert "ratio" not in input_data
    assert "aspect_ratio" not in input_data


@pytest.mark.asyncio
async def test_wan_27_t2v_payload_matches_kie_docs(monkeypatch):
    captured = {}
    service = KlingService(kie_key="test-key")

    async def fake_post(endpoint, payload):
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        return {"task_id": "task_wan_t2v", "status": "pending"}

    monkeypatch.setattr(service, "_kie_post", fake_post)

    result = await service.generate_video(
        prompt="futuristic city at night",
        model="wan_27_t2v",
        duration=15,
        aspect_ratio="3:4",
        negative_prompt="blur, low quality",
        wan_resolution="1080p",
        wan_prompt_extend=True,
        wan_watermark=False,
        wan_nsfw_checker=True,
        wan_audio_url="https://example.com/audio.wav",
        wan_seed=42,
        webhook_url="https://example.com/webhook",
    )

    assert result["task_id"] == "task_wan_t2v"
    assert captured["endpoint"] == "/api/v1/jobs/createTask"
    assert captured["payload"]["model"] == "wan/2-7-text-to-video"
    assert captured["payload"]["callBackUrl"] == "https://example.com/webhook"
    input_data = captured["payload"]["input"]
    assert input_data == {
        "prompt": "futuristic city at night",
        "negative_prompt": "blur, low quality",
        "resolution": "1080p",
        "duration": 15,
        "prompt_extend": True,
        "watermark": False,
        "ratio": "3:4",
        "audio_url": "https://example.com/audio.wav",
        "seed": 42,
        "nsfw_checker": True,
    }
    assert "aspect_ratio" not in input_data


@pytest.mark.asyncio
async def test_wan_27_image_payload_matches_kie_docs(monkeypatch):
    captured = {}
    service = KlingService(kie_key="test-key")

    async def fake_post(endpoint, payload):
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        return {"task_id": "task_wan_image", "status": "pending"}

    monkeypatch.setattr(service, "_kie_post", fake_post)

    result = await service.generate_wan_image(
        prompt="turn image into a pencil drawing",
        model="wan_27_image",
        input_urls=["https://example.com/in.webp"],
        n=4,
        enable_sequential=False,
        resolution="2K",
        thinking_mode=True,
        aspect_ratio="21:9",
        watermark=True,
        seed=42,
        nsfw_checker=True,
        callback_url="https://example.com/webhook",
    )

    assert result["task_id"] == "task_wan_image"
    assert captured["endpoint"] == "/api/v1/jobs/createTask"
    assert captured["payload"]["model"] == "wan/2-7-image"
    assert captured["payload"]["input"] == {
        "prompt": "turn image into a pencil drawing",
        "input_urls": ["https://example.com/in.webp"],
        "n": 4,
        "enable_sequential": False,
        "resolution": "2K",
        "thinking_mode": True,
        "aspect_ratio": "21:9",
        "watermark": True,
        "seed": 42,
        "nsfw_checker": True,
    }


@pytest.mark.asyncio
async def test_wan_27_image_pro_payload_matches_kie_docs(monkeypatch):
    captured = {}
    service = KlingService(kie_key="test-key")

    async def fake_post(endpoint, payload):
        captured["payload"] = payload
        return {"task_id": "task_wan_image_pro", "status": "pending"}

    monkeypatch.setattr(service, "_kie_post", fake_post)

    await service.generate_wan_image(
        prompt="premium product photo",
        model="wan_27_image_pro",
        resolution="4K",
        thinking_mode=False,
        aspect_ratio="1:1",
    )

    assert captured["payload"]["model"] == "wan/2-7-image-pro"
    assert captured["payload"]["input"]["resolution"] == "4K"
    assert captured["payload"]["input"]["thinking_mode"] is False


@pytest.mark.asyncio
async def test_wan_27_image_pro_keeps_4k_with_reference(monkeypatch):
    captured = {}
    service = KlingService(kie_key="test-key")

    async def fake_post(endpoint, payload):
        captured["payload"] = payload
        return {"task_id": "task_wan_image_pro", "status": "pending"}

    monkeypatch.setattr(service, "_kie_post", fake_post)

    await service.generate_wan_image(
        prompt="premium product photo",
        model="wan_27_image_pro",
        input_urls=["https://example.com/ref.jpg"],
        resolution="4K",
        thinking_mode=False,
        aspect_ratio="1:1",
    )

    input_data = captured["payload"]["input"]
    assert input_data["input_urls"] == ["https://example.com/ref.jpg"]
    assert input_data["resolution"] == "4K"


@pytest.mark.asyncio
async def test_wan_27_image_pro_retries_2k_when_kie_rejects_4k_reference(monkeypatch):
    captured = []
    service = KlingService(kie_key="test-key")

    async def fake_post(endpoint, payload):
        captured.append(payload["input"]["resolution"])
        if len(captured) == 1:
            return {
                "error": "api_error",
                "message": "resolution 4K is only supported for non-sequential text-to-image",
                "status_code": 422,
            }
        return {"task_id": "task_wan_image_pro", "status": "pending"}

    monkeypatch.setattr(service, "_kie_post", fake_post)

    result = await service.generate_wan_image(
        prompt="premium product photo",
        model="wan_27_image_pro",
        input_urls=["https://example.com/ref.jpg"],
        resolution="4K",
        thinking_mode=False,
        aspect_ratio="1:1",
    )

    assert captured == ["4K", "2K"]
    assert result["task_id"] == "task_wan_image_pro"


@pytest.mark.asyncio
async def test_wan_27_image_pro_downgrades_4k_with_sequential(monkeypatch):
    captured = {}
    service = KlingService(kie_key="test-key")

    async def fake_post(endpoint, payload):
        captured["payload"] = payload
        return {"task_id": "task_wan_image_pro", "status": "pending"}

    monkeypatch.setattr(service, "_kie_post", fake_post)

    await service.generate_wan_image(
        prompt="premium product photo series",
        model="wan_27_image_pro",
        n=3,
        enable_sequential=True,
        resolution="4K",
        thinking_mode=False,
        aspect_ratio="1:1",
    )

    input_data = captured["payload"]["input"]
    assert input_data["enable_sequential"] is True
    assert input_data["resolution"] == "2K"


@pytest.mark.asyncio
async def test_wan_27_r2v_payload_matches_kie_docs(monkeypatch):
    captured = {}
    service = KlingService(kie_key="test-key")

    async def fake_post(endpoint, payload):
        captured["payload"] = payload
        return {"task_id": "task_wan_r2v", "status": "pending"}

    monkeypatch.setattr(service, "_kie_post", fake_post)

    result = await service.generate_video(
        prompt="Replace the vase with the style of the reference image.",
        model="wan_27_r2v",
        duration=9,
        aspect_ratio="4:3",
        image_url="https://example.com/first.png",
        negative_prompt="bad anatomy",
        wan_reference_image=["https://example.com/ref.jpg"],
        wan_reference_video=["https://example.com/ref.mp4"],
        wan_reference_voice="https://example.com/voice.wav",
        wan_resolution="1080p",
        wan_prompt_extend=True,
        wan_watermark=False,
        wan_nsfw_checker=True,
        wan_seed=42,
    )

    assert result["task_id"] == "task_wan_r2v"
    assert captured["payload"]["model"] == "wan/2-7-r2v"
    assert captured["payload"]["input"] == {
        "prompt": "Replace the vase with the style of the reference image.",
        "negative_prompt": "bad anatomy",
        "reference_image": ["https://example.com/ref.jpg"],
        "reference_video": ["https://example.com/ref.mp4"],
        "first_frame": "https://example.com/first.png",
        "reference_voice": "https://example.com/voice.wav",
        "resolution": "1080p",
        "aspect_ratio": "4:3",
        "duration": 9,
        "prompt_extend": True,
        "watermark": False,
        "seed": 42,
        "nsfw_checker": True,
    }


@pytest.mark.asyncio
async def test_wan_27_videoedit_payload_matches_kie_docs(monkeypatch):
    captured = {}
    service = KlingService(kie_key="test-key")

    async def fake_post(endpoint, payload):
        captured["payload"] = payload
        return {"task_id": "task_wan_edit", "status": "pending"}

    monkeypatch.setattr(service, "_kie_post", fake_post)

    result = await service.generate_video(
        prompt="Change the vase to pink.",
        model="wan_27_videoedit",
        duration=9,
        aspect_ratio="16:9",
        video_urls=["https://example.com/input.mp4"],
        negative_prompt="bad quality",
        wan_reference_image_url="https://example.com/ref.png",
        wan_resolution="720p",
        wan_prompt_extend=True,
        wan_watermark=True,
        wan_nsfw_checker=True,
        wan_seed=42,
    )

    assert result["task_id"] == "task_wan_edit"
    assert captured["payload"]["model"] == "wan/2-7-videoedit"
    assert captured["payload"]["input"] == {
        "prompt": "Change the vase to pink.",
        "negative_prompt": "bad quality",
        "video_url": "https://example.com/input.mp4",
        "reference_image": "https://example.com/ref.png",
        "resolution": "720p",
        "duration": 9,
        "aspect_ratio": "16:9",
        "audio_setting": "auto",
        "prompt_extend": True,
        "watermark": True,
        "seed": 42,
        "nsfw_checker": True,
    }


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


def test_wan_27_t2v_keyboard_shows_all_kie_ratios():
    kb = get_create_video_keyboard(
        current_v_type="text",
        current_model="wan_27_t2v",
        current_duration=5,
        current_ratio="16:9",
    )

    callback_data = [
        str(button.callback_data) for row in kb.inline_keyboard for button in row
    ]

    for ratio in ["16_9", "9_16", "1_1", "4_3", "3_4"]:
        assert f"vratio_{ratio}" in callback_data
