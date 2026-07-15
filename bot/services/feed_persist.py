"""
Скачивание результатов генерации с временных хостов (tempfile.aiquickdraw.com)
на сервер, чтобы они не удалялись по TTL.

Вызывается из share_to_feed() при публикации в ленту.
"""

import asyncio
import logging
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from PIL import Image, ImageOps

from bot.config import config

logger = logging.getLogger(__name__)

FEED_STORAGE_DIR = Path("static/uploads/feed")
FEED_THUMB_STORAGE_DIR = FEED_STORAGE_DIR / "thumbs"
FEED_THUMB_MAX_SIDE = 768
FEED_THUMB_QUALITY = 84


async def download_to_local(url: str, max_size_bytes: int = 50 * 1024 * 1024) -> str | None:
    """
    Скачивает файл по URL в static/uploads/feed/<uuid>.<ext>.
    Возвращает локальный URL (STATIC_BASE_URL/uploads/feed/<filename>),
    который будет обслуживаться nginx/aiohttp.
    """
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    logger.warning("Feed persist: HTTP %s for %s", resp.status, url)
                    return None

                content_type = resp.headers.get("Content-Type", "")

                # Определяем расширение
                ext = _content_type_to_ext(content_type, url)
                filename = f"{uuid.uuid4().hex}{ext}"

                FEED_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
                filepath = FEED_STORAGE_DIR / filename

                downloaded = 0
                with open(filepath, "wb") as f:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if downloaded > max_size_bytes:
                            os.remove(filepath)
                            logger.warning("Feed persist: file too large (>%d) for %s", max_size_bytes, url)
                            return None

                local_url = f"{config.static_base_url.rstrip('/')}/uploads/feed/{filename}"
                logger.info("Feed persist: downloaded %s -> %s (%d bytes)", url, local_url, downloaded)
                return local_url

    except asyncio.TimeoutError:
        logger.warning("Feed persist: timeout downloading %s", url)
    except Exception:
        logger.exception("Feed persist: failed to download %s", url)

    return None


def _content_type_to_ext(content_type: str, fallback_url: str) -> str:
    """Определяет расширение файла по Content-Type или URL."""
    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
    }

    # По Content-Type
    for ct, ext in ext_map.items():
        if ct in content_type:
            return ext

    # По URL
    parsed = urlparse(fallback_url)
    path = parsed.path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm", ".mov"):
        if path.endswith(ext):
            return ext

    return ".jpg"  # fallback


def _local_feed_upload_path(url: str) -> Path | None:
    parsed = urlparse(str(url or ""))
    path = parsed.path if parsed.scheme else str(url or "")
    prefix = "/uploads/feed/"
    if not path.startswith(prefix) or "/thumbs/" in path:
        return None
    rel = path[len("/uploads/") :].lstrip("/")
    candidate = Path("static/uploads") / rel
    try:
        candidate.resolve().relative_to(Path("static/uploads").resolve())
    except ValueError:
        return None
    return candidate


def feed_thumbnail_url_for(url: str) -> str | None:
    """Return an existing lightweight thumbnail URL for a local feed image."""
    source = _local_feed_upload_path(url)
    if not source or source.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        return None
    thumb = FEED_THUMB_STORAGE_DIR / f"{source.stem}.jpg"
    if not thumb.exists():
        return None
    return f"{config.static_base_url.rstrip('/')}/uploads/feed/thumbs/{thumb.name}"


def ensure_feed_thumbnail(url: str) -> str | None:
    """Create a WebP thumbnail for a local feed image and return its public URL."""
    existing = feed_thumbnail_url_for(url)
    if existing:
        return existing

    source = _local_feed_upload_path(url)
    if not source or not source.exists() or not source.is_file():
        return None
    if source.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        return None

    thumb = FEED_THUMB_STORAGE_DIR / f"{source.stem}.jpg"
    tmp = thumb.with_suffix(".tmp.jpg")
    try:
        FEED_THUMB_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((FEED_THUMB_MAX_SIDE, FEED_THUMB_MAX_SIDE), Image.Resampling.LANCZOS)
            if image.mode != "RGB":
                image = image.convert("RGB")
            image.save(tmp, "JPEG", quality=FEED_THUMB_QUALITY, optimize=True)
        os.replace(tmp, thumb)
        return f"{config.static_base_url.rstrip('/')}/uploads/feed/thumbs/{thumb.name}"
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        logger.exception("Feed thumbnail: failed for %s", url)
        return None


async def persist_feed_result_urls(result_urls: list[str]) -> list[str]:
    """
    Принимает список URL результатов генерации.
    Если URL ведёт на эфемерный хост — скачивает локально.
    Возвращает список URL (некоторые могут быть заменены на локальные).
    """
    from bot.database import FEED_EPHEMERAL_RESULT_HOSTS, _feed_result_host

    if not FEED_EPHEMERAL_RESULT_HOSTS:
        return result_urls

    persisted: list[str] = []
    for url in result_urls:
        host = _feed_result_host(url)
        is_ephemeral = any(
            host == ephemeral or host.endswith(f".{ephemeral}")
            for ephemeral in FEED_EPHEMERAL_RESULT_HOSTS
        )
        if is_ephemeral:
            local = await download_to_local(url)
            if local:
                ensure_feed_thumbnail(local)
                persisted.append(local)
            else:
                # Если скачать не удалось — оставляем оригинал
                persisted.append(url)
        else:
            persisted.append(url)

    return persisted
