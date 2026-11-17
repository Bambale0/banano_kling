"""Bounded, resumable thumbnail backfill for public curated Trend cards.

Run inside the bot container: python -m scripts.backfill_trend_catalog_media --limit 20
Read-only by default; add --execute to download originals, create ~480px JPEG
thumbnails and store their durable S3 URLs. No originals or recipes are changed.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
from pathlib import Path

from bot import trend_catalog
from bot.services.media_input_utils import resolve_local_upload_path
from bot.services.media_storage import persist_upload_file
from bot.services.trend_catalog_media_cache import (
    cached_thumbnails,
    record_thumbnail,
    source_key,
)
from bot.services.trend_preview_service import (
    VIDEO_PREVIEW_EXTENSIONS,
    _run_ffmpeg_poster,
)

logger = logging.getLogger(__name__)
MAX_SOURCE_BYTES = 200 * 1024 * 1024
THUMBNAIL_DIR = Path("static/uploads/trend-previews/catalog")
THUMBNAIL_VERSION = "v1-480-jpeg"


def _image_thumbnail(source: Path, target: Path) -> None:
    from PIL import Image, ImageOps

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp.jpg")
    try:
        with Image.open(source) as original:
            if original.width * original.height > 75_000_000:
                raise ValueError("Image too large to create a thumbnail safely")
            frame = ImageOps.exif_transpose(original).convert("RGB")
            frame.thumbnail((480, 640), Image.Resampling.LANCZOS)
            frame.save(temp, "JPEG", quality=78, optimize=True)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


async def generate_thumbnail(preview_url: str) -> str | None:
    key = source_key(preview_url)
    if key is None:
        return None
    digest = hashlib.sha256((THUMBNAIL_VERSION + "|" + key).encode()).hexdigest()[:32]
    destination = THUMBNAIL_DIR / f"{digest}.jpg"
    source_name = await asyncio.to_thread(resolve_local_upload_path, preview_url)
    if not source_name:
        return None
    source = Path(source_name)
    if not source.is_file() or not 0 < source.stat().st_size <= MAX_SOURCE_BYTES:
        return None
    if not destination.exists() or destination.stat().st_size == 0:
        if source.suffix.lower() in VIDEO_PREVIEW_EXTENSIONS:
            await asyncio.to_thread(_run_ffmpeg_poster, source, destination)
        else:
            await asyncio.to_thread(_image_thumbnail, source, destination)
    # S3 confirmation occurs before publishing manifest. Originals stay untouched.
    relative = destination.relative_to(Path("static/uploads")).as_posix()
    thumbnail_url = await asyncio.to_thread(
        persist_upload_file, relative, destination,
        content_type="image/jpeg", cache_control="public, max-age=31536000, immutable",
    )
    await record_thumbnail(preview_url, thumbnail_url)
    return thumbnail_url


async def run(*, limit: int = 20, execute: bool = False) -> dict[str, int]:
    # Prioritize what users see on the initial Trends screen, in display order.
    categories = await trend_catalog.list_catalog(is_admin=False, per_category=6)
    urls = list(dict.fromkeys(
        url for cat in categories for item in cat.get("items", [])
        if (url := str(item.get("preview_url") or "")) and source_key(url)
    ))
    outcome = {"total_visible": len(urls), "checked": 0,
               "cached": 0, "created": 0, "failed": 0, "skipped": 0}
    urls = urls[:limit]
    existing = await cached_thumbnails(urls)
    for url in urls:
        outcome["checked"] += 1
        if source_key(url) in existing:
            outcome["cached"] += 1
            continue
        if not execute:
            outcome["skipped"] += 1
            continue
        try:
            if await generate_thumbnail(url):
                outcome["created"] += 1
            else:
                outcome["skipped"] += 1
        except Exception:  # noqa: BLE001 -- bounded maintenance isolates per-item errors
            # Avoid printing birth data, URLs or private provider references.
            logger.warning("Trend thumbnail backfill failed for item index=%s", outcome["checked"])
            outcome["failed"] += 1
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 200:
        parser.error("--limit must be between 1 and 200")
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(run(limit=args.limit, execute=args.execute)))


if __name__ == "__main__":
    main()
