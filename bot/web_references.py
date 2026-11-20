"""Verified browser ownership of S3-backed generation input images.

Clients submit only opaque reference IDs, never arbitrary provider-facing URLs.
Files are verified by signature, bounded in size and persisted before exposure.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from uuid import uuid4

from aiohttp import web
from aiohttp.multipart import MultipartReader
from aiohttp.streams import StreamReader

from bot import db as db_backend
from bot.services.media_storage import is_s3_enabled, persist_upload_bytes
from bot.web_media_delivery import _media_type
from bot.web_tasks import ensure_web_tasks_schema

_REF_ID = re.compile(r"^wr_[a-f0-9]{32}$")


def _max_references() -> int:
    try:
        value = int(os.getenv("WEB_GENERATION_MAX_REFERENCES", "10"))
    except (TypeError, ValueError):
        return 10
    return value if 1 <= value <= 12 else 10


def _max_bytes() -> int:
    try:
        value = int(os.getenv("WEB_GENERATION_REFERENCE_MAX_BYTES", str(16 * 1024 * 1024)))
    except (TypeError, ValueError):
        value = 16 * 1024 * 1024
    return value if 100_000 <= value <= 32 * 1024 * 1024 else 16 * 1024 * 1024


async def owned_reference_urls(account_id: str, reference_ids: list[str]) -> list[str]:
    if (not isinstance(reference_ids, list) or len(reference_ids) > _max_references()
            or any(not isinstance(r, str) or not _REF_ID.fullmatch(r) for r in reference_ids)
            or len(set(reference_ids)) != len(reference_ids)):
        raise ValueError("Invalid or duplicate reference ID")
    if not reference_ids:
        return []
    await ensure_web_tasks_schema()
    placeholders = ",".join("?" for _ in reference_ids)
    async with db_backend.connect() as db:
        rows = await (await db.execute(
            """SELECT reference_id,url FROM web_generation_references
               WHERE reference_id IN (""" + placeholders + """)
               AND account_id IN (WITH RECURSIVE owned(id) AS (
                    SELECT ? UNION ALL SELECT a.id FROM shared_accounts a
                    JOIN owned o ON a.merged_into=o.id WHERE a.status='merged'
                ) SELECT id FROM owned)""",
            (*reference_ids, account_id),
        )).fetchall()
    mapped = {str(row[0]): str(row[1]) for row in rows}
    if len(mapped) != len(reference_ids):
        raise PermissionError("Reference not found in authenticated account")
    return [mapped[reference_id] for reference_id in reference_ids]


async def upload_reference(request: web.Request) -> web.Response:
    from bot.web_auth import _json, _session_account, _valid_browser_origin

    if not _valid_browser_origin(request):
        return _json({"ok": False, "error": "origin_rejected"}, 403)
    account = await _session_account(request)
    if not account:
        return _json({"ok": False, "error": "session_required"}, 401)
    if not is_s3_enabled():
        return _json({"ok": False, "error": "Durable reference storage unavailable"}, 503)
    maximum = _max_bytes()
    if request.content_length is not None and request.content_length > maximum + 65536:
        return _json({"ok": False, "error": "Файл слишком большой."}, 413)
    try:
        # Application request middleware can read() the body in advance
        # (including the production runtime body audit). In aiohttp 3.14
        # request.multipart() reads the now-empty live stream, ignoring the
        # already-cached bytes and raising "Could not find starting boundary".
        # Reconstruct a standard bounded MultipartReader from the exact
        # cached bytes without relaxing MIME or single-part validation.
        cached = getattr(request, "_read_bytes", None)
        if cached is not None:
            if len(cached) > maximum + 65536:
                return _json({"ok": False, "error": "Файл слишком большой."}, 413)
            replay = StreamReader(request._protocol, limit=maximum + 65536)
            replay.feed_data(cached)
            replay.feed_eof()
            multipart = MultipartReader(request.headers, replay)
        else:
            multipart = await request.multipart()
        part = await multipart.next()
        if part is None or part.name != "image":
            raise ValueError("Expected an image input")
        contents = bytearray()
        while True:
            chunk = await part.read_chunk(256 * 1024)
            if not chunk:
                break
            if len(contents) + len(chunk) > maximum:
                return _json({"ok": False, "error": "Файл слишком большой."}, 413)
            contents.extend(chunk)
        extra = await multipart.next()
        if extra is not None:
            raise ValueError("Only one reference may be uploaded per request")
        ext, mime = _media_type(bytes(contents[:24]), "image")
    except (TypeError, ValueError, RuntimeError):
        return _json({"ok": False, "error": "Поддерживаются PNG, JPEG и WebP."}, 400)
    digest = hashlib.sha256(contents).hexdigest()
    await ensure_web_tasks_schema()
    async with db_backend.connect() as db:
        row = await (await db.execute(
            "SELECT reference_id,url FROM web_generation_references "
            "WHERE account_id=? AND content_sha256=?",
            (account, digest),
        )).fetchone()
    if row:
        return _json({"ok": True, "reference_id": str(row[0]), "url": str(row[1]),
                      "mime": mime})
    try:
        quota = int(os.getenv("WEB_GENERATION_REFERENCE_UPLOADS_PER_DAY", "100"))
    except (TypeError, ValueError):
        quota = 100
    if not 1 <= quota <= 2000:
        quota = 100
    async with db_backend.connect() as db:
        row = await (await db.execute(
            """SELECT COUNT(*) FROM web_generation_references WHERE account_id=?
               AND created_at_epoch>?""",
            (account, int(time.time()) - 86400),
        )).fetchone()
    if int(row[0]) >= quota:
        return _json({"ok": False, "error": "Лимит загрузки референсов на сегодня."}, 429)
    identifier = "wr_" + uuid4().hex
    try:
        url = await asyncio.to_thread(
            persist_upload_bytes,
            "web_refs/" + identifier + "." + ext, bytes(contents),
            content_type=mime, cache_control="private, max-age=31536000, immutable",
        )
    except Exception:  # noqa: BLE001 - untrusted S3 provider failures must be sanitized
        return _json({"ok": False, "error": "Не удалось сохранить референс в S3."}, 503)
    async with db_backend.connect() as db:
        await db.execute(
            """INSERT INTO web_generation_references
               (reference_id,account_id,content_sha256,url,media_type,created_at_epoch)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(account_id,content_sha256) DO NOTHING""",
            (identifier, account, digest, url, mime, int(time.time())),
        )
        row = await (await db.execute(
            "SELECT reference_id,url FROM web_generation_references "
            "WHERE account_id=? AND content_sha256=?",
            (account, digest),
        )).fetchone()
        await db.commit()
    return _json({"ok": True, "reference_id": str(row[0]), "url": str(row[1]),
                  "mime": mime})


def register_routes(app: web.Application, prefix: str) -> None:
    app.router.add_post(prefix + "/web-generation/reference", upload_reference)
