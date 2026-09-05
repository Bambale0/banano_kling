from pathlib import Path

from bot.handlers.miniapp_video_continuity_compat import (
    _video_remix_link,
    enrich_video_repeat_body,
)


def test_seedance25_repeat_restores_server_side_references_and_options() -> None:
    source_task = {
        "prompt": "keep the original motion",
        "model": "seedance_2_5",
        "duration": 8,
        "aspect_ratio": "9:16",
        "request_data": {
            "v_type": "video",
            "seedance25_scenario": "multimodal",
            "reference_images": ["https://example.test/image-1.png"],
            "v_reference_videos": ["https://example.test/video-1.mp4"],
            "reference_audios": ["https://example.test/audio-1.mp3"],
            "resolution": "720p",
            "generate_audio": True,
            "return_last_frame": True,
            "output_format": "mp4",
            "web_search": False,
            "nsfw_checker": False,
        },
    }
    body = {
        "v_model": "seedance_2_5",
        "source_feed_gen_id": 42,
        "reference_images": [],
        "v_reference_videos": [],
    }

    restored = enrich_video_repeat_body(body, source_task)

    assert restored["prompt"] == "keep the original motion"
    assert restored["v_duration"] == 8
    assert restored["v_ratio"] == "9:16"
    assert restored["seedance25_scenario"] == "multimodal"
    assert restored["reference_images"] == ["https://example.test/image-1.png"]
    assert restored["v_reference_videos"] == ["https://example.test/video-1.mp4"]
    assert restored["seedance25_reference_audio_urls"] == [
        "https://example.test/audio-1.mp3"
    ]
    assert restored["audio_url"] == "https://example.test/audio-1.mp3"
    assert restored["seedance25_resolution"] == "720p"
    assert restored["seedance25_return_last_frame"] is True


def test_repeat_restores_legacy_reference_aliases() -> None:
    source_task = {
        "prompt": "legacy prompt",
        "model": "seedance_2_5",
        "duration": 6,
        "aspect_ratio": "16:9",
        "request_data": {
            "scenario": "multimodal",
            "reference_image_urls": ["https://example.test/legacy-image.jpg"],
            "reference_video_urls": ["https://example.test/legacy-video.mp4"],
            "reference_audio_urls": ["https://example.test/legacy-audio.wav"],
        },
    }

    restored = enrich_video_repeat_body(
        {"v_model": "seedance_2_5", "sourceFeedGenId": 77},
        source_task,
    )

    assert restored["reference_images"] == ["https://example.test/legacy-image.jpg"]
    assert restored["v_reference_videos"] == ["https://example.test/legacy-video.mp4"]
    assert restored["seedance25_reference_audio_urls"] == [
        "https://example.test/legacy-audio.wav"
    ]
    assert restored["seedance25_scenario"] == "multimodal"


def test_video_share_converts_miniapp_post_link_to_remix_link() -> None:
    payload = {
        "miniapp_post_link": "https://t.me/NeuromixBot/app?startapp=feed_123_PARTNER",
    }

    assert _video_remix_link(payload) == (
        "https://t.me/NeuromixBot/app?startapp=remix_123_PARTNER"
    )


def test_regular_image_to_video_repeat_restores_private_start_frame() -> None:
    source_task = {
        "prompt": "animate this frame",
        "model": "seedance_1_5_pro",
        "duration": 10,
        "aspect_ratio": "16:9",
        "request_data": {
            "v_type": "imgtxt",
            "v_image_url": "https://example.test/private-start.jpg",
        },
    }

    restored = enrich_video_repeat_body(
        {
            "v_model": "seedance_1_5_pro",
            "v_type": "imgtxt",
            "source_feed_gen_id": 91,
            "v_image_url": None,
        },
        source_task,
    )

    assert restored["v_image_url"] == "https://example.test/private-start.jpg"


def test_feed_repeat_form_uses_photo_references_instead_of_start_image() -> None:
    form_path = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "miniapp-v0"
        / "components"
        / "forms"
        / "video-generator-form.tsx"
    )
    source = form_path.read_text(encoding="utf-8")

    assert "Стартовое изображение" not in source
    assert "Сохранённые стартовые кадры" not in source
    assert "const needsPhotoReference" in source
    assert "photoReferences.length === 0" in source
    assert 'libraryLabel="Сохранённые фото-референсы"' in source


def test_repeat_selected_photo_reference_overrides_private_source_image() -> None:
    source_task = {
        "prompt": "animate this frame",
        "model": "seedance_2",
        "duration": 10,
        "aspect_ratio": "16:9",
        "request_data": {
            "v_type": "imgtxt",
            "v_image_url": "https://example.test/private-source.jpg",
        },
    }

    restored = enrich_video_repeat_body(
        {
            "v_model": "seedance_2",
            "v_type": "imgtxt",
            "source_feed_gen_id": 92,
            "v_image_url": None,
            "reference_images": [
                "https://example.test/user-photo.jpg",
                "https://example.test/extra-reference.jpg",
            ],
        },
        source_task,
    )

    assert restored["v_image_url"] == "https://example.test/user-photo.jpg"
    assert restored["reference_images"] == ["https://example.test/extra-reference.jpg"]
