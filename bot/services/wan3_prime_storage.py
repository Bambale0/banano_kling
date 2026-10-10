from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp
from PIL import Image

from bot import database
from bot import db as db_backend
from bot.genjutsu.media import PublicResolver
from bot.services.wan3_prime_media import (
    AUDIO_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    MediaInfo,
    Wan3PrimeValidationError,
    assert_public_url,
    canonical_child_path,
)

CHUNK_SIZE = 7 * 1024 * 1024
MAX_UNFINISHED_SESSIONS = 5
ROOT = Path("static/uploads/wan3_prime")
UPLOAD_ROOT = ROOT / "references"
CHUNK_ROOT = ROOT / "chunks"


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")


def _expires(minutes: int = 60) -> str:
    return (datetime.now(UTC) + timedelta(minutes=minutes)).replace(tzinfo=None).isoformat(sep=" ")


def _safe_basename(filename: str) -> str:
    value = Path(str(filename or "upload")).name
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return value[:100] or "upload"


def _kind_limit(kind: str) -> int:
    return {
        "image": 20 * 1024 * 1024,
        "video": 100 * 1024 * 1024,
        "audio": 15 * 1024 * 1024,
        "file": 100 * 1024 * 1024,
    }.get(kind, 0)


def _allowed_ext(kind: str) -> set[str]:
    return {
        "image": IMAGE_EXTENSIONS,
        "video": VIDEO_EXTENSIONS,
        "audio": AUDIO_EXTENSIONS,
        "file": DOCUMENT_EXTENSIONS,
    }.get(kind, set())


def _public_url_for_path(path: str | os.PathLike[str]) -> str:
    rel = Path(path).resolve().relative_to(Path("static/uploads").resolve())
    try:
        from bot.config import config

        base = str(getattr(config, "static_base_url", "") or "").rstrip("/")
    except (ImportError, AttributeError):
        base = ""
    return f"{base}/uploads/{rel.as_posix()}" if base else f"/uploads/{rel.as_posix()}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_path() -> str:
    return str(getattr(database, "DATABASE_PATH", None) or os.getenv("DATABASE_PATH") or "bot.db")


