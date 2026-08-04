from __future__ import annotations

from pathlib import Path
import asyncio

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
