"""Author publication must not save a repeat that its consumer cannot prepare."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database, miniapp
from bot import repeat_personalization as rp
from bot.handlers.publication_scope_compat import _miniapp_generation_share_scoped

IMAGES = [f"https://example.test/source-{i}.jpg" for i in range(3)]


def fields(indices):
    return [{
        "key": key, "label": label, "image_slot_index": index,
        "image_choices": [{
            "id": key, "label": label,
            "image_url": f"https://neuromixbot.com/uploads/repeat-choices/{letter * 32}.jpg",
        }],
    } for key, label, index, letter in zip(
        ["car", "outfit"], ["Машина", "Одежда"], indices, ["a", "b"],
    )]


@pytest.mark.parametrize("scope", ["feed", "profile"])
@pytest.mark.parametrize("indices,retained,expected", [
    ([0, 0], [], 400),  # two groups cannot replace the same photo
    ([1, 2], [1, 2], 400),  # a source cannot be fixed and replaceable
    ([1, 99], [], 400),
    ([1, 2], [], 200),  # the first photo stays available for the visitor
])
async def test_author_can_only_publish_preparable_catalog_slots(
    monkeypatch, scope, indices, retained, expected,
):
    monkeypatch.setenv(rp.PUBLIC_FEATURE_FLAG, "1")
    owner = await database.get_or_create_user(991701)
    await database.add_generation_task(
        owner.id, owner.telegram_id, "catalog-integrity-source", "video", "seedance_2_5",
        model="seedance_2_5", prompt="Person @Image1, car @Image2, outfit @Image3.",
        request_data={"seedance25_scenario": "multimodal", "reference_images": IMAGES},
    )
    await database.complete_video_task(
        "catalog-integrity-source", "https://example.test/result.mp4",
    )
    card = await database.share_to_feed(
        "catalog-integrity-source", owner.id, repeat_reference_image_indices=[],
    )
    source_id = card["id"]
    before = await database.get_generation_task_payload(source_id)
    body = {
        "task_id": "catalog-integrity-source", "publication_scope": scope,
        "repeat_user_fields": fields(indices),
        "repeat_reference_image_indices": retained, "repeat_reference_video_indices": [],
    }
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(return_value=body))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(
        return_value=(owner.telegram_id, {"user": owner}),
    ))
    request = SimpleNamespace(app={"bot": SimpleNamespace(get_me=AsyncMock(
        return_value=SimpleNamespace(username="test"),
    ))})
    response = await _miniapp_generation_share_scoped(miniapp, request)
    assert response.status == expected, response.text
    if expected == 400:
        assert await rp.get_repeat_fields(source_id) == []
        after = await database.get_generation_task_payload(source_id)
        for key in ["is_public_feed", "is_profile_visible", "feed_repeat_reference_selection"]:
            assert after[key] == before[key]
        return
    public = await database.get_profile_generation_card(source_id)
    await miniapp._attach_repeat_personalization([public], telegram_id=991702)
    assert public["repeat_reference_slots"]["available"] is True
    assert [s["binding"] for s in public["repeat_reference_slots"]["images"]] == [
        "upload", "choice", "choice",
    ]
    assert all(url not in json.dumps(public) for url in IMAGES)


async def test_consent_only_edit_cannot_break_existing_catalog(monkeypatch):
    monkeypatch.setenv(rp.PUBLIC_FEATURE_FLAG, "1")
    owner = await database.get_or_create_user(991701)
    await database.add_generation_task(
        owner.id, owner.telegram_id, "catalog-consent-source", "video", "seedance_2_5",
        model="seedance_2_5", prompt="Person @Image1, car @Image2, outfit @Image3.",
        request_data={"seedance25_scenario": "multimodal", "reference_images": IMAGES},
    )
    await database.complete_video_task(
        "catalog-consent-source", "https://example.test/result.mp4",
    )
    card = await database.share_to_feed(
        "catalog-consent-source", owner.id, repeat_reference_image_indices=[],
    )
    saved = rp.normalize_repeat_fields(fields([1, 2]), prompt="source")
    await rp.save_repeat_fields(card["id"], saved, actor_telegram_id=owner.telegram_id)
    before = await database.get_generation_task_payload(card["id"])
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(return_value={
        "task_id": "catalog-consent-source", "repeat_reference_image_indices": [1],
    }))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(
        return_value=(owner.telegram_id, {"user": owner}),
    ))
    request = SimpleNamespace(app={"bot": SimpleNamespace(get_me=AsyncMock(
        return_value=SimpleNamespace(username="test"),
    ))})
    response = await _miniapp_generation_share_scoped(miniapp, request)
    assert response.status == 400, response.text
    assert await rp.get_repeat_fields(card["id"]) == saved
    after = await database.get_generation_task_payload(card["id"])
    assert after["feed_repeat_reference_selection"] == before["feed_repeat_reference_selection"]

@pytest.mark.parametrize("scope", ["feed", "profile"])
async def test_concurrent_author_edits_cannot_combine_incompatible_catalog_and_consent(monkeypatch, scope):
    import asyncio

    from bot.handlers import publication_scope_compat as publication

    monkeypatch.setenv(rp.PUBLIC_FEATURE_FLAG, "1")
    owner = await database.get_or_create_user(991701)
    await database.add_generation_task(
        owner.id, owner.telegram_id, "catalog-concurrent-source", "video", "seedance_2_5",
        model="seedance_2_5", prompt="Person @Image1, car @Image2, outfit @Image3.",
        request_data={"seedance25_scenario": "multimodal", "reference_images": IMAGES},
    )
    await database.complete_video_task("catalog-concurrent-source", "https://example.test/result.mp4")
    card = await database.share_to_feed(
        "catalog-concurrent-source", owner.id, repeat_reference_image_indices=[],
    )
    entered_a, finished_b = asyncio.Event(), asyncio.Event()
    target = "share_to_feed_scoped" if scope == "feed" else "share_to_profile"
    original_share = getattr(publication, target)

    async def interleaved_share(*args, **kwargs):
        if kwargs["repeat_reference_image_indices"] == [2]:
            entered_a.set()
            await asyncio.wait_for(finished_b.wait(), timeout=5)
        result = await original_share(*args, **kwargs)
        if kwargs["repeat_reference_image_indices"] == [1]:
            finished_b.set()
        return result

    monkeypatch.setattr(publication, target, interleaved_share)

    async def payload(request):
        return request.payload

    monkeypatch.setattr(miniapp, "_miniapp_payload", payload)
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(
        return_value=(owner.telegram_id, {"user": owner}),
    ))
    app = {"bot": SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="test")))}

    def request(slot, retained):
        return SimpleNamespace(app=app, payload={
            "task_id": "catalog-concurrent-source", "publication_scope": scope,
            "repeat_user_fields": fields([slot]),
            "repeat_reference_image_indices": retained, "repeat_reference_video_indices": [],
        })

    first = asyncio.create_task(_miniapp_generation_share_scoped(miniapp, request(1, [2])))
    await asyncio.wait_for(entered_a.wait(), timeout=5)
    second = await _miniapp_generation_share_scoped(miniapp, request(2, [1]))
    first = await first
    assert [first.status, second.status] == [400, 200]
    saved = await rp.get_repeat_fields(card["id"])
    assert saved[0]["image_slot_index"] == 2
    public = await database.get_profile_generation_card(card["id"])
    await miniapp._attach_repeat_personalization([public], telegram_id=991702)
    assert public["repeat_reference_slots"]["available"] is True
    assert [s["binding"] for s in public["repeat_reference_slots"]["images"]] == [
        "upload", "fixed", "choice",
    ]

@pytest.mark.parametrize("scope", ["feed", "profile"])
async def test_publication_holds_catalog_lock_through_media_persistence(monkeypatch, scope):
    import asyncio

    from bot.services import feed_persist

    monkeypatch.setenv(rp.PUBLIC_FEATURE_FLAG, "1")
    owner = await database.get_or_create_user(991701)
    await database.add_generation_task(
        owner.id, owner.telegram_id, "catalog-locked-source", "video", "seedance_2_5",
        model="seedance_2_5", prompt="Person @Image1, car @Image2, outfit @Image3.",
        request_data={"seedance25_scenario": "multimodal", "reference_images": IMAGES},
    )
    await database.complete_video_task("catalog-locked-source", "https://example.test/result.mp4")
    card = await database.share_to_feed(
        "catalog-locked-source", owner.id, repeat_reference_image_indices=[],
    )
    persistence_entered, release_persistence = asyncio.Event(), asyncio.Event()
    second_save_entered, second_saved = asyncio.Event(), asyncio.Event()
    original_persist = feed_persist.persist_feed_result_urls
    original_save = miniapp.save_repeat_fields
    pause_once = True

    async def persist(*args, **kwargs):
        nonlocal pause_once
        if pause_once:
            pause_once = False
            persistence_entered.set()
            await asyncio.wait_for(release_persistence.wait(), timeout=5)
        return await original_persist(*args, **kwargs)

    async def save(generation_id, new_fields, **kwargs):
        is_second = new_fields[0]["image_slot_index"] == 2
        if is_second:
            second_save_entered.set()
        result = await original_save(generation_id, new_fields, **kwargs)
        if is_second:
            second_saved.set()
        return result

    monkeypatch.setattr(feed_persist, "persist_feed_result_urls", persist)
    monkeypatch.setattr(miniapp, "save_repeat_fields", save)

    async def payload(request):
        return request.payload

    monkeypatch.setattr(miniapp, "_miniapp_payload", payload)
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(
        return_value=(owner.telegram_id, {"user": owner}),
    ))
    app = {"bot": SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="test")))}

    def request(slot, retained):
        return SimpleNamespace(app=app, payload={
            "task_id": "catalog-locked-source", "publication_scope": scope,
            "repeat_user_fields": fields([slot]),
            "repeat_reference_image_indices": retained, "repeat_reference_video_indices": [],
        })

    first = asyncio.create_task(_miniapp_generation_share_scoped(miniapp, request(1, [2])))
    await asyncio.wait_for(persistence_entered.wait(), timeout=5)
    second = asyncio.create_task(_miniapp_generation_share_scoped(miniapp, request(2, [1])))
    await asyncio.wait_for(second_save_entered.wait(), timeout=5)
    try:
        await asyncio.wait_for(second_saved.wait(), timeout=0.3)
    except TimeoutError:
        pass
    was_serialized = not second_saved.is_set()
    release_persistence.set()
    replies = await asyncio.gather(first, second)
    assert was_serialized, "another mapping committed after validation but before publication"
    assert [reply.status for reply in replies] == [200, 200]
    public = await database.get_profile_generation_card(card["id"])
    await miniapp._attach_repeat_personalization([public], telegram_id=991702)
    assert public["repeat_reference_slots"]["available"] is True
