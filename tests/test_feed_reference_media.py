from pathlib import Path

import pytest
from aiohttp import web
from PIL import Image

from bot import feed_reference_media as media


@pytest.mark.asyncio
async def test_visible_local_reference_is_resolved(monkeypatch, tmp_path: Path):
    source = tmp_path / "reference.png"
    Image.new("RGB", (1200, 1800), "white").save(source)

    async def fake_card(_gen_id):
        return {
            "reference_images": ["/uploads/refs/image/ref.png"],
            "references_hidden": False,
            "feed_references_visible": True,
        }

    monkeypatch.setattr(media, "get_feed_generation_card", fake_card)
    monkeypatch.setattr(media, "resolve_local_upload_path", lambda _url: str(source))

    assert await media._public_image_reference_path("123", 0) == source


@pytest.mark.asyncio
async def test_hidden_reference_returns_not_found(monkeypatch):
    async def fake_card(_gen_id):
        return {
            "reference_images": ["/uploads/refs/image/ref.png"],
            "references_hidden": True,
            "feed_references_visible": False,
        }

    monkeypatch.setattr(media, "get_feed_generation_card", fake_card)
    with pytest.raises(web.HTTPNotFound):
        await media._public_image_reference_path("123", 0)


def test_thumbnail_is_small_webp(tmp_path: Path):
    source = tmp_path / "reference.png"
    target = tmp_path / "thumb.webp"
    Image.new("RGB", (1800, 1200), "white").save(source)

    media._build_thumbnail(source, target)

    with Image.open(target) as preview:
        assert max(preview.size) <= media.REFERENCE_THUMB_MAX_EDGE
        assert preview.format == "WEBP"
