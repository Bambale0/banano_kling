from __future__ import annotations

import pytest

from bot.model_capabilities import get_video_capability
from bot.services.seedance_25_service import Seedance25Service


@pytest.mark.asyncio
@pytest.mark.parametrize("video_editing,expected_duration,expected_ratio", [(True, -1, "adaptive"), (False, 12, "9:16")])
async def test_seedance_25_editing_preserves_reference_generation(monkeypatch, video_editing, expected_duration, expected_ratio):
    service = Seedance25Service(kie_key="test-key")
    captured = {}

    async def fake_kie_post(path, payload):
        captured.update(payload)
        return {"task_id": "editing-test"}

    monkeypatch.setattr(service, "_kie_post", fake_kie_post)
    result = await service.generate_video(
        prompt="Replace the background of @Video1",
        duration=12,
        aspect_ratio="9:16",
        reference_video_urls=["https://example.com/source.mp4"],
        video_editing=video_editing,
    )
    assert result["success"] is True
    assert captured["input"]["duration"] == expected_duration
    assert captured["input"]["aspect_ratio"] == expected_ratio
    assert "video_editing" not in captured["input"]
    assert result["duration"] == expected_duration
    assert result["aspect_ratio"] == expected_ratio
    assert result["video_editing"] is video_editing


@pytest.mark.asyncio
@pytest.mark.parametrize("videos", [[], ["https://example.com/one.mp4", "https://example.com/two.mp4"]])
async def test_seedance_25_editing_requires_one_video(monkeypatch, videos):
    service = Seedance25Service(kie_key="test-key")

    async def no_provider_call(*args):
        pytest.fail("Invalid editing inputs must not reach KIE")

    monkeypatch.setattr(service, "_kie_post", no_provider_call)
    result = await service.generate_video(prompt="Edit video", video_editing=True, reference_video_urls=videos)
    assert result["success"] is False
    assert "exactly one video" in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("video_editing", ["false", "true", 0, 1, None])
async def test_seedance_25_editing_rejects_non_boolean_intent(monkeypatch, video_editing):
    service = Seedance25Service(kie_key="test-key")

    async def no_provider_call(*args):
        pytest.fail("Invalid editing intent must not reach KIE")

    monkeypatch.setattr(service, "_kie_post", no_provider_call)
    result = await service.generate_video(prompt="Edit video", video_editing=video_editing)
    assert result["success"] is False
    assert "boolean" in result["error"]


@pytest.mark.asyncio
async def test_seedance_25_editing_does_not_bypass_regular_input_validation(monkeypatch):
    service = Seedance25Service(kie_key="test-key")

    async def no_provider_call(*args):
        pytest.fail("Invalid ordinary parameters must not reach KIE")

    monkeypatch.setattr(service, "_kie_post", no_provider_call)
    arguments = {"prompt": "Edit video", "video_editing": True, "reference_video_urls": ["https://example.com/source.mp4"]}
    assert (await service.generate_video(**arguments, duration=3))["success"] is False
    assert (await service.generate_video(**arguments, aspect_ratio="2:3"))["success"] is False
    assert (await service.generate_video(**arguments, first_frame_url="https://example.com/first.png"))["success"] is False


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
    assert (await service.generate_video(prompt="x" * 30001))["success"] is False


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


@pytest.mark.asyncio
async def test_seedance_25_canonicalizes_reference_mentions(monkeypatch):
    service = Seedance25Service(kie_key="test-key")
    captured = {}

    async def fake_kie_post(path, payload):
        captured["payload"] = payload
        return {"task_id": "task-bindings"}

    monkeypatch.setattr(service, "_kie_post", fake_kie_post)

    result = await service.generate_video(
        prompt=(
            "@IMAGE 1 = первый человек; @image2 = второй; "
            "@IMAGE3 = третий; движения строго из @image 4."
        ),
        reference_image_urls=[
            "https://example.com/p1.png",
            "https://example.com/p2.png",
            "https://example.com/p3.png",
        ],
        reference_video_urls=["https://example.com/motion.mp4"],
    )

    assert result["task_id"] == "task-bindings"
    assert captured["payload"]["input"]["prompt"] == (
        "@Image1 = первый человек; @Image2 = второй; "
        "@Image3 = третий; движения строго из @Video1."
    )


