"""Stable unit tests for database helpers."""

import json
import os
from unittest.mock import AsyncMock

from bot import db as db_backend
import pytest

import bot.database as database
from bot.services.preset_manager import PresetManager
from bot.services.feed_persist import persist_feed_result_urls


class FakeConnection:
    def __init__(self):
        self.execute = AsyncMock()
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_feed_persistence_downloads_non_ephemeral_photo_when_required(
    monkeypatch,
):
    expected = "https://test.example.com/uploads/feed/downloaded.png"
    download = AsyncMock(return_value=expected)
    monkeypatch.setattr("bot.services.feed_persist.download_to_local", download)

    persisted = await persist_feed_result_urls(
        ["https://permanent-provider.example/result.png"],
        require_local=True,
    )

    assert persisted == [expected]
    download.assert_awaited_once_with(
        "https://permanent-provider.example/result.png"
    )


@pytest.mark.asyncio
async def test_complete_video_task_marks_completed_with_result_url(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(database.db_backend, "connect", lambda *_args, **_kwargs: conn)
    credit = AsyncMock()
    monkeypatch.setattr(
        database, "_credit_feed_repeat_on_webhook_completion", credit
    )

    result = await database.complete_video_task("task-ok", "http://result.url")

    assert result is True
    sql, params = conn.execute.await_args.args
    assert "UPDATE generation_tasks" in sql
    assert params == ("completed", "http://result.url", "task-ok", "task-ok")
    conn.commit.assert_awaited_once()
    credit.assert_awaited_once_with("task-ok")


@pytest.mark.asyncio
async def test_complete_video_task_marks_failed_without_result_url(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(database.db_backend, "connect", lambda *_args, **_kwargs: conn)
    credit = AsyncMock()
    monkeypatch.setattr(
        database, "_credit_feed_repeat_on_webhook_completion", credit
    )

    result = await database.complete_video_task("task-fail", None)

    assert result is True
    sql, params = conn.execute.await_args.args
    assert "UPDATE generation_tasks" in sql
    assert params == ("failed", None, "task-fail", "task-fail")
    conn.commit.assert_awaited_once()
    credit.assert_not_awaited()


class FakeCursor:
    def __init__(self, row):
        self._row = row

    async def fetchone(self):
        return self._row


@pytest.mark.asyncio
async def test_webhook_completion_skips_tasks_without_feed_source(monkeypatch):
    conn = FakeConnection()
    conn.execute = AsyncMock(return_value=FakeCursor(None))
    monkeypatch.setattr(database.db_backend, "connect", lambda *_args, **_kwargs: conn)
    credit_repeat = AsyncMock(return_value=False)
    monkeypatch.setattr(database, "credit_feed_prompt_repeat", credit_repeat)

    await database._credit_feed_repeat_on_webhook_completion("task-plain")

    credit_repeat.assert_not_awaited()


@pytest.mark.asyncio
async def test_webhook_completion_credits_feed_repeat(monkeypatch):
    row = {
        "task_id": "task-feed-repeat",
        "user_id": 4242,
        "cost": 2.5,
        "source_feed_gen_id": 186039,
    }
    conn = FakeConnection()
    conn.execute = AsyncMock(return_value=FakeCursor(row))
    monkeypatch.setattr(database.db_backend, "connect", lambda *_args, **_kwargs: conn)
    credit_repeat = AsyncMock(return_value=True)
    monkeypatch.setattr(database, "credit_feed_prompt_repeat", credit_repeat)

    await database._credit_feed_repeat_on_webhook_completion("task-feed-repeat")

    credit_repeat.assert_awaited_once_with(
        186039,
        4242,
        repeat_task_id="task-feed-repeat",
        credits_spent=2.5,
    )


@pytest.mark.asyncio
async def test_webhook_completion_swallows_errors(monkeypatch):
    conn = FakeConnection()
    conn.execute = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(database.db_backend, "connect", lambda *_args, **_kwargs: conn)

    # Helper must never break the completion flow
    await database._credit_feed_repeat_on_webhook_completion("task-boom")


@pytest.mark.asyncio
async def test_prompt_repeat_reward_dedupes_by_repeat_task_id(monkeypatch):
    conn = FakeConnection()

    async def fake_fetchone():
        return (1,)

    conn.fetchone = fake_fetchone
    monkeypatch.setattr(database.db_backend, "connect", lambda *_args, **_kwargs: conn)

    result = await database._credit_prompt_repeat_reward_in_db(
        conn,
        author_id=15943,
        repeater_id=20100,
        source_type="feed",
        source_id=186039,
        repeat_task_id="61b1d7f5b6e8abba98d3219eb0bbf8b5",
        credits_spent=2.5,
    )

    assert result is False
    # Only the dedup SELECT must run — no INSERT, no balance UPDATE
    assert conn.execute.await_count == 1
    sql = conn.execute.await_args.args[0]
    assert "prompt_repeat_events" in sql
    conn.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_master_partner_user_uses_master_telegram_id(monkeypatch):
    expected_user = object()
    get_or_create_user = AsyncMock(return_value=expected_user)
    monkeypatch.setattr(database, "get_or_create_user", get_or_create_user)

    user = await database.get_master_partner_user()

    assert user is expected_user
    get_or_create_user.assert_awaited_once_with(database.MASTER_PARTNER_TELEGRAM_ID)


@pytest.mark.asyncio
async def test_get_task_by_id_accepts_numeric_generation_id(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "tasks.db"))

    await database.init_db()
    user = await database.get_or_create_user(123001)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "provider-task-123",
        "image",
        "miniapp_image",
        model="banana_pro",
        aspect_ratio="1:1",
        prompt="Prompt",
        cost=2,
    )
    await database.complete_video_task("provider-task-123", "https://example.com/result.png")

    by_task_id = await database.get_task_by_id("provider-task-123")
    by_numeric_id = await database.get_task_by_id(str(by_task_id.id))

    assert by_task_id is not None
    assert by_numeric_id is not None
    assert by_numeric_id.id == by_task_id.id
    assert by_numeric_id.task_id == "provider-task-123"


