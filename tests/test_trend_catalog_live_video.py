"""Compact Trend loop generation never modifies originals and is restart-safe."""

from unittest.mock import AsyncMock

import pytest

from bot.services import trend_catalog_live_video as live

URL = "https://neuromixbot.com/uploads/feed/sample.mp4"
PUBLIC = "https://neuromixbot.com/uploads/trend-previews/live/" + "a" * 32 + ".mp4"


@pytest.mark.asyncio
async def test_live_generation_persists_before_manifest_and_keeps_original(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "static/uploads/feed/sample.mp4"
    source.parent.mkdir(parents=True)
    original = b"original-not-modified" * 100
    source.write_bytes(original)
    monkeypatch.setattr(live, "is_s3_enabled", lambda: False)
    monkeypatch.setattr(live, "resolve_local_upload_path", lambda _u: str(source))
    lookup = AsyncMock(return_value={})
    recorded = AsyncMock()
    monkeypatch.setattr(live, "cached_live_previews", lookup)
    monkeypatch.setattr(live, "record_live_preview", recorded)
    calls = []
    def encode(_source, dest):
        calls.append(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"test" * 30)
    monkeypatch.setattr(live, "_encode_live_preview", encode)
    monkeypatch.setattr(live, "persist_upload_file", lambda *a, **k: PUBLIC)

    result = await live.generate_live_preview(URL)
    assert result == PUBLIC
    assert source.read_bytes() == original
    assert len(calls) == 1
    recorded.assert_awaited_once_with(URL, PUBLIC)
    assert calls[0].name.endswith(".mp4")


@pytest.mark.asyncio
async def test_external_and_photo_sources_are_rejected_before_materialization(monkeypatch):
    monkeypatch.setattr(
        live, "resolve_local_upload_path",
        lambda *_: pytest.fail("external URL must not be downloaded"),
    )
    assert await live.generate_live_preview("https://other.example/uploads/private.mp4") is None
    assert await live.generate_live_preview("https://neuromixbot.com/uploads/feed/photo.png") is None


def test_only_public_approved_video_is_scheduled(monkeypatch):
    monkeypatch.setattr(live.asyncio, "create_task", lambda _c: pytest.fail("no task allowed"))
    for value in (
        {"status": "pending", "is_public": True, "tags": ["trend"], "category": "video", "preview_url": URL},
        {"status": "approved", "is_public": False, "tags": ["trend"], "category": "video", "preview_url": URL},
        {"status": "approved", "is_public": True, "tags": ["private"], "category": "video", "preview_url": URL},
    ):
        assert live.schedule_published_live_preview(value) is False
