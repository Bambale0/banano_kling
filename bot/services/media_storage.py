from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Any

import aiofiles
import aiohttp

logger = logging.getLogger(__name__)

MEDIA_DIR = os.getenv("MEDIA_DIR", "static/uploads/feed")
_RETRY_ATTEMPTS = 3
_RETRY_DELAY = 1.5


async def _ensure_media_dir() -> None:
    Path(MEDIA_DIR).mkdir(parents=True, exist_ok=True)


def _local_path(task_id: str, url: str) -> str:
    """Генерирует стабильный локальный путь для задачи."""
    ext = _guess_extension(url)
    return os.path.join(MEDIA_DIR, f"{task_id}{ext}")


def _guess_extension(url: str) -> str:
    clean = url.split("?")[0].split("#")[0].lower().rstrip("/")
    for ext in (".mp4", ".webm", ".mov", ".m4v", ".png", ".jpg", ".jpeg", ".gif", ".webp"):
        if clean.endswith(ext):
            return ext
    return ".jpg"


def _local_url_from_path(path: str) -> str:
    """Преобразует локальный путь файла в URL для статики."""
    return f"/uploads/feed/{os.path.basename(path)}"


def _should_download(url: str) -> bool:
    """Нужно ли качать — только внешние URL."""
    if not url:
        return False
    if url.startswith("/uploads/") or url.startswith("uploads/"):
        return False
    return url.startswith(("http://", "https://"))


async def download_media(task_id: str, url: str) -> tuple[str, str | None]:
    """
    Скачивает внешний медиа-файл на сервер.
    Возвращает (локальный_url, ошибка).
    Если файл уже есть — возвращает существующий локальный URL.
    """
    if not _should_download(url):
        return url, None

    await _ensure_media_dir()

    local_path = _local_path(task_id, url)
    if os.path.isfile(local_path):
        logger.info("Media already cached locally: %s -> %s", task_id, local_path)
        return _local_url_from_path(local_path), None

    last_error: str | None = None
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            timeout = aiohttp.ClientTimeout(total=180)
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; BoomBot/1.0)",
                "Accept": "*/*",
            }
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        last_error = f"HTTP {resp.status} for {url}"
                        logger.warning(
                            "Download attempt %d/%d failed: %s",
                            attempt, _RETRY_ATTEMPTS, last_error,
                        )
                        await asyncio_sleep(_RETRY_DELAY * attempt)
                        continue

                    tmp_path = local_path + ".tmp"
                    async with aiofiles.open(tmp_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(1024 * 128):
                            if chunk:
                                await f.write(chunk)

                    os.replace(tmp_path, local_path)
                    logger.info(
                        "Downloaded media: task=%s url=%s -> %s",
                        task_id, url[:60], local_path,
                    )
                    return _local_url_from_path(local_path), None

        except Exception as e:
            last_error = str(e)
            logger.warning(
                "Download attempt %d/%d for task %s failed: %s",
                attempt, _RETRY_ATTEMPTS, task_id, last_error,
            )
            if attempt < _RETRY_ATTEMPTS:
                await asyncio_sleep(_RETRY_DELAY * attempt)

    # Clean up partial temp file if any
    tmp_path = local_path + ".tmp"
    if os.path.isfile(tmp_path):
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    logger.error("All download attempts failed for task %s: %s", task_id, last_error)
    return url, last_error


async def asyncio_sleep(seconds: float) -> None:
    """Обёртка для asyncio.sleep с совместимостью импорта."""
    import asyncio
    await asyncio.sleep(seconds)