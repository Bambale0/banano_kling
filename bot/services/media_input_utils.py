import base64
import io
import mimetypes
import os
from typing import Iterable
from urllib.parse import urlparse

from PIL import Image

from bot.config import config


def _guess_mime_type(source: str) -> str:
    mime, _ = mimetypes.guess_type(source)
    return mime or "image/png"


def _resolve_local_upload_path(source: str) -> str | None:
    if not isinstance(source, str) or not source:
        return None
    if source.startswith("data:image/"):
        return None

    parsed = urlparse(source)
    path = parsed.path or source

    if path.startswith("/uploads/"):
        rel_path = path[len("/uploads/") :].lstrip("/")
        candidate = os.path.join("static", "uploads", rel_path)
        return candidate if os.path.exists(candidate) else None

    if path.startswith("static/uploads/") and os.path.exists(path):
        return path

    static_base = (config.static_base_url or "").rstrip("/")
    if static_base and isinstance(source, str) and source.startswith(static_base):
        base_path = source[len(static_base) :]
        if base_path.startswith("/uploads/"):
            rel_path = base_path[len("/uploads/") :].lstrip("/")
            candidate = os.path.join("static", "uploads", rel_path)
            return candidate if os.path.exists(candidate) else None

    return None


def image_source_to_data_uri(source: str | bytes | bytearray) -> str:
    if isinstance(source, (bytes, bytearray)):
        try:
            image = Image.open(io.BytesIO(source))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            normalized = buffer.getvalue()
            return (
                f"data:image/png;base64,{base64.b64encode(normalized).decode('utf-8')}"
            )
        except Exception:
            return f"data:image/png;base64,{base64.b64encode(source).decode('utf-8')}"

    if not isinstance(source, str):
        return source

    if source.startswith("data:image/"):
        return source

    local_path = _resolve_local_upload_path(source)
    if not local_path:
        return source

    try:
        with Image.open(local_path) as image:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            raw = buffer.getvalue()
        return f"data:image/png;base64,{base64.b64encode(raw).decode('utf-8')}"
    except Exception:
        with open(local_path, "rb") as f:
            raw = f.read()
        mime_type = _guess_mime_type(local_path)
        return f"data:{mime_type};base64,{base64.b64encode(raw).decode('utf-8')}"


def image_sources_to_data_uris(
    sources: Iterable[str | bytes | bytearray] | None,
) -> list[str]:
    if not sources:
        return []
    return [image_source_to_data_uri(source) for source in sources]


def image_source_to_supported_image_url(source: str | bytes | bytearray) -> str:
    """Return a URL/file path for providers that require fetchable image URLs.

    For local uploaded images we normalize to PNG on disk so providers that reject
    WEBP still receive a supported file type.
    """
    if not isinstance(source, str) or not source or source.startswith("data:image/"):
        return source

    local_path = _resolve_local_upload_path(source)
    if not local_path:
        return source

    try:
        with Image.open(local_path) as image:
            image_format = (image.format or "").upper()
            if image_format in {"PNG", "JPEG", "JPG"}:
                return source

            png_path = os.path.splitext(local_path)[0] + ".png"
            if not os.path.exists(png_path):
                image.save(png_path, format="PNG")

            rel_path = os.path.relpath(png_path, os.path.join("static", "uploads"))
            rel_path = rel_path.replace(os.sep, "/")
            return f"{config.static_base_url.rstrip('/')}/uploads/{rel_path}"
    except Exception:
        return source


def image_sources_to_supported_image_urls(
    sources: Iterable[str | bytes | bytearray] | None,
) -> list[str]:
    if not sources:
        return []
    return [image_source_to_supported_image_url(source) for source in sources]


def image_source_to_provider_safe_png_url(source: str | bytes | bytearray) -> str:
    """Return a PNG URL for local uploads to reduce provider format issues."""
    if not isinstance(source, str) or not source or source.startswith("data:image/"):
        return source

    local_path = _resolve_local_upload_path(source)
    if not local_path:
        return source

    try:
        with Image.open(local_path) as image:
            png_path = os.path.splitext(local_path)[0] + ".png"
            if not os.path.exists(png_path):
                normalized = image.convert("RGBA" if "A" in image.mode else "RGB")
                normalized.save(png_path, format="PNG")

        rel_path = os.path.relpath(png_path, os.path.join("static", "uploads"))
        rel_path = rel_path.replace(os.sep, "/")
        return f"{config.static_base_url.rstrip('/')}/uploads/{rel_path}"
    except Exception:
        return source


def image_sources_to_provider_safe_png_urls(
    sources: Iterable[str | bytes | bytearray] | None,
) -> list[str]:
    if not sources:
        return []
    return [image_source_to_provider_safe_png_url(source) for source in sources]
