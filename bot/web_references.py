"""Verified browser ownership of S3-backed generation input images.

Clients submit only opaque reference IDs, never arbitrary provider-facing URLs.
Files are verified by signature, bounded in size and persisted before exposure.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import re
import time
import zipfile
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit
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


def _max_bytes(kind: str = "image") -> int:
    settings = {
        "image": ("WEB_GENERATION_REFERENCE_MAX_BYTES", 16 * 1024 * 1024, 32 * 1024 * 1024),
        "video": ("WEB_GENERATION_VIDEO_REFERENCE_MAX_BYTES", 32 * 1024 * 1024, 64 * 1024 * 1024),
        "audio": ("WEB_GENERATION_AUDIO_REFERENCE_MAX_BYTES", 16 * 1024 * 1024, 32 * 1024 * 1024),
        "file": ("WEB_GENERATION_FILE_REFERENCE_MAX_BYTES", 32 * 1024 * 1024, 64 * 1024 * 1024),
    }
    if kind not in settings:
        raise ValueError("Unsupported reference media kind")
    name, default, upper_bound = settings[kind]
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return value if 100_000 <= value <= upper_bound else default


async def owned_reference_urls(
    account_id: str, reference_ids: list[str], *, kind: str = "image",
) -> list[str]:
    if kind not in ("image", "video", "audio", "file", "link"):
        raise ValueError("Unsupported reference media kind")
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
               AND media_type LIKE ?
               AND account_id IN (WITH RECURSIVE owned(id) AS (
                    SELECT ? UNION ALL SELECT a.id FROM shared_accounts a
                    JOIN owned o ON a.merged_into=o.id WHERE a.status='merged'
                ) SELECT id FROM owned)""",
            (*reference_ids, kind + "/%", account_id),
        )).fetchall()
    mapped = {str(row[0]): str(row[1]) for row in rows}
    if len(mapped) != len(reference_ids):
        raise PermissionError("Reference not found in authenticated account")
    return [mapped[reference_id] for reference_id in reference_ids]


async def owned_reference_media(
    account_id: str, reference_ids: list[str], *, kind: str,
) -> list:
    """Inspect DB-owned S3 objects, never provider URLs supplied by a browser.

    Wan's media billing requires actual input seconds. Materialize ONLY a
    reference owned by the logged-in account; recheck its stored SHA-256, then
    reuse the existing Wan ffprobe/image validator on the verified local file.
    """
    from bot.services.media_storage import materialize_upload
    from bot.services.wan3_prime_media import MediaInfo
    from bot.services.wan3_prime_storage import ActualWan3PrimeProbe

    urls = await owned_reference_urls(account_id, reference_ids, kind=kind)
    if not urls:
        return []
    await ensure_web_tasks_schema()
    placeholders = ",".join("?" for _ in reference_ids)
    async with db_backend.connect() as db:
        rows = await (await db.execute(
            "SELECT reference_id,content_sha256,url FROM web_generation_references "
            "WHERE reference_id IN (" + placeholders + ") AND media_type LIKE ? "
            "AND account_id IN (WITH RECURSIVE owned(id) AS (SELECT ? UNION ALL "
            "SELECT a.id FROM shared_accounts a JOIN owned o "
            "ON a.merged_into=o.id WHERE a.status='merged') SELECT id FROM owned)",
            (*reference_ids, kind + "/%", account_id),
        )).fetchall()
    records = {str(row[0]): (str(row[1]), str(row[2])) for row in rows}
    if len(records) != len(reference_ids):
        raise PermissionError("Reference ownership has changed")
    probe = ActualWan3PrimeProbe()
    result = []
    for reference_id, url in zip(reference_ids, urls, strict=True):
        stored_digest, recorded_url = records[reference_id]
        if url != recorded_url:
            raise ValueError("Reference URL mismatch")
        path = urlsplit(url).path
        # Never let a stored URL select any local/S3 path outside our
        # original web_refs namespace. Extension is signature-derived.
        suffix = path.rsplit("/", 1)[-1]
        if (not suffix.startswith(reference_id + ".")
                or not re.fullmatch(r"wr_[a-f0-9]{32}\\.(?:png|jpg|jpeg|webp|mp4|webm|mp3|wav|ogg|pdf|txt|md|doc|xls|ppt|docx|xlsx|pptx|pages|numbers|key)", suffix)):
            raise ValueError("Invalid owner reference storage key")
        relative = "web_refs/" + suffix
        local = await asyncio.to_thread(materialize_upload, relative)
        if not local:
            raise ValueError("Owned media is unavailable in durable storage")
        def digest_file(path: str = local) -> str:
            with open(path, "rb") as source:
                digest = hashlib.sha256()
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                return digest.hexdigest()
        if await asyncio.to_thread(digest_file) != stored_digest:
            raise ValueError("Owned media SHA256 no longer matches S3 object")
        inspected: MediaInfo = await probe.probe_file(local, kind=kind)
        result.append(replace(inspected, url=url, sha256=stored_digest, path=None))
    return result


