from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from bot.services.neironych_seedance_admin_service import NeironychSeedanceAdminService


def test_documented_seedance_models_and_limits():
    specs = NeironychSeedanceAdminService.MODEL_SPECS

    assert set(specs) == {
        "seedance-2.5",
        "seedance-2.0",
        "seedance-2.0-mini",
        "seedance-2.0-fast",
    }
    assert specs["seedance-2.5"].duration_range == (4, 30)
    assert specs["seedance-2.5"].resolutions == ("480p", "720p", "1080p")
    assert specs["seedance-2.5"].max_images == 30
    assert specs["seedance-2.5"].max_videos == 10
    assert specs["seedance-2.5"].max_audios == 10
    assert specs["seedance-2.5"].max_references == 50

    assert specs["seedance-2.0"].duration_range == (4, 15)
    assert specs["seedance-2.0"].resolutions == ("480p", "720p", "1080p", "4k")
    assert specs["seedance-2.0-mini"].resolutions == ("480p", "720p")
    assert specs["seedance-2.0-fast"].resolutions == ("480p", "720p")


def test_seedance25_reference_payload_matches_documented_contract():
    payload = NeironychSeedanceAdminService.build_payload(
        model="seedance-2.5",
        mode="reference",
        prompt="Animate @Image 1 and use @Audio 1",
        duration=8,
        resolution="720p",
        aspect_ratio="9:16",
        reference_images=["https://cdn.example/ref.jpg"],
        reference_videos=["https://cdn.example/ref.mp4"],
        reference_audios=["https://cdn.example/ref.mp3"],
    )

    assert payload == {
        "model": "seedance-2.5",
        "prompt": "Animate @Image 1 and use @Audio 1",
        "duration": 8,
        "resolution": "720p",
        "aspect_ratio": "9:16",
        "reference_images": [{"url": "https://cdn.example/ref.jpg"}],
        "reference_videos": [{"url": "https://cdn.example/ref.mp4"}],
        "reference_audios": [{"url": "https://cdn.example/ref.mp3"}],
        "omni_reference_task_type": "reference",
    }
    assert "generate_audio" not in payload
    assert "seed" not in payload
    assert "watermark" not in payload


def test_seedance25_frames_force_adaptive_ratio():
    payload = NeironychSeedanceAdminService.build_payload(
        model="seedance-2.5",
        mode="frames",
        prompt="Smooth transition",
        duration=6,
        resolution="1080p",
        aspect_ratio="adaptive",
        start_image="https://cdn.example/start.jpg",
        end_image="https://cdn.example/end.jpg",
    )

    assert payload["start_image"] == {"url": "https://cdn.example/start.jpg"}
    assert payload["end_image"] == {"url": "https://cdn.example/end.jpg"}
    assert payload["aspect_ratio"] == "adaptive"
    assert "reference_images" not in payload

    with pytest.raises(ValueError, match="adaptive"):
        NeironychSeedanceAdminService.build_payload(
            model="seedance-2.5",
            mode="frames",
            prompt="bad ratio",
            duration=6,
            resolution="720p",
            aspect_ratio="9:16",
            start_image="https://cdn.example/start.jpg",
        )


def test_seedance25_edit_requires_video_and_uses_source_duration():
    payload = NeironychSeedanceAdminService.build_payload(
        model="seedance-2.5",
        mode="edit",
        prompt="Replace the sky in @Video 1 using @Image 1 and @Audio 1",
        duration=12,
        resolution="720p",
        aspect_ratio="9:16",
        reference_images=["https://cdn.example/look.jpg"],
        reference_videos=["https://cdn.example/source.mp4"],
        reference_audios=["https://cdn.example/music.mp3"],
    )

    assert payload["duration"] == -1
    assert payload["aspect_ratio"] == "adaptive"
    assert payload["omni_reference_task_type"] == "edit"
    assert payload["reference_videos"] == [{"url": "https://cdn.example/source.mp4"}]
    assert payload["reference_images"] == [{"url": "https://cdn.example/look.jpg"}]
    assert payload["reference_audios"] == [{"url": "https://cdn.example/music.mp3"}]

    with pytest.raises(ValueError, match="reference_videos"):
        NeironychSeedanceAdminService.build_payload(
            model="seedance-2.5",
            mode="edit",
            prompt="Replace the sky",
            duration=12,
            resolution="720p",
            aspect_ratio="adaptive",
        )


