"""Contract regression for the admin-only Neironych WAN 3.0 lab.

These tests do not submit real paid provider tasks.
"""
from unittest.mock import AsyncMock

import pytest

from bot.services.neironych_wan3_admin_service import NeironychWan3AdminService


def build(**overrides):
    args = {"mode": "text", "prompt": "A quiet red tram at sunrise",
            "duration": 5, "resolution": "720p", "aspect_ratio": "16:9",
            "generate_audio": True, "seed": None}
    args.update(overrides)
    return NeironychWan3AdminService.build_payload(**args)


def test_text_contract_is_native_wan_not_kie():
    assert build(seed=42, generate_audio=False) == {
        "model": "wan-3", "prompt": "A quiet red tram at sunrise",
        "duration": 5, "resolution": "720p", "aspect_ratio": "16:9",
        "generate_audio": False, "seed": 42,
    }


def test_reference_mode_preserves_input_order_and_audio_only():
    url = "https://media.example.org/a.jpg"
    payload = build(mode="reference", reference_images=[url, url],
                    reference_videos=["https://media.example.org/clip.mp4"],
                    reference_audios=["https://media.example.org/a.mp3"],
                    prompt="Use @Image 2, @Video 1 and @Audio 1")
    assert payload["reference_images"] == [{"url": url}, {"url": url}]
    assert payload["reference_videos"] == [{"url": "https://media.example.org/clip.mp4"}]
    assert payload["reference_audios"] == [{"url": "https://media.example.org/a.mp3"}]
    assert payload["omni_reference_task_type"] == "reference"
    assert "input" not in payload and "callBackUrl" not in payload
    only_audio = build(mode="reference", reference_audios=["https://media.example.org/a.mp3"])
    assert "reference_audios" in only_audio


def test_edit_has_no_duration_or_aspect_ratio_and_requires_video():
    payload = build(mode="edit", duration=15, aspect_ratio="9:16",
                    reference_videos=["https://media.example.org/source.mp4"],
                    reference_images=["https://media.example.org/look.jpg"])
    assert payload["omni_reference_task_type"] == "edit"
    assert "duration" not in payload
    assert "aspect_ratio" not in payload
    assert payload["reference_videos"][0]["url"].endswith("source.mp4")
    with pytest.raises(ValueError, match="video"):
        build(mode="edit")


def test_frames_are_native_start_end_objects_and_not_prime():
    payload = build(mode="frames", aspect_ratio="adaptive",
                    start_image="https://media.example.org/start.jpg",
                    end_image="https://media.example.org/end.jpg")
    assert payload["start_image"] == {"url": "https://media.example.org/start.jpg"}
    assert payload["end_image"] == {"url": "https://media.example.org/end.jpg"}
    assert payload["aspect_ratio"] == "adaptive"
    with pytest.raises(ValueError, match="start"):
        build(mode="frames", aspect_ratio="adaptive")


@pytest.mark.parametrize("kwargs", [
    {"duration": 1}, {"duration": 31}, {"duration": True},
    {"resolution": "4k"}, {"aspect_ratio": "wrong"},
    {"seed": -1}, {"seed": 4294967296}, {"seed": True},
    {"generate_audio": "false"}, {"prompt": " "}, {"prompt": "x" * 20001},
    {"mode": "unknown"},
    {"mode": "text", "reference_images": ["https://media.example.org/a.jpg"]},
    {"mode": "reference"},
    {"mode": "reference", "reference_images": ["http://example.org/a.jpg"]},
    {"mode": "reference", "reference_images": ["https://u:p@example.org/a.jpg"]},
    {"mode": "reference", "reference_images": [f"https://media.example.org/{i}.jpg" for i in range(11)]},
    {"mode": "reference", "reference_images": ["https://media.example.org/a.jpg"],
     "prompt": "@Image 2 has the dress"},
    {"mode": "edit", "start_image": "https://media.example.org/a.jpg",
     "reference_videos": ["https://media.example.org/a.mp4"]},
])
def test_invalid_wan_payload_fails_before_paid_submission(kwargs):
    with pytest.raises((ValueError, TypeError)):
        build(**kwargs)


async def test_model_catalog_is_read_only_and_submit_is_idempotent():
    service = NeironychWan3AdminService(api_key="synthetic-key")
    service._request_json = AsyncMock(side_effect=[
        (200, {"data": [{"id": "wan-3"}, {"id": "wan-3-prime"}, {"id": "seedance-2.0"}]}),
        (202, {"request_id": "wan-admin-123"}),
    ])
    assert await service.list_enabled_wan_models() == {"wan-3"}
    assert await service.submit(build(), idempotency_key="wan-test-id-123") == {
        "request_id": "wan-admin-123", "status": "pending"
    }
    assert service._request_json.await_args.kwargs == {
        "method": "POST", "path": "/v1/videos/generations",
        "headers": {"Idempotency-Key": "wan-test-id-123"},
        "json_body": build(), "retry": False,
    }
