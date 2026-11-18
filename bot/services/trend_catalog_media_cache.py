"""Durable catalog poster mapping. Catalog reads never call S3 or ffmpeg.

Preview thumbnails are generated explicitly by bounded maintenance jobs and are
stored in the same public upload bucket as their immutable originals.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from urllib.parse import unquote, urlsplit

from bot import db as db_backend
from bot.config import config
from bot.services.media_storage import is_s3_enabled, presigned_upload_url

logger = logging.getLogger(__name__)
_ALLOWED_HOSTS = frozenset({
    "neuromixbot.com", "vk.neuromixbot.com",
    "tanyapp.chillcreative.ru", "tanyapi.chillcreative.ru",
    "cdn.chillcreative.ru", "tanyapp.xn--e1aikcel5c5a.online",
})
_SOURCE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".avif",
                    ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi")
# Posters are public assets. Keep direct S3 signatures for a bounded fraction
# of their configured expiry, so repeated catalog reads don't re-sign ~100 URLs.
# URLs stay short-lived; the durable /uploads URL is always returned as fallback.
_signed_poster_lock = threading.Lock()
_signed_poster_cache: dict[str, tuple[float, str]] = {}
_SIGNED_POSTER_CACHE_MAX_ITEMS = 2048


def _signed_preview_now() -> float:
    return time.monotonic()


def _signed_preview_cache_seconds() -> int:
    try:
        return max(1, int(config.MEDIA_S3_PRESIGN_TTL_SECONDS) // 2)
    except (ValueError, TypeError):
        return 0


_TABLE = """
    CREATE TABLE IF NOT EXISTS trend_catalog_preview_assets (
        source_key TEXT PRIMARY KEY,
        thumbnail_url TEXT NOT NULL,
        updated_at BIGINT NOT NULL
    )
"""


def source_key(value: str | None) -> str | None:
    """Normalize only known public /uploads URLs; never persist signed URLs."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        url = urlsplit(value.strip())
        if url.scheme and url.scheme != "https":
            return None
        if url.netloc and (url.hostname or "").lower() not in _ALLOWED_HOSTS:
            return None
        raw_path = unquote(url.path)
        if not raw_path.startswith("/uploads/") or "\\" in raw_path:
            return None
        parts = raw_path.split("/")
        if any(part in ("", ".", "..") for part in parts[2:]):
            return None
        if not raw_path.lower().endswith(_SOURCE_SUFFIXES):
            return None
        return raw_path
    except ValueError:
        return None


async def initialize() -> None:
    async with db_backend.connect() as conn:
        if db_backend.is_postgres():
            await conn.execute_native_ddl(_TABLE)
        else:
            await conn.execute(_TABLE)
        await conn.commit()


async def record_thumbnail(source_url: str, thumbnail_url: str) -> None:
    key = source_key(source_url)
    thumbnail = source_key(thumbnail_url)
    if not key or not thumbnail or not thumbnail.startswith("/uploads/trend-previews/catalog/"):
        raise ValueError("Only verified catalog thumbnails may be recorded")
    await initialize()
    async with db_backend.connect() as conn:
        await conn.execute(
            """INSERT INTO trend_catalog_preview_assets (source_key, thumbnail_url, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT (source_key) DO UPDATE SET
                   thumbnail_url = excluded.thumbnail_url,
                   updated_at = excluded.updated_at""",
            (key, thumbnail_url, int(time.time())),
        )
        await conn.commit()


async def cached_thumbnails(source_urls: list[str]) -> dict[str, str]:
    """One database read per catalog page, never per card and never an S3 HEAD."""
    keys = list(dict.fromkeys(key for url in source_urls if (key := source_key(url))))
    if not keys:
        return {}
    # Bound query size and avoid untrusted URLs in SQL structure.
    if len(keys) > 500:
        keys = keys[:500]
    try:
        async with db_backend.connect() as conn:
            rows = await (await conn.execute(
                "SELECT source_key, thumbnail_url FROM trend_catalog_preview_assets WHERE source_key IN ("
                + ",".join("?" for _ in keys) + ")",
                tuple(keys),
            )).fetchall()
        return {str(row[0]): str(row[1]) for row in rows
                if source_key(str(row[1]))
                and str(row[1]).split("/uploads/", 1)[-1].startswith("trend-previews/catalog/")}
    except Exception:  # noqa: BLE001 -- optional read-side cache must fail open
        # Before the first explicit backfill the table need not exist.
        # A read-only storefront must never fail just because previews are absent.
        logger.debug("Trend preview manifest unavailable; originals remain accessible")
        return {}


async def enrich_cards(cards: list[dict]) -> None:
    if not cards:
        return
    by_key = await cached_thumbnails([
        str(card.get("preview_url") or "") for card in cards
        if not card.get("preview_poster_url")
    ])
    for card in cards:
        if card.get("preview_poster_url"):
            continue
        key = source_key(card.get("preview_url"))
        if key and key in by_key:
            card["preview_poster_url"] = by_key[key]

    # The durable URL stays unchanged. For the gallery we also expose a
    # short-lived direct S3 URL, avoiding an extra no-store 307 per thumbnail.
    # The client falls back to the durable URL if the signer's TTL expires
    # while a Mini App session is open. Never sign original photos/videos.
    if not is_s3_enabled():
        return
    keys = list(dict.fromkeys(
        key for card in cards
        if (key := source_key(card.get("preview_poster_url")))
        and key.startswith("/uploads/trend-previews/")
        and key.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".avif"))
    ))
    if not keys:
        return
    signed = await asyncio.to_thread(_sign_public_poster_urls, keys)
    for card in cards:
        key = source_key(card.get("preview_poster_url"))
        if key in signed:
            card["preview_poster_fast_url"] = signed[key]



def _sign_public_poster_urls(keys: list[str]) -> dict[str, str]:
    """Sign only public preview images; reuse bounded short-lived local results.

    Never HEAD/GET S3 in a catalog read. The signature is safe to share because
    the corresponding preview is already publicly served via /uploads.
    """
    result: dict[str, str] = {}
    cache_seconds = _signed_preview_cache_seconds()
    for key in keys:
        with _signed_poster_lock:
            now = _signed_preview_now()
            cached = _signed_poster_cache.get(key)
            if cached and cached[0] > now:
                result[key] = cached[1]
                continue
            try:
                url = presigned_upload_url(key.removeprefix("/uploads/"), method="GET")
            except Exception:  # noqa: BLE001 -- durable /uploads poster remains usable
                _signed_poster_cache.pop(key, None)
                logger.warning("Could not sign one public trend preview; stable URL retained")
                continue
            result[key] = url
            if cache_seconds > 0:
                if key not in _signed_poster_cache and len(_signed_poster_cache) >= _SIGNED_POSTER_CACHE_MAX_ITEMS:
                    _signed_poster_cache.pop(next(iter(_signed_poster_cache)))
                _signed_poster_cache[key] = (now + cache_seconds, url)
    return result
