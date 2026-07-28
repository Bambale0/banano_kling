import asyncio

from bot.handlers.seedance_multimodal_compat import (
    SEEDANCE_MODELS,
    seedance_needs_multimodal_promotion,
)
from bot.handlers.generation import _seedance_media_inputs
from bot.services.seedance_service import SeedanceService
from bot.video_reference_policy import apply_video_reference_cost


class CaptureSeedanceService(SeedanceService):
    def __init__(self) -> None:
        super().__init__(kie_key="test-key")
        self.last_payload = None

    async def _prepare_image_urls(self, image_urls):
        return list(image_urls), [], []

    async def _kie_post(self, endpoint, payload):
        self.last_payload = payload
        return {"task_id": "seedance-test-task"}


def test_seedance_combines_identity_image_and_motion_video() -> None:
    service = CaptureSeedanceService()
    prompt = (
        "девушка @image1 одета в @image2, движения танца с @video1. "
        "Атмосфера и фон из @image3"
    )

    result = asyncio.run(
        service.generate_video(
            prompt=prompt,
            duration=8,
            aspect_ratio="9:16",
            resolution="1080p",
            reference_image_urls=[
                "https://cdn.test/person.jpg",
                "https://cdn.test/outfit.jpg",
                "https://cdn.test/location.jpg",
            ],
            reference_video_urls=["https://cdn.test/dance.mp4"],
        )
    )

    assert result["task_id"] == "seedance-test-task"
    payload = service.last_payload
    assert payload["model"] == "bytedance/seedance-2"
    assert payload["input"]["reference_image_urls"] == [
        "https://cdn.test/person.jpg",
        "https://cdn.test/outfit.jpg",
        "https://cdn.test/location.jpg",
    ]
    assert payload["input"]["reference_video_urls"] == [
        "https://cdn.test/dance.mp4"
    ]
    assert "first_frame_url" not in payload["input"]
    assert payload["input"]["prompt"] == prompt
    assert "IDENTITY AND REFERENCE ROLE LOCK" not in payload["input"]["prompt"]


def test_seedance_normalizes_duplicate_first_frame_from_old_repeat_payload() -> None:
    service = CaptureSeedanceService()
    image_url = "https://cdn.test/start.jpg"

    result = asyncio.run(
        service.generate_video(
            prompt="Animate the source image.",
            first_frame_url=image_url,
            reference_image_urls=[image_url],
        )
    )

    assert result["task_id"] == "seedance-test-task"
    payload = service.last_payload["input"]
    assert payload["first_frame_url"] == image_url
    assert "reference_image_urls" not in payload


def test_seedance_uses_current_documented_limits() -> None:
    service = CaptureSeedanceService()

    asyncio.run(
        service.generate_video(
            prompt="Four second adaptive 4K clip.",
            duration=4,
            aspect_ratio="adaptive",
            resolution="4k",
            reference_audio_urls=[
                "https://cdn.test/a1.mp3",
                "https://cdn.test/a2.mp3",
                "https://cdn.test/a3.mp3",
            ],
        )
    )

    payload = service.last_payload["input"]
    assert payload["duration"] == 4
    assert payload["aspect_ratio"] == "adaptive"
    assert payload["resolution"] == "4k"
    assert payload["reference_audio_urls"] == [
        "https://cdn.test/a1.mp3",
        "https://cdn.test/a2.mp3",
        "https://cdn.test/a3.mp3",
    ]


def test_legacy_image_led_seedance_state_is_promoted_only_when_video_refs_exist() -> None:
    assert "seedance_2" in SEEDANCE_MODELS
    assert seedance_needs_multimodal_promotion(
        {
            "v_model": "seedance_2",
            "v_type": "imgtxt",
            "v_image_url": "https://cdn.test/person.jpg",
            "v_reference_videos": ["https://cdn.test/dance.mp4"],
        }
    )
    assert not seedance_needs_multimodal_promotion(
        {
            "v_model": "seedance_2",
            "v_type": "imgtxt",
            "v_image_url": "https://cdn.test/person.jpg",
            "v_reference_videos": [],
        }
    )
    assert not seedance_needs_multimodal_promotion(
        {
            "v_model": "v3_pro",
            "v_type": "imgtxt",
            "v_reference_videos": ["https://cdn.test/dance.mp4"],
        }
    )


def test_seedance_transport_keeps_primary_photo_with_video_reference() -> None:
    first_frame, images, videos = _seedance_media_inputs(
        "imgtxt",
        "https://cdn.test/person.jpg",
        [],
        ["https://cdn.test/dance.mp4"],
    )

    assert first_frame is None
    assert images == ["https://cdn.test/person.jpg"]
    assert videos == ["https://cdn.test/dance.mp4"]


def test_seedance_transport_preserves_all_photo_reference_order() -> None:
    first_frame, images, videos = _seedance_media_inputs(
        "video",
        "https://cdn.test/person.jpg",
        ["https://cdn.test/outfit.jpg", "https://cdn.test/location.jpg"],
        ["https://cdn.test/dance.mp4"],
    )

    assert first_frame is None
    assert images == [
        "https://cdn.test/person.jpg",
        "https://cdn.test/outfit.jpg",
        "https://cdn.test/location.jpg",
    ]
    assert videos == ["https://cdn.test/dance.mp4"]


def test_seedance_video_reference_doubles_price_once() -> None:
    assert apply_video_reference_cost(
        "seedance_2",
        7,
        ["https://cdn.test/a.mp4"],
    ) == 14
    assert apply_video_reference_cost(
        "bytedance/seedance-2",
        7,
        ["https://cdn.test/a.mp4", "https://cdn.test/b.mp4"],
    ) == 14


def test_seedance_without_video_reference_keeps_base_price() -> None:
    assert apply_video_reference_cost("seedance_2", 7, []) == 7
    assert apply_video_reference_cost(
        "gemini_omni_video",
        7,
        ["https://cdn.test/a.mp4"],
    ) == 7