@pytest.mark.asyncio
async def test_complete_video_task_accepts_task_id_alias(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "tasks.db"))

    await database.init_db()
    user = await database.get_or_create_user(123002)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "provider-task-456",
        "video",
        "miniapp_video",
        model="grok_imagine",
        aspect_ratio="9:16",
        prompt="Prompt",
        cost=9,
        request_data={"task_id_aliases": ["local-task-456"]},
    )

    await database.complete_video_task("local-task-456", "https://example.com/result.mp4")
    task = await database.get_task_by_id("provider-task-456")

    assert task is not None
    assert task.status == "completed"
    assert task.result_url == "https://example.com/result.mp4"


@pytest.mark.asyncio
async def test_save_user_channel_url_normalizes_and_rejects_non_telegram_links(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "channel.db"))

    await database.init_db()
    user = await database.get_or_create_user(123456)

    saved = await database.save_user_channel_url(user.telegram_id, "@my_channel")
    assert saved == "https://t.me/my_channel"

    updated = await database.get_or_create_user(user.telegram_id)
    assert updated.channel_url == "https://t.me/my_channel"

    with pytest.raises(ValueError):
        await database.save_user_channel_url(user.telegram_id, "https://example.com/my_channel")

    cleared = await database.save_user_channel_url(user.telegram_id, "")
    assert cleared == ""
    updated = await database.get_or_create_user(user.telegram_id)
    assert updated.channel_url is None


@pytest.mark.asyncio
async def test_channel_subscription_required_setting_roundtrip():
    assert await database.is_channel_subscription_required() is False

    assert await database.set_channel_subscription_required(
        True,
        updated_by_telegram_id=123456,
    )
    assert await database.is_channel_subscription_required() is True

    assert await database.set_channel_subscription_required(False)
    assert await database.is_channel_subscription_required() is False


@pytest.mark.asyncio
async def test_referral_purchase_notification_setting_roundtrip():
    settings = await database.get_user_settings(555002)
    assert settings["referral_purchase_notifications_enabled"] is True

    assert await database.save_user_settings(
        555002,
        referral_purchase_notifications_enabled=False,
    )
    settings = await database.get_user_settings(555002)
    assert settings["referral_purchase_notifications_enabled"] is False

    assert await database.save_user_settings(
        555002,
        referral_purchase_notifications_enabled=True,
    )
    settings = await database.get_user_settings(555002)
    assert settings["referral_purchase_notifications_enabled"] is True


