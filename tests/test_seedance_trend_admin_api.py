import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import seedance_trend_admin_api as api
from bot.seedance_trend_recipe import compile_seedance_trend_recipe


@pytest.mark.asyncio
async def test_source_task_allows_owned_generation_from_ordinary_saved_prompt(
    monkeypatch,
):
    from bot import miniapp as miniapp_module

    user = SimpleNamespace(id=81)
    monkeypatch.setattr(
        miniapp_module,
        "_get_user_context",
        AsyncMock(return_value=(9001, {"user": user})),
    )
    monkeypatch.setattr(api.config, "is_admin", lambda telegram_id: telegram_id == 9001)
    monkeypatch.setattr(
        api,
        "get_generation_task_payload",
        AsyncMock(
            return_value={
                "id": 501,
                "task_id": "ordinary-prompt-seedance",
                "model": "seedance_2",
                "type": "video",
                "status": "completed",
                "result_url": "https://provider.example.test/result.mp4",
                "prompt": "@Image1 wears @Image2",
                "source_feed_gen_id": None,
                "action_type": None,
                "request_data": {
                    "prompt_source_id": 44,
                    "v_image_url": "https://source.example.test/creator.jpg",
                    "reference_images": ["https://source.example.test/dress.jpg"],
                },
            }
        ),
    )

    class Request:
        def __init__(self) -> None:
            self.app = {}

    telegram_id, resolved_user, task = await api._admin_source_task(
        Request(),
        {"init_data": "signed", "task_id": "ordinary-prompt-seedance"},
    )

    assert telegram_id == 9001
    assert resolved_user is user
    assert task["task_id"] == "ordinary-prompt-seedance"


@pytest.mark.asyncio
async def test_editing_trend_settings_use_measured_hidden_video_duration(monkeypatch):
    from bot.handlers import seedance_25_fullstack as fullstack

    validate = AsyncMock(return_value=11.2)
    monkeypatch.setattr(fullstack, "_validate_local_source", validate)
    recipe = SimpleNamespace(
        image_assets=(object(),),
        video_assets=(object(),),
        audio_assets=(),
    )
    settings = await api._generation_settings(
        {
            "model": "seedance_2_5",
            "duration": -1,
            "aspect_ratio": "adaptive",
        },
        {
            "seedance25_video_editing": True,
            "resolution": "720p",
        },
        recipe,
        [
            {
                "media_type": "video",
                "file_url": "https://assets.example.test/uploads/trend-assets/source.mp4",
            }
        ],
    )

    assert settings["duration"] == -1
    assert settings["ratio"] == "adaptive"
    assert settings["source_video_duration_seconds"] == 12
    assert settings["fixed_image_reference_count"] == 1
    assert settings["fixed_video_reference_count"] == 1
    validate.assert_awaited_once_with(
        "https://assets.example.test/uploads/trend-assets/source.mp4",
        "video",
    )


@pytest.mark.asyncio
async def test_generation_settings_publish_safe_replaceable_video_slot_plan() -> None:
    recipe = compile_seedance_trend_recipe(
        prompt="Person @Image1 wears @Image2 and follows @Video1.",
        model="seedance_2_5",
        source_images=["https://source.test/face.jpg", "https://source.test/dress.jpg"],
        source_videos=["https://source.test/motion.mp4"],
        source_audios=[],
        identity_image_index=1,
        fixed_image_indices=[2],
        fixed_video_indices=[],
        fixed_audio_indices=[],
        replaceable_video_indices=[1],
    )
    settings = await api._generation_settings(
        {"model": "seedance_2_5", "duration": 5, "aspect_ratio": "9:16"},
        {"resolution": "720p"},
        recipe,
        [{"media_type": "image", "file_url": "/uploads/trend-assets/dress.jpg"}],
    )

    assert settings["reference_plan_version"] == 2
    assert settings["reference_slots"] == [
        {"media_type": "image", "position": 1, "label": "ВАШЕ ЛИЦО"},
        {
            "media_type": "video",
            "position": 1,
            "label": "ВАШЕ ВИДЕО · @Video1",
        },
    ]
    assert settings["fixed_image_reference_count"] == 1
    assert settings["fixed_video_reference_count"] == 0
    assert settings["automatic_hidden_references"] is True
    assert "source.test" not in json.dumps(settings)


