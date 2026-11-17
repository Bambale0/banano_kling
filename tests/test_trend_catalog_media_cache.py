"""Catalog preview URLs must remain lightweight and durable after local S3 cache cleanup."""
import pytest

from bot.services import trend_catalog_media_cache as media


def test_source_identity_ignores_legacy_domain_and_query_string():
    a = "https://neuromixbot.com/uploads/refs/video/42/example.mp4"
    b = "https://tanyapp.chillcreative.ru/uploads/refs/video/42/example.mp4?old=123"
    assert media.source_key(a) == media.source_key(b) == "/uploads/refs/video/42/example.mp4"
    assert media.source_key("https://example.com/private/refs/video/42/example.mp4") is None
    assert media.source_key("https://neuromixbot.com/uploads/../private.mp4") is None
    assert media.source_key("https://neuromixbot.com/uploads/refs/video/42/example.mp4?x=1#t=0.001")


@pytest.mark.asyncio
async def test_manifest_survives_restart_and_uses_one_lookup_not_s3(isolated_database, monkeypatch):
    key = "https://tanyapp.chillcreative.ru/uploads/feed/clip.mp4"
    poster = "https://neuromixbot.com/uploads/trend-previews/catalog/abc.jpg"
    await media.record_thumbnail(key, poster)
    assert (await media.cached_thumbnails([key])) == {media.source_key(key): poster}
    mock = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("S3 queried during catalog read"))
    monkeypatch.setattr(media, "resolve_remote", mock, raising=False)
    migrated_url = "https://neuromixbot.com/uploads/feed/clip.mp4"
    await media.enrich_cards([{"preview_url": migrated_url, "preview_poster_url": None}])
    cards = [{"preview_url": migrated_url, "preview_poster_url": None}]
    await media.enrich_cards(cards)
    assert cards[0]["preview_url"] == migrated_url  # original video preserved for dialog
    assert cards[0]["preview_poster_url"] == poster


@pytest.mark.asyncio
async def test_manifest_does_not_overwrite_existing_poster_or_external_url(isolated_database):
    original = "https://neuromixbot.com/uploads/feed/clip.mp4"
    await media.record_thumbnail(
        original, "https://neuromixbot.com/uploads/trend-previews/catalog/abc.jpg")
    cards = [
        {"preview_url": original, "preview_poster_url": "https://neuromixbot.com/uploads/trend-previews/old.jpg"},
        {"preview_url": "https://external.example/clip.mp4", "preview_poster_url": None},
    ]
    await media.enrich_cards(cards)
    assert cards[0]["preview_poster_url"].endswith("/old.jpg")
    assert cards[1]["preview_poster_url"] is None