@pytest.mark.asyncio
async def test_promo_code_redemption_tracks_repeatable_topup_bonus():
    user = await database.get_or_create_user(555001)
    promo = await database.create_promo_code(
        "maria",
        partner_name="Мария",
        created_by_telegram_id=123456,
    )

    assert promo is not None
    assert promo.code == "MARIA"
    assert database.get_promo_bonus_for_credits(25) == 5
    assert database.get_promo_bonus_for_credits(15) == 0

    created = await database.create_transaction(
        order_id="promo-order-1",
        user_id=user.id,
        payment_id="pay-1",
        provider="yookassa",
        credits=30,
        amount_rub=250,
        status="completed",
        promo_code_id=promo.id,
        promo_code=promo.code,
        promo_bonus_credits=5,
    )
    assert created is True

    transaction = await database.get_transaction_by_order("promo-order-1")
    assert transaction.promo_code == "MARIA"
    assert transaction.promo_bonus_credits == 5

    first_record = await database.record_promo_redemption(transaction)
    second_record = await database.record_promo_redemption(transaction)

    assert first_record["inserted"] is True
    assert second_record["inserted"] is False

    details = await database.get_promo_code_details(promo.id)
    assert details["promo"]["usage_count"] == 1
    assert details["promo"]["total_bonus_credits"] == 5
    assert details["redemptions"][0]["telegram_id"] == user.telegram_id


