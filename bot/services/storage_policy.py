"""Upload storage layout helpers.

URL compatibility is preserved by keeping everything under /uploads/, while
separating physical storage into temp_refs, results, and user_uploads.
"""

from __future__ import annotations

from pathlib import Path

IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "heic", "heif", "dng"}
VIDEO_EXTS = {"mp4", "mov", "webm", "mkv", "avi"}
ALLOWED_CATEGORIES = {"temp_refs", "results", "user_uploads"}


def normalize_ext(file_ext: str) -> str:
    return (file_ext or "bin").lower().lstrip(".")


def choose_upload_category(file_ext: str, *, is_reference: bool = False) -> str:
    ext = normalize_ext(file_ext)
    if is_reference and ext in IMAGE_EXTS:
        return "temp_refs"
    if is_reference:
        return "user_uploads"
    return "results"


def upload_path(root: str | Path, category: str, date_str: str, filename: str) -> Path:
    if category not in ALLOWED_CATEGORIES:
        raise ValueError(f"invalid upload category: {category}")
    return Path(root) / category / date_str / filename


def public_upload_url(base_url: str, category: str, date_str: str, filename: str) -> str:
    if category not in ALLOWED_CATEGORIES:
        raise ValueError(f"invalid upload category: {category}")
    return f"{base_url.rstrip('/')}/uploads/{category}/{date_str}/{filename}"
