"""Owner-scoped, authenticated VK uploads for the native image workflow.

The VK actor is resolved from a revocable signed session outside this module.
The URLs are public to allow external image providers to fetch these inputs,
but they are never a source of authorization or account identity.
"""
from __future__ import annotations

import asyncio
import io
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from bot.config import config

ROOT = Path('static/uploads/vk-refs/image')
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 30_000_000
MAX_REFS = 4


def verified_image_urls(actor_id: int, raw: object) -> list[str]:
    if type(actor_id) is not int or not 0 < actor_id < 2**63:
        raise ValueError('Invalid VK actor')
    if not isinstance(raw, list) or len(raw) > MAX_REFS:
        raise ValueError('Invalid VK references')
    media_base = config.static_base_url.rstrip('/')
    parsed_base = urlsplit(media_base)
    if parsed_base.scheme != 'https' or not parsed_base.hostname:
        raise ValueError('Invalid VK media origin')
    valid: list[str] = []
    for raw_url in raw:
        if not isinstance(raw_url, str):
            raise ValueError('Invalid VK reference URL')
        parsed = urlsplit(raw_url)
        if (parsed.scheme != parsed_base.scheme or parsed.netloc != parsed_base.netloc
            or parsed.query or parsed.fragment or
            not re.fullmatch(rf'/uploads/vk-refs/image/{actor_id}/[0-9a-f]{{32}}\.jpg', parsed.path)):
            raise ValueError('VK reference is not owned by this account')
        local_path = ROOT / str(actor_id) / Path(parsed.path).name
        if not local_path.is_file() or local_path.is_symlink():
            raise ValueError('VK reference is no longer available')
        valid.append(raw_url)
    if len(set(valid)) != len(valid):
        raise ValueError('Duplicate VK references')
    return valid


def _write_image(actor_id: int, raw: bytes) -> str:
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError('Image is too large or empty')
    # iOS Photos supplies HEIC/HEIF; match the existing Mini App codec.
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > MAX_PIXELS or min(image.size) <= 0:
                raise ValueError('Image dimensions are too large')
            image.load()
            converted = ImageOps.exif_transpose(image)
            if converted.mode not in {'RGB', 'L'}:
                converted = converted.convert('RGB')
            output = io.BytesIO()
            converted.save(output, format='JPEG', quality=90, optimize=True)
            jpeg = output.getvalue()
            if not jpeg or len(jpeg) > MAX_UPLOAD_BYTES:
                raise ValueError('Processed image is too large')
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('Invalid image') from exc

    folder = ROOT / str(actor_id)
    folder.mkdir(parents=True, exist_ok=True)
    # Bounded retention until DB-aware media GC is available. Do not silently
    # erase uploaded references that an active native VK task may still use.
    max_files = int(os.getenv('VK_MINIAPP_REF_MAX_FILES_PER_USER', '100'))
    min_free = int(os.getenv('VK_MINIAPP_REF_MIN_FREE_BYTES', str(5 * 1024**3)))
    if not 1 <= max_files <= 10000 or min_free < 1024**3:
        raise ValueError('VK reference storage is not configured')
    available = os.statvfs(folder)
    if available.f_bavail * available.f_frsize < min_free:
        raise ValueError('VK image storage is temporarily full')
    if sum(1 for entry in folder.iterdir() if entry.is_file()) >= max_files:
        raise ValueError('Maximum uploaded VK references reached')
    filename = uuid4().hex + '.jpg'
    local_path = folder / filename
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(local_path, flags, 0o644), 'wb') as output:
        output.write(jpeg)
    base = config.static_base_url.rstrip('/')
    return f'{base}/uploads/vk-refs/image/{actor_id}/{filename}'


async def save_vk_image(actor_id: int, raw: bytes) -> str:
    if type(actor_id) is not int or not 0 < actor_id < 2**63:
        raise ValueError('Invalid VK actor')
    return await asyncio.to_thread(_write_image, actor_id, raw)
