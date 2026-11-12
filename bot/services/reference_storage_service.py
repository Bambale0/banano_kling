import asyncio
import hashlib
import logging
import os
import re
from datetime import UTC, datetime

from bot.database import (
    SavedReference,
    get_saved_reference_by_hash,
    save_user_reference,
    touch_saved_references,
)
from bot.services.media_input_utils import (
    image_source_to_provider_safe_png_url,
    resolve_local_upload_path,
)

logger = logging.getLogger(__name__)

REFERENCE_ROOT = os.path.join("static", "uploads", "refs")


def _build_reference_public_url(relative_path: str) -> str:
    from bot.services.media_storage import public_upload_url

    return public_upload_url(relative_path.replace(os.sep, "/"))


def _provider_safe_reference_url(file_url: str, kind: str) -> str:
    if kind != "image":
        return file_url
    try:
        safe_url = image_source_to_provider_safe_png_url(file_url)
        return safe_url or file_url
    except Exception:
        logger.exception("Failed to normalize image reference: %s", file_url)
        return file_url


async def save_reference_file(
    telegram_id: int,
    file_bytes: bytes,
    *,
    file_ext: str,
    kind: str = "image",
    original_filename: str | None = None,
    content_type: str | None = None,
    source: str = "telegram",
    category_id: str | None = None,
) -> tuple[str | None, SavedReference | None]:
    """Persist reusable reference media outside the ephemeral uploads cleanup path."""
    try:
        if not isinstance(file_bytes, (bytes, bytearray)) or not file_bytes:
            return None, None

        normalized_kind = kind if kind in {"image", "video", "audio"} else "image"
        file_hash = hashlib.sha256(bytes(file_bytes)).hexdigest()
        existing = await get_saved_reference_by_hash(telegram_id, normalized_kind, file_hash)
        if existing:
            local_path = resolve_local_upload_path(existing.file_url)
            if local_path and os.path.exists(local_path):
                public_url = _provider_safe_reference_url(existing.file_url, normalized_kind)
                await touch_saved_references(
                    telegram_id, [existing.file_url], kind=normalized_kind
                )
                if category_id:
                    existing = await save_user_reference(
                        telegram_id, kind=normalized_kind, file_url=public_url, file_hash=file_hash,
                        original_filename=original_filename, content_type=existing.content_type, source=source,
                        category_id=category_id,
                    )
                return public_url, existing

        safe_ext = (file_ext or "bin").lower().strip(".")
        if not re.fullmatch(r"[a-z0-9]{1,10}", safe_ext):
            safe_ext = "bin"
        month = datetime.now(UTC).strftime("%Y%m")
        relative_dir = os.path.join("refs", normalized_kind, str(telegram_id), month)
        filename = f"{file_hash[:32]}.{safe_ext}"
        relative_path = os.path.join(relative_dir, filename)
        from bot.services.media_storage import persist_upload_bytes, upload_exists

        normalized_relative_path = relative_path.replace(os.sep, "/")
        if not await asyncio.to_thread(upload_exists, normalized_relative_path):
            original_public_url = await asyncio.to_thread(
                persist_upload_bytes,
                normalized_relative_path,
                bytes(file_bytes),
                content_type=content_type,
                cache_control="private, max-age=0",
            )
        else:
            original_public_url = _build_reference_public_url(relative_path)
        public_url = _provider_safe_reference_url(original_public_url, normalized_kind)
        persisted_content_type = (
            "image/png"
            if normalized_kind == "image" and public_url != original_public_url
            else content_type
        )
        saved_reference = await save_user_reference(
            telegram_id,
            kind=normalized_kind,
            file_url=public_url,
            file_hash=file_hash,
            original_filename=original_filename,
            content_type=persisted_content_type,
            source=source,
            **({"category_id": category_id} if category_id else {}),
        )
        return public_url, saved_reference
    except Exception:
        logger.exception("Failed to persist reusable reference for telegram_id=%s", telegram_id)
        return None, None