def test_video_quality_costs_scale_with_selected_resolution(tmp_path):
    price_path = tmp_path / "price.json"
    price_path.write_text(
        json.dumps(
            {
                "packages": [],
                "costs_reference": {
                    "image_models": {},
                    "video_models": {
                        "veo3_fast": {
                            "base": 15,
                            "quality_costs": {
                                "720p": 2.5,
                                "1080p": 3.5,
                                "4k": 5,
                            },
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    manager = PresetManager(
        presets_path=str(tmp_path / "missing_presets.json"),
        price_path=str(price_path),
    )

    assert manager.get_video_cost_with_quality("veo3_fast", 6, "720p") == 15
    assert manager.get_video_cost_with_quality("veo3_fast", 6, "1080p") == 21
    assert manager.get_video_cost_with_quality("veo3_fast", 6, "4k") == 30


@pytest.mark.asyncio
async def test_admin_prompt_listing_includes_status_counts_author_and_pages():
    user = await database.get_or_create_user(100012)
    await database.update_user_profile(
        user.telegram_id,
        username="prompt_author",
        first_name="Prompt",
        last_name="Author",
    )

    created_ids = []
    for index in range(12):
        prompt = await database.create_prompt(
            author_id=user.id,
            prompt_text=f"Prompt text {index}",
            title=f"Prompt {index}",
        )
        created_ids.append(prompt["id"])

    approved = await database.approve_prompt(created_ids[0])

    stats = await database.get_admin_prompt_stats()
    first_page = await database.get_admin_prompts("pending", limit=10, offset=0)
    second_page = await database.get_admin_prompts("pending", limit=10, offset=10)
    details = await database.get_admin_prompt_details(created_ids[-1])

    pending_ids = created_ids[1:]
    assert approved["status"] == "approved"
    assert stats["total"] == 12
    assert stats["pending"] == 11
    assert stats["approved"] == 1
    assert [item["id"] for item in first_page] == list(reversed(pending_ids[1:]))
    assert [item["id"] for item in second_page] == [pending_ids[0]]
    assert details["author_telegram_id"] == user.telegram_id
    assert details["author_username"] == "prompt_author"


@pytest.mark.asyncio
async def test_admin_prompt_moderation_syncs_source_generation_flag():
    user = await database.get_or_create_user(10007)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "library-sync-image",
        "image",
        "miniapp_image",
        model="banana_pro",
        aspect_ratio="1:1",
        prompt="Studio portrait with clean light",
        cost=2,
    )
    await database.complete_video_task(
        "library-sync-image", "https://example.com/library-sync.png"
    )
    await database.share_to_library("library-sync-image", user.id)
    prompt = (await database.get_author_prompts(user.id))[0]

    rejected = await database.reject_prompt(prompt["id"], "Needs cleanup")
    rejected_payload = await database.get_generation_task_payload(
        "library-sync-image", user_id=user.id
    )
    restored = await database.approve_prompt(prompt["id"])
    restored_payload = await database.get_generation_task_payload(
        "library-sync-image", user_id=user.id
    )

    assert rejected["status"] == "rejected"
    assert bool(rejected_payload["is_prompt_library"]) is False
    assert restored["status"] == "approved"
    assert bool(restored_payload["is_prompt_library"]) is True


@pytest.mark.asyncio
async def test_pruned_saved_reference_file_is_deferred_to_orphan_cleanup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "refs.db"))
    monkeypatch.setattr(database, "SAVED_REFERENCES_MAX_PER_KIND", 2)

    async def noop_invalidate(_telegram_id):
        return None

    monkeypatch.setattr(database, "_invalidate_saved_reference_cache", noop_invalidate)

    await database.init_db()

    reference_paths = []
    for name in ("old", "middle", "new"):
        path = (
            tmp_path
            / "static"
            / "uploads"
            / "refs"
            / "image"
            / "12345"
            / "202605"
            / f"{name}.png"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode("utf-8"))
        reference_paths.append(path)

        await database.save_user_reference(
            12345,
            kind="image",
            file_url=path.relative_to(tmp_path).as_posix(),
            file_hash=name,
        )

    async with db_backend.connect(database.DATABASE_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM saved_references")
        refs_count = (await cursor.fetchone())[0]

    assert refs_count == 2
    assert reference_paths[0].exists()
    assert reference_paths[1].exists()
    assert reference_paths[2].exists()

    old_mtime = 1_700_000_000
    os.utime(reference_paths[0], (old_mtime, old_mtime))

    stats = await database.cleanup_orphaned_reference_files(max_age_seconds=1)

    assert stats["removed_count"] == 1
    assert not reference_paths[0].exists()
    assert reference_paths[1].exists()
    assert reference_paths[2].exists()


@pytest.mark.asyncio
async def test_orphaned_reference_cleanup_keeps_database_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "refs.db"))

    async def noop_invalidate(_telegram_id):
        return None

    monkeypatch.setattr(database, "_invalidate_saved_reference_cache", noop_invalidate)

    await database.init_db()

    referenced = tmp_path / "static" / "uploads" / "refs" / "image" / "12345" / "202605" / "kept.png"
    orphaned = tmp_path / "static" / "uploads" / "refs" / "image" / "12345" / "202605" / "orphaned.png"
    referenced.parent.mkdir(parents=True, exist_ok=True)
    referenced.write_bytes(b"kept")
    orphaned.write_bytes(b"orphaned")

    old_mtime = 1_700_000_000
    os.utime(referenced, (old_mtime, old_mtime))
    os.utime(orphaned, (old_mtime, old_mtime))

    await database.save_user_reference(
        12345,
        kind="image",
        file_url=referenced.relative_to(tmp_path).as_posix(),
        file_hash="kept",
    )

    stats = await database.cleanup_orphaned_reference_files(max_age_seconds=1)

    assert stats["removed_count"] == 1
    assert referenced.exists()
    assert not orphaned.exists()


@pytest.mark.asyncio
async def test_share_to_feed_controls_prompt_and_reference_visibility(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "feed_visibility.db"))

    await database.init_db()
    user = await database.get_or_create_user(332211)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "feed-visibility-task",
        "image",
        "banana_pro",
        model="banana_pro",
        aspect_ratio="1:1",
        prompt="private prompt",
        cost=2,
        request_data={
            "reference_images": ["https://example.com/ref.png"],
            "source_reference_images": ["https://example.com/source-ref.png"],
        },
    )
    await database.complete_video_task(
        "feed-visibility-task",
        "https://example.com/result.png",
    )

    hidden_card = await database.share_to_feed("feed-visibility-task", user.id)

    assert hidden_card is not None
    assert hidden_card["prompt"] == ""
    assert hidden_card["prompt_hidden"] is True
    assert hidden_card["reference_images"] == []
    assert hidden_card["references_hidden"] is True
    assert hidden_card["feed_prompt_visible"] is False
    assert hidden_card["feed_references_visible"] is False

    visible_card = await database.share_to_feed(
        "feed-visibility-task",
        user.id,
        prompt_visible=True,
        references_visible=True,
    )

    assert visible_card is not None
    assert visible_card["prompt"] == "private prompt"
    assert visible_card["prompt_hidden"] is False
    assert visible_card["reference_images"] == ["https://example.com/source-ref.png"]
    assert visible_card["references_hidden"] is False
    assert visible_card["feed_prompt_visible"] is True
    assert visible_card["feed_references_visible"] is True


