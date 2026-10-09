from __future__ import annotations

import pytest

from bot.model_capabilities import get_video_capability
from bot.services.wan3_prime_service import Wan3PrimeService
from bot.video_reference_policy import apply_video_reference_cost


@pytest.fixture(autouse=True)
def isolated_database():
    yield


class CaptureWan3PrimeService(Wan3PrimeService):
    def __init__(self) -> None:
        super().__init__(kie_key="test-key")
        self.last_endpoint = ""
        self.last_payload = {}

    async def _kie_post(self, endpoint, payload):
        self.last_endpoint = endpoint
        self.last_payload = payload
        return {"task_id": "wan-prime-task"}


@pytest.mark.asyncio
async def test_wan3_prime_full_reference_payload_preserves_all_documented_fields():
    service = CaptureWan3PrimeService()

    result = await service.generate_video(
        prompt="Use Image1, Video1, Audio1, the PDF and the webpage.",
        duration=30,
        aspect_ratio="16:9",
        resolution="1080P",
        reference_image_urls=["https://cdn.test/a.png"],
        reference_video_urls=["https://cdn.test/source.mp4"],
        reference_audio_urls=["https://cdn.test/voice.mp3"],
        reference_file_urls=["https://cdn.test/spec.pdf"],
        seed=0,
        audio=False,
        nsfw_checker=True,
        callBackUrl="https://example.test/callback",
    )

    assert result["success"] is True
    assert result["provider_model"] == "wan/3-0-video-prime"
    assert service.last_endpoint == "/api/v1/jobs/createTask"
    assert service.last_payload == {
        "model": "wan/3-0-video-prime",
        "callBackUrl": "https://example.test/callback",
        "input": {
            "prompt": "Use Image1, Video1, Audio1, the PDF and the webpage.",
            "resolution": "1080P",
            "aspect_ratio": "16:9",
            "duration": 30,
            "audio": False,
            "seed": 0,
            "nsfw_checker": True,
            "reference_image_urls": ["https://cdn.test/a.png"],
            "reference_video_urls": ["https://cdn.test/source.mp4"],
            "reference_audio_urls": ["https://cdn.test/voice.mp3"],
            "reference_file_urls": ["https://cdn.test/spec.pdf"],
        },
    }


@pytest.mark.asyncio
async def test_wan3_prime_edit_is_prompt_workflow_not_provider_field():
    service = CaptureWan3PrimeService()

    result = await service.generate_video(
        prompt="Change the jacket to red. Keep the camera move.",
        scenario="edit",
        duration=8,
        aspect_ratio="9:16",
        resolution="720P",
        reference_image_urls=["https://cdn.test/style.webp"],
        reference_video_urls=[
            "https://cdn.test/source.mov",
            "https://cdn.test/extra.mp4",
        ],
        reference_audio_urls=["https://cdn.test/music.wav"],
        seed=2147483647,
        audio=True,
    )

    assert result["success"] is True
    payload = service.last_payload["input"]
    assert payload["reference_video_urls"] == [
        "https://cdn.test/source.mov",
        "https://cdn.test/extra.mp4",
    ]
    assert payload["reference_image_urls"] == ["https://cdn.test/style.webp"]
    assert payload["reference_audio_urls"] == ["https://cdn.test/music.wav"]
    assert payload["duration"] == 8
    assert payload["aspect_ratio"] == "9:16"
    assert payload["seed"] == 2147483647
    assert payload["prompt"].startswith(
        "Edit Video1 according to these instructions:"
    )
    assert "Change the jacket to red. Keep the camera move." in payload["prompt"]
    assert "first_frame_url" not in payload
    assert "last_frame_url" not in payload
    assert "edit" not in payload
    assert "omni_reference_task_type" not in payload
    assert result["raw_prompt"] == "Change the jacket to red. Keep the camera move."
    assert result["scenario"] == "edit"


@pytest.mark.asyncio
async def test_wan3_prime_frames_cannot_mix_with_references_and_last_requires_first():
    service = CaptureWan3PrimeService()

    mixed = await service.generate_video(
        prompt="bad",
        first_frame_url="https://cdn.test/first.png",
        reference_image_urls=["https://cdn.test/ref.png"],
    )
    last_only = await service.generate_video(
        prompt="bad",
        last_frame_url="https://cdn.test/last.png",
    )

    assert mixed["success"] is False
    assert "cannot be combined" in mixed["error"]
    assert last_only["success"] is False
    assert "requires first_frame_url" in last_only["error"]