_OFFICE_MIME = {
    "doc": "application/msword",
    "xls": "application/vnd.ms-excel",
    "ppt": "application/vnd.ms-powerpoint",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pages": "application/x-iwork-pages-sffpages",
    "numbers": "application/x-iwork-numbers-sffnumbers",
    "key": "application/x-iwork-keynote-sffkey",
}
_ZIP_OFFICE_ENTRY = {
    "docx": "word/document.xml",
    "xlsx": "xl/workbook.xml",
    "pptx": "ppt/presentation.xml",
    "pages": "index.xml",
    "numbers": "index.xml",
    "key": "index.xml",
}
_OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")


def _document_type(data: bytes, filename: str) -> tuple[str, str]:
    """Sniff documents independent of client-declared Content-Type.

    Refuse mismatched extensions, malformed archives, absolute archive paths
    and declared ZIP decompression bombs before any durable S3 write.
    """
    suffix = Path(str(filename or "").replace(chr(92), "/")).suffix.lower().lstrip(".")
    if suffix == "pdf" and data.startswith(b"%PDF-"):
        return suffix, "application/pdf"
    if suffix in ("txt", "md"):
        if not data or b"\x00" in data:
            raise ValueError("Invalid text reference")
        text = data.decode("utf-8")
        if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text):
            raise ValueError("Unsafe text reference")
        return suffix, "text/plain"
    if suffix in ("doc", "xls", "ppt") and data.startswith(_OLE_MAGIC):
        return suffix, _OFFICE_MIME[suffix]
    if suffix in _ZIP_OFFICE_ENTRY and data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                members = archive.infolist()
                if not 1 <= len(members) <= 1024:
                    raise ValueError("Invalid office archive member count")
                total = 0
                names = set()
                for item in members:
                    if (item.filename.startswith("/") or chr(92) in item.filename
                            or ".." in item.filename.split("/")):
                        raise ValueError("Unsafe office archive member")
                    total += item.file_size
                    if total > 128 * 1024 * 1024:
                        raise ValueError("Office archive exceeds decompression limit")
                    if item.file_size > 100 * max(item.compress_size, 1) + 1024 * 1024:
                        raise ValueError("Compressed office file exceeds safety ratio")
                    names.add(item.filename.lower())
                required = _ZIP_OFFICE_ENTRY[suffix]
                if required not in names and not (
                    suffix in ("pages", "numbers", "key")
                    and any(name.startswith("index/") for name in names)
                ):
                    raise ValueError("Office document does not match extension")
        except (zipfile.BadZipFile, OSError) as exc:
            raise ValueError("Malformed office reference") from exc
        return suffix, _OFFICE_MIME[suffix]
    raise ValueError("Unsupported or mismatched document extension/signature")


async def upload_reference(request: web.Request) -> web.Response:
    from bot.web_auth import _json, _session_account, _valid_browser_origin

    if not _valid_browser_origin(request):
        return _json({"ok": False, "error": "origin_rejected"}, 403)
    account = await _session_account(request)
    if not account:
        return _json({"ok": False, "error": "session_required"}, 401)
    if not is_s3_enabled():
        return _json({"ok": False, "error": "Durable reference storage unavailable"}, 503)
    maximum = max(_max_bytes(kind) for kind in ("image", "video", "audio", "file"))
    if request.content_length is not None and request.content_length > maximum + 65536:
        return _json({"ok": False, "error": "Файл слишком большой."}, 413)
    try:
        # Some middleware reads/caches the request body before the handler.
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
        kind = part.name if part is not None else None
        if kind not in ("image", "video", "audio", "file"):
            raise ValueError("Expected an image, video, audio or file input")
        limit = _max_bytes(kind)
        contents = bytearray()
        while True:
            chunk = await part.read_chunk(256 * 1024)
            if not chunk:
                break
            if len(contents) + len(chunk) > limit:
                return _json({"ok": False, "error": "Файл слишком большой."}, 413)
            contents.extend(chunk)
        extra = await multipart.next()
        if extra is not None:
            raise ValueError("Only one reference may be uploaded per request")
        ext, mime = (
            _document_type(bytes(contents), part.filename or "")
            if kind == "file" else _media_type(bytes(contents[:24]), kind)
        )
    except (TypeError, ValueError, RuntimeError):
        return _json({"ok": False, "error": "Поддерживаются PNG, JPEG, WebP, MP4, WebM, MP3, WAV, OGG."}, 400)
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
            (identifier, account, digest, url,
             "file/" + mime if kind == "file" else mime, int(time.time())),
        )
        row = await (await db.execute(
            "SELECT reference_id,url FROM web_generation_references "
            "WHERE account_id=? AND content_sha256=?",
            (account, digest),
        )).fetchone()
        await db.commit()
    return _json({"ok": True, "reference_id": str(row[0]), "url": str(row[1]),
                  "mime": mime})


