"""Durable muted H.264 loops for public Trend grid tiles.

Full originals remain untouched for detail/repeat. Compact 4-second clips are
generated only off the API read path, persisted to S3, and indexed by canonical
public source. The background reconciler also recovers abandoned approvals
after a process restart without an external queue.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import subprocess
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from bot import db as db_backend
from bot.services.media_input_utils import resolve_local_upload_path
from bot.services.media_storage import (
    is_s3_enabled,
    persist_upload_file,
    remote_upload_size,
)
from bot.services.trend_catalog_media_cache import (
    cached_live_previews,
    record_live_preview,
    source_key,
)
from bot.services.trend_preview_service import VIDEO_PREVIEW_EXTENSIONS

logger = logging.getLogger(__name__)
MAX_SOURCE_BYTES = 200 * 1024 * 1024
LIVE_DIR = Path("static/uploads/trend-previews/live")
LIVE_VERSION = "muted-loop-h264-faststart-v1"
_VIDEO_SEMAPHORE = asyncio.Semaphore(1)
_ACTIVE: set[asyncio.Task[object]] = set()


def _number(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(os.getenv(name, str(default)))))
    except (ValueError, TypeError):
        return default


def _destination(source_key_value: str) -> Path:
    params = (
        LIVE_VERSION,
        str(_number("TREND_LIVE_PREVIEW_SECONDS", 4, 2, 6)),
        str(_number("TREND_LIVE_PREVIEW_FPS", 12, 8, 20)),
        str(_number("TREND_LIVE_PREVIEW_WIDTH", 480, 240, 720)),
        source_key_value,
    )
    digest = hashlib.sha256("|".join(params).encode("utf-8")).hexdigest()[:32]
    return LIVE_DIR / f"{digest}.mp4"


def _encode_live_preview(source: Path, destination: Path) -> None:
    """Produce a short, muted, fast-start H.264 file, never rewrite the source."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.stem + "." + uuid4().hex + ".tmp.mp4")
    duration = _number("TREND_LIVE_PREVIEW_SECONDS", 4, 2, 6)
    fps = _number("TREND_LIVE_PREVIEW_FPS", 12, 8, 20)
    width = _number("TREND_LIVE_PREVIEW_WIDTH", 480, 240, 720)
    timeout = _number("TREND_LIVE_FFMPEG_TIMEOUT_SECONDS", 90, 20, 180)
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source), "-t", str(duration), "-map", "0:v:0",
        "-an", "-vf", f"scale=w='min({width},iw)':h=-2",
        "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast",
        "-profile:v", "baseline", "-level", "3.0",
        "-pix_fmt", "yuv420p", "-crf", "32",
        "-movflags", "+faststart", str(temp),
    ]
    try:
        subprocess.run(command, check=True, timeout=timeout, capture_output=True)
        if not temp.is_file() or temp.stat().st_size < 64:
            raise ValueError("FFmpeg created an empty compact trend video")
        if temp.stat().st_size > 6 * 1024 * 1024:
            raise ValueError("Compact trend MP4 exceeds the same-origin proxy limit")
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)


async def generate_live_preview(original_url: str) -> str | None:
    """Idempotently materialize own public video, encode, upload and commit mapping."""
    key = source_key(original_url)
    if not key or Path(key).suffix.lower() not in VIDEO_PREVIEW_EXTENSIONS:
        return None
    existing = await cached_live_previews([original_url])
    if key in existing:
        return existing[key]
    async with _VIDEO_SEMAPHORE:
        existing = await cached_live_previews([original_url])
        if key in existing:
            return existing[key]
        if is_s3_enabled():
            size = await asyncio.to_thread(remote_upload_size, key.split("/uploads/", 1)[1])
            if size is None or not 0 < size <= MAX_SOURCE_BYTES:
                return None
        path = await asyncio.to_thread(resolve_local_upload_path, original_url)
        if not path:
            return None
        source = Path(path)
        if not source.is_file() or not 0 < source.stat().st_size <= MAX_SOURCE_BYTES:
            return None
        dest = _destination(key)
        if not dest.is_file() or dest.stat().st_size <= 0:
            await asyncio.to_thread(_encode_live_preview, source, dest)
        relative = dest.relative_to(Path("static/uploads")).as_posix()
        public_url = await asyncio.to_thread(
            persist_upload_file, relative, dest,
            content_type="video/mp4",
            cache_control="public, max-age=31536000, immutable",
        )
        await record_live_preview(original_url, public_url)
        return public_url


