from pathlib import Path

import pytest

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


def test_exact_video_repeat_restores_full_recipe_from_source_id_only() -> None:
    source_task = {
        "prompt": "private original prompt",
        "model": "seedance_2_5",
        "duration": 12,
        "aspect_ratio": "9:16",
        "request_data": {
            "v_type": "video",
            "seedance25_scenario": "multimodal",
            "reference_images": ["https://example.test/private-image.png"],
            "v_reference_videos": ["https://example.test/private-video.mp4"],
            "reference_audios": ["https://example.test/private-audio.mp3"],
            "resolution": "720p",
            "generate_audio": True,
            "return_last_frame": False,
            "output_format": "mp4",
            "web_search": False,
            "nsfw_checker": False,
        },
    }

    restored = enrich_video_repeat_body(
        {"source_feed_gen_id": 42},
        source_task,
    )

    assert restored["v_model"] == "seedance_2_5"
    assert restored["prompt"] == "private original prompt"
    assert restored["v_duration"] == 12
    assert restored["v_ratio"] == "9:16"
    assert restored["seedance25_scenario"] == "multimodal"
    assert restored["reference_images"] == ["https://example.test/private-image.png"]
    assert restored["v_reference_videos"] == ["https://example.test/private-video.mp4"]
    assert restored["seedance25_reference_audio_urls"] == [
        "https://example.test/private-audio.mp3"
    ]



def test_seedance25_text_repeat_with_new_photo_becomes_multimodal() -> None:
    source_task = {
        "prompt": "source prompt",
        "model": "seedance_2_5",
        "duration": 8,
        "aspect_ratio": "9:16",
        "request_data": {
            "v_type": "text",
            "seedance25_scenario": "text",
        },
    }

    restored = enrich_video_repeat_body(
        {
            "v_model": "seedance_2_5",
            "v_type": "text",
            "source_feed_gen_id": 101,
            "reference_images": ["https://example.test/user-photo.jpg"],
        },
        source_task,
    )

    assert restored["seedance25_scenario"] == "multimodal"
    assert restored["reference_images"] == ["https://example.test/user-photo.jpg"]


def test_seedance25_first_frame_repeat_uses_new_photo_as_first_frame() -> None:
    source_task = {
        "prompt": "source prompt",
        "model": "seedance_2_5",
        "duration": 8,
        "aspect_ratio": "9:16",
        "request_data": {
            "v_type": "imgtxt",
            "seedance25_scenario": "first_frame",
            "first_frame_url": "https://example.test/private-source.jpg",
        },
    }

    restored = enrich_video_repeat_body(
        {
            "v_model": "seedance_2_5",
            "v_type": "imgtxt",
            "source_feed_gen_id": 102,
            "reference_images": ["https://example.test/user-photo.jpg"],
        },
        source_task,
    )

    assert restored["seedance25_scenario"] == "first_frame"
    assert restored["seedance25_first_frame_url"] == "https://example.test/user-photo.jpg"


def test_seedance25_first_last_repeat_uses_two_new_photos_as_frames() -> None:
    source_task = {
        "prompt": "source prompt",
        "model": "seedance_2_5",
        "duration": 8,
        "aspect_ratio": "9:16",
        "request_data": {
            "v_type": "imgtxt",
            "seedance25_scenario": "first_last",
            "first_frame_url": "https://example.test/private-first.jpg",
            "last_frame_url": "https://example.test/private-last.jpg",
        },
    }

    restored = enrich_video_repeat_body(
        {
            "v_model": "seedance_2_5",
            "v_type": "imgtxt",
            "source_feed_gen_id": 103,
            "reference_images": [
                "https://example.test/user-first.jpg",
                "https://example.test/user-last.jpg",
            ],
        },
        source_task,
    )

    assert restored["seedance25_scenario"] == "first_last"
    assert restored["seedance25_first_frame_url"] == "https://example.test/user-first.jpg"
    assert restored["seedance25_last_frame_url"] == "https://example.test/user-last.jpg"


def test_seedance25_repeat_preserves_only_author_selected_reference_slots() -> None:
    face = "https://example.test/face.png"
    cake = "https://example.test/cake.png"
    outfit = "https://example.test/outfit.png"
    car = "https://example.test/car.png"
    viewer = "https://example.test/viewer.png"
    source_task = {
        "type": "video",
        "status": "completed",
        "prompt": "Image1 person with Image2 cake, Image3 outfit and Image4 car",
        "model": "seedance_2_5",
        "duration": 10,
        "aspect_ratio": "9:16",
        "is_public_feed": True,
        "feed_references_visible": True,
        "feed_reference_selection": {"images": [cake, outfit, car], "videos": []},
        "request_data": {
            "v_type": "video",
            "seedance25_scenario": "multimodal",
            "reference_images": [face, cake, outfit, car],
            "v_reference_videos": [],
        },
    }

    restored = enrich_video_repeat_body(
        {
            "v_model": "seedance_2_5",
            "source_feed_gen_id": 291846,
            "reference_images": [viewer],
        },
        source_task,
    )

    assert restored["seedance25_scenario"] == "multimodal"
    assert restored["reference_images"] == [viewer, cake, outfit, car]
    assert face not in restored["reference_images"]
    assert restored["_private_repeat_reference_images"] == [cake, outfit, car]