async def import_web_link(request: web.Request) -> web.Response:
    """Register a validated public webpage under the authenticated account.

    This never accepts a provider-visible URL in a paid task body; the
    opaque wr_ id is resolved with a second DNS-safe fetch at quote time.
    """
    from bot.services.wan3_prime_media import assert_public_url
    from bot.services.wan3_prime_storage import fetch_public_asset
    from bot.web_auth import _json, _session_account, _valid_browser_origin

    if not _valid_browser_origin(request):
        return _json({"ok": False, "error": "origin_rejected"}, 403)
    account = await _session_account(request)
    if not account:
        return _json({"ok": False, "error": "session_required"}, 401)
    if request.content_length and request.content_length > 5000:
        return _json({"ok": False, "error": "URL is too long"}, 413)
    try:
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"url"}:
            raise ValueError("Expected an URL only")
        url = body["url"]
        if not isinstance(url, str) or not 1 <= len(url) <= 4096:
            raise ValueError("Invalid URL")
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.fragment or parsed.port not in (None, 443)):
            raise ValueError("Only public HTTPS pages are supported")
        await assert_public_url(url)
        result = await fetch_public_asset(
            url, destination=None, max_bytes=2 * 1024 * 1024,
            webpage=True, timeout_seconds=35,
        )
        final = str(result.get("url") or "")
        parsed_final = urlsplit(final)
        if (parsed_final.scheme != "https" or parsed_final.username
                or parsed_final.password or parsed_final.fragment
                or parsed_final.port not in (None, 443)
                or len(final) > 4096
                or result.get("content_type") not in (
                    "text/html", "application/xhtml+xml",
                )):
            raise ValueError("Untrusted public webpage response")
        await assert_public_url(final)
    except Exception:  # noqa: BLE001 - untrusted link fetch and DNS failures
        # The URL is untrusted; do not leak DNS/network/SSL diagnostics to users.
        return _json({"ok": False, "error": "Не удалось подтвердить публичную HTTPS-страницу."}, 400)
    await ensure_web_tasks_schema()
    digest = hashlib.sha256(("web-link:" + final).encode()).hexdigest()
    async with db_backend.connect() as db:
        existing = await (await db.execute(
            "SELECT reference_id FROM web_generation_references "
            "WHERE account_id=? AND content_sha256=?",
            (account, digest),
        )).fetchone()
        if existing:
            return _json({"ok": True, "reference_id": str(existing[0])})
        count = await (await db.execute(
            "SELECT COUNT(*) FROM web_generation_references "
            "WHERE account_id=? AND created_at_epoch>?",
            (account, int(time.time()) - 86400),
        )).fetchone()
        try:
            limit = int(os.getenv("WEB_GENERATION_REFERENCE_UPLOADS_PER_DAY", "100"))
        except (ValueError, TypeError):
            limit = 100
        if not 1 <= limit <= 2000:
            limit = 100
        if int(count[0]) >= limit:
            return _json({"ok": False, "error": "Дневной лимит ссылок и референсов."}, 429)
        identifier = "wr_" + uuid4().hex
        await db.execute(
            "INSERT INTO web_generation_references "
            "(reference_id,account_id,content_sha256,url,media_type,created_at_epoch) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(account_id,content_sha256) DO NOTHING",
            (identifier, account, digest, final, "link/url", int(time.time())),
        )
        row = await (await db.execute(
            "SELECT reference_id FROM web_generation_references "
            "WHERE account_id=? AND content_sha256=?",
            (account, digest),
        )).fetchone()
        await db.commit()
    return _json({"ok": True, "reference_id": str(row[0])})


def register_routes(app: web.Application, prefix: str) -> None:
    app.router.add_post(prefix + "/web-generation/reference", upload_reference)
    app.router.add_post(prefix + "/web-generation/link", import_web_link)
