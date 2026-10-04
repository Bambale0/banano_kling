"""Public Mini App privacy boundaries, using only synthetic task data."""
import json
from unittest.mock import AsyncMock

import pytest

from bot import database, miniapp, trend_task_privacy


class _Request:
    def __init__(self, task_id):
        self.app = {}
        self.task_id = task_id

    async def json(self):
        return {"init_data": "signed", "task_id": self.task_id}


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["feed", "profile"])
@pytest.mark.parametrize("references_visible", [False, True])
async def test_task_detail_hides_legacy_child_recipe_but_preserves_owner_inputs(
    monkeypatch, scope, references_visible
):
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(trend_task_privacy, "DATABASE_PATH", database.DATABASE_PATH)
    author = await database.get_or_create_user(810001)
    viewer = await database.get_or_create_user(810002)
    author_reference = "https://example.test/author-private-face.png"
    viewer_reference = "https://example.test/viewer-face.png"
    original_request = {
        "reference_images": [author_reference],
        "source_reference_images": [author_reference],
        "img_quality": "2K",
    }
    await database.add_generation_task(
        author.id, author.telegram_id, "privacy-source", "image", "banana_pro",
        prompt="Synthetic source recipe", request_data=original_request,
    )
    await database.complete_video_task(
        "privacy-source", "https://example.test/source-result.png"
    )
    source = await database.share_to_feed(
        "privacy-source", author.id,
        references_visible=references_visible, publication_scope=scope,
    )
    assert source is not None
    # Simulate a pre-fix child with copied references and a source recipe.
    await database.add_generation_task(
        viewer.id, viewer.telegram_id, "legacy-child", "image", "banana_pro",
        source_feed_gen_id=source["id"], parent_generation_id=source["id"],
        action_type="remix", prompt="Synthetic source recipe",
        request_data={
            **original_request,
            "reference_images": [viewer_reference, author_reference],
            "source_reference_images": [viewer_reference, author_reference],
            "prompt": "Synthetic source recipe",
            "effective_prompt": "Synthetic provider recipe",
        },
    )
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(
        return_value=(viewer.telegram_id, {"user": viewer})))

    response = await miniapp.miniapp_task_detail(_Request("legacy-child"))

    assert response.status == 200
    task = json.loads(response.text)["task"]
    assert author_reference not in response.text
    assert "Synthetic source recipe" not in response.text
    assert "Synthetic provider recipe" not in response.text
    assert "publication_reference_images" not in task
    assert "feed_reference_selection" not in task
    assert task["prompt_hidden"] is True
    assert task["request_data"]["img_quality"] == "2K"
    # This is the existing browser middleware contract for remix children:
    # the entire provider recipe is private, including the child's own uploads.
    assert viewer_reference not in response.text

    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(
        return_value=(author.telegram_id, {"user": author})))
    owner_response = await miniapp.miniapp_task_detail(_Request("privacy-source"))
    owner_task = json.loads(owner_response.text)["task"]
    assert owner_response.status == 200
    assert owner_task["request_data"]["reference_images"] == [author_reference]
    assert owner_task["publication_reference_images"] == [author_reference]
    # Response redaction must never delete private inputs needed internally.
    persisted = await database.get_generation_task_payload("legacy-child")
    assert persisted["request_data"]["reference_images"] == [
        viewer_reference, author_reference
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["feed", "profile"])
@pytest.mark.parametrize("legacy", [False, True])
async def test_publication_visibility_controls_repeat_and_withdrawal(scope, legacy):
    from bot import db as db_backend
    from bot.handlers import publication_scope_compat as publication_scope

    author = await database.get_or_create_user(820001)
    viewer = await database.get_or_create_user(820002)
    hidden_face = "https://example.test/first-source-face.png"
    selected_outfit = "https://example.test/selected-outfit.png"
    user_face = "https://example.test/second-user-face.png"
    await database.add_generation_task(
        author.id, author.telegram_id, "publication-source", "image", "banana_pro",
        prompt="Synthetic clothing reference",
        request_data={"source_reference_images": [hidden_face, selected_outfit]},
    )
    await database.complete_video_task(
        "publication-source", "https://example.test/public-result.png"
    )
    owner_card = await database.share_to_feed(
        "publication-source", author.id, references_visible=True,
        reference_image_indices=[1], publication_scope=scope,
    )
    if legacy:
        # Pre-selection rows used visibility as the all-or-nothing control.
        async with db_backend.connect(database.DATABASE_PATH) as connection:
            await connection.execute(
                "UPDATE generation_tasks SET feed_reference_selection = NULL WHERE id = ?",
                (owner_card["id"],),
            )
            await connection.commit()
    get_card = (
        database.get_feed_generation_card
        if scope == "feed"
        else database.get_profile_generation_card
    )
    source = await get_card(owner_card["id"], viewer_user_id=viewer.id)
    payload = await database.get_generation_task_payload(owner_card["id"])
    references, _ = miniapp._merge_remix_image_references(source, payload, [user_face])
    # Publication visibility is display-only for the owner. Foreign viewers do
    # not receive source URLs and therefore cannot inherit them client-side.
    assert references == [user_face]
    assert miniapp._filter_foreign_feed_source_references(
        source, payload, [hidden_face, selected_outfit, *references], viewer_telegram_id=viewer.telegram_id
    ) == [user_face]

    # Hiding references must override a previously stored selection/card.
    await database.share_to_feed(
        "publication-source", author.id, references_visible=False,
        publication_scope=scope,
    )
    hidden_payload = await database.get_generation_task_payload(owner_card["id"])
    hidden_refs, _ = miniapp._merge_remix_image_references(source, hidden_payload, [user_face])
    assert hidden_refs == [user_face]
    assert miniapp._filter_foreign_feed_source_references(
        source, hidden_payload, [hidden_face, selected_outfit, user_face],
        viewer_telegram_id=viewer.telegram_id,
    ) == [user_face]

    # Owner private inputs are still intact and reusable after hiding.
    own_refs = miniapp._filter_foreign_feed_source_references(
        {"is_mine": True}, hidden_payload, [hidden_face, selected_outfit],
        viewer_telegram_id=author.telegram_id,
    )
    assert own_refs == [hidden_face, selected_outfit]

    await database.share_to_feed(
        "publication-source", author.id, references_visible=True,
        publication_scope=scope,
    )
    # In production, removal from discovery keeps the publication on the
    # profile. It is still shared; only remove_publication withdraws it fully.
    assert await publication_scope.remove_from_feed_scoped(owner_card["id"], author.id)
    profile_payload = await database.get_generation_task_payload(owner_card["id"])
    assert not profile_payload["is_public_feed"]
    assert profile_payload["is_profile_visible"]
    profile_refs, _ = miniapp._merge_remix_image_references(
        source, profile_payload, [user_face]
    )
    assert profile_refs == [user_face]

    assert await publication_scope.remove_publication(owner_card["id"], author.id)
    withdrawn_payload = await database.get_generation_task_payload(owner_card["id"])
    withdrawn_refs, _ = miniapp._merge_remix_image_references(
        source, withdrawn_payload, [user_face]
    )
    assert withdrawn_refs == [user_face]
    assert await database.get_profile_generation_card(
        owner_card["id"], viewer_user_id=viewer.id
    ) is None


