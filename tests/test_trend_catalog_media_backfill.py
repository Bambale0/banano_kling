"""The backfill never fetches originals during a read-only scan."""
import pytest

from scripts import backfill_trend_catalog_media as backfill


@pytest.mark.asyncio
async def test_catalog_backfill_skips_existing_posters_and_deduplicates(monkeypatch):
    original = "https://neuromixbot.com/uploads/feed/older.mp4"
    categories = [{
        "items": [
            {"preview_url": original, "preview_poster_url": None},
            {"preview_url": original, "preview_poster_url": None},
            {"preview_url": "https://neuromixbot.com/uploads/feed/ready.mp4",
             "preview_poster_url": "https://neuromixbot.com/uploads/trend-previews/ready.jpg"},
        ]
    }]
    async def fake_catalog(**kwargs):
        assert kwargs == {"is_admin": False, "per_category": 6}
        return categories

    async def fake_cached(urls):
        assert urls == [original]
        return {}

    created = []
    async def fake_generate(url):
        created.append(url)
        return "https://neuromixbot.com/uploads/trend-previews/catalog/new.jpg"

    monkeypatch.setattr(backfill.trend_catalog, "list_catalog", fake_catalog)
    monkeypatch.setattr(backfill, "cached_thumbnails", fake_cached)
    monkeypatch.setattr(backfill, "generate_thumbnail", fake_generate)
    dry = await backfill.run(limit=20, execute=False)
    assert dry == {"total_visible": 1, "checked": 1, "cached": 0,
                   "created": 0, "failed": 0, "skipped": 1}
    assert not created
    result = await backfill.run(limit=20, execute=True)
    assert result["created"] == 1
    assert result["checked"] == 1
    assert created == [original]
