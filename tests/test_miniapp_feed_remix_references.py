import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import miniapp


class _Request:
    def __init__(self, body=None) -> None:
        self.app: dict = {}
        self.body = body or {}

    async def json(self):
        return self.body


@pytest.mark.asyncio
async def test_own_profile_remix_keeps_selected_outfit_after_face_upload(monkeypatch):
    source_face = "https://example.test/source-face.png"
    source_outfit = "https://example.test/source-outfit.png"
    user_face = "https://example.test/user-face.png"
    source = {
        "id": 42,
        "gen_type": "image",
        "is_mine": True,
        "publication_scope": "profile",
        "references_hidden": True,
        "feed_references_visible": False,
        "model": "banana_pro",
        "aspect_ratio": "9:16",
        "result_url": "https://example.test/result.png",
    }
    source_task = {
        "feed_references_visible": False,
        "prompt": "Use Image1 as the person and Image2 as the outfit.",
        "feed_reference_selection": json.dumps(
            {
                "images": [
                    source_outfit,
                    "https://attacker.test/not-a-source-reference.png",
                ],
                "videos": [],
            }
        ),
        "request_data": {
            "source_reference_images": [source_face, source_outfit],
        },
    }
    launch = AsyncMock(return_value={"status": "failed"})

    monkeypatch.setattr(
        miniapp,
        "_miniapp_payload",
        AsyncMock(
            return_value={
                "init_data": "signed",
                "gen_id": 42,
                "img_service": "banana_pro",
                "img_ratio": "9:16",
                "img_quality": "2K",
                "reference_images": [user_face],
            }
        ),
    )
    monkeypatch.setattr(
        miniapp,
        "_get_user_context",
        AsyncMock(return_value=(123, {"user": SimpleNamespace(id=7, credits=100)})),
    )
    monkeypatch.setattr(
        miniapp,
        "_get_feed_remix_source_card",
        AsyncMock(return_value=source),
    )
    monkeypatch.setattr(
        miniapp,
        "get_generation_task_payload",
        AsyncMock(return_value=source_task),
    )
    monkeypatch.setattr(miniapp, "missing_local_upload_sources", lambda _refs: [])
    monkeypatch.setattr(miniapp, "touch_saved_references", AsyncMock())
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _telegram_id: True)
    monkeypatch.setattr(miniapp, "_start_image_generation_task_lazy", launch)

    response = await miniapp.miniapp_feed_remix(_Request())

    assert response.status == 500
    assert launch.await_args.kwargs["reference_images"] == [user_face, source_outfit]
    assert source_face not in launch.await_args.kwargs["reference_images"]


def test_foreign_remix_restores_only_explicitly_selected_source_references():
    submitted = ["https://example.test/user-face.png"]
    outfit = "https://example.test/outfit.png"
    hidden_face = "https://example.test/source-face.png"
    task_payload = {
        "is_public_feed": True,
        "feed_references_visible": True,
        "feed_reference_selection": {"images": [outfit]},
        "request_data": {
            "source_reference_images": [hidden_face, outfit]
        },
    }
    card = {
        "is_mine": False,
        "feed_references_visible": True,
        "references_hidden": False,
        "reference_images": [outfit],
    }
    references, retained_count = miniapp._merge_remix_image_references(
        card,
        task_payload,
        submitted,
    )

    assert references == [*submitted, outfit]
    assert retained_count == 1
    assert miniapp._filter_foreign_feed_source_references(
        card,
        task_payload,
        [hidden_face, *references],
        viewer_telegram_id=123,
    ) == [*submitted, outfit]


@pytest.mark.asyncio
@pytest.mark.parametrize("references_visible", [False, True])
@pytest.mark.parametrize("endpoint", ["remix", "generate"])
async def test_foreign_remix_obeys_visibility_before_launch(monkeypatch, references_visible, endpoint):
    hidden_face = "https://example.test/private-face.png"
    retained_outfit = "https://example.test/outfit.png"
    private_board = "https://example.test/uploads/reference_boards/private-board.jpg"
    user_face = "https://example.test/viewer-face.png"
    source = {
        "id": 42,
        "gen_type": "image",
        "is_mine": False,
        "model": "banana_pro",
        "feed_references_visible": references_visible,
        "references_hidden": not references_visible,
        "reference_images": [retained_outfit] if references_visible else [],
    }
    source_task = {
        "prompt": "Use the supplied outfit",
        "is_public_feed": True,
        "feed_references_visible": references_visible,
        # Legacy publications retain a selection even when it is hidden.
        "feed_reference_selection": {"images": [retained_outfit], "videos": []},
        "request_data": {
            "source_reference_images": [hidden_face, retained_outfit],
            "reference_images": [private_board],
        },
    }
    launch = AsyncMock(return_value={"status": "failed"})
    body = {
        "init_data": "signed", "gen_id": 42, "source_feed_gen_id": 42,
        "reference_images": [user_face, hidden_face, retained_outfit, private_board],
    }
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(return_value=body))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(
        return_value=(123, {"user": SimpleNamespace(id=7, credits=100)})))
    monkeypatch.setattr(miniapp, "_get_feed_remix_source_card", AsyncMock(return_value=source))
    monkeypatch.setattr(miniapp, "_get_repeat_source_card", AsyncMock(return_value=source))
    monkeypatch.setattr(miniapp, "get_generation_task_payload", AsyncMock(return_value=source_task))
    monkeypatch.setattr(miniapp, "missing_local_upload_sources", lambda _refs: [])
    monkeypatch.setattr(miniapp, "touch_saved_references", AsyncMock())
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _telegram_id: True)
    monkeypatch.setattr(miniapp, "_start_image_generation_task_lazy", launch)

    route = miniapp.miniapp_feed_remix if endpoint == "remix" else miniapp.miniapp_generate_image
    response = await route(_Request(body))

    assert response.status == 500
    expected = [user_face, retained_outfit] if references_visible else [user_face]
    assert launch.await_args.kwargs["reference_images"] == expected
    assert miniapp.touch_saved_references.await_args.args[1] == expected
