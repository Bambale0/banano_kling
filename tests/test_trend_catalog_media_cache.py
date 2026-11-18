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


@pytest.mark.asyncio
async def test_public_s3_posters_have_direct_fast_url_with_stable_fallback(monkeypatch):
    """Only canonical public thumbnails are signed; duplicates are signed once."""
    thumb = "https://neuromixbot.com/uploads/trend-previews/catalog/abc.jpg"
    legacy = "https://tanyapp.chillcreative.ru/uploads/trend-previews/catalog/abc.jpg"
    called = []

    def fake_presign(path, *, method="GET"):
        called.append((path, method))
        return "https://s3.example.test/bucket/uploads/" + path + "?signed=1"

    monkeypatch.setattr(media, "is_s3_enabled", lambda: True)
    monkeypatch.setattr(media, "presigned_upload_url", fake_presign)
    monkeypatch.setattr(media, "_signed_poster_cache", {})
    monkeypatch.setattr(media, "_signed_preview_cache_seconds", lambda: 30)
    cards = [
        {"preview_url": "/uploads/feed/a.mp4", "preview_poster_url": thumb},
        {"preview_url": "/uploads/feed/b.mp4", "preview_poster_url": legacy},
        {"preview_url": "/uploads/feed/c.mp4", "preview_poster_url": "https://other.example/uploads/trend-previews/secret.jpg"},
        {"preview_url": "/uploads/feed/d.mp4", "preview_poster_url": None},
    ]
    await media.enrich_cards(cards)

    assert called == [("trend-previews/catalog/abc.jpg", "GET")]
    assert cards[0]["preview_poster_fast_url"].startswith("https://s3.example.test/")
    assert cards[1]["preview_poster_fast_url"] == cards[0]["preview_poster_fast_url"]
    assert cards[0]["preview_poster_url"] == thumb
    assert cards[1]["preview_poster_url"] == legacy
    assert "preview_poster_fast_url" not in cards[2]
    assert "preview_poster_fast_url" not in cards[3]


@pytest.mark.asyncio
async def test_fast_url_signing_failure_preserves_stable_poster(monkeypatch):
    poster = "https://neuromixbot.com/uploads/trend-previews/catalog/abc.jpg"
    monkeypatch.setattr(media, "is_s3_enabled", lambda: True)
    monkeypatch.setattr(media, "_signed_poster_cache", {})

    def fail(*_args, **_kwargs):
        raise RuntimeError("simulated signer outage")

    monkeypatch.setattr(media, "presigned_upload_url", fail)
    card = {"preview_url": "/uploads/feed/example.mp4", "preview_poster_url": poster}
    await media.enrich_cards([card])
    assert card["preview_poster_url"] == poster
    assert "preview_poster_fast_url" not in card



def test_signed_poster_cache_reuses_signature_until_its_early_expiry(monkeypatch):
    """Do not re-sign the entire catalog on every visit, but never serve stale."""
    clock = [100.0]
    calls = []

    def fake_sign(relative, *, method="GET"):
        calls.append((relative, method))
        return "https://s3.example.test/public.jpg?signature=" + str(len(calls))

    monkeypatch.setattr(media, "_signed_poster_cache", {})
    monkeypatch.setattr(media, "_signed_preview_now", lambda: clock[0])
    monkeypatch.setattr(media, "_signed_preview_cache_seconds", lambda: 30)
    monkeypatch.setattr(media, "presigned_upload_url", fake_sign)
    key = "/uploads/trend-previews/catalog/abc.jpg"
    first = media._sign_public_poster_urls([key])[key]
    clock[0] = 110.0
    assert media._sign_public_poster_urls([key])[key] == first
    assert len(calls) == 1
    clock[0] = 131.0
    assert media._sign_public_poster_urls([key])[key] != first
    assert len(calls) == 2