class Wan3PrimeStorage:
    async def init_schema(self) -> None:
        from bot.services.wan3_prime_schema import execute_wan_ddl

        async with db_backend.connect(_sqlite_path()) as db:
            await execute_wan_ddl(db,
                """
                CREATE TABLE IF NOT EXISTS wan3_prime_media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id BIGINT NOT NULL,
                    telegram_id BIGINT NOT NULL,
                    kind TEXT NOT NULL,
                    public_url TEXT UNIQUE NOT NULL,
                    local_path TEXT NOT NULL,
                    filename TEXT,
                    content_type TEXT,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    media_info TEXT NOT NULL,
                    source TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await execute_wan_ddl(db,
                """
                CREATE TABLE IF NOT EXISTS wan3_prime_upload_sessions (
                    upload_id TEXT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    telegram_id BIGINT NOT NULL,
                    kind TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT,
                    declared_size INTEGER NOT NULL,
                    total_chunks INTEGER,
                    received_chunks INTEGER NOT NULL DEFAULT 0,
                    chunk_hashes TEXT NOT NULL DEFAULT '{}',
                    completed_result TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await execute_wan_ddl(db, "CREATE TABLE IF NOT EXISTS wan3_prime_storage_lock (id INTEGER PRIMARY KEY)")
            await db.execute("INSERT INTO wan3_prime_storage_lock (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
            await execute_wan_ddl(db, "CREATE TABLE IF NOT EXISTS wan3_prime_cleanup_cursor (id INTEGER PRIMARY KEY, last_media_id BIGINT NOT NULL DEFAULT 0)")
            await db.execute("INSERT INTO wan3_prime_cleanup_cursor (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
            await db.commit()

    async def cleanup_expired(self, *, limit: int = 100) -> dict[str, int]:
        from bot.services.wan3_prime_result_retention import cleanup_results
        from bot.services.wan3_prime_retention import cleanup_expired

        await self.init_schema()
        summary = await cleanup_expired(limit=limit)
        summary['removed_results'] = await cleanup_results(limit=limit)
        return summary

    async def init_upload(self, actor, *, kind: str, filename: str, size: int, content_type: str | None = None, importing: bool = False) -> dict[str, Any]:
        from bot.services.wan3_prime_storage_policy import (
            ACTIVE_UPLOAD_STATES,
            assert_capacity,
            lock_storage,
        )

        await self.init_schema()
        kind = str(kind or "").strip().lower()
        if kind not in {"image", "video", "audio", "file"}:
            raise Wan3PrimeValidationError("Unsupported upload kind")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size > _kind_limit(kind):
            raise Wan3PrimeValidationError("Upload size is not allowed")
        filename = _safe_basename(filename)
        if Path(filename).suffix.lower() not in _allowed_ext(kind):
            raise Wan3PrimeValidationError("Upload extension is not allowed")
        async with db_backend.connect(_sqlite_path()) as db:
            await lock_storage(db)
            await assert_capacity(db, actor.user_id, size)
            row = await (await db.execute(
                f"SELECT COUNT(*) FROM wan3_prime_upload_sessions WHERE user_id = ? AND status IN {ACTIVE_UPLOAD_STATES}",
                (actor.user_id,),
            )).fetchone()
            if int(row[0] or 0) >= MAX_UNFINISHED_SESSIONS:
                raise Wan3PrimeValidationError("Too many unfinished Wan 3.0 uploads", status=429)
            upload_id, expires_at = uuid.uuid4().hex, _expires()
            await db.execute(
                "INSERT INTO wan3_prime_upload_sessions "
                "(upload_id, user_id, telegram_id, kind, filename, content_type, declared_size, expires_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (upload_id, actor.user_id, actor.telegram_id, kind, filename, content_type or "", size, expires_at, "importing" if importing else "open"),
            )
            await db.commit()
        await asyncio.to_thread(canonical_child_path(CHUNK_ROOT, upload_id).mkdir, parents=True, exist_ok=True)
        return {"ok": True, "upload_id": upload_id, "chunk_size": CHUNK_SIZE, "expires_at": expires_at}

    async def save_chunk(self, actor, *, upload_id: str, index: int, total: int, chunk: bytes) -> None:
        await self.init_schema()
        if isinstance(index, bool) or isinstance(total, bool) or not isinstance(index, int) or not isinstance(total, int) or index < 0 or total <= 0 or index >= total:
            raise Wan3PrimeValidationError("Invalid chunk index")
        if not chunk or len(chunk) > CHUNK_SIZE:
            raise Wan3PrimeValidationError("Invalid chunk size")
        async with db_backend.connect(_sqlite_path()) as db:
            db.row_factory = db_backend.Row
            await db.execute("BEGIN IMMEDIATE")
            row = await (
                await db.execute(
                    "SELECT * FROM wan3_prime_upload_sessions WHERE upload_id = ? AND user_id = ? AND status = 'open' AND expires_at > CURRENT_TIMESTAMP" + (" FOR UPDATE" if db_backend.is_postgres() else ""),
                    (upload_id, actor.user_id),
                )
            ).fetchone()
            if not row:
                await db.rollback()
                raise Wan3PrimeValidationError("Upload session not found", status=404)
            expected_total = (int(row["declared_size"]) + CHUNK_SIZE - 1) // CHUNK_SIZE
            expected_size = min(CHUNK_SIZE, int(row["declared_size"]) - index * CHUNK_SIZE)
            if total != expected_total or len(chunk) != expected_size:
                await db.rollback()
                raise Wan3PrimeValidationError("Chunk does not match the declared upload size", status=409)
            if row["total_chunks"] is not None and int(row["total_chunks"]) != total:
                await db.rollback()
                raise Wan3PrimeValidationError("Upload chunk total changed", status=409)
            hashes = json.loads(row["chunk_hashes"] or "{}")
            digest = hashlib.sha256(chunk).hexdigest()
            key = str(index)
            if key in hashes and hashes[key] != digest:
                await db.rollback()
                raise Wan3PrimeValidationError("Chunk hash changed", status=409)
            if key not in hashes:
                hashes[key] = digest
                await db.execute(
                    "UPDATE wan3_prime_upload_sessions SET total_chunks = ?, received_chunks = received_chunks + 1, chunk_hashes = ?, updated_at = CURRENT_TIMESTAMP WHERE upload_id = ?",
                    (total, json.dumps(hashes, sort_keys=True), upload_id),
                )
            from bot.services.wan3_prime_files import write_chunk

            chunk_path = canonical_child_path(CHUNK_ROOT, f"{upload_id}/{index:06d}.part")
            await asyncio.to_thread(write_chunk, chunk_path, chunk, digest)
            await db.commit()

    async def complete_upload(self, actor, *, upload_id: str) -> dict[str, Any]:
        from bot.services.wan3_prime_files import assemble_chunks
        from bot.services.wan3_prime_storage_policy import positive_setting

        await self.init_schema()
        async with db_backend.connect(_sqlite_path()) as db:
            db.row_factory = db_backend.Row
            await db.execute("BEGIN IMMEDIATE")
            row = await (await db.execute(
                "SELECT * FROM wan3_prime_upload_sessions WHERE upload_id = ? AND user_id = ?" + (" FOR UPDATE" if db_backend.is_postgres() else ""),
                (upload_id, actor.user_id),
            )).fetchone()
            if not row:
                raise Wan3PrimeValidationError("Upload session not found", status=404)
            if row["status"] == "completed" and row["completed_result"]:
                return json.loads(row["completed_result"])
            now = datetime.now(UTC).replace(tzinfo=None)
            expires = datetime.fromisoformat(str(row["expires_at"]))
            if expires.tzinfo is not None:
                expires = expires.astimezone(UTC).replace(tzinfo=None)
            if expires < now:
                raise Wan3PrimeValidationError("Upload session expired", status=410)
            if row["status"] == "assembling":
                updated = datetime.fromisoformat(str(row["updated_at"]))
                if updated.tzinfo is not None:
                    updated = updated.astimezone(UTC).replace(tzinfo=None)
                if (now - updated).total_seconds() < positive_setting("WAN3_ASSEMBLY_LEASE_SECONDS", 300):
                    raise Wan3PrimeValidationError("Upload is being finalized", status=409)
            elif row["status"] != "open":
                raise Wan3PrimeValidationError("Upload session is not open", status=409)
            total = int(row["total_chunks"] or 0)
            expected_total = (int(row["declared_size"]) + CHUNK_SIZE - 1) // CHUNK_SIZE
            if total != expected_total or int(row["received_chunks"] or 0) != total:
                raise Wan3PrimeValidationError("Upload is incomplete", status=409)
            stamp = _now()
            await db.execute("UPDATE wan3_prime_upload_sessions SET status = 'assembling', updated_at = ? WHERE upload_id = ?", (stamp, upload_id))
            await db.commit()
        session_dir = canonical_child_path(CHUNK_ROOT, upload_id)
        assembled = session_dir / ("assembled-" + uuid.uuid4().hex + Path(row["filename"]).suffix.lower())
        try:
            await asyncio.to_thread(assemble_chunks, session_dir, assembled, json.loads(row["chunk_hashes"]), total, int(row["declared_size"]))
            saved = await self.save_owned_file(actor, kind=row["kind"], filename=row["filename"], path=assembled,
                content_type=row["content_type"], source="miniapp_wan3_prime_upload", upload_id=upload_id, assembly_stamp=stamp)
            with contextlib.suppress(OSError):
                await asyncio.to_thread(shutil.rmtree, session_dir)
            return saved
        except (Exception, asyncio.CancelledError) as exc:
            from bot.services.wan3_prime_files import Wan3PrimeDocumentError

            terminal = isinstance(exc, Wan3PrimeDocumentError)
            next_status = 'rejected' if terminal else 'open'
            async with db_backend.connect(_sqlite_path()) as db:
                changed = await db.execute("UPDATE wan3_prime_upload_sessions SET status = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE upload_id = ? AND status = 'assembling' AND updated_at = ?", (next_status, upload_id, stamp))
                await db.commit()
            if terminal and changed.rowcount == 1:
                # Retain quota until the actual rejected bytes are removed.
                await self.discard_import(actor, upload_id)
            raise

    async def save_owned_file(self, actor, *, kind: str, filename: str, path: Path, content_type: str | None = None,
                              source: str = "miniapp_wan3_prime", upload_id: str | None = None, assembly_stamp: str | None = None) -> dict[str, Any]:
        from bot.services.wan3_prime_files import copy_atomic
        from bot.services.wan3_prime_media import _check_dimensions, _check_duration
        from bot.services.wan3_prime_storage_policy import assert_capacity, lock_storage

        await self.init_schema()
        from bot.services.wan3_prime_probe_cache import probe_slot

        async with probe_slot(actor.user_id):
            inspection = asyncio.create_task(ActualWan3PrimeProbe(storage=self).probe_file(str(path), kind=kind))
            try:
                info = await asyncio.shield(inspection)
            except asyncio.CancelledError:
                # Retain admission until the bounded parser finishes.
                await asyncio.shield(inspection)
                raise
        if info.size_bytes is None or info.size_bytes <= 0 or info.size_bytes > _kind_limit(kind):
            raise Wan3PrimeValidationError("Stored media size is not allowed")
        ext = (info.extension or Path(filename).suffix).lower()
        if ext not in _allowed_ext(kind):
            raise Wan3PrimeValidationError("Stored media extension is not allowed")
        if kind in {"audio", "video"}:
            _check_duration(info, kind=kind)
        if kind == "video":
            _check_dimensions(info, min_px=240, max_px=4096)
        if info.pages is not None and info.pages > 50:
            raise Wan3PrimeValidationError("reference file must be <= 50 pages")
        media_key = upload_id or uuid.uuid4().hex
        dest = canonical_child_path(UPLOAD_ROOT, f"{actor.user_id}/{media_key}{ext}")
        public_url = _public_url_for_path(dest)
        async with db_backend.connect(_sqlite_path()) as db:
            db.row_factory = db_backend.Row
            await lock_storage(db)
            if upload_id:
                session = await (await db.execute(
                    "SELECT * FROM wan3_prime_upload_sessions WHERE upload_id = ? AND user_id = ?" + (" FOR UPDATE" if db_backend.is_postgres() else ""),
                    (upload_id, actor.user_id),
                )).fetchone()
                if not session or session["kind"] != kind:
                    raise Wan3PrimeValidationError("Upload session not found", status=404)
                if session["status"] == "completed" and session["completed_result"]:
                    return json.loads(session["completed_result"])
                if session["status"] not in {"assembling", "importing"} or info.size_bytes > int(session["declared_size"]):
                    raise Wan3PrimeValidationError("Upload reservation changed", status=409)
                if assembly_stamp and str(session["updated_at"]) != assembly_stamp:
                    raise Wan3PrimeValidationError("Upload assembly lease changed", status=409)
            await assert_capacity(db, actor.user_id, info.size_bytes, exclude_upload_id=upload_id or "")
            digest = await asyncio.to_thread(copy_atomic, path, dest)
            await db.execute(
                "INSERT INTO wan3_prime_media "
                "(user_id, telegram_id, kind, public_url, local_path, filename, content_type, size_bytes, sha256, media_info, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (actor.user_id, actor.telegram_id, kind, public_url, str(dest), filename,
                 content_type or mimetypes.guess_type(str(dest))[0] or "", int(info.size_bytes), digest,
                 json.dumps(asdict(info), sort_keys=True), source),
            )
            media_row = await (await db.execute("SELECT id FROM wan3_prime_media WHERE public_url = ?", (public_url,))).fetchone()
            saved = {"ok": True, "url": public_url, "kind": kind, "filename": filename, "size": int(info.size_bytes),
                     "reference": {"id": media_row[0], "created_at": _now(), "source": source}}
            if upload_id:
                await db.execute("UPDATE wan3_prime_upload_sessions SET status = 'completed', completed_result = ?, "
                                 "updated_at = CURRENT_TIMESTAMP WHERE upload_id = ?", (json.dumps(saved), upload_id))
            await db.commit()
        return saved

    async def discard_import(self, actor, upload_id: str) -> None:
        """Release a reservation only after its bounded temporary files are gone."""
        from bot.services.wan3_prime_storage_policy import lock_storage

        async with db_backend.connect(_sqlite_path()) as db:
            await lock_storage(db)
            row = await (await db.execute("SELECT status FROM wan3_prime_upload_sessions WHERE upload_id = ? AND user_id = ?", (upload_id, actor.user_id))).fetchone()
            if not row or row[0] not in {"importing", "completed", "rejected"}:
                return
            directory = canonical_child_path(CHUNK_ROOT, upload_id)
            if directory.exists():
                await asyncio.to_thread(shutil.rmtree, directory)
            await db.execute("UPDATE wan3_prime_upload_sessions SET status = 'failed', updated_at = CURRENT_TIMESTAMP WHERE upload_id = ? AND status IN ('importing', 'rejected')", (upload_id,))
            await db.commit()

    async def import_url(self, actor, *, kind: str, url: str) -> dict[str, Any]:
        kind = str(kind or "").strip().lower()
        if kind not in {"image", "video", "audio", "file", "link"}:
            raise Wan3PrimeValidationError("Unsupported import kind")
        if kind == "link":
            from bot.services.wan3_prime_probe_cache import probe_slot

            async with probe_slot(actor.user_id):
                fetched = await fetch_public_asset(url, destination=None, max_bytes=2 * 1024 * 1024, webpage=True)
            return {"ok": True, "url": fetched["url"], "kind": "link", "filename": None, "size": None}
        initial_extension = {"image": ".jpg", "video": ".mp4", "audio": ".mp3", "file": ".txt"}[kind]
        reservation = await self.init_upload(actor, kind=kind, filename="import" + initial_extension,
                                             size=_kind_limit(kind), importing=True)
        upload_id = reservation["upload_id"]
        temporary = canonical_child_path(CHUNK_ROOT, f"{upload_id}/download")
        try:
            fetched = await fetch_public_asset(url, destination=temporary, max_bytes=_kind_limit(kind))
            filename = _safe_basename(Path(urlparse(fetched["url"]).path).name)
            extension = Path(filename).suffix.lower()
            if extension not in _allowed_ext(kind):
                extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/bmp": ".bmp",
                    "video/mp4": ".mp4", "video/quicktime": ".mov", "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
                    "application/pdf": ".pdf", "text/plain": ".txt", "text/markdown": ".md",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
                }.get(fetched["content_type"], "")
                filename = "import" + extension
            if extension not in _allowed_ext(kind):
                raise Wan3PrimeValidationError("Cannot determine a supported file format; upload the file directly")
            typed = temporary.with_suffix(extension)
            await asyncio.to_thread(os.replace, temporary, typed)
            return await self.save_owned_file(actor, kind=kind, filename=filename, path=typed,
                                              source="miniapp_wan3_prime_import", upload_id=upload_id)
        finally:
            await self.discard_import(actor, upload_id)


async def fetch_public_asset(url: str, *, destination: Path | None, max_bytes: int, webpage: bool = False, timeout_seconds: int = 90) -> dict[str, Any]:
    """Reuse the project's validated-at-connect resolver and inspect every redirect."""
    resolver = PublicResolver()
    connector = aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False, limit=4)
    timeout = aiohttp.ClientTimeout(total=timeout_seconds, connect=15, sock_read=25)
    current = url
    partial = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.part') if destination else None
    try:
        async with asyncio.timeout(timeout_seconds):
            async with aiohttp.ClientSession(connector=connector, timeout=timeout, trust_env=False, cookie_jar=aiohttp.DummyCookieJar()) as session:
                for _ in range(4):
                    await assert_public_url(current)
                    async with session.get(current, allow_redirects=False) as response:
                        if response.status in {301, 302, 303, 307, 308}:
                            location = response.headers.get('Location')
                            if not location:
                                raise Wan3PrimeValidationError('Invalid media redirect')
                            current = urljoin(current, location)
                            continue
                        if response.status != 200:
                            raise Wan3PrimeValidationError('Material must be publicly accessible without login')
                        mime = response.headers.get('Content-Type', '').split(';', 1)[0].lower()
                        if webpage and mime not in {'text/html', 'application/xhtml+xml'}:
                            raise Wan3PrimeValidationError('Expected a public webpage, not a file')
                        if response.content_length is not None and response.content_length > max_bytes:
                            raise Wan3PrimeValidationError('Material exceeds the file size limit')
                        size = 0
                        handle = None
                        if partial is not None:
                            partial.parent.mkdir(parents=True, exist_ok=True)
                            handle = partial.open('xb')
                        try:
                            async for block in response.content.iter_chunked(65536):
                                size += len(block)
                                if size > max_bytes:
                                    raise Wan3PrimeValidationError('Material exceeds the file size limit')
                                if handle is not None:
                                    await asyncio.to_thread(handle.write, block)
                        finally:
                            if handle is not None:
                                handle.close()
                        if not size:
                            raise Wan3PrimeValidationError('The material is empty')
                        if partial is not None and destination is not None:
                            os.replace(partial, destination)
                        return {'url': current, 'content_type': mime, 'size': size}
        raise Wan3PrimeValidationError('Too many media redirects')
    except (aiohttp.ClientError, TimeoutError, OSError) as exc:
        raise Wan3PrimeValidationError('Material download failed; try uploading the file directly') from exc
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)
        await resolver.close()


