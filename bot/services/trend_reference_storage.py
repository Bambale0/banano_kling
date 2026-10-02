"""Durable, private-at-the-API-boundary storage for curated trend references."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, UnidentifiedImageError

from bot.config import config
from bot.services.media_input_utils import resolve_local_upload_path

logger = logging.getLogger(__name__)

TREND_REFERENCE_ROOT = Path("static/uploads/trend-assets")
MAX_BYTES = {
    "image": int(os.getenv("TREND_REFERENCE_IMAGE_MAX_BYTES", str(40 * 1024 * 1024))),
    "video": int(os.getenv("TREND_REFERENCE_VIDEO_MAX_BYTES", str(300 * 1024 * 1024))),
    "audio": int(os.getenv("TREND_REFERENCE_AUDIO_MAX_BYTES", str(100 * 1024 * 1024))),
}
_IMAGE_FORMATS = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "WEBP": (".webp", "image/webp"),
    "GIF": (".gif", "image/gif"),
    "AVIF": (".avif", "image/avif"),
    "HEIF": (".heif", "image/heif"),
}
_EXTENSIONS = {
    "video": {".mp4", ".mov", ".m4v", ".webm"},
    "audio": {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"},
}


class TrendReferenceStorageError(ValueError):
    """Raised when a source reference cannot be persisted safely."""


@dataclass(frozen=True)
class PersistedTrendReference:
    media_type: str
    file_url: str
    file_hash: str
    mime_type: str
    size_bytes: int

    def as_dict(self) -> dict[str, object]:
        return {
            "media_type": self.media_type,
            "file_url": self.file_url,
            "file_hash": self.file_hash,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
        }


def _public_url(path: Path) -> str:
    relative = path.relative_to(Path("static"))
    return f"{config.static_base_url.rstrip('/')}/{relative.as_posix()}"


def _normalize_media_type(value: str) -> str:
    media_type = str(value or "").strip().lower()
    if media_type not in MAX_BYTES:
        raise TrendReferenceStorageError(
            f"Unsupported trend reference type: {media_type}"
        )
    return media_type


async def _read_local(path: Path, *, limit: int) -> tuple[bytes, str]:
    try:
        stat = await asyncio.to_thread(path.stat)
    except OSError as exc:
        raise TrendReferenceStorageError("Reference file is unavailable") from exc
    if not path.is_file() or stat.st_size <= 0:
        raise TrendReferenceStorageError("Reference file is unavailable")
    if stat.st_size > limit:
        raise TrendReferenceStorageError("Reference file is too large")
    data = await asyncio.to_thread(path.read_bytes)
    return data, mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _image_metadata(data: bytes) -> tuple[str, str]:
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
            image_format = str(image.format or "").upper()
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise TrendReferenceStorageError("Reference is not a valid image") from exc
    metadata = _IMAGE_FORMATS.get(image_format)
    if not metadata:
        raise TrendReferenceStorageError(
            f"Unsupported image format: {image_format or 'unknown'}"
        )
    return metadata


def _media_metadata(
    media_type: str,
    data: bytes,
    *,
    content_type: str,
    source_url: str,
) -> tuple[str, str]:
    if media_type == "image":
        return _image_metadata(data)

    guessed_extension = Path(urlparse(source_url).path).suffix.lower()
    mime = str(content_type or "").lower()
    if media_type == "video":
        declared_extension = guessed_extension
        if declared_extension not in _EXTENSIONS["video"] and mime.startswith("video/"):
            declared_extension = (mimetypes.guess_extension(mime) or "").lower()
        if declared_extension not in _EXTENSIONS["video"]:
            raise TrendReferenceStorageError(
                "Reference has an unsupported video extension"
            )

        if len(data) >= 12 and data[4:8] == b"ftyp":
            extension = declared_extension
            mime = "video/quicktime" if extension == ".mov" else "video/mp4"
        elif data.startswith(b"\x1a\x45\xdf\xa3") and declared_extension == ".webm":
            extension, mime = ".webm", "video/webm"
        else:
            raise TrendReferenceStorageError("Reference is not a supported video")
    else:
        if data.startswith(b"ID3"):
            extension, mime = ".mp3", "audio/mpeg"
        elif len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0:
            if guessed_extension == ".aac" or "aac" in mime:
                extension, mime = ".aac", "audio/aac"
            else:
                extension, mime = ".mp3", "audio/mpeg"
        elif data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WAVE":
            extension, mime = ".wav", "audio/wav"
        elif data.startswith(b"OggS"):
            extension, mime = ".ogg", "audio/ogg"
        elif data.startswith(b"fLaC"):
            extension, mime = ".flac", "audio/flac"
        elif (
            len(data) >= 12
            and data[4:8] == b"ftyp"
            and guessed_extension in {".m4a", ".aac"}
        ):
            extension, mime = guessed_extension, "audio/mp4"
        else:
            raise TrendReferenceStorageError("Reference is not a supported audio file")

    return extension, mime


async def persist_trend_reference(
    source_url: str,
    *,
    media_type: str,
) -> PersistedTrendReference:
    """Copy a task reference into durable trend storage and return safe metadata."""

    normalized_type = _normalize_media_type(media_type)
    source = str(source_url or "").strip()
    if not source:
        raise TrendReferenceStorageError("Reference URL is empty")
    limit = MAX_BYTES[normalized_type]

    local_path = resolve_local_upload_path(source)
    if not local_path:
        raise TrendReferenceStorageError(
            "Закрепить можно только загруженный в NEUROMIX референс, который ещё не удалён"
        )
    data, content_type = await _read_local(Path(local_path), limit=limit)

    extension, normalized_mime = _media_metadata(
        normalized_type,
        data,
        content_type=content_type,
        source_url=source,
    )
    digest = hashlib.sha256(data).hexdigest()
    target_dir = TREND_REFERENCE_ROOT / normalized_type / digest[:2]
    target = target_dir / f"{digest}{extension}"
    target_dir.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        from uuid import uuid4

        temporary = target.with_suffix(
            target.suffix + f".{os.getpid()}.{uuid4().hex}.tmp"
        )
        await asyncio.to_thread(temporary.write_bytes, data)
        try:
            temporary.replace(target)
        except FileExistsError:
            temporary.unlink(missing_ok=True)
    logger.info(
        "Persisted private trend reference: type=%s hash=%s bytes=%s",
        normalized_type,
        digest[:12],
        len(data),
    )
    return PersistedTrendReference(
        media_type=normalized_type,
        file_url=_public_url(target),
        file_hash=digest,
        mime_type=normalized_mime,
        size_bytes=len(data),
    )