@pytest.mark.asyncio
async def test_share_to_feed_does_not_publish_image_when_storage_fails(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        database,
        "DATABASE_PATH",
        str(tmp_path / "feed-storage-failure.db"),
    )
    await database.init_db()
    user = await database.get_or_create_user(332212)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "feed-storage-failure",
        "image",
        "banana_pro",
        model="banana_pro",
        aspect_ratio="1:1",
        prompt="must stay private",
        cost=2,
    )
    original_url = "https://provider.example/result.png"
    await database.complete_video_task("feed-storage-failure", original_url)

    async def failed_download(_url):
        return None

    monkeypatch.setattr(
        "bot.services.feed_persist.download_to_local",
        failed_download,
    )

    assert await database.share_to_feed("feed-storage-failure", user.id) is None
    task = await database.get_task_by_id("feed-storage-failure")
    assert task is not None
    assert task.is_public_feed is False
    assert task.result_url == original_url


@pytest.mark.asyncio
async def test_profile_only_publication_is_hidden_from_general_feed(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "profile_scope.db"))
    await database.init_db()
    user = await database.get_or_create_user(440001)
    await database.add_generation_task(
        user.id, user.telegram_id, "profile-only-task", "image", "banana_pro",
        model="banana_pro", aspect_ratio="1:1", prompt="portrait", cost=2,
    )
    await database.complete_video_task(
        "profile-only-task", "https://example.com/profile-only.png"
    )

    card = await database.share_to_feed(
        "profile-only-task", user.id, publication_scope="profile", blurred=True
    )

    assert card is not None
    assert card["publication_scope"] == "profile"
    assert card["is_profile_visible"] is True
    assert card["feed_interactions_enabled"] is False
    assert card["feed_blurred"] is True
    assert await database.get_feed_generations(limit=20) == []
    profile_cards = await database.get_user_feed_generations(
        user.id, profile_visible_only=True, include_unavailable=True
    )
    assert [item["id"] for item in profile_cards] == [card["id"]]


@pytest.mark.asyncio
async def test_adult_content_is_profile_only_but_blur_is_user_controlled(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "adult_scope.db"))
    await database.init_db()
    user = await database.get_or_create_user(440002)
    await database.add_generation_task(
        user.id, user.telegram_id, "adult-task", "image", "banana_pro",
        model="banana_pro", aspect_ratio="1:1", prompt="adult portrait", cost=2,
    )
    await database.complete_video_task("adult-task", "https://example.com/adult.png")

    card = await database.share_to_feed(
        "adult-task",
        user.id,
        publication_scope="feed",
        adult_content=True,
        blurred=False,
    )

    assert card is not None
    assert card["publication_scope"] == "profile"
    assert card["is_adult_content"] is True
    assert card["feed_blurred"] is False
    assert card["feed_interactions_enabled"] is False
    assert await database.get_feed_generations(limit=20) == []

    blurred = await database.set_feed_blurred(card["id"], user.id, True)
    assert blurred is not None
    assert blurred["feed_blurred"] is True
    unblurred = await database.set_feed_blurred(card["id"], user.id, False)
    assert unblurred is not None
    assert unblurred["feed_blurred"] is False


