from unittest.mock import AsyncMock

import pytest

from bot import database, miniapp
from bot.handlers import generation

LEGACY = "https://tanyapi.chillcreative.ru/uploads/synthetic-fixed.png"
CANONICAL = "https://tanyapp.xn--e1aikcel5c5a.online/uploads/synthetic-fixed.png"
OWN = "https://example.test/own-replacement.png"


def test_telegram_slot_merge_accepts_unique_authorized_alias():
    result = generation._merge_repeat_private_reference_slots(
        {"source_reference_images": ["https://example.test/old-person.png", CANONICAL]},
        [OWN], [LEGACY],
    )
    assert result == [OWN, CANONICAL]


@pytest.mark.asyncio
async def test_central_launch_normalizes_private_alias_to_actual_provider_input(monkeypatch):
    author = await database.get_or_create_user(948001)
    viewer = await database.get_or_create_user(948002)
    monkeypatch.setattr(database, "_is_feed_result_url_available", lambda *_args: True)
    await database.add_generation_task(author.id, author.telegram_id, "alias-root", "image", "banana_pro",
        prompt="Synthetic recipe", request_data={"source_reference_images": [LEGACY]})
    await database.complete_video_task("alias-root", "https://example.test/result.png")
    root = await database.share_to_feed("alias-root", author.id, repeat_reference_image_indices=[0])
    provider = AsyncMock(return_value={"task_id": "synthetic-review-provider"})
    monkeypatch.setattr(generation.nano_banana_pro_service, "generate_image", provider)
    monkeypatch.setattr(generation, "_available_reference_images", lambda refs: (refs, []))
    result = await generation._start_image_generation_task(
        user=viewer, telegram_id=viewer.telegram_id, img_service="banana_pro",
        prompt="Synthetic recipe", img_ratio="1:1", reference_images=[OWN, CANONICAL],
        private_repeat_reference_images=[LEGACY], source_feed_gen_id=root["id"], unit_cost=0,
    )
    assert result["status"] == "queued"
    assert provider.await_args.kwargs["image_input"] == [OWN, CANONICAL]
    task = await database.get_generation_task_payload("synthetic-review-provider")
    assert task["request_data"]["private_repeat_reference_images"] == [CANONICAL]
    assert generation._source_reference_images_from_request(task["request_data"]) == [OWN]


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("selected_index", [0, 1])
def test_alias_collision_preserves_exact_selected_image_slot(monkeypatch, private, selected_index):
    selected = [LEGACY, CANONICAL][selected_index]
    payload = {"type": "image", "status": "completed", "is_public_feed": True,
        "feed_reference_selection": {"images": [selected], "videos": []},
        "feed_repeat_reference_selection": {"images": [selected]},
        "request_data": {"source_reference_images": [LEGACY, CANONICAL]}}
    monkeypatch.setattr(database, "_is_feed_result_url_available", lambda *_args: True)
    if private:
        result = miniapp._merge_private_repeat_references(payload, [OWN])
    else:
        result, _ = miniapp._merge_remix_image_references({"is_mine": True}, payload, [OWN])
    assert result == ([LEGACY, OWN] if selected_index == 0 else [OWN, CANONICAL])


def test_explicit_source_occurrences_do_not_collapse_during_owner_merge():
    assert miniapp._merge_image_reference_slots([LEGACY, CANONICAL], [LEGACY, CANONICAL], [LEGACY]) == [LEGACY, CANONICAL]


def test_ambiguous_third_alias_does_not_guess_a_numbered_slot():
    from bot.services.media_input_utils import resolve_reference_source
    with pytest.raises(ValueError, match="Неоднозначный"):
        resolve_reference_source("https://media.chillcreative.ru/uploads/synthetic-fixed.png", [LEGACY, CANONICAL])
    assert resolve_reference_source(LEGACY, [LEGACY, CANONICAL]) == LEGACY
    assert resolve_reference_source("https://external.test/uploads/synthetic-fixed.png", [LEGACY, CANONICAL]) is None


def test_private_reference_alias_cannot_be_restored_as_visible_child_input():
    data = {"source_reference_images": [CANONICAL, OWN], "private_repeat_reference_images": [LEGACY]}
    assert generation._source_reference_images_from_request(data) == [OWN]
