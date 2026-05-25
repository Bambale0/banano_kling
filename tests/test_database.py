"""Stable unit tests for database helpers."""

import json
import os
from unittest.mock import AsyncMock

import aiosqlite
import pytest

import bot.database as database
from bot.services.preset_manager import PresetManager


class FakeConnection:
    def __init__(self):
        self.execute = AsyncMock()
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_complete_video_task_marks_completed_with_result_url(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(database.aiosqlite, "connect", lambda *_args, **_kwargs: conn)

    result = await database.complete_video_task("task-ok", "http://result.url")

    assert result is True
    conn.execute.assert_awaited_once()
    sql, params = conn.execute.await_args.args
    assert "UPDATE generation_tasks" in sql
    assert params == ("completed", "http://result.url", "task-ok")
    conn.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_video_task_marks_failed_without_result_url(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(database.aiosqlite, "connect", lambda *_args, **_kwargs: conn)

    result = await database.complete_video_task("task-fail", None)

    assert result is True
    sql, params = conn.execute.await_args.args
    assert "UPDATE generation_tasks" in sql
    assert params == ("failed", None, "task-fail")
    conn.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_master_partner_user_uses_master_telegram_id(monkeypatch):
    expected_user = object()
    get_or_create_user = AsyncMock(return_value=expected_user)
    monkeypatch.setattr(database, "get_or_create_user", get_or_create_user)

    user = await database.get_master_partner_user()

    assert user is expected_user
    get_or_create_user.assert_awaited_once_with(database.MASTER_PARTNER_TELEGRAM_ID)


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
async def test_pruned_saved_reference_file_is_removed(tmp_path, monkeypatch):
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

    async with aiosqlite.connect(database.DATABASE_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM saved_references")
        refs_count = (await cursor.fetchone())[0]

    assert refs_count == 2
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

    async with aiosqlite.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE users SET credits = 0 WHERE id = ?", (user.id,))
        await db.execute(
            "UPDATE generation_tasks SET created_at = datetime('now', '-2 hours') WHERE task_id = ?",
            ("img_stale_seedream",),
        )
        await db.commit()

    stats = await database.cleanup_stale_local_generation_tasks(
        max_age_seconds=60 * 60
    )

    async with aiosqlite.connect(database.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
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
