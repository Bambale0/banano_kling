from __future__ import annotations

import asyncio
from pathlib import Path

from bot.services import trend_preview_service


def test_local_video_preview_gets_compressed_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    source = Path("static/uploads/trends/original.mp4")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"original video bytes")

    def fake_run_ffmpeg_preview(source_path: Path, output_path: Path) -> None:
        assert source_path == source
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"compressed")

    monkeypatch.setattr(
        trend_preview_service,
        "_run_ffmpeg_preview",
        fake_run_ffmpeg_preview,
    )

    result = asyncio.run(
        trend_preview_service.ensure_lightweight_trend_preview_url(
            "/uploads/trends/original.mp4"
        )
    )

    assert result is not None
    assert "/uploads/trend-previews/" in result
    assert result.endswith(".mp4")
    assert list(Path("static/uploads/trend-previews").rglob("*.mp4"))


def test_non_video_preview_is_left_unchanged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    source = Path("static/uploads/trends/cover.jpg")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"jpg")

    result = asyncio.run(
        trend_preview_service.ensure_lightweight_trend_preview_url(
            "/uploads/trends/cover.jpg"
        )
    )

    assert result == "/uploads/trends/cover.jpg"


def test_catalog_read_does_not_materialize_missing_s3_objects(
    tmp_path: Path, monkeypatch
) -> None:
    """An S3 cache miss must not block the Mini App catalog's event loop."""
    from bot.config import config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "MEDIA_STORAGE_BACKEND", "s3")

    def unexpected_download(*_args, **_kwargs):
        raise AssertionError("Catalog must not download objects from S3")

    monkeypatch.setattr(trend_preview_service, "resolve_local_upload_path", unexpected_download)
    monkeypatch.setattr(trend_preview_service, "_materialize_derived", unexpected_download)

    original = "https://neuromixbot.com/uploads/trends/missing.mp4"
    assert trend_preview_service.cached_trend_preview_assets(original) == {
        "preview_url": original,
        "preview_poster_url": None,
    }


def test_catalog_read_uses_existing_local_derivatives_without_s3(
    tmp_path: Path, monkeypatch
) -> None:
    from bot.config import config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "MEDIA_STORAGE_BACKEND", "s3")
    source = Path("static/uploads/trends/source.mp4")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"original-video")
    original = "/uploads/trends/source.mp4"

    mp4 = trend_preview_service._preview_output_path(source, original)
    poster = trend_preview_service._poster_output_path(source, original)
    mp4.parent.mkdir(parents=True)
    mp4.write_bytes(b"cached-mp4")
    poster.write_bytes(b"cached-poster")

    def unexpected_download(*_args, **_kwargs):
        raise AssertionError("Catalog must not download objects from S3")

    monkeypatch.setattr(trend_preview_service, "resolve_local_upload_path", unexpected_download)
    monkeypatch.setattr(trend_preview_service, "_materialize_derived", unexpected_download)
    assets = trend_preview_service.cached_trend_preview_assets(original)

    assert "/uploads/trend-previews/" in str(assets["preview_url"])
    assert str(assets["preview_url"]).endswith(".mp4")
    assert "/uploads/trend-previews/" in str(assets["preview_poster_url"])
    assert str(assets["preview_poster_url"]).endswith(".jpg")


def test_explicit_preview_generation_offloads_source_materialization(
    tmp_path: Path, monkeypatch
) -> None:
    """Even an explicit preview generation must not block its event loop."""
    monkeypatch.chdir(tmp_path)
    original = "/uploads/trends/remote.mp4"
    local = Path("static/uploads/trends/remote.mp4")
    local.parent.mkdir(parents=True)
    local.write_bytes(b"source")
    calls = []

    def fake_resolve(_url: str):
        import threading

        calls.append(threading.current_thread().name)
        return str(local)

    def fake_preview(_source: Path, destination: Path):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"preview")

    monkeypatch.setattr(trend_preview_service, "resolve_local_upload_path", fake_resolve)
    monkeypatch.setattr(trend_preview_service, "_run_ffmpeg_preview", fake_preview)
    monkeypatch.setattr(trend_preview_service, "_run_ffmpeg_poster", fake_preview)
    monkeypatch.setattr(
        trend_preview_service,
        "_persist_derived",
        lambda path, *, content_type: f"/uploads/{path.name}",
    )
    asyncio.run(trend_preview_service.ensure_trend_preview_assets(original))

    assert calls and all(name != "MainThread" for name in calls)