@pytest.mark.asyncio
async def test_task_detail_privacy_lookup_failure_is_fail_closed(monkeypatch):
    async def broken_lookup(_task_ids):
        raise RuntimeError("synthetic lookup failure")

    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(123, {})))
    monkeypatch.setattr(miniapp, "_fetch_task_detail", AsyncMock(return_value={
        "task_id": "legacy-child",
        "request_data": {"reference_images": ["https://example.test/private.png"]},
        "publication_reference_images": ["https://example.test/private.png"],
    }))
    monkeypatch.setattr(trend_task_privacy, "_protected_task_ids", broken_lookup)

    response = await miniapp.miniapp_task_detail(_Request("legacy-child"))

    assert response.status == 200
    assert "https://example.test/private.png" not in response.text
    assert json.loads(response.text)["task"]["prompt_hidden"] is True


@pytest.mark.asyncio
async def test_foreign_repeat_does_not_inherit_references_through_legacy_child():
    from bot import db as db_backend

    author = await database.get_or_create_user(830001)
    viewer = await database.get_or_create_user(830002)
    inherited_reference = "https://example.test/ancestor-reference.png"
    user_reference = "https://example.test/new-user-reference.png"
    await database.add_generation_task(
        author.id, author.telegram_id, "root-source", "image", "banana_pro",
        prompt="Synthetic root recipe",
    )
    root = await database.get_generation_task_payload("root-source")
    await database.add_generation_task(
        author.id, author.telegram_id, "legacy-published-child", "image", "banana_pro",
        prompt="Synthetic inherited recipe", source_feed_gen_id=root["id"],
        action_type="remix",
        request_data={"source_reference_images": [inherited_reference]},
    )
    await database.complete_video_task(
        "legacy-published-child", "https://example.test/child-result.png"
    )
    # Modern share rejects remix children. Exercise an already-published legacy row.
    async with db_backend.connect(database.DATABASE_PATH) as connection:
        await connection.execute(
            """UPDATE generation_tasks
               SET is_public_feed = 1, is_profile_visible = 1,
                   feed_references_visible = 1, feed_reference_selection = ?
               WHERE task_id = ?""",
            (json.dumps({"images": [inherited_reference], "videos": []}),
             "legacy-published-child"),
        )
        await connection.commit()
    payload = await database.get_generation_task_payload("legacy-published-child")
    card = await database.get_feed_generation_card(payload["id"], viewer_user_id=viewer.id)

    assert card["reference_images"] == []
    references, retained_count = miniapp._merge_remix_image_references(
        card, payload, [user_reference]
    )
    assert references == [user_reference]
    assert retained_count == 0
    assert miniapp._filter_foreign_feed_source_references(
        card, payload, [user_reference, inherited_reference],
        viewer_telegram_id=viewer.telegram_id,
    ) == [user_reference]


