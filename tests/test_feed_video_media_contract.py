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


def test_video_backfill_requires_real_nonempty_file(tmp_path, monkeypatch):
    upload_root = tmp_path / "uploads"
    feed_dir = upload_root / "feed"
    feed_dir.mkdir(parents=True)
    monkeypatch.setattr(backfill, "UPLOAD_ROOT", upload_root)
    monkeypatch.setattr(backfill, "MIN_VALID_VIDEO_BYTES", 8)

    url = "https://tanyapi.chillcreative.ru/uploads/feed/video.mp4"
    assert backfill._is_durable_feed_url(url)
    assert not backfill._durable_feed_file_exists(url)

    video = feed_dir / "video.mp4"
    video.write_bytes(b"1234567")
    assert not backfill._durable_feed_file_exists(url)

    video.write_bytes(b"12345678")
    assert backfill._durable_feed_file_exists(url)


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


def test_production_deploy_keeps_video_backfill_in_opt_in_maintenance():
    source = Path("scripts/deploy_backend_docker.sh").read_text(encoding="utf-8")
    deploy = source.split("\ndeploy() {", 1)[1].split("\nstatus() {", 1)[0]
    maintenance = source.split("\nmaintenance_media() {", 1)[1].split(
        "\nrollback_to_systemd() {", 1
    )[0]
    backfill = source.split("\nbackfill_public_feed_videos() {", 1)[1].split(
        "\nreconcile_rendergrid_legacy_images() {", 1
    )[0]

    assert "backfill_public_feed_videos" not in deploy
    assert "reconcile_rendergrid_legacy_images" not in deploy
    assert deploy.index('require_disk_space "$PROJECT_DIR"') < deploy.index(
        "build_or_pull_image"
    ) < deploy.index("backup_database") < deploy.index("if ! wait_for_health; then")
    assert 'maintenance-media) maintenance_media ;;' in source
    assert '[ "${ALLOW_MEDIA_MAINTENANCE:-0}" = "1" ]' in maintenance
    assert '[ "$SKIP_BACKUP" != "1" ]' in maintenance
    assert maintenance.index("ALLOW_MEDIA_MAINTENANCE") < maintenance.index(
        "wait_for_health"
    ) < maintenance.index("backup_database") < maintenance.index(
        "backfill_public_feed_videos"
    )
    assert "compose exec -T bot python -m scripts.backfill_feed_video_media" in backfill
    assert "maintenance failed" in backfill
    assert "return 1" in backfill
