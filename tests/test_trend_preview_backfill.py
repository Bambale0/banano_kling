"""Backfill should select actual video sources before consuming its LIMIT."""

from __future__ import annotations

import pytest

from bot import database
from scripts import backfill_trend_previews


@pytest.fixture(autouse=True)
async def isolated_trend_metrics_database(isolated_database, monkeypatch):
    from bot.handlers import trend_success_compat

    monkeypatch.setattr(trend_success_compat, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(trend_success_compat, "_SCHEMA_READY", False)


@pytest.mark.asyncio
async def test_image_newer_than_video_does_not_hide_video_from_single_item_batch(
    monkeypatch,
):
    user = await database.get_or_create_user(991001)
    for title, preview in [
        ("Older MP4", "https://static.example/uploads/older.mp4"),
        ("Newer image", "https://static.example/uploads/newer.jpg"),
    ]:
        trend = await database.create_prompt(
            author_id=user.id,
            prompt_text="Test scene",
            title=title,
            preview_url=preview,
            tags=["trend"],
            category="photo",
            is_public=True,
        )
        await database.approve_prompt(trend["id"])

    monkeypatch.setattr(
        backfill_trend_previews,
        "resolve_local_upload_path",
        lambda url: "/tmp/test.mp4" if url.endswith(".mp4") else "/tmp/test.jpg",
    )
    monkeypatch.setattr(
        backfill_trend_previews,
        "cached_trend_preview_assets",
        lambda url: {"preview_url": url, "preview_poster_url": None},
    )
    outcome = await backfill_trend_previews.run(limit=1, before_id=None, execute=False)
    assert outcome == {
        "checked": 1,
        "cached": 0,
        "created": 0,
        "failed": 0,
        "skipped": 1,
    }
