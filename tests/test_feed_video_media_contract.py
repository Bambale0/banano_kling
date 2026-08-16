from pathlib import Path

import pytest

from bot.services import feed_persist
from scripts import backfill_feed_video_media as backfill


@pytest.mark.asyncio
async def test_external_published_video_is_localized_even_without_strict_mode(monkeypatch):
    source_url = "https://provider.example/results/video.mp4"
    durable_url = "https://tanyapi.chillcreative.ru/uploads/feed/durable.mp4"
    calls: list[tuple[str, int]] = []

    monkeypatch.setattr(feed_persist, "_copy_local_upload_to_feed", lambda _url: None)
    monkeypatch.setattr(feed_persist, "ensure_feed_thumbnail", lambda _url: None)

    async def fake_download(url: str, max_size_bytes: int):
        calls.append((url, max_size_bytes))
        return durable_url

    monkeypatch.setattr(feed_persist, "download_to_local", fake_download)

    result = await feed_persist.persist_feed_result_urls(
        [source_url],
        require_local=False,
        max_size_bytes=123456,
    )

    assert result == [durable_url]
    assert calls == [(source_url, 123456)]


def test_video_backfill_url_parsing_and_local_detection():
    assert backfill._parse_result_urls(
        '["https://provider.example/a.mp4", "https://provider.example/b.mp4"]',
        "https://provider.example/a.mp4",
    ) == [
        "https://provider.example/a.mp4",
        "https://provider.example/b.mp4",
    ]
    assert backfill._is_durable_feed_url(
        "https://tanyapi.chillcreative.ru/uploads/feed/video.mp4"
    )
    assert not backfill._is_durable_feed_url(
        "https://provider.example/results/video.mp4"
    )


def test_feed_video_preview_uses_video_element_not_mp4_as_image():
    source = Path("frontend/miniapp-v0/components/tabs/feed-tab.tsx").read_text(
        encoding="utf-8"
    )
    component = source.split("function FeedVideoPreview", 1)[1].split(
        "export function FeedTab", 1
    )[0]

    assert "<video" in component
    assert "<img" not in component
    assert 'preload="metadata"' in component
    assert "feedMediaUrl(previewItem.result_url)" in source


def test_production_deploy_runs_video_backfill_after_health_gate():
    source = Path("scripts/deploy_backend_docker.sh").read_text(encoding="utf-8")

    health_index = source.index("if ! wait_for_health; then")
    backfill_index = source.index("backfill_public_feed_videos", health_index)
    assert backfill_index > health_index
    assert "compose exec -T bot python scripts/backfill_feed_video_media.py" in source
