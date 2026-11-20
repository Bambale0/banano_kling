"""Durable browser result delivery with bounded HTTPS fetch and SSRF protections."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import aiohttp

from bot.services.media_storage import is_s3_enabled, persist_upload_file

logger = logging.getLogger(__name__)
_DEFAULT_RESULT_HOSTS = "kie.ai,aiquickdraw.com,redpandaai.co,rendergrid.io"
_MAX_IMAGE_BYTES = 40 * 1024 * 1024
_MAX_VIDEO_BYTES = 400 * 1024 * 1024


def _trusted_result_url(url: str) -> bool:
    parsed = urlsplit(str(url or ""))
    host = (parsed.hostname or "").lower().rstrip(".")
    allowed = {
        part.strip().lower().strip(".") for part in
        os.getenv("WEB_GENERATION_RESULT_HOSTS", _DEFAULT_RESULT_HOSTS).split(",")
        if part.strip()
    }
    try:
        return (
            parsed.scheme == "https"
            and bool(host)
            and parsed.port in (None, 443)
            and not parsed.username and not parsed.password
            and len(url) <= 4096 and not parsed.fragment
            and any(host == suffix or host.endswith("." + suffix) for suffix in allowed)
        )
    except ValueError:
        return False


class _PublicOnlyResolver(aiohttp.abc.AbstractResolver):
    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        addresses = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM,
        )
        result = []
        for af, socktype, proto, canonical, sockaddr in addresses:
            address = str(sockaddr[0])
            if not ipaddress.ip_address(address).is_global:
                raise ValueError("Provider media resolved to a non-public IP")
            result.append({
                "hostname": host, "host": address, "port": port,
                "family": af, "proto": proto, "flags": socket.AI_NUMERICHOST,
            })
        if not result:
            raise ConnectionError("Provider media DNS resolution returned no addresses")
        return result

    async def close(self):
        return None


def _media_type(prefix: bytes, media_type: str) -> tuple[str, str]:
    if media_type == "image":
        if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
            return "png", "image/png"
        if prefix.startswith(b"\xff\xd8\xff"):
            return "jpg", "image/jpeg"
        if prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP":
            return "webp", "image/webp"
    if media_type == "video":
        if prefix[4:8] == b"ftyp":
            return "mp4", "video/mp4"
        if prefix.startswith(b"\x1a\x45\xdf\xa3"):
            return "webm", "video/webm"
    if media_type == "audio":
        if prefix.startswith((b"ID3", b"\xff\xfb")):
            return "mp3", "audio/mpeg"
        if prefix.startswith(b"RIFF") and prefix[8:12] == b"WAVE":
            return "wav", "audio/wav"
        if prefix.startswith(b"OggS"):
            return "ogg", "audio/ogg"
    raise ValueError("Unexpected or unsupported result file signature")


async def archive_web_result(source_url: str, task_id: str, asset_key: str, media_type: str) -> str:
    """Never expose expiring provider CDN URLs as final results.

    Only source hosts explicitly permitted for KIE responses can be reached.
    DNS is resolved and validated for every fetch and bounded redirect.
    The Selectel S3 upload must succeed before the paid task is completed.
    """
    if not is_s3_enabled():
        raise RuntimeError("Web result delivery requires durable S3 storage")
    if not _trusted_result_url(source_url):
        raise ValueError("Untrusted provider result host")
    if media_type not in ("image", "video"):
        raise ValueError("Unsupported web media type")
    max_bytes = _MAX_IMAGE_BYTES if media_type == "image" else _MAX_VIDEO_BYTES
    max_bytes = int(os.getenv(
        "WEB_GENERATION_MAX_IMAGE_BYTES" if media_type == "image"
        else "WEB_GENERATION_MAX_VIDEO_BYTES", str(max_bytes),
    ))
    if not 1_000_000 <= max_bytes <= 2 * 1024 * 1024 * 1024:
        raise ValueError("Unsafe web media size limit")
    timeout = aiohttp.ClientTimeout(total=150, sock_connect=12, sock_read=40)
    connector = aiohttp.TCPConnector(
        resolver=_PublicOnlyResolver(), use_dns_cache=False, ttl_dns_cache=0,
        limit_per_host=2,
    )
    partial = Path("")
    try:
        async with aiohttp.ClientSession(
            connector=connector, timeout=timeout, trust_env=False,
        ) as session:
            current_url = source_url
            for _redirect in range(4):
                if not _trusted_result_url(current_url):
                    raise ValueError("Provider redirected to an untrusted host")
                async with session.get(current_url, allow_redirects=False) as response:
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            raise ValueError("Invalid provider redirect")
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status != 200:
                        raise ConnectionError("Provider result not available")
                    length = response.headers.get("Content-Length")
                    if length and int(length) > max_bytes:
                        raise ValueError("Provider media exceeds configured byte limit")
                    with tempfile.NamedTemporaryFile(
                        prefix="neuromix-web-result-", delete=False,
                    ) as file:
                        partial = Path(file.name)
                        size = 0
                        prefix = b""
                        async for chunk in response.content.iter_chunked(256 * 1024):
                            size += len(chunk)
                            if size > max_bytes:
                                raise ValueError("Provider media exceeds configured byte limit")
                            if len(prefix) < 24:
                                prefix = (prefix + chunk)[:24]
                            file.write(chunk)
                        if not size:
                            raise ValueError("Provider media is empty")
                    break
            else:
                raise ValueError("Too many provider media redirects")
        extension, mime = _media_type(prefix, media_type)
        relative = f"web_results/{task_id}/{asset_key}.{extension}"
        return await asyncio.to_thread(
            persist_upload_file,
            relative, str(partial),
            content_type=mime, cache_control="private, max-age=31536000, immutable",
        )
    finally:
        if partial and partial.is_file():
            partial.unlink(missing_ok=True)