@pytest.mark.asyncio
async def test_profile_only_interactions_require_profile_context(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "profile_interactions.db"))
    await database.init_db()
    author = await database.get_or_create_user(440010)
    viewer = await database.get_or_create_user(440011)
    await database.add_generation_task(
        author.id,
        author.telegram_id,
        "profile-interactions-task",
        "image",
        "banana_pro",
        model="banana_pro",
        aspect_ratio="1:1",
        prompt="profile interaction test",
        cost=2,
    )
    await database.complete_video_task(
        "profile-interactions-task",
        "https://example.com/profile-interactions.png",
    )
    card = await database.share_to_feed(
        "profile-interactions-task",
        author.id,
        publication_scope="profile",
    )

    assert await database.like_feed_generation(card["id"], viewer.id) is None
    assert await database.increment_feed_share(card["id"]) is None
    assert await database.add_feed_comment(card["id"], viewer.id, "hidden") is None

    liked = await database.like_feed_generation(
        card["id"],
        viewer.id,
        allow_profile=True,
    )
    shared = await database.increment_feed_share(card["id"], allow_profile=True)
    comment = await database.add_feed_comment(
        card["id"],
        viewer.id,
        "Работает в профиле",
        allow_profile=True,
    )

    assert liked is not None
    assert liked["publication_scope"] == "profile"
    assert liked["likes_count"] == 1
    assert shared is not None
    assert shared["shares_count"] == 1
    assert comment is not None
    assert comment["text"] == "Работает в профиле"
    comments = await database.get_feed_comments(card["id"], viewer_user_id=viewer.id)
    assert [item["text"] for item in comments] == ["Работает в профиле"]
    assert await database.get_feed_generations(limit=20) == []


@pytest.mark.asyncio
async def test_feed_publication_is_visible_in_feed_and_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "feed_scope.db"))
    await database.init_db()
    user = await database.get_or_create_user(440003)
    await database.add_generation_task(
        user.id, user.telegram_id, "feed-and-profile-task", "image", "banana_pro",
        model="banana_pro", aspect_ratio="1:1", prompt="safe portrait", cost=2,
    )
    await database.complete_video_task(
        "feed-and-profile-task", "https://example.com/feed.png"
    )

    card = await database.share_to_feed(
        "feed-and-profile-task", user.id, publication_scope="feed"
    )

    assert card is not None
    assert card["publication_scope"] == "feed"
    assert card["is_profile_visible"] is True
    assert card["feed_interactions_enabled"] is True
    assert [item["id"] for item in await database.get_feed_generations(limit=20)] == [card["id"]]
    profile_cards = await database.get_user_feed_generations(
        user.id, profile_visible_only=True, include_unavailable=True
    )
    assert [item["id"] for item in profile_cards] == [card["id"]]


@pytest.mark.asyncio
async def test_profile_owner_can_toggle_blur_without_general_feed(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "profile_blur.db"))
    await database.init_db()
    user = await database.get_or_create_user(440004)
    await database.add_generation_task(
        user.id, user.telegram_id, "profile-blur-task", "image", "banana_pro",
        model="banana_pro", aspect_ratio="1:1", prompt="portrait", cost=2,
    )
    await database.complete_video_task(
        "profile-blur-task", "https://example.com/profile-blur.png"
    )
    published = await database.share_to_feed(
        "profile-blur-task", user.id, publication_scope="profile"
    )
    updated = await database.set_feed_blurred(published["id"], user.id, True)

    assert updated is not None
    assert updated["publication_scope"] == "profile"
    assert updated["feed_blurred"] is True
    assert await database.get_feed_generations(limit=20) == []


@pytest.mark.asyncio
async def test_cleanup_stale_local_generation_tasks_refunds_old_img_tasks(monkeypatch):
    user = await database.get_or_create_user(987654321)

    await database.add_generation_task(
        user.id,
        987654321,
        "img_stale_seedream",
        "image",
        "seedream_edit",
        model="seedream_edit",
        cost=1.5,
    )
    await database.add_generation_task(
        user.id,
        987654321,
        "img_recent_seedream",
        "image",
        "seedream_edit",
        model="seedream_edit",
        cost=1.5,
    )

    async with db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE users SET credits = 0 WHERE id = ?", (user.id,))
        await db.execute(
            "UPDATE generation_tasks SET created_at = datetime('now', '-2 hours') WHERE task_id = ?",
            ("img_stale_seedream",),
        )
        await db.commit()

    stats = await database.cleanup_stale_local_generation_tasks(
        max_age_seconds=60 * 60
    )

    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        stale_cursor = await db.execute(
            "SELECT status FROM generation_tasks WHERE task_id = ?",
            ("img_stale_seedream",),
        )
        stale = await stale_cursor.fetchone()
        recent_cursor = await db.execute(
            "SELECT status FROM generation_tasks WHERE task_id = ?",
            ("img_recent_seedream",),
        )
        recent = await recent_cursor.fetchone()
        credits_cursor = await db.execute(
            "SELECT credits FROM users WHERE id = ?", (user.id,)
        )
        credits = await credits_cursor.fetchone()

    assert stats == {"failed_count": 1, "refunded_credits": 1.5}
    assert stale["status"] == "failed"
    assert recent["status"] == "pending"
    assert credits["credits"] == 1.5