def test_seedance20_rejects_audio_only_and_supports_4k():
    with pytest.raises(ValueError, match="audio requires"):
        NeironychSeedanceAdminService.build_payload(
            model="seedance-2.0",
            mode="reference",
            prompt="Use audio",
            duration=5,
            resolution="720p",
            aspect_ratio="16:9",
            reference_audios=["https://cdn.example/ref.mp3"],
        )

    payload = NeironychSeedanceAdminService.build_payload(
        model="seedance-2.0",
        mode="reference",
        prompt="Animate",
        duration=15,
        resolution="4k",
        aspect_ratio="21:9",
        reference_images=["https://cdn.example/ref.png"],
        reference_audios=["https://cdn.example/ref.mp3"],
    )
    assert payload["resolution"] == "4k"
    assert payload["aspect_ratio"] == "21:9"


@pytest.mark.parametrize("model", ["seedance-2.0-mini", "seedance-2.0-fast"])
def test_seedance20_compact_variants_reject_1080p(model: str):
    with pytest.raises(ValueError, match="resolution"):
        NeironychSeedanceAdminService.build_payload(
            model=model,
            mode="text",
            prompt="test",
            duration=5,
            resolution="1080p",
            aspect_ratio="16:9",
        )


def test_reference_limits_are_enforced():
    with pytest.raises(ValueError, match="at most 30"):
        NeironychSeedanceAdminService.build_payload(
            model="seedance-2.5",
            mode="reference",
            prompt="test",
            duration=5,
            resolution="720p",
            aspect_ratio="16:9",
            reference_images=[f"https://cdn.example/{i}.jpg" for i in range(31)],
        )

    with pytest.raises(ValueError, match="at most 12"):
        NeironychSeedanceAdminService.build_payload(
            model="seedance-2.0",
            mode="reference",
            prompt="test",
            duration=5,
            resolution="720p",
            aspect_ratio="16:9",
            reference_images=[f"https://cdn.example/{i}.jpg" for i in range(9)],
            reference_videos=[f"https://cdn.example/{i}.mp4" for i in range(3)],
            reference_audios=["https://cdn.example/a.mp3"],
        )


def test_submit_uses_video_endpoint_without_automatic_post_retry():
    async def run():
        service = NeironychSeedanceAdminService(api_key="secret")
        service._request_json = AsyncMock(return_value=(202, {"request_id": "req-1"}))
        result = await service.submit(
            {
                "model": "seedance-2.5",
                "prompt": "test",
                "duration": 4,
                "resolution": "480p",
                "aspect_ratio": "9:16",
            },
            idempotency_key="same-request-key",
        )
        return service, result

    service, result = asyncio.run(run())
    assert result["request_id"] == "req-1"
    service._request_json.assert_awaited_once()
    kwargs = service._request_json.await_args.kwargs
    assert kwargs["method"] == "POST"
    assert kwargs["path"] == "/v1/videos/generations"
    assert kwargs["headers"]["Idempotency-Key"] == "same-request-key"
    assert kwargs["retry"] is False


def test_list_models_returns_current_enabled_ids():
    async def run():
        service = NeironychSeedanceAdminService(api_key="")
        service._request_json = AsyncMock(
            return_value=(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": "seedance-2.5"},
                        {"id": "seedance-2.0"},
                        {"id": "other-model"},
                    ],
                },
            )
        )
        return service, await service.list_enabled_seedance_models()

    service, result = asyncio.run(run())
    assert result == {"seedance-2.5", "seedance-2.0"}
    service._request_json.assert_awaited_once()
    kwargs = service._request_json.await_args.kwargs
    assert kwargs["method"] == "GET"
    assert kwargs["path"] == "/v1/models"


def test_prompt_limit_and_reference_integrity_are_checked_before_submit():
    NeironychSeedanceAdminService.build_payload(
        model="seedance-2.5",
        mode="reference",
        prompt="Keep @Image 1 and @Video1 coherent",
        duration=5,
        resolution="720p",
        aspect_ratio="16:9",
        reference_images=["https://cdn.example/a.jpg"],
        reference_videos=["https://cdn.example/a.mp4"],
    )

    with pytest.raises(ValueError, match="@Image2"):
        NeironychSeedanceAdminService.build_payload(
            model="seedance-2.5",
            mode="reference",
            prompt="Use @Image 2",
            duration=5,
            resolution="720p",
            aspect_ratio="16:9",
            reference_images=["https://cdn.example/a.jpg"],
        )

    with pytest.raises(ValueError, match="40 000"):
        NeironychSeedanceAdminService.build_payload(
            model="seedance-2.0",
            mode="text",
            prompt="я" * 20_001,
            duration=5,
            resolution="720p",
            aspect_ratio="16:9",
        )


def test_reference_urls_reject_embedded_credentials():
    with pytest.raises(ValueError, match="credentials"):
        NeironychSeedanceAdminService.build_payload(
            model="seedance-2.0",
            mode="reference",
            prompt="test",
            duration=5,
            resolution="720p",
            aspect_ratio="16:9",
            reference_images=["https://user:pass@cdn.example/a.jpg"],
        )
