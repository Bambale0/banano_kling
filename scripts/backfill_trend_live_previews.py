"""Bounded, resumable S3 backfill for short public video Trend grid loops.

Dry-run unless --execute is explicitly specified. Never rewrites original
media, paid task output, reference assets, prompt recipes or balances.

Usage (production container):
  python -m scripts.backfill_trend_live_previews --limit 40
  python -m scripts.backfill_trend_live_previews --limit 40 --execute
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from bot import db as db_backend
from bot.services.trend_catalog_live_video import generate_live_preview
from bot.services.trend_catalog_media_cache import (
    cached_live_previews,
    source_key,
)
from bot.services.trend_preview_service import VIDEO_PREVIEW_EXTENSIONS

logger = logging.getLogger(__name__)


async def run(*, limit: int = 40, execute: bool = False) -> dict[str, int]:
    max_attempts = max(1, min(200, int(limit)))
    async with db_backend.connect() as conn:
        rows = await (await conn.execute(
            """SELECT id, preview_url FROM user_prompts
               WHERE status = 'approved' AND is_public = TRUE
                 AND category = 'video'
                 AND LOWER(COALESCE(tags, '')) LIKE '%"trend"%'
               ORDER BY id DESC LIMIT 500"""
        )).fetchall()

    urls = [str(row[1] or "") for row in rows]
    have = await cached_live_previews(urls)
    out = {
        "visible": len(rows), "with_live_preview": 0,
        "missing": 0, "attempted": 0, "created": 0,
        "failed": 0, "skipped": 0,
    }
    pending = []
    seen = set()
    for row in rows:
        url = str(row[1] or "")
        key = source_key(url)
        if not key or Path(key).suffix.lower() not in VIDEO_PREVIEW_EXTENSIONS:
            out["skipped"] += 1
            continue
        if key in have:
            out["with_live_preview"] += 1
            continue
        if key not in seen:
            seen.add(key)
            pending.append((row[0], url))
    out["missing"] = len(pending)
    if not execute:
        return out

    for trend_id, url in pending[:max_attempts]:
        out["attempted"] += 1
        try:
            if await generate_live_preview(url):
                out["created"] += 1
            else:
                out["failed"] += 1
                logger.warning("Live Trend source unavailable: trend_id=%s", trend_id)
        except Exception as exc:  # noqa: BLE001 -- isolate each public conversion
            out["failed"] += 1
            logger.warning(
                "Live Trend backfill failed: trend_id=%s type=%s",
                trend_id, type(exc).__name__,
            )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 200:
        parser.error("--limit must be between 1 and 200")
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(run(limit=args.limit, execute=args.execute)))


if __name__ == "__main__":
    main()
