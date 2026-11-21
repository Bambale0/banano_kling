"""Regression: video Trends have a durable, same-origin live MP4 without losing the full original."""

import pytest

from bot.services import trend_catalog_media_cache as media

ORIGINAL = "https://tanyapp.chillcreative.ru/uploads/feed/clip.mp4"
ALIAS = "https://neuromixbot.com/uploads/feed/clip.mp4"
LIVE = "https://neuromixbot.com/uploads/trend-previews/live/" + "a" * 32 + ".mp4"
POSTER = "https://neuromixbot.com/uploads/trend-previews/catalog/" + "b" * 32 + ".jpg"


@pytest.mark.asyncio
async def test_durable_live_preview_preserves_original_and_poster(isolated_database):
    await media.record_thumbnail(ORIGINAL, POSTER)
    await media.record_live_preview(ORIGINAL, LIVE)
    assert await media.cached_live_previews([ALIAS]) == {media.source_key(ALIAS): LIVE}
    cards = [
        {"id": 7, "preview_url": ALIAS, "category": "video",
         "preview_poster_url": None,
         "preview_video_url": "/uploads/trend-previews/179502/old-s3-redirect.mp4"},
        {"id": 8, "preview_url": "https://example.net/private.mp4", "category": "video", "preview_poster_url": None},
    ]
    await media.enrich_cards(cards)
    assert cards[0]["preview_url"] == ALIAS  # Full original remains for detail modal
    assert cards[0]["preview_video_url"] == LIVE  # Only grid autoplay uses short MP4
    assert cards[0]["preview_poster_url"] == POSTER
    assert cards[1].get("preview_video_url") is None


@pytest.mark.asyncio
async def test_photo_and_external_urls_are_not_rewritten(isolated_database):
    photo = "https://neuromixbot.com/uploads/feed/photo.png"
    cards = [{"preview_url": photo, "category": "photo", "preview_poster_url": None}]
    await media.enrich_cards(cards)
    assert cards[0]["preview_url"] == photo
    assert "preview_video_url" not in cards[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("src,target", [
    ("https://attacker.example/uploads/feed/private.mp4", LIVE),
    (ORIGINAL, "https://s3.example/signature=secret"),
    (ORIGINAL, "https://neuromixbot.com/uploads/feed/full.mp4"),
    ("https://neuromixbot.com/uploads/feed/photo.png", LIVE),
    (ORIGINAL, "https://neuromixbot.com/uploads/trend-previews/live/../../secret.mp4"),
])
async def test_manifest_refuses_unsafe_sources_or_outputs(isolated_database, src, target):
    with pytest.raises(ValueError):
        await media.record_live_preview(src, target)


@pytest.mark.asyncio
async def test_missing_manifest_fails_open_without_s3(monkeypatch, isolated_database):
    cards = [{"preview_url": ALIAS, "category": "video", "preview_poster_url": POSTER}]
    await media.enrich_cards(cards)
    assert cards == [{"preview_url": ALIAS, "category": "video", "preview_poster_url": POSTER}]
