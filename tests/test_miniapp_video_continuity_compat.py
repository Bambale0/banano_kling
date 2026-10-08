from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bot.handlers.miniapp_video_continuity_compat import (
    VideoRepeatReferenceError,
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

    with pytest.raises(VideoRepeatReferenceError, match="не хватает"):
        enrich_video_repeat_body(
            {
                "v_model": "seedance_2",
                "source_feed_gen_id": 42,
                "reference_images": [],
            },
            source_task,
        )


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
    source_task = {
        "prompt": "repeat", "model": "seedance_2",
        "user_id": 1, "type": "video", "status": "completed", "is_public_feed": True,
        "feed_references_visible": True,
        "feed_reference_selection": {"images": [private_outfit], "videos": []},
        "request_data": {"reference_images": [
            "https://example.test/author-face.png", private_outfit,
        ]},
    }
    monkeypatch.setattr(
        miniapp, "get_generation_task_payload", AsyncMock(return_value=source_task),
    )
    from bot.handlers import miniapp_video_continuity_compat as continuity
    monkeypatch.setattr(
        continuity, "get_generation_task_payload", AsyncMock(return_value=source_task),
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



def test_video_repeat_uses_private_grant_when_public_references_are_hidden() -> None:
    author_face = "https://example.test/author-face.png"
    fixed_outfit = "https://example.test/fixed-outfit.png"
    author_motion = "https://example.test/author-motion.mp4"
    fixed_motion = "https://example.test/fixed-motion.mp4"
    viewer_face = "https://example.test/viewer-face.png"
    viewer_motion = "https://example.test/viewer-motion.mp4"
    source_task = {
        "type": "video",
        "status": "completed",
        "prompt": "Image1 person Image2 outfit Video1 motion Video2 style",
        "model": "seedance_2_5",
        "duration": 10,
        "aspect_ratio": "9:16",
        "is_public_feed": True,
        "feed_references_visible": False,
        "feed_reference_selection": {"images": [], "videos": []},
        "feed_repeat_reference_selection": {
            "version": 1,
            "images": [fixed_outfit],
            "videos": [fixed_motion],
        },
        "request_data": {
            "seedance25_scenario": "multimodal",
            "reference_images": [author_face, fixed_outfit],
            "v_reference_videos": [author_motion, fixed_motion],
        },
    }

    restored = enrich_video_repeat_body(
        {
            "source_feed_gen_id": 44,
            "reference_images": [viewer_face],
            "v_reference_videos": [viewer_motion],
        },
        source_task,
    )

    assert restored["reference_images"] == [viewer_face, fixed_outfit]
    assert restored["v_reference_videos"] == [viewer_motion, fixed_motion]
    assert restored["_private_repeat_reference_images"] == [fixed_outfit]
    assert restored["_private_repeat_reference_videos"] == [fixed_motion]


def test_video_repeat_private_revocation_overrides_public_reference_selection() -> None:
    fixed_image = "https://example.test/fixed-image.png"
    fixed_video = "https://example.test/fixed-video.mp4"
    source_task = {
        "type": "video",
        "status": "completed",
        "prompt": "repeat",
        "model": "seedance_2_5",
        "feed_references_visible": True,
        "feed_reference_selection": {
            "images": [fixed_image],
            "videos": [fixed_video],
        },
        "feed_repeat_reference_selection": {"version": 1, "images": [], "videos": []},
        "request_data": {
            "seedance25_scenario": "multimodal",
            "reference_images": [fixed_image],
            "v_reference_videos": [fixed_video],
        },
    }

    with pytest.raises(VideoRepeatReferenceError):
        enrich_video_repeat_body({"source_feed_gen_id": 45}, source_task)


def test_legacy_video_repeat_without_video_private_key_keeps_public_selection_fallback() -> None:
    fixed = "https://example.test/legacy-fixed.png"
    source_task = {
        "type": "video",
        "status": "completed",
        "prompt": "repeat",
        "model": "seedance_2",
        "feed_references_visible": True,
        "feed_reference_selection": {"images": [fixed], "videos": []},
        # Old image-only releases wrote this shape for video publications.
        "feed_repeat_reference_selection": {"images": []},
        "request_data": {
            "v_type": "video",
            "reference_images": [fixed],
        },
    }

    restored = enrich_video_repeat_body({"source_feed_gen_id": 46}, source_task)

    assert restored["reference_images"] == [fixed]
    assert restored["_private_repeat_reference_images"] == [fixed]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,target,suffix", [
    ("images", "reference_images", ".png"),
    ("videos", "v_reference_videos", ".mp4"),
])
@pytest.mark.parametrize("replacement_count", [0, 1, 2])
async def test_video_repeat_api_rejects_incomplete_fixed_reference_slots(
    monkeypatch, kind, target, suffix, replacement_count,
):
    """Real installed entry point must stop before its billing/provider handler."""
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aiohttp import web

    from bot import miniapp
    from bot.handlers import miniapp_video_continuity_compat as continuity

    source_identity = [f"https://example.test/author-{i}{suffix}" for i in range(2)]
    fixed = f"https://example.test/fixed-template{suffix}"
    replacements = [f"https://example.test/viewer-{i}{suffix}" for i in range(replacement_count)]
    source_task = {
        "prompt": "Synthetic slot-preserving recipe",
        "model": "seedance_2_5",
        "feed_references_visible": True,
        "feed_reference_selection": {"images": [], "videos": [], kind: [fixed]},
        "request_data": {
            "v_type": "video", "seedance25_scenario": "multimodal",
            target: [*source_identity, fixed],
        },
    }
    body = {"init_data": "signed", "source_feed_gen_id": 42, target: replacements}

    class Request:
        def __init__(self):
            self.app = {}
            self._read_bytes = json.dumps(body).encode()

        async def json(self):
            return json.loads(self._read_bytes)

    request = Request()
    delegate = AsyncMock(return_value=web.json_response({"ok": True}))
    monkeypatch.setattr(miniapp, "miniapp_generate_video", delegate)
    monkeypatch.setattr(miniapp, "miniapp_feed_share", AsyncMock())
    monkeypatch.setattr(miniapp, "_video_continuity_compat_installed", False, raising=False)
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(
        return_value=(700001, {"user": SimpleNamespace(id=501)})))
    monkeypatch.setattr(miniapp, "_get_repeat_source_card", AsyncMock(
        return_value={
            "id": 42, "gen_type": "video", "prompt": "",
            "reference_images": [], "reference_videos": [],
            "references_hidden": True, "prompt_hidden": True,
            "prompt_actions_allowed": False,
        }))
    monkeypatch.setattr(continuity, "get_generation_task_payload", AsyncMock(
        return_value=source_task))
    continuity.install_miniapp_video_continuity_compat()

    response = await miniapp.miniapp_generate_video(request)

    if replacement_count < 2:
        assert response.status == 400
        assert json.loads(response.text)["code"] == "repeat_reference_incomplete"
        assert fixed not in response.text
        assert all(url not in response.text for url in source_identity)
        delegate.assert_not_awaited()
    else:
        assert response.status == 200
        delegate.assert_awaited_once()
        restored = await request.json()
        # Public preview redaction never revokes the stored selection contract.
        assert restored[target] == [*replacements, fixed]
        assert restored["prompt"] == source_task["prompt"]
        assert source_task["prompt"] not in response.text
        assert all(url not in restored[target] for url in source_identity)
        assert restored[f"_private_repeat_reference_{kind}"] == [fixed]


