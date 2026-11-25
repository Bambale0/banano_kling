"""Attachment delivery for existing public uploads; never fetch arbitrary URLs.

The opaque upload path grants exactly the same access as /uploads/. Private
Genjutsu media stays on its signed route with its original signature/expiry.
"""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from aiohttp import web

from bot.config import config
from bot.services import media_storage

logger = logging.getLogger(__name__)
DOWNLOAD_PREFIX = "/api/media-download/"
_PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def original_download_url(source: str) -> str:
    """Convert our public preview capability only; retain external/signed URLs."""
    from bot.services.media_input_utils import _static_upload_hosts

    value = str(source or "")
    try:
        parsed = urlsplit(value)
        relative = not parsed.scheme and not parsed.netloc
        own_origin = (
            parsed.scheme in {"http", "https"}
            and (parsed.hostname or "").lower() in _static_upload_hosts()
            and not parsed.username and not parsed.password
            and parsed.port in {None, 80, 443}
        )
        if not (relative or own_origin):
            return value
        query = parse_qsl(parsed.query, keep_blank_values=True)
        if parsed.path.startswith("/genjutsu/media/"):
            # Download is a presentation option on this existing signed route.
            query = [(k, v) for k, v in query if k != "download"] + [("download", "1")]
            return urlunsplit(parsed._replace(query=urlencode(query)))
        if not parsed.path.startswith("/uploads/"):
            return value
        # Never strip an unknown token, version, or signature from a capability.
        if any(key != "download" for key, _ in query):
            return value
        path = unquote(parsed.path[len("/uploads/"):])
        media_storage._validate_relative_path(path)
        return config.static_base_url.rstrip("/") + DOWNLOAD_PREFIX + quote(path, safe="/")
    except ValueError:
        return value


async def original_download(request: web.Request) -> web.StreamResponse:
    try:
        relative = media_storage._validate_relative_path(request.match_info["path"])
        disposition = media_storage.attachment_content_disposition(relative)
        if media_storage.is_s3_enabled():
            location = await asyncio.to_thread(
                media_storage.presigned_upload_url, relative,
                method=request.method, download=True,
            )
            # Preserve HEAD and Range through the redirect. Only S3 serves bytes.
            raise web.HTTPTemporaryRedirect(location=location, headers=_PRIVATE_HEADERS)
        path = media_storage.local_upload_path(relative)
        if not path.is_file():
            raise web.HTTPNotFound(headers=_PRIVATE_HEADERS)
        return web.FileResponse(path, headers={
            **_PRIVATE_HEADERS, "Content-Disposition": disposition,
        })
    except ValueError:
        raise web.HTTPNotFound(headers=_PRIVATE_HEADERS) from None
    except web.HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - HTTP boundary hides storage/config internals.
        # Do not log a bearer URL, S3 signature, or customer filename.
        logger.error(
            "Original download unavailable: method=%s error_type=%s",
            request.method, type(exc).__name__[:64],
        )
        raise web.HTTPServiceUnavailable(
            text="Media temporarily unavailable", headers=_PRIVATE_HEADERS,
        ) from None


def setup_original_download_routes(app: web.Application) -> None:
    app.router.add_get(DOWNLOAD_PREFIX + "{path:.*}", original_download)