def _is_published_video(prompt: dict | None) -> bool:
    if not isinstance(prompt, dict):
        return False
    tags = prompt.get("tags") or ()
    return (
        prompt.get("status") == "approved"
        and prompt.get("is_public") is True
        and isinstance(tags, (list, tuple, set))
        and "trend" in tags
        and (
            prompt.get("category") == "video"
            or (source_key(prompt.get("preview_url")) or "").lower().endswith(
                tuple(VIDEO_PREVIEW_EXTENSIONS)
            )
        )
        and bool(source_key(prompt.get("preview_url")))
    )


async def _generate_for_published(prompt: dict) -> None:
    try:
        async with asyncio.timeout(
            _number("TREND_LIVE_PUBLISH_TIMEOUT_SECONDS", 120, 20, 180)
        ):
            result = await generate_live_preview(str(prompt["preview_url"]))
        if result:
            logger.info("Trend live preview persisted: trend_id=%s", prompt.get("id"))
        else:
            logger.warning("Trend live preview pending retry: trend_id=%s", prompt.get("id"))
    except Exception as exc:  # noqa: BLE001 -- publication must not be rolled back
        logger.warning(
            "Trend live preview failed after approval: trend_id=%s type=%s",
            prompt.get("id"), type(exc).__name__,
        )


def schedule_published_live_preview(prompt: dict | None) -> bool:
    """Nonblocking post-commit conversion, backed by periodic DB reconciliation."""
    if not _is_published_video(prompt):
        return False
    task = asyncio.create_task(_generate_for_published(prompt))
    _ACTIVE.add(task)
    task.add_done_callback(_ACTIVE.discard)
    return True


async def reconcile_live_previews(*, limit: int = 2) -> dict[str, int]:
    """Recover unpublished derivatives from DB after restarts/S3 failures."""
    count = max(1, min(12, int(limit)))
    async with db_backend.connect() as conn:
        rows = await (await conn.execute(
            """SELECT id, preview_url FROM user_prompts
               WHERE status = 'approved' AND is_public = 1
                 AND category = 'video'
                 AND LOWER(COALESCE(tags, '')) LIKE '%"trend"%'
               ORDER BY id DESC LIMIT 500"""
        )).fetchall()
    urls = [str(r[1] or "") for r in rows]
    have = await cached_live_previews(urls)
    stats = {"checked": len(rows), "created": 0, "failed": 0, "skipped": 0}
    for row in rows:
        source = str(row[1] or "")
        key = source_key(source)
        if not key or Path(key).suffix.lower() not in VIDEO_PREVIEW_EXTENSIONS:
            stats["skipped"] += 1
            continue
        if key in have:
            continue
        if stats["created"] + stats["failed"] >= count:
            break
        try:
            async with asyncio.timeout(
                _number("TREND_LIVE_RECONCILE_TIMEOUT_SECONDS", 120, 20, 180)
            ):
                output = await generate_live_preview(source)
            if output:
                stats["created"] += 1
            else:
                stats["failed"] += 1
                logger.warning("Trend live preview source missing: trend_id=%s", row[0])
        except Exception as exc:  # noqa: BLE001 -- one bad video must not block others
            stats["failed"] += 1
            logger.warning("Trend live preview retry failed: trend_id=%s type=%s", row[0], type(exc).__name__)
    return stats


async def _reconciliation_worker() -> None:
    await asyncio.sleep(_number("TREND_LIVE_RECONCILE_START_DELAY_SECONDS", 20, 5, 120))
    while True:
        try:
            summary = await reconcile_live_previews(
                limit=_number("TREND_LIVE_RECONCILE_BATCH_SIZE", 2, 1, 12),
            )
            if summary["created"] or summary["failed"]:
                logger.info("Trend live preview reconciliation: %s", summary)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- keep eventual retry healthy
            logger.warning("Trend live preview worker error: %s", type(exc).__name__)
        await asyncio.sleep(_number("TREND_LIVE_RECONCILE_INTERVAL_SECONDS", 180, 30, 3600))


async def live_preview_reconciliation_ctx(app):
    """Aiohttp lifecycle: ephemeral worker, durable worklist is public Trend rows."""
    enabled = os.getenv("TREND_LIVE_RECONCILE_ENABLED", "1").lower()
    task = None
    if enabled not in {"0", "false", "off"}:
        task = asyncio.create_task(_reconciliation_worker())
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
