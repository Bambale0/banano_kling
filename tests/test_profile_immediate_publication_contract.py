from pathlib import Path

PROFILE_PATH = Path("frontend/miniapp-v0/components/tabs/profile-tab.tsx")
EVENTS_PATH = Path("frontend/miniapp-v0/lib/feed-events.ts")
MINIAPP_PATH = Path("bot/miniapp.py")
MAIN_PATH = Path("bot/main.py")


def test_profile_uses_publication_event_payload_directly() -> None:
    source = PROFILE_PATH.read_text(encoding="utf-8")
    assert "(event as CustomEvent<FeedItem | undefined>).detail" in source
    assert "mergePublication(current, published, 'profile')" in source
    assert "loading && !profileItems.length" in source


def test_pending_publication_is_shared_across_dynamic_chunks() -> None:
    source = EVENTS_PATH.read_text(encoding="utf-8")
    assert "__BANANO_PENDING_PUBLICATION__" in source
    assert (
        "new CustomEvent<FeedItem | undefined>('banano:feed-changed', { detail: item })"
        in source
    )


def test_pending_publication_is_not_injected_into_another_users_profile() -> None:
    source = PROFILE_PATH.read_text(encoding="utf-8")
    foreign_profile_marker = (
        "const result = await fetchProfileFeed("
        "targetReferralCode, PROFILE_FEED_PAGE_SIZE)"
    )
    assert foreign_profile_marker in source

    foreign_profile_block = source.split(foreign_profile_marker, 1)[1].split(
        "} catch (e) {",
        1,
    )[0]
    assert "setItems(result.feed)" in foreign_profile_block
    assert "mergePendingPublication(result.feed, 'profile')" not in foreign_profile_block


def test_private_profile_repeat_merges_only_owner_selected_references() -> None:
    from bot import miniapp

    face = "https://example.test/private-face.png"
    outfit = "https://example.test/selected-outfit.png"
    new_face = "https://example.test/new-face.png"
    source_task = {
        "is_profile_visible": True,
        "feed_references_visible": False,
        "feed_reference_selection": {"images": [outfit], "videos": []},
        "request_data": {"source_reference_images": [face, outfit]},
    }
    private_profile = {
        "is_mine": True,
        "publication_scope": "profile",
        "references_hidden": True,
        "feed_references_visible": False,
        "reference_images": [],
    }

    references, retained = miniapp._merge_remix_image_references(
        private_profile, source_task, [new_face]
    )
    assert references == [new_face, outfit]
    assert retained == 1

    foreign_profile = {**private_profile, "is_mine": False}
    references, retained = miniapp._merge_remix_image_references(
        foreign_profile, source_task, [new_face]
    )
    assert references == [new_face]
    assert retained == 0


def test_result_caption_does_not_reveal_feed_repeat_prompt() -> None:
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert 'getattr(task, "source_feed_gen_id", None)' in source
    assert 'return "<b>Промпт скрыт</b>", "Промпт"' in source