@pytest.mark.asyncio
async def test_publish_seedance_trend_persists_recipe_and_returns_only_public_metadata(
    monkeypatch,
):
    task = {
        "id": 501,
        "task_id": "seedance-source-task",
        "model": "seedance_2",
        "type": "video",
        "status": "completed",
        "duration": 10,
        "aspect_ratio": "9:16",
        "prompt": "Dress the person in the supplied outfit and follow the supplied motion.",
        "result_url": "https://provider.example.test/result.mp4",
        "request_data": {
            "v_image_url": "https://source.example.test/creator.jpg",
            "reference_images": ["https://source.example.test/dress.jpg"],
            "v_reference_videos": ["https://source.example.test/motion.mp4"],
            "resolution": "720p",
        },
        "source_feed_gen_id": None,
        "action_type": None,
    }
    user = SimpleNamespace(id=81)
    monkeypatch.setattr(
        api, "_admin_source_task", AsyncMock(return_value=(9001, user, task))
    )
    monkeypatch.setattr(
        api,
        "get_active_seedance_trend_by_source_generation",
        AsyncMock(return_value=None),
    )
    persisted_assets = [
        {
            "media_type": "image",
            "position": 2,
            "source_position": 2,
            "role": "fixed_hidden",
            "file_url": "https://assets.example.test/uploads/trend-assets/dress.png",
            "file_hash": "a" * 64,
            "mime_type": "image/png",
            "size_bytes": 100,
            "label": "@Image2",
        },
        {
            "media_type": "video",
            "position": 1,
            "source_position": 1,
            "role": "fixed_hidden",
            "file_url": "https://assets.example.test/uploads/trend-assets/motion.mp4",
            "file_hash": "b" * 64,
            "mime_type": "video/mp4",
            "size_bytes": 1000,
            "label": "@Video1",
        },
    ]
    monkeypatch.setattr(
        api, "_persist_recipe_assets", AsyncMock(return_value=persisted_assets)
    )
    monkeypatch.setattr(
        api,
        "persist_feed_result_urls",
        AsyncMock(return_value=["https://assets.example.test/uploads/feed/result.mp4"]),
    )
    create = AsyncMock(return_value={"id": 77})
    monkeypatch.setattr(api, "create_prompt", create)
    approved = {
        "id": 77,
        "status": "approved",
        "is_public": True,
        "tags": ["trend", "trend-video", "seedance-private-references"],
        "prompt_text": "PRIVATE PROMPT",
        "model": "seedance_2",
        "category": "video",
        "generation_settings": {
            "kind": "video",
            "ratio": "9:16",
            "reference_count": 1,
            "reference_labels": ["ВАШЕ ЛИЦО"],
            "automatic_hidden_references": True,
        },
    }
    monkeypatch.setattr(api, "approve_prompt", AsyncMock(return_value=approved))

    class Request:
        def __init__(self) -> None:
            self.app = {}

        async def json(self):
            return {
                "task_id": "seedance-source-task",
                "title": "Dress motion",
                "description": "Upload your face",
                "identity_image_index": 1,
                "fixed_image_indices": [2],
                "fixed_video_indices": [1],
                "fixed_audio_indices": [],
                "preview_url": "http://127.0.0.1/private-admin-override.mp4",
            }

    response = await api.miniapp_admin_publish_seedance_trend(Request())
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["ok"] is True
    assert payload["prompt"]["prompt_text"] == ""
    assert payload["prompt"]["model"] is None
    assert payload["prompt"]["generation_settings"] == {
        "kind": "video",
        "ratio": "9:16",
        "reference_count": 1,
        "reference_labels": ["ВАШЕ ЛИЦО"],
        "automatic_hidden_references": True,
    }
    api.persist_feed_result_urls.assert_awaited_once_with(
        ["https://provider.example.test/result.mp4"],
        require_local=True,
    )
    kwargs = create.await_args.kwargs
    assert kwargs["source_generation_id"] == 501
    assert kwargs["trend_reference_assets"] == persisted_assets
    assert kwargs["model"] == "seedance_2"
    assert kwargs["prompt_text"].startswith(
        "Dress the person in the supplied outfit and follow the supplied motion."
    )
    assert "SEEDANCE_TREND_IDENTITY_CONTRACT_V1" in kwargs["prompt_text"]
    assert "@Image1 is the only identity/person source" in kwargs["prompt_text"]
    assert "@Image2" in kwargs["prompt_text"]
    assert "@Video1" in kwargs["prompt_text"]
    assert "creator.jpg" not in json.dumps(kwargs)


@pytest.mark.asyncio
async def test_publish_seedance_trend_rejects_duplicate_source_before_copying_assets(
    monkeypatch,
):
    task = {
        "id": 501,
        "task_id": "seedance-source-task",
        "model": "seedance_2",
        "type": "video",
        "status": "completed",
        "result_url": "https://provider.example.test/result.mp4",
        "prompt": "@Image1 wears @Image2",
        "request_data": {
            "v_image_url": "https://source.example.test/creator.jpg",
            "reference_images": ["https://source.example.test/dress.jpg"],
        },
        "source_feed_gen_id": None,
        "action_type": None,
    }
    user = SimpleNamespace(id=81)
    monkeypatch.setattr(
        api, "_admin_source_task", AsyncMock(return_value=(9001, user, task))
    )
    monkeypatch.setattr(
        api,
        "get_active_seedance_trend_by_source_generation",
        AsyncMock(
            return_value={
                "id": 77,
                "status": "approved",
                "is_public": True,
                "tags": ["trend", "trend-video", "seedance-private-references"],
                "prompt_text": "PRIVATE",
                "model": "seedance_2",
                "category": "video",
                "generation_settings": {
                    "kind": "video",
                    "ratio": "9:16",
                    "reference_count": 1,
                },
            }
        ),
    )
    persist = AsyncMock()
    monkeypatch.setattr(api, "_persist_recipe_assets", persist)

    class Request:
        def __init__(self) -> None:
            self.app = {}

        async def json(self):
            return {"task_id": "seedance-source-task", "title": "Duplicate"}

    response = await api.miniapp_admin_publish_seedance_trend(Request())
    payload = json.loads(response.text)

    assert response.status == 409
    assert payload["prompt"]["prompt_text"] == ""
    persist.assert_not_awaited()
