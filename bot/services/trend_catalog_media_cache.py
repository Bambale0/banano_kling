"""Durable catalog poster mapping. Catalog reads never call S3 or ffmpeg.

Preview thumbnails are generated explicitly by bounded maintenance jobs and are
stored in the same public upload bucket as their immutable originals.
"""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import unquote, urlsplit

from bot import db as db_backend

logger = logging.getLogger(__name__)
_ALLOWED_HOSTS = frozenset({
    "neuromixbot.com", "vk.neuromixbot.com",
    "tanyapp.chillcreative.ru", "tanyapi.chillcreative.ru",
    "cdn.chillcreative.ru", "tanyapp.xn--e1aikcel5c5a.online",
})
_SOURCE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".avif",
                    ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi")
_TABLE = """
    CREATE TABLE IF NOT EXISTS trend_catalog_preview_assets (
        source_key TEXT PRIMARY KEY,
        thumbnail_url TEXT NOT NULL,
        updated_at BIGINT NOT NULL
    )
"""
_LIVE_TABLE = """
    CREATE TABLE IF NOT EXISTS trend_catalog_live_video_assets (
        source_key TEXT PRIMARY KEY,
        preview_url TEXT NOT NULL,
        updated_at BIGINT NOT NULL
    )
"""
_LIVE_OUTPUT_RE = re.compile(r"/uploads/trend-previews/live/[a-f0-9]{32}\.mp4")
_VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi")


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



async def initialize_live_previews() -> None:
    """Create the small independent live-clip manifest without migrating poster rows."""
    async with db_backend.connect() as conn:
        if db_backend.is_postgres():
            await conn.execute_native_ddl(_LIVE_TABLE)
        else:
            await conn.execute(_LIVE_TABLE)
        await conn.commit()


async def record_live_preview(source_url: str, preview_url: str) -> None:
    """Publish only own public short video derivatives, never a private original."""
    source = source_key(source_url)
    clip = source_key(preview_url)
    if not source or not source.lower().endswith(_VIDEO_SUFFIXES):
        raise ValueError("Live preview source must be a known video upload")
    if not clip or not _LIVE_OUTPUT_RE.fullmatch(clip):
        raise ValueError("Live preview must be a verified public H.264 derivative")
    await initialize_live_previews()
    async with db_backend.connect() as conn:
        await conn.execute(
            """INSERT INTO trend_catalog_live_video_assets (source_key, preview_url, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT (source_key) DO UPDATE SET
                   preview_url = excluded.preview_url,
                   updated_at = excluded.updated_at""",
            (source, preview_url, int(time.time())),
        )
        await conn.commit()


async def cached_live_previews(source_urls: list[str]) -> dict[str, str]:
    """One database read per catalog page; never fetch media or transcode on hot reads."""
    keys = list(dict.fromkeys(
        key for url in source_urls
        if (key := source_key(url)) and key.lower().endswith(_VIDEO_SUFFIXES)
    ))[:500]
    if not keys:
        return {}
    try:
        async with db_backend.connect() as conn:
            rows = await (await conn.execute(
                "SELECT source_key, preview_url FROM trend_catalog_live_video_assets WHERE source_key IN ("
                + ",".join("?" for _ in keys) + ")",
                tuple(keys),
            )).fetchall()
        return {
            str(row[0]): str(row[1]) for row in rows
            if (preview := source_key(str(row[1]))) and _LIVE_OUTPUT_RE.fullmatch(preview)
        }
    except Exception:  # noqa: BLE001 -- missing/temporarily unavailable optional manifest
        logger.debug("Trend live preview manifest unavailable; JPG fallback remains visible")
        return {}


async def enrich_cards(cards: list[dict]) -> None:
    if not cards:
        return
    original_urls = [str(card.get("preview_url") or "") for card in cards]
    by_key = await cached_thumbnails([
        url for url, card in zip(original_urls, cards)
        if not card.get("preview_poster_url")
    ])
    live = await cached_live_previews(original_urls)
    for card, original in zip(cards, original_urls):
        key = source_key(original)
        if key and not card.get("preview_poster_url") and key in by_key:
            card["preview_poster_url"] = by_key[key]
        # Keep preview_url untouched: dialogs/repeats must open the full source.
        # A durable same-origin live clip supersedes legacy local previews
        # which still redirect to S3 and can stall in Telegram WebView.
        if key and key in live:
            card["preview_video_url"] = live[key]
