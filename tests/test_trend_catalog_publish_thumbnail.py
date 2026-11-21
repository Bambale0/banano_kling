"""New approved public trends must get a durable poster without breaking approval."""

from unittest.mock import AsyncMock

import pytest

from bot.services import trend_catalog_publish_thumbnail as publisher


def prompt(url="/uploads/feed/clip.mp4", **overrides):
    return {
        "id": 2643,
        "status": "approved",
        "is_public": True,
        "tags": ["trend", "trend-video"],
        "preview_url": url,
        **overrides,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://neuromixbot.com/uploads/feed/new.mp4",
    "https://neuromixbot.com/uploads/feed/new.png",
    "/uploads/refs/video/2/clip.mov",
])
async def test_published_media_creates_durable_poster(monkeypatch, url):
    from scripts import backfill_trend_catalog_media as backfill

    async def no_manifest(_urls):
        return {}

    generated = AsyncMock(return_value="/uploads/trend-previews/catalog/poster.jpg")
    monkeypatch.setattr(publisher, "cached_thumbnails", no_manifest)
    monkeypatch.setattr(backfill, "generate_thumbnail", generated)

    assert await publisher.ensure_published_trend_poster(prompt(url)) is True
    generated.assert_awaited_once_with(url)


@pytest.mark.asyncio
async def test_existing_manifest_never_regenerates(monkeypatch):
    from scripts import backfill_trend_catalog_media as backfill
    generated = AsyncMock(side_effect=AssertionError("S3/ffmpeg must not run"))
    monkeypatch.setattr(backfill, "generate_thumbnail", generated)

    async def manifest(_urls):
        return {"/uploads/feed/clip.mp4": "/uploads/trend-previews/catalog/existing.jpg"}
    monkeypatch.setattr(publisher, "cached_thumbnails", manifest)

    assert await publisher.ensure_published_trend_poster(prompt()) is True
    generated.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [
    prompt(status="pending"),
    prompt(is_public=False),
    prompt(tags=["not-a-trend"]),
    prompt(url="https://untrusted.example/private.mp4"),
    prompt(url=""),
    None,
])
async def test_private_pending_or_unsupported_media_never_upload(monkeypatch, value):
    from scripts import backfill_trend_catalog_media as backfill
    generated = AsyncMock(side_effect=AssertionError("must not upload"))
    monkeypatch.setattr(backfill, "generate_thumbnail", generated)
    assert await publisher.ensure_published_trend_poster(value) is False
    generated.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", [RuntimeError("S3 unavailable"), TimeoutError()])
async def test_storage_failure_fails_open_after_approval(monkeypatch, caplog, problem):
    from scripts import backfill_trend_catalog_media as backfill

    async def no_manifest(_urls):
        return {}

    monkeypatch.setattr(publisher, "cached_thumbnails", no_manifest)
    generated = AsyncMock(side_effect=problem)
    monkeypatch.setattr(backfill, "generate_thumbnail", generated)

    assert await publisher.ensure_published_trend_poster(prompt()) is False
    assert "trend_id=2643" in caplog.text