@pytest.mark.asyncio
async def test_cleanup_stale_local_generation_tasks_uses_like_param_for_postgres(isolated_database, monkeypatch):
    from bot import database

    user = await database.get_or_create_user(555001)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        'img_pg_like_stale',
        'image',
        'seedream_edit',
        model='seedream_edit',
        cost=1.0,
    )

    async with db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE generation_tasks SET created_at = datetime('now', '-2 hours') WHERE task_id = ?",
            ('img_pg_like_stale',),
        )
        await db.commit()

    stats = await database.cleanup_stale_local_generation_tasks(max_age_seconds=60 * 60)
    assert stats['failed_count'] == 1


@pytest.mark.asyncio
async def test_cleanup_saved_references_uses_count_having_expression(isolated_database):
    from bot import database

    user = await database.get_or_create_user(555002)
    for i in range(3):
        await database.save_user_reference(
            telegram_id=user.telegram_id,
            file_url=f'https://example.com/ref_{i}.png',
            file_hash=f'hash_{i}',
            kind='image',
        )

    removed = await database.cleanup_saved_references(keep_latest=2, max_age_days=0, min_keep_per_kind=1)
    assert removed >= 1


@pytest.mark.asyncio
async def test_profile_only_publication_repeat_credits_author(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "profile-repeat-reward.db"))
    await database.init_db()

    author = await database.get_or_create_user(100041)
    repeater = await database.get_or_create_user(100042)
    await database.add_generation_task(
        author.id,
        author.telegram_id,
        "profile-repeat-source",
        "image",
        "miniapp_image",
        model="banana_pro",
        aspect_ratio="1:1",
        prompt="Profile-only source",
        cost=2,
    )
    await database.complete_video_task(
        "profile-repeat-source", "https://example.com/profile-repeat-source.png"
    )
    source = await database.share_to_feed(
        "profile-repeat-source",
        author.id,
        publication_scope="profile",
    )

    assert source is not None
    assert source["publication_scope"] == "profile"
    assert source["is_profile_visible"] is True
    assert await database.get_feed_generations(limit=10) == []

    credited = await database.credit_feed_prompt_repeat(
        source["id"],
        repeater.id,
        repeat_task_id="profile-repeat-task-1",
        credits_spent=2,
    )

    assert credited is True
    overview = await database.get_partner_overview(author.telegram_id)
    assert overview["balance_rub"] == 10
    assert overview["prompt_repeat_balance_rub"] == 10
    assert overview["prompt_repeat_total_rub"] == 10


@pytest.mark.asyncio
async def test_private_generation_repeat_does_not_credit_author(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "private-repeat-no-reward.db"))
    await database.init_db()

    author = await database.get_or_create_user(100043)
    repeater = await database.get_or_create_user(100044)
    await database.add_generation_task(
        author.id,
        author.telegram_id,
        "private-repeat-source",
        "image",
        "miniapp_image",
        model="banana_pro",
        aspect_ratio="1:1",
        prompt="Private source",
        cost=2,
    )
    await database.complete_video_task(
        "private-repeat-source", "https://example.com/private-repeat-source.png"
    )
    source = await database.get_task_by_id("private-repeat-source")
    assert source is not None

    credited = await database.credit_feed_prompt_repeat(
        source.id,
        repeater.id,
        repeat_task_id="private-repeat-task-1",
        credits_spent=2,
    )

    assert credited is False
    overview = await database.get_partner_overview(author.telegram_id)
    assert overview["balance_rub"] == 0
    assert overview["prompt_repeat_balance_rub"] == 0
    assert overview["prompt_repeat_total_rub"] == 0
