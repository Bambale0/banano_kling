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


def test_foreign_remix_never_restores_display_only_source_references():
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

    assert references == submitted
    assert retained_count == 0
    assert miniapp._filter_foreign_feed_source_references(
        card,
        task_payload,
        [hidden_face, outfit, *references],
        viewer_telegram_id=123,
    ) == submitted


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
    # Visibility controls preview only. Foreign repeats never inherit source
    # inputs unless the author granted them separately via private repeat consent.
    expected = [user_face]
    assert launch.await_args.kwargs["reference_images"] == expected
    assert miniapp.touch_saved_references.await_args.args[1] == expected


@pytest.mark.parametrize("endpoint", ["remix", "generate"])
@pytest.mark.parametrize("is_owner", [False, True])
@pytest.mark.parametrize("submitted", [[], ["https://neuromixbot.com/uploads/refs/image/99/foreign.jpg"],
                                     ["https://neuromixbot.com/uploads/refs/video/123/clip.mp4"],
                                     ["https://neuromixbot.com/uploads/refs/image/99/foreign.jpg",
                                      "https://neuromixbot.com/uploads/refs/image/123/own.jpg"],
                                     ["https://neuromixbot.com/uploads/refs/image/123/own.jpg"]])
@pytest.mark.parametrize("send_values", [False, True])
@pytest.mark.parametrize("retained_primary", [False, True])
async def test_curated_photo_repeat_requires_explicit_owned_photo_before_billing(
    monkeypatch, endpoint, is_owner, submitted, send_values, retained_primary,
):
    source = {"id": 42, "gen_type": "image", "model": "banana_pro", "is_mine": is_owner}
    task = {"id": 42, "type": "image", "prompt": "Person with a car", "request_data": {}}
    author_face, author_car = "https://example.test/author-face.jpg", "https://example.test/author-car.jpg"
    if retained_primary:
        task.update(status="completed", is_public_feed=True,
                    request_data={"source_reference_images": [author_face, author_car]},
                    feed_repeat_reference_selection={"images": [author_face, author_car]})
        from bot import database
        monkeypatch.setattr(database, "_is_feed_result_url_available", lambda *_args: True)
    choice = "https://neuromixbot.com/uploads/repeat-choices/" + "a" * 32 + ".jpg"
    fields = [{"key": "car", "label": "Машина", "type": "text",
               "image_choices": [{"id": "car", "label": "Машина", "image_url": choice}]}]
    body = {"init_data": "signed", "gen_id": 42, "source_feed_gen_id": 42,
            "reference_images": submitted}
    if send_values:
        body["repeat_user_values"] = {"car": "car"}
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(return_value=body))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(
        return_value=(123, {"user": SimpleNamespace(id=7, credits=100)})))
    monkeypatch.setattr(miniapp, "_get_feed_remix_source_card", AsyncMock(return_value=source))
    monkeypatch.setattr(miniapp, "_get_repeat_source_card", AsyncMock(return_value=source))
    monkeypatch.setattr(miniapp, "get_generation_task_payload", AsyncMock(return_value=task))
    monkeypatch.setattr(miniapp, "_repeat_personalization_allowed", lambda _id: True)
    monkeypatch.setattr(miniapp, "get_repeat_fields", AsyncMock(return_value=fields))
    monkeypatch.setattr(miniapp, "missing_local_upload_sources", lambda _refs: [])
    quote, debit = AsyncMock(return_value=1), AsyncMock(return_value=True)
    launch = AsyncMock(return_value={"status": "queued", "task_id": "synthetic-photo-repeat"})
    monkeypatch.setattr(miniapp, "touch_saved_references", AsyncMock())
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _id: False)
    monkeypatch.setattr(miniapp, "check_can_afford", AsyncMock(return_value=True))
    monkeypatch.setattr(miniapp, "_notify_miniapp_image_task_queued", AsyncMock())
    monkeypatch.setattr(miniapp, "_deliver_miniapp_direct_image_result", AsyncMock())
    monkeypatch.setattr(miniapp, "credit_feed_prompt_repeat", AsyncMock())
    monkeypatch.setattr(miniapp, "get_or_create_user", AsyncMock(return_value=SimpleNamespace(credits=99)))
    monkeypatch.setattr(miniapp, "_resolve_actor_image_unit_cost", quote)
    monkeypatch.setattr(miniapp, "deduct_credits", debit)
    monkeypatch.setattr(miniapp, "_start_image_generation_task_lazy", launch)
    route = miniapp.miniapp_feed_remix if endpoint == "remix" else miniapp.miniapp_generate_image
    response = await route(_Request(body))
    if submitted == ["https://neuromixbot.com/uploads/refs/image/123/own.jpg"]:
        assert response.status == 200, response.text
        outgoing = launch.await_args.kwargs
        assert outgoing["prompt"].startswith(task["prompt"])
        assert outgoing["reference_images"] == submitted + ([author_car] if retained_primary else []) + ([choice] if send_values else [])
        assert author_face not in outgoing["reference_images"]
        assert outgoing["private_repeat_reference_images"] == ([author_car] if retained_primary else [])
        debit.assert_awaited_once_with(123, 1)
        assert task["prompt"] not in response.text
        return
    assert response.status == 400, response.text
    assert "своё фото" in json.loads(response.text)["error"]
    quote.assert_not_awaited()
    debit.assert_not_awaited()
    launch.assert_not_awaited()


async def test_curated_photo_replaced_primary_passes_real_launcher_private_reference_contract(monkeypatch):
    from bot import database
    from bot.handlers import generation

    user = await database.get_or_create_user(123)
    own = "https://neuromixbot.com/uploads/refs/image/123/own.jpg"
    author_face, car = "https://example.test/author-face.jpg", "https://example.test/car.jpg"
    task = {"id": 42, "type": "image", "status": "completed", "is_public_feed": True,
            "feed_repeat_reference_selection": {"images": [author_face, car]},
            "request_data": {"source_reference_images": [author_face, car]}}
    monkeypatch.setattr(database, "_is_feed_result_url_available", lambda *_args: True)
    monkeypatch.setattr(generation, "get_generation_task_payload", AsyncMock(return_value=task))
    monkeypatch.setattr(generation, "_available_reference_images", lambda refs: (refs, []))
    provider = AsyncMock(return_value={"task_id": "synthetic-primary-replacement"})
    monkeypatch.setattr(generation.nano_banana_pro_service, "generate_image", provider)
    references = [own, car]
    private = miniapp._selected_private_repeat_references(task, reference_images=references)
    assert private == [car]
    result = await generation._start_image_generation_task(
        user=user, telegram_id=123, img_service="banana_pro", prompt="Person @Image1 with car @Image2",
        img_ratio="1:1", reference_images=references, private_repeat_reference_images=private,
        unit_cost=1, source_feed_gen_id=42, private_repeat_permission_source_id=42,
        parent_generation_id=42, action_type="remix",
    )
    assert result["status"] == "queued", result
    assert provider.await_args.kwargs["image_input"] == references
    stored = await database.get_generation_task_payload("synthetic-primary-replacement")
    assert stored["request_data"]["private_repeat_reference_images"] == [car]
