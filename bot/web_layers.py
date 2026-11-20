"""Web-account Seedream 5.5 Layers: all images + ZIP persisted before billing.

Does not reuse the Telegram legacy layer-settlement tables or its urllib
downloader. Fetches must go through the same public-IP-only resolver and KIE
host allowlist as ordinary independent web generation results.
"""
from __future__ import annotations

import asyncio
import json
import re
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urljoin

import aiohttp

from bot.services.media_storage import is_s3_enabled, persist_upload_file
from bot.web_media_delivery import (
    _media_type,
    _PublicOnlyResolver,
    _trusted_result_url,
)

_MAX_SINGLE_IMAGE = 35 * 1024 * 1024
_MAX_TOTAL_LAYER_BYTES = 500 * 1024 * 1024
_ID = re.compile(r"^web_[a-f0-9]{32}$")
_KEY = re.compile(r"^[a-f0-9]{32}$")


async def _download_layer(
    session: aiohttp.ClientSession,
    source_url: str,
    target: Path,
    remaining_total: int,
) -> tuple[str, str, int]:
    current = source_url
    for _ in range(4):
        if not _trusted_result_url(current):
            raise ValueError("Untrusted Seedream layer asset host")
        async with session.get(current, allow_redirects=False) as response:
            if response.status in (301, 302, 303, 307, 308):
                destination = response.headers.get("Location")
                if not destination:
                    raise ValueError("Seedream layer redirect has no location")
                current = urljoin(current, destination)
                continue
            if response.status != 200:
                raise ConnectionError("Seedream layer result not ready")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > min(
                _MAX_SINGLE_IMAGE, remaining_total
            ):
                raise ValueError("Seedream layer exceeds bounded size")
            total = 0
            prefix = b""
            with target.open("wb") as output:
                async for chunk in response.content.iter_chunked(128 * 1024):
                    total += len(chunk)
                    if total > _MAX_SINGLE_IMAGE or total > remaining_total:
                        raise ValueError("Seedream layer exceeds bounded size")
                    if len(prefix) < 24:
                        prefix = (prefix + chunk)[:24]
                    output.write(chunk)
            if not total:
                raise ValueError("Empty Seedream layer output")
            extension, mime = _media_type(prefix, "image")
            return extension, mime, total
    raise ValueError("Too many Seedream layer redirects")


async def archive_web_layers(
    task_id: str, asset_key: str, source_urls: list[str],
) -> tuple[list[str], str]:
    """Persist ordered images plus downloadable ZIP, or raise before settlement.

    S3 object paths are deterministic for crash-safe repeated persistence.
    The caller records the returned durable URLs only after *every* write
    succeeded. Refund/capture is a separate durable ledger transaction.
    """
    if not _ID.fullmatch(task_id) or not _KEY.fullmatch(asset_key):
        raise ValueError("Invalid destination task identity")
    if (not isinstance(source_urls, list) or not 2 <= len(source_urls) <= 100
            or len(set(source_urls)) != len(source_urls)):
        raise ValueError("Invalid or duplicate layered output list")
    if not is_s3_enabled():
        raise RuntimeError("Layer bundle requires durable S3")
    for url in source_urls:
        if not isinstance(url, str) or not _trusted_result_url(url):
            raise ValueError("Untrusted layer URL")
    resolver = _PublicOnlyResolver()
    connector = aiohttp.TCPConnector(
        resolver=resolver, use_dns_cache=False, ttl_dns_cache=0, limit_per_host=2,
    )
    timeout = aiohttp.ClientTimeout(total=240, sock_connect=12, sock_read=40)
    saved_urls: list[str] = []
    with tempfile.TemporaryDirectory(prefix="neuromix-web-layers-") as workspace:
        root = Path(workspace)
        archive_path = root / "layers.zip"
        used_bytes = 0
        manifest = []
        async with aiohttp.ClientSession(
            connector=connector, trust_env=False, timeout=timeout,
        ) as session:
            with zipfile.ZipFile(
                archive_path, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True,
            ) as archive:
                for idx, source in enumerate(source_urls):
                    path = root / f"image-{idx:03d}.bin"
                    extension, mime, size = await _download_layer(
                        session, source, path, _MAX_TOTAL_LAYER_BYTES - used_bytes,
                    )
                    used_bytes += size
                    name = f"{idx:03d}_{'base' if idx == 0 else 'layer'}.{extension}"
                    relative = f"web_results/{task_id}/{asset_key}-layer-{idx:03d}.{extension}"
                    durable_url = await asyncio.to_thread(
                        persist_upload_file, relative, str(path),
                        content_type=mime,
                        cache_control="private, max-age=31536000, immutable",
                    )
                    if not isinstance(durable_url, str) or not durable_url.startswith("https://"):
                        raise OSError("S3 layer was not persisted")
                    saved_urls.append(durable_url)
                    archive.write(path, arcname=name)
                    manifest.append({
                        "index": idx,
                        "name": name,
                        "mime": mime,
                        "byte_size": size,
                    })
                    path.unlink(missing_ok=True)
                archive.writestr(
                    "layers.json",
                    json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
                )
        bundle = await asyncio.to_thread(
            persist_upload_file,
            f"web_results/{task_id}/{asset_key}-layers.zip",
            str(archive_path), content_type="application/zip",
            cache_control="private, max-age=31536000, immutable",
        )
        if not isinstance(bundle, str) or not bundle.startswith("https://"):
            raise OSError("S3 layer ZIP was not persisted")
        return saved_urls, bundle