class ActualWan3PrimeProbe:
    def __init__(self, storage: Wan3PrimeStorage | None = None, actor=None) -> None:
        self.storage = storage
        self.actor = actor

    def for_actor(self, actor):
        return ActualWan3PrimeProbe(self.storage, actor)

    async def probe_url(self, url: str, *, kind: str) -> MediaInfo:
        if self.storage is not None:
            async with db_backend.connect(_sqlite_path()) as db:
                db.row_factory = db_backend.Row
                row = await (await db.execute("SELECT * FROM wan3_prime_media WHERE public_url = ?", (url,))).fetchone()
            if row:
                if self.actor is not None and int(row["user_id"]) != self.actor.user_id:
                    raise Wan3PrimeValidationError("This media belongs to another user", status=403)
                if row["kind"] != kind:
                    raise Wan3PrimeValidationError("Media type does not match the selected field")
                local = Path(row["local_path"]).resolve()
                base = UPLOAD_ROOT.resolve()
                if base not in local.parents or not local.is_file():
                    raise Wan3PrimeValidationError("Owned media is no longer available")
                from bot.services.wan3_prime_probe_cache import verified_metadata

                return await verified_metadata(row, local, _sha256_file)
        if kind == "link":
            from bot.services.wan3_prime_probe_cache import probe_slot

            async with probe_slot(int(getattr(self.actor, 'user_id', 0))):
                await fetch_public_asset(url, destination=None, max_bytes=2 * 1024 * 1024, webpage=True)
            return MediaInfo(kind="link", url=url)
        raise Wan3PrimeValidationError("Media URL must be imported or uploaded before launch")

    async def probe_file(self, path: str, *, kind: str) -> MediaInfo:
        file_path = Path(path)
        if not file_path.exists() or not file_path.is_file():
            raise Wan3PrimeValidationError("Media file is missing")
        ext = file_path.suffix.lower()
        size = file_path.stat().st_size
        if kind == "image":
            def inspect_image() -> MediaInfo:
                with Image.open(file_path) as image:
                    has_alpha = image.mode in {"RGBA", "LA"} or ("transparency" in image.info)
                    actual_extension = {"JPEG": ".jpg", "PNG": ".png", "BMP": ".bmp", "WEBP": ".webp"}.get(image.format or "")
                    if not actual_extension:
                        raise Wan3PrimeValidationError("Unsupported image format")
                    width, height = image.size
                    if not 240 <= width <= 8000 or not 240 <= height <= 8000 or max(width, height) / min(width, height) > 8 or has_alpha:
                        raise Wan3PrimeValidationError("Image dimensions or transparency are unsupported")
                    image.verify()
                    return MediaInfo(kind=kind, path=str(file_path), size_bytes=size, width=width, height=height, extension=actual_extension, has_alpha=has_alpha)
            try:
                return await asyncio.to_thread(inspect_image)
            except (OSError, Image.DecompressionBombError) as exc:
                raise Wan3PrimeValidationError("Invalid or unsafe image") from exc
        if kind in {"video", "audio"}:
            return await self._ffprobe(file_path, kind=kind, size=size, ext=ext)
        pages = await asyncio.to_thread(self._document_pages, file_path)
        return MediaInfo(kind=kind, path=str(file_path), size_bytes=size, extension=ext, pages=pages, upstream_page_validation_required=pages is None)

    async def _ffprobe(self, path: Path, *, kind: str, size: int, ext: str) -> MediaInfo:
        def run_probe() -> MediaInfo:
            try:
                completed = subprocess.run(
                    [
                        "ffprobe",
                        "-protocol_whitelist", "file,pipe",
                        "-format_whitelist", "mov,wav,mp3,ogg,aac",
                        "-v",
                        "error",
                        "-print_format",
                        "json",
                        "-show_streams",
                        "-show_format",
                        str(path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                data = json.loads(completed.stdout or "{}")
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                raise Wan3PrimeValidationError("Could not inspect media") from exc
            if completed.returncode != 0 or not isinstance(data, dict):
                raise Wan3PrimeValidationError("Cannot decode media")
            streams = data.get("streams")
            if not isinstance(streams, list) or not any(item.get("codec_type") == kind for item in streams if isinstance(item, dict)):
                raise Wan3PrimeValidationError(f"File does not contain a {kind} stream")
            container = str((data.get("format") or {}).get("format_name") or "")
            formats = set(container.split(","))
            if kind == "audio":
                ext = ".wav" if "wav" in formats else ".mp3" if "mp3" in formats else ""
                if not ext:
                    raise Wan3PrimeValidationError("Audio container must be WAV or MP3")
            elif not formats.intersection({"mov", "mp4"}):
                raise Wan3PrimeValidationError("Video container must be MP4 or MOV")
            duration = None
            width = None
            height = None
            fmt = data.get("format") if isinstance(data, dict) else {}
            if isinstance(fmt, dict):
                try:
                    duration = float(fmt.get("duration"))
                except (TypeError, ValueError):
                    duration = None
            for stream in data.get("streams", []) if isinstance(data, dict) else []:
                if kind == "video" and stream.get("codec_type") == "video":
                    width = stream.get("width")
                    height = stream.get("height")
                    if duration is None:
                        try:
                            duration = float(stream.get("duration"))
                        except (TypeError, ValueError):
                            pass
                    break
                if kind == "audio" and stream.get("codec_type") == "audio":
                    if duration is None:
                        try:
                            duration = float(stream.get("duration"))
                        except (TypeError, ValueError):
                            pass
                    break
            return MediaInfo(kind=kind, path=str(path), size_bytes=size, width=width, height=height, duration_seconds=duration, extension=(ext if kind == "audio" else path.suffix.lower()))

        return await asyncio.to_thread(run_probe)

    def _document_pages(self, path: Path) -> int | None:
        from bot.services.wan3_prime_files import document_pages

        return document_pages(path)


wan3_prime_storage = Wan3PrimeStorage()
wan3_prime_probe = ActualWan3PrimeProbe(wan3_prime_storage)