@pytest.mark.asyncio
async def test_seedance_25_blocks_missing_video_reference_tag(monkeypatch):
    service = Seedance25Service(kie_key="test-key")
    called = False

    async def fake_kie_post(path, payload):
        nonlocal called
        called = True
        return {"task_id": "should-not-run"}

    monkeypatch.setattr(service, "_kie_post", fake_kie_post)

    result = await service.generate_video(
        prompt="@Image1 follows @Video1 exactly.",
        reference_image_urls=["https://example.com/person.png"],
        reference_video_urls=[],
    )

    assert result["success"] is False
    assert "@Video1" in result["error"]
    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize("length", [5001, 30000])
async def test_seedance25_long_prompt_reaches_provider_intact(monkeypatch, length):
    service = Seedance25Service(kie_key="test-key")
    captured = {}

    async def fake_post(path, payload):
        captured.update(payload)
        return {"task_id": "long-prompt"}

    monkeypatch.setattr(service, "_kie_post", fake_post)
    prompt = "я" * (length - 1) + "🎬"
    result = await service.generate_video(prompt=prompt)
    assert result.get("task_id") == "long-prompt"
    assert captured["input"]["prompt"] == prompt


@pytest.mark.asyncio
async def test_seedance25_overlong_prompt_never_calls_provider(monkeypatch):
    service = Seedance25Service(kie_key="test-key")

    async def unexpected_post(*args, **kwargs):
        pytest.fail("Overlong prompt must be rejected before provider launch")

    monkeypatch.setattr(service, "_kie_post", unexpected_post)
    result = await service.generate_video(prompt="я" * 30001)
    assert result["success"] is False
    assert "30000" in result["error"]


@pytest.mark.asyncio
async def test_seedance_25_rebases_legacy_local_media_refs(monkeypatch):
    from bot.config import config

    service = Seedance25Service(kie_key="test-key")
    captured = {}

    async def fake_kie_post(path, payload):
        captured["payload"] = payload
        return {"task_id": "canonical-media"}

    monkeypatch.setattr(service, "_kie_post", fake_kie_post)
    monkeypatch.setattr(
        config,
        "STATIC_BASE_URL",
        "https://tanyapp.xn--e1aikcel5c5a.online",
    )

    await service.generate_video(
        prompt="Use @Image1, @Video1 and @Audio1",
        reference_image_urls=[
            "https://tanyapi.chillcreative.ru/uploads/refs/image/123/face.png"
        ],
        reference_video_urls=[
            "https://tanyapi.chillcreative.ru/uploads/refs/video/123/motion.mp4"
        ],
        reference_audio_urls=[
            "https://tanyapi.chillcreative.ru/uploads/refs/audio/123/music.mp3"
        ],
    )

    assert captured["payload"]["input"]["reference_image_urls"] == [
        "https://tanyapp.xn--e1aikcel5c5a.online/uploads/refs/image/123/face.png"
    ]
    assert captured["payload"]["input"]["reference_video_urls"] == [
        "https://tanyapp.xn--e1aikcel5c5a.online/uploads/refs/video/123/motion.mp4"
    ]
    assert captured["payload"]["input"]["reference_audio_urls"] == [
        "https://tanyapp.xn--e1aikcel5c5a.online/uploads/refs/audio/123/music.mp3"
    ]


@pytest.mark.asyncio
async def test_seedance_25_rebases_legacy_local_first_last_frames(monkeypatch):
    from bot.config import config

    service = Seedance25Service(kie_key="test-key")
    captured = {}

    async def fake_kie_post(path, payload):
        captured["payload"] = payload
        return {"task_id": "canonical-frames"}

    monkeypatch.setattr(service, "_kie_post", fake_kie_post)
    monkeypatch.setattr(
        config,
        "STATIC_BASE_URL",
        "https://tanyapp.xn--e1aikcel5c5a.online",
    )

    await service.generate_video(
        prompt="Transition between frames",
        first_frame_url="https://tanyapi.chillcreative.ru/uploads/refs/image/123/first.png",
        last_frame_url="https://tanyapi.chillcreative.ru/uploads/refs/image/123/last.png",
    )

    assert captured["payload"]["input"]["first_frame_url"] == (
        "https://tanyapp.xn--e1aikcel5c5a.online/uploads/refs/image/123/first.png"
    )
    assert captured["payload"]["input"]["last_frame_url"] == (
        "https://tanyapp.xn--e1aikcel5c5a.online/uploads/refs/image/123/last.png"
    )