@pytest.mark.asyncio
async def test_public_viewer_never_receives_raw_reference_urls_even_when_author_enables_them():
    author = await database.get_or_create_user(830101)
    viewer = await database.get_or_create_user(830102)
    face = "https://example.test/private-face.png"
    outfit = "https://example.test/private-outfit.png"
    await database.add_generation_task(
        author.id,
        author.telegram_id,
        "owner-visible-public-hidden-refs",
        "image",
        "banana_pro",
        prompt="portrait",
        request_data={"source_reference_images": [face, outfit]},
    )
    await database.complete_video_task(
        "owner-visible-public-hidden-refs",
        "https://example.test/result.png",
    )
    owner_card = await database.share_to_feed(
        "owner-visible-public-hidden-refs",
        author.id,
        references_visible=True,
        reference_image_indices=[0, 1],
    )
    assert owner_card is not None
    assert owner_card["reference_images"] == [face, outfit]

    public_card = await database.get_feed_generation_card(
        owner_card["id"],
        viewer_user_id=viewer.id,
    )
    assert public_card is not None
    assert public_card["reference_images"] == []
    assert public_card["reference_videos"] == []
    assert public_card["references_count"] == 0
    assert face not in json.dumps(public_card)
    assert outfit not in json.dumps(public_card)


@pytest.mark.asyncio
async def test_video_owner_detail_recovers_legacy_start_image_and_video_references(monkeypatch):
    from bot.handlers import publication_scope_compat as publication_scope

    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    publication_scope._SCHEMA_READY_PATHS.discard(str(database.DATABASE_PATH))
    await publication_scope._ensure_publication_scope_schema()
    author = await database.get_or_create_user(830103)
    start_image = "https://example.test/outfit.png"
    motion_video = "https://example.test/motion.mp4"
    await database.add_generation_task(
        author.id,
        author.telegram_id,
        "legacy-video-reference-detail",
        "video",
        "seedance_2",
        prompt="look",
        request_data={
            "reference_images": [],
            "v_image_url": start_image,
            "v_reference_videos": [motion_video],
        },
    )
    await database.complete_video_task(
        "legacy-video-reference-detail",
        "https://example.test/result.mp4",
    )

    detail = await miniapp._fetch_task_detail(
        author.telegram_id,
        "legacy-video-reference-detail",
    )
    assert detail is not None
    assert detail["publication_reference_images"] == [start_image]
    assert detail["publication_reference_videos"] == [motion_video]
    assert detail["publication_reference_image_indices"] == [0]
    assert detail["publication_reference_video_indices"] == [0]
