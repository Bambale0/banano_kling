from __future__ import annotations

import pytest

from bot.handlers.seedance_25_fullstack import (
    MAX_VIDEO_PIXELS,
    MIN_VIDEO_PIXELS,
    _classify_results,
    _float_fraction,
    _seedance25_model_meta,
    _validate_dimensions,
)
from bot.services.seedance_25_service import Seedance25Service, get_seedance25_callback_url


def test_seedance25_model_meta_exposes_full_admin_contract():
    meta = _seedance25_model_meta()

    assert meta["id"] == "seedance_2_5"
    assert meta["admin_only"] is True
    assert meta["seedance25_resolutions"] == ["480p", "720p"]
    assert meta["seedance25_output_formats"] == ["mp4", "mov"]
    assert meta["seedance25_scenarios"] == [
        "text",
        "first_frame",
        "first_last",
        "multimodal",
    ]
    assert meta["durations"][0] == -1
    assert meta["durations"][1:] == list(range(4, 31))
    assert meta["max_image_references"] == 30
    assert meta["max_video_references"] == 10
    assert meta["max_audio_references"] == 10
    assert meta["supports_generate_audio"] is True
    assert meta["supports_return_last_frame"] is True
    assert meta["supports_web_search"] is True
    assert meta["supports_nsfw_checker"] is True
    assert meta["camera_control_via_prompt"] is True


def test_seedance25_classifies_video_and_returned_last_frame():
    request_data = {"return_last_frame": True, "output_format": "mov"}
    video, frame = _classify_results(
        [
            "https://cdn.example/result.mov",
            "https://cdn.example/last-frame.png",
        ],
        request_data,
    )
    assert video == "https://cdn.example/result.mov"
    assert frame == "https://cdn.example/last-frame.png"


def test_seedance25_fraction_parser_handles_ffprobe_rates():
    assert _float_fraction("30/1") == 30.0
    assert _float_fraction("60000/1001") == pytest.approx(59.94005994)
    assert _float_fraction("0/0") == 0.0


def test_seedance25_video_geometry_enforces_spec_pixel_range():
    _validate_dimensions(640, 640, video=True)

    with pytest.raises(ValueError):
        _validate_dimensions(639, 640, video=True)

    # Still inside side/ratio limits but over the Kie per-frame pixel ceiling.
    assert 1000 * 1000 > MAX_VIDEO_PIXELS
    with pytest.raises(ValueError):
        _validate_dimensions(1000, 1000, video=True)

    assert 640 * 640 == MIN_VIDEO_PIXELS


@pytest.mark.asyncio
async def test_seedance25_rejects_reference_overflow_instead_of_truncating(monkeypatch):
    service = Seedance25Service(kie_key="test-key")

    async def unexpected_post(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("provider call must not happen")

    monkeypatch.setattr(service, "_kie_post", unexpected_post)
    result = await service.generate_video(
        prompt="test",
        reference_image_urls=[f"https://example.com/{idx}.png" for idx in range(31)],
    )
    assert result["success"] is False
    assert "at most 30" in result["error"]


def test_seedance25_dedicated_callback_path_when_host_available(monkeypatch):
    # The helper reuses the public Kie callback host and switches only the path.
    import bot.services.seedance_25_service as module

    monkeypatch.setattr(module.config, "kie_notification_url", "https://example.com/webhook/kie_ai")
    assert get_seedance25_callback_url() == "https://example.com/webhook/kie_seedance25"