def test_video_repeat_does_not_restore_unselected_publication_refs_without_replacement() -> None:
    face = "https://example.test/face.png"
    outfit = "https://example.test/outfit.png"
    source_task = {
        "type": "video",
        "status": "completed",
        "prompt": "Image1 person Image2 outfit",
        "model": "seedance_2",
        "duration": 5,
        "aspect_ratio": "9:16",
        "is_public_feed": True,
        "feed_references_visible": True,
        "feed_reference_selection": {"images": [outfit], "videos": []},
        "request_data": {
            "v_type": "video",
            "reference_images": [face, outfit],
        },
    }

    restored = enrich_video_repeat_body(
        {
            "v_model": "seedance_2",
            "source_feed_gen_id": 42,
            "reference_images": [],
        },
        source_task,
    )

    assert face not in restored.get("reference_images", [])
    assert outfit not in restored.get("reference_images", [])
    assert restored.get("_private_repeat_reference_images", []) == []


@pytest.mark.asyncio
async def test_generic_video_repeat_keeps_private_author_refs_out_of_viewer_library(monkeypatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot import miniapp

    viewer = "https://example.test/viewer.png"
    private_outfit = "https://example.test/private-outfit.png"
    body = {
        "init_data": "signed",
        "source_feed_gen_id": 42,
        "v_model": "seedance_2",
        "v_type": "imgtxt",
        "prompt": "repeat",
        "v_duration": 5,
        "v_ratio": "9:16",
        "v_image_url": viewer,
        "reference_images": [viewer, private_outfit],
        "_private_repeat_reference_images": [private_outfit],
    }
    monkeypatch.setattr(
        miniapp,
        "_get_user_context",
        AsyncMock(return_value=(700003, {"user": SimpleNamespace(id=503, credits=100)})),
    )
    monkeypatch.setattr(
        miniapp,
        "_get_repeat_source_card",
        AsyncMock(return_value={"id": 42, "gen_type": "video", "model": "seedance_2"}),
    )
    monkeypatch.setattr(
        miniapp,
        "get_generation_task_payload",
        AsyncMock(return_value={"prompt": "repeat", "request_data": {}}),
    )
    monkeypatch.setattr(miniapp, "missing_local_upload_sources", lambda _refs: [])
    touch = AsyncMock()
    monkeypatch.setattr(miniapp, "touch_saved_references", touch)
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _telegram_id: True)
    launch = AsyncMock(return_value={"status": "failed", "error": "synthetic"})
    monkeypatch.setattr(miniapp, "_launch_video_generation_task", launch)

    response = await miniapp.miniapp_generate_video(
        SimpleNamespace(app={}, json=AsyncMock(return_value=body))
    )

    assert response.status == 500
    assert launch.await_args.kwargs["image_url"] == viewer
    assert private_outfit in launch.await_args.kwargs["image_references"]
    touched = [
        url
        for call in touch.await_args_list
        for url in call.args[1]
    ]
    assert viewer in touched
    assert private_outfit not in touched


def test_video_repeat_preserves_selected_video_reference_slots() -> None:
    source_motion = "https://example.test/source-motion.mp4"
    author_style = "https://example.test/author-style.mp4"
    viewer_motion = "https://example.test/viewer-motion.mp4"
    source_task = {
        "type": "video",
        "status": "completed",
        "prompt": "Video1 motion Video2 style",
        "model": "seedance_2",
        "duration": 5,
        "aspect_ratio": "9:16",
        "is_public_feed": True,
        "feed_references_visible": True,
        "feed_reference_selection": {"images": [], "videos": [author_style]},
        "request_data": {
            "v_type": "video",
            "v_reference_videos": [source_motion, author_style],
        },
    }

    restored = enrich_video_repeat_body(
        {
            "v_model": "seedance_2",
            "source_feed_gen_id": 43,
            "v_reference_videos": [viewer_motion],
        },
        source_task,
    )

    assert restored["v_reference_videos"] == [viewer_motion, author_style]
    assert source_motion not in restored["v_reference_videos"]
    assert restored["_private_repeat_reference_videos"] == [author_style]