@pytest.fixture
def video_repeat_entrypoint(monkeypatch):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aiohttp import web

    from bot import miniapp
    from bot.handlers import miniapp_video_continuity_compat as continuity

    class Request:
        def __init__(self, body):
            self.app = {}
            self._read_bytes = json.dumps(body).encode()

        async def json(self):
            return json.loads(self._read_bytes)

    delegate = AsyncMock(return_value=web.json_response({"ok": True}))
    context = AsyncMock(return_value=(700001, {"user": SimpleNamespace(id=501)}))
    card = AsyncMock(return_value={"id": 42, "gen_type": "video"})
    source = AsyncMock(return_value={
        "prompt": "synthetic recipe", "model": "seedance_2_5", "request_data": {},
    })
    availability = MagicMock(return_value=[])
    monkeypatch.setattr(miniapp, "miniapp_generate_video", delegate)
    monkeypatch.setattr(miniapp, "miniapp_feed_share", AsyncMock())
    monkeypatch.setattr(miniapp, "_video_continuity_compat_installed", False, raising=False)
    monkeypatch.setattr(miniapp, "_get_user_context", context)
    monkeypatch.setattr(miniapp, "_get_repeat_source_card", card)
    monkeypatch.setattr(continuity, "get_generation_task_payload", source)
    monkeypatch.setattr(continuity, "missing_local_upload_sources", availability, raising=False)
    continuity.install_miniapp_video_continuity_compat()
    return SimpleNamespace(
        call=miniapp.miniapp_generate_video, request=Request, delegate=delegate,
        context=context, card=card, source=source, availability=availability,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,expected_status", [
    ("transient_source", 503), ("missing_source", 404), ("missing_card", 404),
    ("invalid_auth", 401), ("forbidden", 403),
])
async def test_video_repeat_restore_failure_never_falls_through(
    video_repeat_entrypoint, failure, expected_status,
):
    import json
    entry = video_repeat_entrypoint
    secret_url = "https://example.test/private-fixed.png"
    if failure == "transient_source":
        # A second lookup would succeed: no retry/fallback may start an empty recipe.
        entry.source.side_effect = [RuntimeError(secret_url), entry.source.return_value]
    elif failure == "missing_source":
        entry.source.return_value = None
    elif failure == "missing_card":
        entry.card.return_value = None
    elif failure == "invalid_auth":
        entry.context.side_effect = ValueError("Invalid Telegram signature")
    else:
        entry.context.side_effect = PermissionError(secret_url)
    response = await entry.call(entry.request({"source_feed_gen_id": 42}))
    assert response.status == expected_status
    assert json.loads(response.text)["ok"] is False
    assert secret_url not in response.text
    entry.delegate.assert_not_awaited()
    if failure == "transient_source":
        assert entry.source.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,field,list_value", [
    ("multimodal", "reference_images", True),
    ("multimodal", "v_reference_videos", True),
    ("multimodal", "seedance25_reference_audio_urls", True),
    ("first_frame", "seedance25_first_frame_url", False),
    ("first_last", "seedance25_last_frame_url", False),
])
@pytest.mark.parametrize("missing", [False, True])
async def test_restored_video_media_is_validated_before_launch(
    video_repeat_entrypoint, scenario, field, list_value, missing,
):
    import json
    entry = video_repeat_entrypoint
    private_url = "/uploads/synthetic-private-reference.bin"
    value = [private_url] if list_value else private_url
    entry.source.return_value["request_data"] = {
        "seedance25_scenario": scenario, field: value,
    }
    entry.availability.side_effect = (
        lambda values: [private_url] if missing and private_url in values else []
    )
    request = entry.request({"source_feed_gen_id": 42})
    response = await entry.call(request)
    entry.availability.assert_called_once()
    assert private_url in entry.availability.call_args.args[0]
    if missing:
        assert response.status == 400
        assert json.loads(response.text)["code"] == "repeat_reference_incomplete"
        assert private_url not in response.text
        entry.delegate.assert_not_awaited()
    else:
        assert response.status == 200
        entry.delegate.assert_awaited_once()
        assert (await request.json())[field] == value


