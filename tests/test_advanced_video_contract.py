import pytest

from bot.model_capabilities import (
    get_video_capability,
    max_video_references,
    normalize_video_model_key,
)
from bot.services.kling_service import KlingService
from bot.video_generation_contract import (
    build_repeat_video_state,
    normalize_video_request,
    validate_video_request,
)


def test_capability_registry_contains_advanced_models():
    assert get_video_capability("v3_4k") is not None
    assert get_video_capability("motion_control_v30") is not None
    assert get_video_capability("seedance_2_fast") is not None
    assert normalize_video_model_key("kling-3.0-4k") == "v3_4k"
    assert max_video_references("seedance_2_fast") == 3


def test_video_request_preserves_advanced_inputs():
    payload = normalize_video_request(
        {
            "v_model": "seedance_2_fast",
            "prompt": "A cinematic scene",
            "duration": 10,
            "aspect_ratio": "9:16",
            "reference_images": ["https://cdn/a.png"],
            "video_references": ["https://cdn/a.mp4", "https://cdn/b.mp4"],
            "audio_references": ["https://cdn/a.mp3"],
        }
    )
    assert payload["v_model"] == "seedance_2_fast"
    assert payload["v_duration"] == 10
    assert payload["v_ratio"] == "9:16"
    assert payload["reference_images"] == ["https://cdn/a.png"]
    assert payload["v_reference_videos"] == [
        "https://cdn/a.mp4",
        "https://cdn/b.mp4",
    ]
    assert payload["v_reference_audio"] == ["https://cdn/a.mp3"]


def test_validation_reports_raw_overflow():
    errors = validate_video_request(
        {
            "v_model": "motion_control_v30",
            "v_reference_videos": ["a", "b"],
        }
    )
    assert errors
    assert "Too many video references" in errors[0]


def test_repeat_keeps_private_media_for_owner():
    state = build_repeat_video_state(
        {
            "v_model": "seedance_2_fast",
            "user_prompt": "repeat me",
            "reference_images": ["image"],
            "v_reference_videos": ["video"],
            "v_reference_audio": ["audio"],
        },
        include_private_media=True,
    )
    assert state["reference_images"] == ["image"]
    assert state["v_reference_videos"] == ["video"]
    assert state["v_reference_audio"] == ["audio"]


@pytest.mark.asyncio
async def test_kling_4k_payload_keeps_mode(monkeypatch):
    service = KlingService(kie_key="test")
    captured = {}

    async def fake_post(endpoint, payload):
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        return {"task_id": "task"}

    monkeypatch.setattr(service, "_kie_post", fake_post)
    await service.generate_video(
        prompt="test",
        model="v3_4k",
        duration=12,
        aspect_ratio="16:9",
        image_input=["https://cdn/ref.png"],
        sound=True,
        multi_shots=True,
    )
    assert captured["payload"]["model"] == "kling-3.0/video"
    assert captured["payload"]["input"]["mode"] == "4k"
    assert captured["payload"]["input"]["duration"] == "12"


@pytest.mark.asyncio
async def test_motion_v30_routes_to_kling_30(monkeypatch):
    service = KlingService(kie_key="test")
    captured = {}

    async def fake_post(endpoint, payload):
        captured["payload"] = payload
        return {"task_id": "task"}

    monkeypatch.setattr(service, "_kie_post", fake_post)
    await service.generate_video(
        prompt="move",
        model="motion_control_v30",
        image_url="https://cdn/person.png",
        video_urls=["https://cdn/motion.mp4"],
        mode="1080p",
    )
    assert captured["payload"]["model"] == "kling-3.0/motion-control"
    assert captured["payload"]["input"]["mode"] == "1080p"
