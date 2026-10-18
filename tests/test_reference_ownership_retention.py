"""Reference lifetime follows generation ownership, not the recent-upload list."""

import json
import os

import pytest

from bot import database
from bot import db as db_backend


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "processing", "completed", "failed"])
@pytest.mark.parametrize(
    "field",
    ["reference_videos", "reference_audio_urls", "first_frame_url", "nested_recipe"],
)
async def test_cleanup_keeps_all_typed_generation_inputs(
    tmp_path, monkeypatch, status, field
):
    monkeypatch.chdir(tmp_path)
    owner = await database.get_or_create_user(3210)
    ref = tmp_path / "static/uploads/refs/video/3210/original.mp4"
    ref.parent.mkdir(parents=True)
    ref.write_bytes(b"owned-original")
    os.utime(ref, (1_700_000_000, 1_700_000_000))
    source = "/uploads/refs/video/3210/original.mp4"
    value = {"inputs": [{"url": source}]} if field == "nested_recipe" else source
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO generation_tasks (user_id, telegram_id, task_id, type, preset_id, status, request_data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                owner.id,
                owner.telegram_id,
                "owned-ref-task",
                "video",
                "test",
                status,
                json.dumps({field: value}),
            ),
        )
        await db.commit()
    stats = await database.cleanup_orphaned_reference_files(max_age_seconds=1)
    assert ref.read_bytes() == b"owned-original"
    assert stats["protected_generation_paths"] >= 1
    assert stats["removed_count"] == 0


@pytest.mark.asyncio
async def test_cleanup_keeps_draft_template_reference(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    owner = await database.get_or_create_user(3210)
    ref = tmp_path / "static/uploads/refs/image/3210/original.png"
    ref.parent.mkdir(parents=True)
    ref.write_bytes(b"template-original")
    os.utime(ref, (1_700_000_000, 1_700_000_000))
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO user_prompts (author_id, title, prompt_text, status, generation_settings) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                owner.id,
                "draft",
                "template",
                "pending",
                json.dumps({"image_urls": ["/uploads/refs/image/3210/original.png"]}),
            ),
        )
        await db.commit()
    await database.cleanup_orphaned_reference_files(max_age_seconds=1)
    assert ref.read_bytes() == b"template-original"


@pytest.mark.asyncio
async def test_removing_recent_reference_defers_physical_deletion(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    ref = tmp_path / "static/uploads/refs/image/3210/original.png"
    ref.parent.mkdir(parents=True)
    ref.write_bytes(b"historical-original")
    await database._remove_saved_reference_file("/uploads/refs/image/3210/original.png")
    assert ref.read_bytes() == b"historical-original"


@pytest.mark.asyncio
async def test_unreadable_owner_snapshot_aborts_before_any_deletion(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    owner = await database.get_or_create_user(3210)
    ref = tmp_path / "static/uploads/refs/image/3210/original.png"
    ref.parent.mkdir(parents=True)
    ref.write_bytes(b"original")
    os.utime(ref, (1_700_000_000, 1_700_000_000))
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO generation_tasks (user_id, telegram_id, task_id, type, preset_id, status, request_data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                owner.id,
                owner.telegram_id,
                "broken-snapshot",
                "video",
                "test",
                "completed",
                "{broken /uploads/refs/image/3210/original.png",
            ),
        )
        await db.commit()
    with pytest.raises(db_backend.OperationalError):
        await database.cleanup_orphaned_reference_files(max_age_seconds=1)
    assert ref.read_bytes() == b"original"


@pytest.mark.asyncio
async def test_generic_upload_cleanup_preserves_private_pending_reference(
    tmp_path, monkeypatch
):
    from bot import main

    monkeypatch.chdir(tmp_path)
    owner = await database.get_or_create_user(3210)
    ref = tmp_path / "static/uploads/20261018/private-input.png"
    garbage = ref.with_name("unowned.png")
    ref.parent.mkdir(parents=True)
    ref.write_bytes(b"private-input")
    garbage.write_bytes(b"unowned")
    for path in (ref, garbage):
        os.utime(path, (1_700_000_000, 1_700_000_000))
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO generation_tasks (user_id, telegram_id, task_id, type, preset_id, status, request_data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                owner.id,
                owner.telegram_id,
                "dated-upload",
                "video",
                "test",
                "pending",
                json.dumps({"image_urls": ["/uploads/20261018/private-input.png"]}),
            ),
        )
        await db.commit()
    protected = await main._public_feed_protected_upload_paths()
    await main._remove_old_files("static/uploads", 1, protected_paths=protected)
    assert ref.read_bytes() == b"private-input"
    assert not garbage.exists()
