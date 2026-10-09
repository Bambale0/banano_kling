from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from bot import database
from bot.services.wan3_prime_lifecycle import Wan3PrimeActor
from bot.services.wan3_prime_media import Wan3PrimeValidationError
from bot.services.wan3_prime_storage import (
    CHUNK_SIZE,
    wan3_prime_probe,
    wan3_prime_storage,
)


async def actor() -> Wan3PrimeActor:
    user = await database.get_or_create_user(919191)
    return Wan3PrimeActor(user_id=user.id, telegram_id=919191)


def png_bytes() -> bytes:
    image = Image.new("RGB", (320, 240), (12, 34, 56))
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_chunked_upload_roundtrip_records_owned_media_and_probe():
    a = await actor()
    raw = png_bytes()
    init = await wan3_prime_storage.init_upload(
        a,
        kind="image",
        filename="sample.png",
        size=len(raw),
        content_type="image/png",
    )
    assert init["chunk_size"] == CHUNK_SIZE
    await wan3_prime_storage.save_chunk(a, upload_id=init["upload_id"], index=0, total=1, chunk=raw)
    completed = await wan3_prime_storage.complete_upload(a, upload_id=init["upload_id"])

    assert completed["ok"] is True
    assert completed["kind"] == "image"
    assert completed["url"].startswith("/uploads/") or "/uploads/" in completed["url"]

    info = await wan3_prime_probe.probe_url(completed["url"], kind="image")
    assert info.width == 320
    assert info.height == 240
    assert info.size_bytes == len(raw)


@pytest.mark.asyncio
async def test_chunk_retry_same_hash_ok_changed_hash_conflict():
    a = await actor()
    raw = png_bytes()
    init = await wan3_prime_storage.init_upload(
        a,
        kind="image",
        filename="retry.png",
        size=len(raw),
        content_type="image/png",
    )
    await wan3_prime_storage.save_chunk(a, upload_id=init["upload_id"], index=0, total=1, chunk=raw)
    await wan3_prime_storage.save_chunk(a, upload_id=init["upload_id"], index=0, total=1, chunk=raw)
    # Keep the declared size unchanged so this reaches the hash guard rather
    # than accidentally testing only the earlier size validator.
    changed = bytes([raw[0] ^ 1]) + raw[1:]
    with pytest.raises(Wan3PrimeValidationError, match="Chunk hash changed") as rejected:
        await wan3_prime_storage.save_chunk(a, upload_id=init["upload_id"], index=0, total=1, chunk=changed)
    assert rejected.value.status == 409
