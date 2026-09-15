from __future__ import annotations

import pytest

from bot import database, miniapp
from bot import db as db_backend


async def _age_task(task_id: str, hours: int) -> None:
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            """
            UPDATE generation_tasks
            SET created_at = datetime('now', ?),
                updated_at = datetime('now', ?),
                completed_at = datetime('now', ?)
            WHERE task_id = ?
            """,
            (f"-{hours} hours", f"-{hours} hours", f"-{hours} hours", task_id),
        )
        await db.commit()


@pytest.mark.asyncio
async def test_rendergrid_external_result_expires_after_provider_specific_24h(monkeypatch):
    monkeypatch.setattr(database, "RENDERGRID_RESULT_TTL_HOURS", 24, raising=False)
    monkeypatch.setattr(database, "FEED_EPHEMERAL_RESULT_TTL_HOURS", 72)

    user = await database.get_or_create_user(880001)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "legacy-rg-25h",
        "image",
        "banana_pro",
        model="banana_pro",
        aspect_ratio="1:1",
        prompt="legacy",
        cost=2,
    )
    await database.complete_video_task(
        "legacy-rg-25h",
        "https://cdn.rendergrid.io/images/legacy-25h.png",
    )
    await _age_task("legacy-rg-25h", 25)

    cards = await database.get_user_feed_generations(
        user.id,
        limit=20,
        include_unpublished_owned=True,
        include_unavailable=True,
    )
    card = next(item for item in cards if item["task_id"] == "legacy-rg-25h")

    assert card["result_urls"] == []
    assert card["result_url"] == ""
    assert card["media_unavailable"] is True


@pytest.mark.asyncio
async def test_rendergrid_external_result_is_still_resolvable_inside_24h(monkeypatch):
    monkeypatch.setattr(database, "RENDERGRID_RESULT_TTL_HOURS", 24, raising=False)
    monkeypatch.setattr(database, "FEED_EPHEMERAL_RESULT_TTL_HOURS", 72)

    user = await database.get_or_create_user(880002)
    url = "https://cdn.rendergrid.io/images/legacy-23h.png"
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "legacy-rg-23h",
        "image",
        "banana_pro",
        model="banana_pro",
        aspect_ratio="1:1",
        prompt="legacy",
        cost=2,
    )
    await database.complete_video_task("legacy-rg-23h", url)
    await _age_task("legacy-rg-23h", 23)

    cards = await database.get_user_feed_generations(
        user.id,
        limit=20,
        include_unpublished_owned=True,
        include_unavailable=True,
    )
    card = next(item for item in cards if item["task_id"] == "legacy-rg-23h")

    assert card["result_urls"] == [url]
    assert card["media_unavailable"] is False


@pytest.mark.asyncio
async def test_miniapp_history_and_task_detail_use_shared_rendergrid_resolver(monkeypatch):
    monkeypatch.setattr(database, "RENDERGRID_RESULT_TTL_HOURS", 24, raising=False)
    monkeypatch.setattr(database, "FEED_EPHEMERAL_RESULT_TTL_HOURS", 72)
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)

    user = await database.get_or_create_user(880003)
    url = "https://cdn.rendergrid.io/images/legacy-miniapp.png"
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "legacy-rg-miniapp",
        "image",
        "banana_pro",
        model="banana_pro",
        aspect_ratio="1:1",
        prompt="legacy miniapp",
        cost=2,
    )
    await database.complete_video_task("legacy-rg-miniapp", url)
    await _age_task("legacy-rg-miniapp", 25)

    history = await miniapp._fetch_recent_tasks(user.telegram_id, limit=8)
    task = next(item for item in history if item["task_id"] == "legacy-rg-miniapp")
    detail = await miniapp._fetch_task_detail(user.telegram_id, "legacy-rg-miniapp")

    assert task["result_url"] is None
    assert task["result_urls"] == []
    assert task["media_unavailable"] is True
    assert detail is not None
    assert detail["result_url"] is None
    assert detail["result_urls"] == []
    assert detail["media_unavailable"] is True
    assert "cdn.rendergrid.io" not in str(task)
    assert "cdn.rendergrid.io" not in str(detail)


@pytest.mark.asyncio
async def test_miniapp_profile_remix_can_read_snapshot_after_rendergrid_media_expires(monkeypatch):
    monkeypatch.setattr(database, "RENDERGRID_RESULT_TTL_HOURS", 24, raising=False)
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)

    user = await database.get_or_create_user(880005)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "legacy-rg-profile-repeat",
        "image",
        "banana_pro",
        model="banana_pro",
        aspect_ratio="1:1",
        prompt="profile repeat",
        cost=2,
        request_data={"source_reference_images": ["https://example.com/source-ref.png"]},
    )
    await database.complete_video_task(
        "legacy-rg-profile-repeat",
        "https://cdn.rendergrid.io/images/profile-repeat.png",
    )
    await _age_task("legacy-rg-profile-repeat", 49)

    task = await database.get_task_by_id("legacy-rg-profile-repeat")
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE generation_tasks SET is_profile_visible = 1 WHERE id = ?",
            (task.id,),
        )
        await db.commit()

    repeat_card = await miniapp._get_repeat_source_card(
        task.id,
        viewer_user_id=user.id,
    )
    remix_card = await miniapp._get_feed_remix_source_card(
        task.id,
        viewer_user_id=user.id,
        allow_profile=True,
    )

    assert repeat_card is not None
    assert repeat_card["media_unavailable"] is True
    assert repeat_card["result_urls"] == []
    assert remix_card is not None
    assert remix_card["media_unavailable"] is True
    assert remix_card["task_id"] == "legacy-rg-profile-repeat"


@pytest.mark.asyncio
async def test_telegram_repeat_restores_local_snapshot_refs_after_24h(tmp_path, monkeypatch):
    from bot.handlers import generation

    monkeypatch.chdir(tmp_path)
    user = await database.get_or_create_user(880006)
    ref_path = (
        tmp_path
        / "static"
        / "uploads"
        / "refs"
        / "image"
        / str(user.telegram_id)
        / "202609"
        / "repeat-ref.png"
    )
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    ref_path.write_bytes(b"repeat-ref")
    ref_url = ref_path.relative_to(tmp_path).as_posix()

    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "telegram-repeat-49h",
        "image",
        "banana_pro",
        model="banana_pro",
        aspect_ratio="1:1",
        prompt="repeat me",
        cost=2,
        request_data={
            "prompt": "repeat me",
            "img_service": "banana_pro",
            "img_ratio": "1:1",
            "reference_images": [ref_url],
            "source_reference_images": [ref_url],
        },
    )
    await database.complete_video_task(
        "telegram-repeat-49h",
        "https://example.com/durable-result.png",
    )
    await _age_task("telegram-repeat-49h", 49)
    task = await database.get_task_by_id("telegram-repeat-49h")

    class FakeState:
        def __init__(self):
            self.data = {}
            self.state = None

        async def clear(self):
            self.data.clear()

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, state):
            self.state = state

    state = FakeState()
    assert generation._can_inherit_repeat_source_references(task, user.id) is True
    restored, error = await generation._restore_image_task_to_state(
        task,
        state,
        include_references=True,
        repeat_source_task_id=task.task_id,
    )

    assert restored is True
    assert error is None
    assert state.data["reference_images"] == [ref_url]
    assert state.data["repeat_inherited_reference_count"] == 1
