from __future__ import annotations

import pytest

from bot.model_capabilities import get_video_capability
from bot.services.seedance_25_service import Seedance25Service


@pytest.mark.asyncio
async def test_seedance_25_full_multimodal_payload(monkeypatch):
    service = Seedance25Service(kie_key="test-key")
    captured = {}

    async def fake_kie_post(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {"task_id": "task-test"}

    monkeypatch.setattr(service, "_kie_post", fake_kie_post)

    result = await service.generate_video(
        prompt="camera follows the subject",
        duration=30,
        aspect_ratio="21:9",
        resolution="480p",
        reference_image_urls=["https://example.com/ref.png"],
        reference_video_urls=["https://example.com/ref.mp4"],
        reference_audio_urls=["https://example.com/ref.mp3"],
        return_last_frame=True,
        generate_audio=False,
        output_format="mov",
        web_search=True,
        nsfw_checker=True,
        callBackUrl="https://example.com/callback",
    )

    assert result["task_id"] == "task-test"
    assert result["scenario"] == "multimodal"
    assert captured["path"] == "/api/v1/jobs/createTask"
    assert captured["payload"] == {
        "model": "bytedance/seedance-2-5",
        "callBackUrl": "https://example.com/callback",
        "input": {
            "prompt": "camera follows the subject",
            "return_last_frame": True,
            "generate_audio": False,
            "resolution": "480p",
            "aspect_ratio": "21:9",
            "duration": 30,
            "output_format": "mov",
            "web_search": True,
            "nsfw_checker": True,
            "reference_image_urls": ["https://example.com/ref.png"],
            "reference_video_urls": ["https://example.com/ref.mp4"],
            "reference_audio_urls": ["https://example.com/ref.mp3"],
        },
    }


@pytest.mark.asyncio
async def test_seedance_25_first_and_last_frame_payload(monkeypatch):
    service = Seedance25Service(kie_key="test-key")
    captured = {}

    async def fake_kie_post(path, payload):
        captured["payload"] = payload
        return {"task_id": "task-frames"}

    monkeypatch.setattr(service, "_kie_post", fake_kie_post)

    result = await service.generate_video(
        prompt="",
        duration=-1,
        aspect_ratio="adaptive",
        first_frame_url="asset://first",
        last_frame_url="asset://last",
    )

    assert result["scenario"] == "first_last"
    assert captured["payload"]["input"]["duration"] == -1
    assert captured["payload"]["input"]["first_frame_url"] == "asset://first"
    assert captured["payload"]["input"]["last_frame_url"] == "asset://last"
    assert "reference_image_urls" not in captured["payload"]["input"]


@pytest.mark.asyncio
async def test_seedance_25_rejects_mixed_first_frame_and_multimodal_refs():
    service = Seedance25Service(kie_key="test-key")

    result = await service.generate_video(
        prompt="test",
        first_frame_url="https://example.com/first.png",
        reference_image_urls=["https://example.com/ref.png"],
    )

    assert result["success"] is False
    assert "cannot be combined" in result["error"]


@pytest.mark.asyncio
async def test_seedance_25_rejects_last_frame_without_first_frame():
    service = Seedance25Service(kie_key="test-key")

    result = await service.generate_video(
        prompt="test",
        last_frame_url="https://example.com/last.png",
    )

    assert result["success"] is False
    assert "requires first_frame_url" in result["error"]


@pytest.mark.asyncio
async def test_seedance_25_rejects_out_of_spec_values():
    service = Seedance25Service(kie_key="test-key")

    assert (await service.generate_video(prompt="x", duration=3))["success"] is False
    assert (await service.generate_video(prompt="x", duration=31))["success"] is False
    assert (await service.generate_video(prompt="x", resolution="1080p"))["success"] is False
    assert (await service.generate_video(prompt="x", aspect_ratio="2:3"))["success"] is False
    assert (await service.generate_video(prompt="x", output_format="webm"))["success"] is False
    assert (await service.generate_video(prompt="x" * 5001))["success"] is False


def test_seedance_25_capability_registry_matches_kie_spec():
    capability = get_video_capability("bytedance/seedance-2-5")

    assert capability is not None
    assert capability.modes == ("text", "first_frame", "first_last", "multimodal")
    assert capability.durations == (-1,) + tuple(range(4, 31))
    assert capability.aspect_ratios == (
        "1:1",
        "4:3",
        "3:4",
        "16:9",
        "9:16",
        "21:9",
        "adaptive",
    )
    assert capability.resolutions == ("480p", "720p")
    assert capability.output_formats == ("mp4", "mov")
    assert capability.supports_start_image is True
    assert capability.supports_end_image is True
    assert capability.supports_reference_images is True
    assert capability.max_reference_images == 30
    assert capability.supports_reference_videos is True
    assert capability.max_reference_videos == 10
    assert capability.supports_audio_input is True
    assert capability.max_reference_audio == 10
    assert capability.supports_generated_audio is True
    assert capability.supports_return_last_frame is True
    assert capability.supports_web_search is True
    assert capability.supports_nsfw_checker is True
    assert capability.supports_auto_duration is True
    assert capability.camera_control_via_prompt is True
