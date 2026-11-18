"""Serve small *public* Trend JPG previews inline from our own origin.

Do not redirect browsers/WebViews to the private S3 endpoint: the signed S3
host may be unreachable or blocked for users even though server probes work.
Original generation media continue using the existing signed redirect route.
"""
from __future__ import annotations

import asyncio
import logging
import re

from aiohttp import web

from bot.services.media_storage import (
    S3Settings,
    _is_missing_object_error,
    _s3_client,
    object_key,
)

logger = logging.getLogger(__name__)

# This narrow public namespace matches both the catalog hash thumbnails and
# existing preview-job hash JPGs. It cannot reach private media or originals.
_PUBLIC_POSTER_RE = re.compile(r"(?:catalog|[0-9]{6})/[0-9a-f]{24,64}\.jpg")
MAX_PUBLIC_POSTER_BYTES = 2 * 1024 * 1024
_PUBLIC_CACHE_CONTROL = "public, max-age=3600, s-maxage=86400"


class PosterTooLargeError(Exception):
    def __init__(self, size: int):
        self.size = size
        super().__init__("Trend poster exceeds public size limit")


def _read_public_trend_poster(relative: str) -> bytes:
    """Fetch a bounded JPEG from S3; called only in an executor thread."""
    settings = S3Settings.from_config()
    result = _s3_client(settings).get_object(
        Bucket=settings.bucket,
        Key=object_key(relative, settings),
        Range=f"bytes=0-{MAX_PUBLIC_POSTER_BYTES}",
    )
    body = result["Body"]
    try:
        # Range protects against downloading huge accidental uploads; also
        # inspect the full object size so we never return a truncated image.
        content_range = str(result.get("ContentRange") or "")
        match = re.fullmatch(r"bytes \d+-\d+/(\d+)", content_range)
        total = int(match.group(1)) if match else None
        if total is not None and total > MAX_PUBLIC_POSTER_BYTES:
            raise PosterTooLargeError(total)
        payload = body.read(MAX_PUBLIC_POSTER_BYTES + 1)
        if len(payload) > MAX_PUBLIC_POSTER_BYTES:
            raise PosterTooLargeError(len(payload))
        if not payload.startswith(b"\xff\xd8"):
            raise ValueError("Stored public trend poster is not a JPEG")
        return payload
    finally:
        body.close()


async def serve_public_trend_poster(request: web.Request) -> web.Response:
    """Public GET/HEAD for /uploads/trend-previews/...jpg without HTTP 307."""
    name = str(request.match_info.get("poster_path") or "")
    if not _PUBLIC_POSTER_RE.fullmatch(name):
        raise web.HTTPNotFound(text="Poster not found")
    try:
        payload = await asyncio.to_thread(
            _read_public_trend_poster, "trend-previews/" + name,
        )
    except PosterTooLargeError as exc:
        logger.warning("Public trend poster exceeds limit; size=%s", exc.size)
        raise web.HTTPRequestEntityTooLarge(
            max_size=MAX_PUBLIC_POSTER_BYTES, actual_size=exc.size,
        ) from exc
    except Exception as exc:
        if _is_missing_object_error(exc):
            raise web.HTTPNotFound(text="Poster not found") from exc
        logger.warning(
            "Public trend poster unavailable; error=%s", type(exc).__name__,
        )
        raise web.HTTPServiceUnavailable(
            text="Poster temporarily unavailable",
        ) from exc

    response = web.Response(body=payload, content_type="image/jpeg")
    response.headers["Cache-Control"] = _PUBLIC_CACHE_CONTROL
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