@pytest.mark.asyncio
async def test_replaced_first_frame_does_not_validate_unused_original(video_repeat_entrypoint):
    entry = video_repeat_entrypoint
    old = "/uploads/removed-original.png"
    replacement = "/uploads/viewer-replacement.png"
    entry.source.return_value["request_data"] = {
        "seedance25_scenario": "first_frame", "first_frame_url": old,
    }
    entry.availability.side_effect = lambda values: [old] if old in values else []
    request = entry.request({"source_feed_gen_id": 42, "reference_images": [replacement]})
    response = await entry.call(request)
    assert response.status == 200
    assert old not in entry.availability.call_args.args[0]
    assert replacement in entry.availability.call_args.args[0]
    assert (await request.json())["seedance25_first_frame_url"] == replacement


@pytest.mark.asyncio
async def test_ordinary_video_without_repeat_source_is_untouched(video_repeat_entrypoint):
    entry = video_repeat_entrypoint
    body = {"prompt": "My original video", "reference_images": ["/uploads/my-photo.png"]}
    request = entry.request(body)
    response = await entry.call(request)
    assert response.status == 200
    assert await request.json() == body
    entry.delegate.assert_awaited_once()
    entry.context.assert_not_awaited()
    entry.source.assert_not_awaited()
    entry.availability.assert_not_called()


