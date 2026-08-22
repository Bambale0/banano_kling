from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import subprocess
from pathlib import Path

from bot.config import config
from bot.services.media_input_utils import resolve_local_upload_path

logger = logging.getLogger(__name__)

VIDEO_PREVIEW_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
TREND_PREVIEW_VERSION = "full-v2"
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
        payload = f"{TREND_PREVIEW_VERSION}|{public_url}|{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
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
    rel_url = str(rel_path).replace(os.sep, "/")
    return f"{config.static_base_url.rstrip('/')}/uploads/{rel_url}"


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
        "-an",
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
    preview_public_url = _preview_public_url(output_path)
    poster_public_url = _preview_public_url(poster_path)

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
        result["preview_url"] = preview_public_url
    if poster_path.exists() and poster_path.stat().st_size > 0:
        result["preview_poster_url"] = poster_public_url
    return result


async def ensure_lightweight_trend_preview_url(preview_url: str | None) -> str | None:
    """Return a compressed local MP4 preview URL for video trend cards.

    The original media remains untouched. Non-local or non-video URLs are returned
    unchanged so externally hosted previews keep working.
    """

    assets = await ensure_trend_preview_assets(preview_url)
    return assets["preview_url"]
