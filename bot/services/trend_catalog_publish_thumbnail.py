"""Best-effort publication-time JPGs for approved public Trends.

The editorial catalog deliberately never calls S3/FFmpeg during reads. Repair
missing posters at approval instead, using the same safe, durable generator as
the bounded operator backfill. An S3 outage cannot revert an already committed
prompt approval; offline backfill remains available for later reconciliation.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from typing import Any

from bot.services.trend_catalog_media_cache import cached_thumbnails, source_key

logger = logging.getLogger(__name__)
_PUBLISH_SEMAPHORE = asyncio.Semaphore(2)


def _timeout_seconds() -> float:
    try:
        return min(45.0, max(3.0, float(
            os.getenv("TREND_CATALOG_PUBLISH_POSTER_TIMEOUT_SECONDS", "15")
        )))
    except (TypeError, ValueError):
        return 15.0


async def ensure_published_trend_poster(prompt: Mapping[str, Any] | None) -> bool:
    """Persist a public JPEG for an approved Trend, before returning publish success.

    False is a recoverable media failure, not a reason to undo approval. Never
    load private, pending, non-Trend or external media into public thumbnails.
    """
    if not isinstance(prompt, Mapping):
        return False
    if prompt.get("status") != "approved" or not prompt.get("is_public"):
        return False
    tags = prompt.get("tags")
    if not isinstance(tags, (tuple, list, set)) or "trend" not in tags:
        return False
    url = str(prompt.get("preview_url") or "").strip()
    key = source_key(url)
    if not key:
        return False

    trend_id = prompt.get("id")
    try:
        async with asyncio.timeout(_timeout_seconds()):
            async with _PUBLISH_SEMAPHORE:
                if key in await cached_thumbnails([url]):
                    return True
                # Reuse the single existing bounded source→JPEG→S3→manifest
                # pipeline, never a second conversion implementation.
                from scripts.backfill_trend_catalog_media import generate_thumbnail
                result = await generate_thumbnail(url)
                if not result:
                    logger.warning("Trend poster unavailable after approval: trend_id=%s", trend_id)
                    return False
                logger.info("Trend poster persisted after approval: trend_id=%s", trend_id)
                return True
    except Exception as exc:  # noqa: BLE001 -- approval is already durable
        logger.warning(
            "Trend poster generation failed after approval: trend_id=%s error=%s",
            trend_id, type(exc).__name__,
        )
        return False