@pytest.mark.parametrize("selected,expected_fixed", [
    ("https://media.chillcreative.ru/uploads/fixed-template.png?revision=2", True),
    ("https://unrelated.example/uploads/fixed-template.png", False),
])
def test_video_repeat_retains_only_matching_known_upload_alias(selected, expected_fixed):
    face = "https://example.test/source-face.png"
    fixed = "/uploads/fixed-template.png"
    viewer = "https://example.test/new-face.png"
    source = {
        "model": "seedance_2_5", "prompt": "Image1 with Image2",
        "feed_references_visible": True,
        "feed_reference_selection": {"images": [selected], "videos": []},
        "request_data": {"seedance25_scenario": "multimodal",
                         "reference_images": [face, fixed]},
    }
    if not expected_fixed:
        with pytest.raises(VideoRepeatReferenceError, match="не полностью"):
            enrich_video_repeat_body(
                {"source_feed_gen_id": 42, "reference_images": [viewer]}, source,
            )
        return
    result = enrich_video_repeat_body(
        {"source_feed_gen_id": 42, "reference_images": [viewer]}, source,
    )
    assert result["reference_images"] == [viewer, fixed]
    assert face not in result["reference_images"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,target", [
    ("images", "reference_images"), ("videos", "v_reference_videos"),
])
@pytest.mark.parametrize("stored", ["partial", "missing", "malformed"])
async def test_selected_video_recipe_cannot_silently_lose_stored_references(
    video_repeat_entrypoint, kind, target, stored,
):
    import json
    entry = video_repeat_entrypoint
    first = "https://example.test/fixed-one"
    second = "https://example.test/fixed-two"
    request_data = {
        "seedance25_scenario": "multimodal", target: [first],
    } if stored == "partial" else (None if stored == "missing" else "{broken-json")
    entry.source.return_value.update(
        feed_references_visible=True,
        feed_reference_selection={"images": [], "videos": [], kind: [first, second]},
        request_data=request_data,
    )
    response = await entry.call(entry.request({"source_feed_gen_id": 42}))
    assert response.status == 400
    assert json.loads(response.text)["code"] == "repeat_reference_incomplete"
    assert first not in response.text and second not in response.text
    entry.delegate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,target,scenario", [
    ("v_image_url", "v_image_url", "imgtxt"),
    ("first_frame_url", "seedance25_first_frame_url", "first_frame"),
    ("last_frame_url", "seedance25_last_frame_url", "first_last"),
])
async def test_selected_scalar_video_reference_is_a_valid_stored_candidate(
    video_repeat_entrypoint, field, target, scenario,
):
    entry = video_repeat_entrypoint
    fixed = "https://example.test/fixed-frame.png"
    entry.source.return_value.update(
        model="seedance_2" if scenario == "imgtxt" else "seedance_2_5",
        feed_references_visible=True,
        feed_reference_selection={"images": [fixed], "videos": []},
        request_data={field: fixed, "seedance25_scenario": scenario, "v_type": "imgtxt"},
    )
    request = entry.request({"source_feed_gen_id": 42})
    response = await entry.call(request)
    assert response.status == 200
    assert (await request.json())[target] == fixed
    entry.delegate.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", [None, {"images": [], "videos": []}])
