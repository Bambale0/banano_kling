from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path

from PIL import Image, ImageOps

from bot.config import config

logger = logging.getLogger(__name__)

FAST_PREVIEW_SIDE = 960
FAST_PREVIEW_QUALITY = 82
FEED_PREVIEW_DIR = Path("static/uploads/feed_previews")
LOCAL_UPLOAD_PREFIX = "/uploads/"
LOCAL_UPLOAD_ROOT = Path("static/uploads")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def feed_media_url(url: str | None) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith("/"):
        return f"{config.static_base_url.rstrip('/')}{value}"
    if value.startswith("uploads/"):
        return f"{config.static_base_url.rstrip('/')}/{value}"
    return value


def _local_upload_path(url: str | None) -> Path | None:
    value = str(url or "").strip()
    if value.startswith(config.static_base_url.rstrip("/") + LOCAL_UPLOAD_PREFIX):
        value = value.removeprefix(config.static_base_url.rstrip("/"))
    elif value.startswith("uploads/"):
        value = f"/{value}"
    if not value.startswith(LOCAL_UPLOAD_PREFIX):
        return None

    relative = Path(value.removeprefix(LOCAL_UPLOAD_PREFIX))
    if relative.is_absolute() or ".." in relative.parts:
        return None
    path = LOCAL_UPLOAD_ROOT / relative
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return None
    return path


def _preview_cache_path(task_id: str, source_path: Path) -> Path:
    digest = hashlib.sha256(str(source_path).encode("utf-8")).hexdigest()[:10]
    safe_task_id = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(task_id)
    )
    return FEED_PREVIEW_DIR / f"{safe_task_id}_{digest}.jpg"


def feed_preview_url(task_id: str, url: str | None) -> str:
    preview_path = create_or_get_feed_preview_path(task_id, url)
    if not preview_path:
        return ""
    try:
        relative = preview_path.relative_to(LOCAL_UPLOAD_ROOT)
    except ValueError:
        return ""
    return feed_media_url(f"/uploads/{relative.as_posix()}")


def create_or_get_feed_preview_path(task_id: str, url: str | None) -> Path | None:
    source_path = _local_upload_path(url)
    if not source_path or not source_path.is_file():
        return None

    preview_path = _preview_cache_path(task_id, source_path)
    try:
        if preview_path.is_file() and preview_path.stat().st_mtime >= source_path.stat().st_mtime:
            return preview_path

        FEED_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        with Image.open(source_path) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            image.thumbnail((FAST_PREVIEW_SIDE, FAST_PREVIEW_SIDE), Image.Resampling.LANCZOS)

            output = io.BytesIO()
            image.save(output, format="JPEG", quality=FAST_PREVIEW_QUALITY, optimize=True)
            preview_path.write_bytes(output.getvalue())
            return preview_path
    except Exception as exc:
        logger.warning("Cannot create fast feed preview for %s: %s", task_id, exc)
        return None


def load_feed_preview_bytes(task_id: str, url: str | None) -> bytes | None:
    preview_path = create_or_get_feed_preview_path(task_id, url)
    if not preview_path:
        return None
    try:
        return preview_path.read_bytes()
    except Exception as exc:
        logger.warning("Cannot read fast feed preview for %s: %s", task_id, exc)
        return None
