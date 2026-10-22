"""Keep explicit historical video reference selections usable across releases."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database, miniapp
from bot.handlers import miniapp_video_continuity_compat as continuity
from bot.handlers import publication_scope_compat as publication
from bot.video_repeat_reference_contract import (
    foreign_video_repeat_task,
    video_repeat_descriptors,
)


async def legacy_publication():
    owner = await database.get_or_create_user(885101)
    images = [f"https://example.test/legacy-{index}.png" for index in range(4)]
    await database.add_generation_task(
        owner.id, owner.telegram_id, "legacy-selected-video", "video", "seedance_2_5",
        model="seedance_2_5", prompt="Synthetic @Image1 @Image2 @Image3 @Image4",
        request_data={"seedance25_scenario": "multimodal", "reference_images": images},
    )
    await database.complete_video_task("legacy-selected-video", "https://example.test/result.mp4")
    card = await database.share_to_feed(
        "legacy-selected-video", owner.id, references_visible=True,
        reference_image_indices=[2, 3], reference_video_indices=[],
    )
    return owner, images, card


@pytest.mark.asyncio
async def test_legacy_explicit_selection_survives_card_owner_editor_and_launch(monkeypatch):
    owner, images, card = await legacy_publication()
    before = await database.get_generation_task_payload(card["id"])
    public = await database.get_feed_generation_card(card["id"])
    slots = public["repeat_reference_slots"]["images"]
    assert [slot["binding"] for slot in slots] == ["upload", "upload", "fixed", "fixed"]
    assert not any(url in json.dumps(public["repeat_reference_slots"]) for url in images)

    refs = {"images": images, "videos": [], "image_indices": list(range(4)), "video_indices": []}
    assert database.generation_repeat_reference_indices(before, refs) == {"images": [2, 3], "videos": []}
    uploads = ["https://example.test/new-face.png", "https://example.test/new-person.png"]
    request = SimpleNamespace(app={})
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(
        885102, {"user": SimpleNamespace(id=owner.id + 1)})))
    monkeypatch.setattr(miniapp, "_get_repeat_source_card", AsyncMock(return_value=public))
    enriched = await continuity._restore_repeat_request(request, {
        "init_data": "signed", "source_feed_gen_id": card["id"], "reference_images": uploads,
    })
    assert enriched["reference_images"] == uploads + images[2:]
    assert await continuity.verify_video_repeat_before_charge(request) is None
    after = await database.get_generation_task_payload(card["id"])
    assert after["feed_repeat_reference_selection"] == before["feed_repeat_reference_selection"]
    assert after["feed_reference_selection"] == before["feed_reference_selection"]
    await database.share_to_feed(
        "legacy-selected-video", owner.id, references_visible=True,
        reference_image_indices=[2, 3], repeat_reference_image_indices=[], repeat_reference_video_indices=[],
    )
    assert (await continuity.verify_video_repeat_before_charge(request)).status == 400
    revoked = await database.get_feed_generation_card(card["id"])
    assert all(slot["binding"] == "upload" for slot in revoked["repeat_reference_slots"]["images"])


@pytest.mark.asyncio
async def test_withdrawn_legacy_publication_never_restores_reference_consent():
    owner, _images, card = await legacy_publication()
    assert await publication.remove_publication(card["id"], owner.id)
    await database.share_to_feed(
        "legacy-selected-video", owner.id, references_visible=True, reference_image_indices=[2, 3],
    )
    public = await database.get_feed_generation_card(card["id"])
    assert all(slot["binding"] == "upload" for slot in public["repeat_reference_slots"]["images"])


@pytest.mark.parametrize("change", [
    {"feed_references_visible": False},
    {"feed_reference_selection": None},
    {"feed_reference_selection": {"images": [], "videos": []}},
    {"private_recipe": True},
    {"source_feed_gen_id": 42},
    {"feed_repeat_reference_selection": {"version": 1, "images": [], "videos": []}},
])
def test_legacy_compatibility_never_grants_unselected_or_revoked_media(change):
    source = {
        "type": "video", "model": "seedance_2_5", "feed_references_visible": True,
        "feed_reference_selection": {"images": ["https://example.test/fixed.png"], "videos": []},
        "request_data": {"seedance25_scenario": "multimodal", "reference_images": [
            "https://example.test/face.png", "https://example.test/fixed.png",
        ]}, **change,
    }
    assert foreign_video_repeat_task(source)["feed_repeat_reference_selection"] == {
        "version": 1, "images": [], "videos": [],
    }
    descriptor = video_repeat_descriptors(source)
    assert all(slot["binding"] == "upload" for slot in descriptor["images"])