async def test_empty_video_selection_does_not_require_a_stored_recipe(
    video_repeat_entrypoint, selection,
):
    entry = video_repeat_entrypoint
    entry.source.return_value.update(
        feed_references_visible=True, feed_reference_selection=selection,
        request_data=None,
    )
    response = await entry.call(entry.request({"source_feed_gen_id": 42}))
    assert response.status == 200
    entry.delegate.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("target,secondary,kind", [
    ("reference_images", "reference_image_urls", "images"),
    ("v_reference_videos", "reference_video_urls", "videos"),
])
async def test_selected_reference_in_shadowed_alias_rejects_before_launch(
    video_repeat_entrypoint, target, secondary, kind,
):
    import json
    entry = video_repeat_entrypoint
    active = "https://example.test/active-primary-reference"
    shadowed = "https://example.test/shadowed-selected-reference"
    entry.source.return_value.update(
        feed_references_visible=True,
        feed_reference_selection={"images": [], "videos": [], kind: [shadowed]},
        request_data={
            "seedance25_scenario": "multimodal", target: [active], secondary: [shadowed],
        },
    )
    response = await entry.call(entry.request({"source_feed_gen_id": 42}))
    assert response.status == 400
    assert json.loads(response.text)["code"] == "repeat_reference_incomplete"
    assert shadowed not in response.text
    entry.delegate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["seedance_2", "seedance_1_5_pro", "grok_imagine_v15"])
@pytest.mark.parametrize("replace", [False, True])
async def test_generic_repeat_validates_only_effective_start_frame(
    video_repeat_entrypoint, model, replace,
):
    entry = video_repeat_entrypoint
    original = "/uploads/removed-start.png"
    replacement = "/uploads/replacement-start.png"
    entry.source.return_value.update(
        model=model, request_data={"v_type": "imgtxt", "v_image_url": original},
    )
    entry.availability.side_effect = lambda values: [original] if original in values else []
    body = {"source_feed_gen_id": 42}
    if replace:
        body["reference_images"] = [replacement]
    request = entry.request(body)
    response = await entry.call(request)
    if replace:
        assert response.status == 200
        assert original not in entry.availability.call_args.args[0]
        assert entry.availability.call_args.args[0] == [replacement]
        assert (await request.json())["v_image_url"] == replacement
        entry.delegate.assert_awaited_once()
    else:
        assert response.status == 400
        entry.delegate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("model,identity", [("seedance_2_5", False), ("seedance_2", True)])
async def test_source_candidate_guard_is_not_bypassed_outside_explicit_identity(
    video_repeat_entrypoint, model, identity,
):
    entry = video_repeat_entrypoint
    entry.source.return_value.update(
        model=model, feed_references_visible=True,
        feed_reference_selection={"images": ["https://example.test/missing-fixed.png"], "videos": []},
        request_data={"v_type": "video"},
    )
    response = await entry.call(entry.request({
        "source_feed_gen_id": 42, "seedance25_identity_transfer": identity,
        "reference_images": ["https://example.test/own-image.png"],
        "v_reference_videos": ["https://example.test/own-video.mp4"],
    }))
    assert response.status == 400
    entry.delegate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("selected,expected", [
    ("/uploads/shared-reference.png", ["/uploads/shared-reference.png", "https://example.test/viewer.png"]),
    ("https://media.chillcreative.ru/uploads/shared-reference.png",
     ["https://example.test/viewer.png", "https://media.chillcreative.ru/uploads/shared-reference.png"]),
    ("https://media.chillcreative.ru/uploads/shared-reference.png?alias=1", None),
])
async def test_video_repeat_keeps_distinct_alias_slots_unmerged(
    video_repeat_entrypoint, selected, expected,
):
    entry = video_repeat_entrypoint
    entry.source.return_value.update(
        feed_references_visible=True,
        feed_reference_selection={"images": [selected], "videos": []},
        request_data={
            "seedance25_scenario": "multimodal",
            "reference_images": ["/uploads/shared-reference.png",
                                 "https://media.chillcreative.ru/uploads/shared-reference.png"],
        },
    )
    request = entry.request({
        "source_feed_gen_id": 42, "reference_images": ["https://example.test/viewer.png"],
    })
    response = await entry.call(request)
    if expected is None:
        assert response.status == 400
        entry.delegate.assert_not_awaited()
    else:
        assert response.status == 200
        assert (await request.json())["reference_images"] == expected
        entry.delegate.assert_awaited_once()