@pytest.mark.asyncio
async def test_wan3_prime_limits_and_file_link_exclusion():
    service = CaptureWan3PrimeService()

    assert (
        await service.generate_video(
            prompt="x",
            reference_image_urls=[f"https://cdn.test/{i}.png" for i in range(11)],
        )
    )["success"] is False
    assert (
        await service.generate_video(
            prompt="x",
            reference_video_urls=[f"https://cdn.test/{i}.mp4" for i in range(6)],
        )
    )["success"] is False
    assert (
        await service.generate_video(
            prompt="x",
            reference_audio_urls=[f"https://cdn.test/{i}.mp3" for i in range(6)],
        )
    )["success"] is False
    assert (
        await service.generate_video(
            prompt="x",
            reference_file_urls=["https://cdn.test/a.pdf"],
            reference_link_urls=["https://example.test/page"],
        )
    )["success"] is False
    assert (await service.generate_video(prompt="x", duration=1))["success"] is False
    assert (await service.generate_video(prompt="x", duration=-1))["success"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"reference_image_urls": "https://cdn.test/a.png"},
        {"reference_video_urls": [123]},
        {"reference_audio_urls": [None]},
        {"reference_file_urls": [""]},
        {"reference_link_urls": [False]},
    ],
)
async def test_wan3_prime_rejects_wrong_reference_shapes(kwargs):
    service = CaptureWan3PrimeService()

    result = await service.generate_video(prompt="Use media", scenario="reference", **kwargs)

    assert result["success"] is False
    assert service.last_payload == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt,kwargs",
    [
        ("Use Image2", {"reference_image_urls": ["https://cdn.test/one.png"]}),
        ("Use Video2", {"reference_video_urls": ["https://cdn.test/one.mp4"]}),
        ("Use Audio2", {"reference_audio_urls": ["https://cdn.test/one.mp3"]}),
    ],
)
async def test_wan3_prime_rejects_missing_numbered_role_tags(prompt, kwargs):
    service = CaptureWan3PrimeService()

    result = await service.generate_video(prompt=prompt, scenario="reference", **kwargs)

    assert result["success"] is False
    assert "only 1" in result["error"]
    assert service.last_payload == {}


@pytest.mark.asyncio
async def test_wan3_prime_edit_uses_managed_template_once(monkeypatch):
    service = CaptureWan3PrimeService()

    async def configured_template():
        return "Video1 source. Apply once: {instruction}"

    monkeypatch.setattr(
        "bot.services.wan3_prime_service.get_wan3_edit_template",
        configured_template,
    )

    result = await service.generate_video(
        prompt="Make the coat blue.",
        scenario="edit",
        reference_video_urls=["https://cdn.test/source.mp4"],
    )

    assert result["success"] is True
    assert result["raw_prompt"] == "Make the coat blue."
    assert result["edit_prompt_template_version"] == "wan3-prime-edit-v1"
    assert service.last_payload["input"]["prompt"] == "Video1 source. Apply once: Make the coat blue."


def test_wan3_prime_capabilities_and_pricing_policy():
    capability = get_video_capability("wan/3-0-video-prime")

    assert capability is not None
    assert capability.key == "wan_3_prime"
    assert capability.modes == (
        "text",
        "first_frame",
        "first_last",
        "reference",
        "edit",
        "file",
        "link",
    )
    assert capability.durations == (-1,) + tuple(range(2, 31))
    assert capability.aspect_ratios == ("adaptive", "16:9", "4:3", "1:1", "3:4", "9:16")
    assert capability.resolutions == ("480P", "720P", "1080P")
    assert capability.max_reference_images == 10
    assert capability.max_reference_videos == 5
    assert capability.max_reference_audio == 5
    assert capability.supports_generated_audio is True
    assert capability.supports_nsfw_checker is True
    assert capability.supports_auto_duration is True
    assert apply_video_reference_cost("wan_3_prime", 12, ["video.mp4"]) == 12
