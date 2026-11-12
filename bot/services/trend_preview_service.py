from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import subprocess
from pathlib import Path

from bot.services.media_input_utils import resolve_local_upload_path

logger = logging.getLogger(__name__)

VIDEO_PREVIEW_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
TREND_PREVIEW_VERSION = "full-v3-audio"
TREND_PREVIEW_MAX_WIDTH = int(os.getenv("TREND_PREVIEW_MAX_WIDTH", "480"))
TREND_PREVIEW_FPS = int(os.getenv("TREND_PREVIEW_FPS", "12"))
TREND_PREVIEW_CRF = int(os.getenv("TREND_PREVIEW_CRF", "32"))
TREND_PREVIEW_POSTER_SECONDS = float(os.getenv("TREND_PREVIEW_POSTER_SECONDS", "0.5"))
TREND_PREVIEW_UPLOAD_SUBDIR = "trend-previews"


def _safe_int(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _is_video_preview_source(source: Path) -> bool:
    return source.suffix.lower() in VIDEO_PREVIEW_EXTENSIONS


def _preview_digest(source: Path, public_url: str) -> str:
    try:
        stat = source.stat()
        payload = f"{TREND_PREVIEW_VERSION}|{public_url}|{stat.st_size}"
    except OSError:
        payload = f"{TREND_PREVIEW_VERSION}|{public_url}|{source}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _preview_output_path(source: Path, public_url: str) -> Path:
    digest = _preview_digest(source, public_url)
    period = "current"
    try:
        period = source.stat().st_mtime_ns and str(source.stat().st_mtime_ns)[:6]
    except OSError:
        pass
    return Path("static") / "uploads" / TREND_PREVIEW_UPLOAD_SUBDIR / period / f"{digest}.mp4"


def _poster_output_path(source: Path, public_url: str) -> Path:
    return _preview_output_path(source, public_url).with_suffix(".jpg")


def _preview_public_url(output_path: Path) -> str:
    rel_path = output_path.relative_to(Path("static") / "uploads")
    from bot.services.media_storage import public_upload_url

    return public_upload_url(str(rel_path).replace(os.sep, "/"))


def _materialize_derived(path: Path) -> Path:
    if path.is_file():
        return path
    from bot.services.media_storage import materialize_upload

    relative = path.relative_to(Path("static/uploads")).as_posix()
    materialized = materialize_upload(relative)
    return Path(materialized) if materialized else path


def _persist_derived(path: Path, *, content_type: str) -> str:
    from bot.services.media_storage import persist_upload_file

    relative = path.relative_to(Path("static/uploads")).as_posix()
    return persist_upload_file(
        relative,
        path,
        content_type=content_type,
        cache_control="public, max-age=31536000, immutable",
    )


def _run_ffmpeg_preview(source: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".tmp.mp4")
    tmp_path.unlink(missing_ok=True)

    max_width = _safe_int(TREND_PREVIEW_MAX_WIDTH, minimum=240, maximum=960)
    fps = _safe_int(TREND_PREVIEW_FPS, minimum=8, maximum=24)
    crf = _safe_int(TREND_PREVIEW_CRF, minimum=26, maximum=38)
    scale_filter = f"scale=w='min({max_width},iw)':h=-2"

    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        scale_filter,
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-profile:v",
        "baseline",
        "-level",
        "3.0",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-movflags",
        "+faststart",
        "-crf",
        str(crf),
        str(tmp_path),
    ]
    subprocess.run(command, check=True, timeout=120)
    tmp_path.replace(output_path)


def _run_ffmpeg_poster(source: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".tmp.jpg")
    tmp_path.unlink(missing_ok=True)

    max_width = _safe_int(TREND_PREVIEW_MAX_WIDTH, minimum=240, maximum=960)
    seek_seconds = max(0.0, min(3.0, float(TREND_PREVIEW_POSTER_SECONDS)))
    scale_filter = f"scale=w='min({max_width},iw)':h=-2"

    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(seek_seconds),
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        scale_filter,
        "-q:v",
        "4",
        str(tmp_path),
    ]
    subprocess.run(command, check=True, timeout=30)
    tmp_path.replace(output_path)


def cached_trend_preview_assets(preview_url: str | None) -> dict[str, str | None]:
    """Resolve only existing small MP4/poster derivatives.

    Catalog reads must not launch ffmpeg for dozens of rows. The normal preview
    pipeline or an explicit backfill can populate the deterministic cache.
    """
    result = {"preview_url": preview_url, "preview_poster_url": None}
    if not preview_url:
        return result
    source_name = resolve_local_upload_path(preview_url)
    if not source_name:
        return result
    source = Path(source_name)
    if not source.is_file() or not _is_video_preview_source(source):
        return result
    mp4 = _preview_output_path(source, preview_url)
    poster = _poster_output_path(source, preview_url)
    mp4 = _materialize_derived(mp4)
    poster = _materialize_derived(poster)
    if mp4.is_file() and mp4.stat().st_size > 0:
        result["preview_url"] = _preview_public_url(mp4)
    if poster.is_file() and poster.stat().st_size > 0:
        result["preview_poster_url"] = _preview_public_url(poster)
    return result


async def ensure_trend_preview_assets(preview_url: str | None) -> dict[str, str | None]:
    """Return card-friendly video preview assets for local trend videos."""

    result = {"preview_url": preview_url, "preview_poster_url": None}
    if not preview_url:
        return result

    local_path = resolve_local_upload_path(preview_url)
    if not local_path:
        return result

    source = Path(local_path)
    if not source.exists() or not source.is_file() or not _is_video_preview_source(source):
        return result

    output_path = _preview_output_path(source, preview_url)
    poster_path = _poster_output_path(source, preview_url)
    if not output_path.exists() or output_path.stat().st_size <= 0:
        try:
            await asyncio.to_thread(_run_ffmpeg_preview, source, output_path)
        except Exception:
            logger.exception(
                "Failed to build lightweight trend preview: source=%s preview_url=%s",
                source,
                preview_url,
            )
            output_path.unlink(missing_ok=True)

    if not poster_path.exists() or poster_path.stat().st_size <= 0:
        try:
            await asyncio.to_thread(_run_ffmpeg_poster, source, poster_path)
        except Exception:
            logger.exception(
                "Failed to build trend preview poster: source=%s preview_url=%s",
                source,
                preview_url,
            )
            poster_path.unlink(missing_ok=True)

    if output_path.exists() and output_path.stat().st_size > 0:
        result["preview_url"] = await asyncio.to_thread(
            _persist_derived, output_path, content_type="video/mp4"
        )
    if poster_path.exists() and poster_path.stat().st_size > 0:
        result["preview_poster_url"] = await asyncio.to_thread(
            _persist_derived, poster_path, content_type="image/jpeg"
        )
    return result


async def ensure_lightweight_trend_preview_url(preview_url: str | None) -> str | None:
    """Return a compressed local MP4 preview URL for video trend cards.

    The original media remains untouched. Non-local or non-video URLs are returned
    unchanged so externally hosted previews keep working.
    """

    assets = await ensure_trend_preview_assets(preview_url)
    return assets["preview_url"]
