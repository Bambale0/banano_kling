from __future__ import annotations

import asyncio
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from bot.services import trend_preview_service


@pytest.mark.parametrize(
    ("renderer_name", "suffix"),
    [
        ("_run_ffmpeg_preview", ".mp4"),
        ("_run_ffmpeg_poster", ".jpg"),
    ],
)
def test_simultaneous_trend_renderers_both_finish_without_temporary_file_race(
    tmp_path: Path, monkeypatch, renderer_name: str, suffix: str
) -> None:
    """A shared output key must not mean a shared ffmpeg temporary file."""
    monkeypatch.chdir(tmp_path)
    source = Path("source.mp4")
    source.write_bytes(b"source")
    output = Path("static/uploads/trend-previews/current/preview" + suffix)
    barrier = threading.Barrier(2, timeout=5)
    temporary_paths: list[str] = []
    guard = threading.Lock()

    def fake_ffmpeg(command: list[str], *, check: bool, timeout: int) -> None:
        assert check is True
        temporary_path = Path(command[-1])
        temporary_path.write_bytes(b"rendered")
        with guard:
            temporary_paths.append(str(temporary_path))
        barrier.wait()

    monkeypatch.setattr(trend_preview_service.subprocess, "run", fake_ffmpeg)
    renderer = getattr(trend_preview_service, renderer_name)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            pool.submit(renderer, source, output)
            for _ in range(2)
        ]
        failures = [future.exception() for future in results]

    assert failures == [None, None]
    assert len(temporary_paths) == 2
    assert len(set(temporary_paths)) == 2
    assert output.read_bytes() == b"rendered"
    assert not list(output.parent.glob("*.tmp" + suffix))


def test_failed_renderer_cannot_delete_a_peer_rendered_preview(
    tmp_path: Path, monkeypatch
) -> None:
    """A failed parallel task must preserve the valid atomic output of its peer."""
    monkeypatch.chdir(tmp_path)
    source = Path("static/uploads/trends/source.mp4")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"original-video")
    original = "/uploads/trends/source.mp4"

    def failed_render(_source: Path, output: Path) -> None:
        # The other renderer completed and renamed its own temp file.
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"valid-preview-from-peer")
        raise OSError("this renderer failed after peer published")

    def make_poster(_source: Path, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"valid-poster")

    monkeypatch.setattr(
        trend_preview_service, "resolve_local_upload_path", lambda _: str(source)
    )
    monkeypatch.setattr(trend_preview_service, "_run_ffmpeg_preview", failed_render)
    monkeypatch.setattr(trend_preview_service, "_run_ffmpeg_poster", make_poster)
    monkeypatch.setattr(
        trend_preview_service,
        "_persist_derived",
        lambda path, *, content_type: "/uploads/" + path.relative_to(
            Path("static/uploads")
        ).as_posix(),
    )

    result = asyncio.run(trend_preview_service.ensure_trend_preview_assets(original))

    assert result["preview_url"] != original
    assert str(result["preview_url"]).endswith(".mp4")
    output = trend_preview_service._preview_output_path(source, original)
    assert output.read_bytes() == b"valid-preview-from-peer"


def test_failed_ffmpeg_removes_its_own_temporary_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    source = Path("source.mp4")
    source.write_bytes(b"original-video")
    output = Path("static/uploads/trend-previews/current/failing.mp4")

    def failed_ffmpeg(command: list[str], *, check: bool, timeout: int) -> None:
        tmp = Path(command[-1])
        tmp.write_bytes(b"partial")
        raise subprocess.CalledProcessError(returncode=1, cmd=command)

    monkeypatch.setattr(trend_preview_service.subprocess, "run", failed_ffmpeg)

    with pytest.raises(subprocess.CalledProcessError):
        trend_preview_service._run_ffmpeg_preview(source, output)

    assert not output.exists()
    assert not list(output.parent.glob("*.tmp.mp4"))
