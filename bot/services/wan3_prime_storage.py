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
from dataclasses import asdict, replace
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
    except Exception:
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
            await db.commit()

    async def init_upload(self, actor, *, kind: str, filename: str, size: int, content_type: str | None = None) -> dict[str, Any]:
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
            row = await (
                await db.execute(
                    "SELECT COUNT(*) FROM wan3_prime_upload_sessions WHERE user_id = ? AND status = 'open' AND expires_at > CURRENT_TIMESTAMP",
                    (actor.user_id,),
                )
            ).fetchone()
            if int(row[0] or 0) >= MAX_UNFINISHED_SESSIONS:
                raise Wan3PrimeValidationError("Too many unfinished Wan 3.0 uploads")
            upload_id = uuid.uuid4().hex
            await db.execute(
                """
                INSERT INTO wan3_prime_upload_sessions
                    (upload_id, user_id, telegram_id, kind, filename, content_type, declared_size, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (upload_id, actor.user_id, actor.telegram_id, kind, filename, content_type or "", size, _expires()),
            )
            await db.commit()
        canonical_child_path(CHUNK_ROOT, upload_id).mkdir(parents=True, exist_ok=True)
        return {"ok": True, "upload_id": upload_id, "chunk_size": CHUNK_SIZE, "expires_at": _expires()}

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
            chunk_path = canonical_child_path(CHUNK_ROOT, f"{upload_id}/{index:06d}.part")
            chunk_path.parent.mkdir(parents=True, exist_ok=True)
            if not chunk_path.exists() or _sha256_file(chunk_path) != digest:
                temporary = chunk_path.with_name(chunk_path.name + "." + uuid.uuid4().hex + ".tmp")
                try:
                    with open(temporary, "xb") as handle:
                        handle.write(chunk)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, chunk_path)
                finally:
                    temporary.unlink(missing_ok=True)
            await db.commit()

    async def complete_upload(self, actor, *, upload_id: str) -> dict[str, Any]:
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
            if row["status"] != "open":
                raise Wan3PrimeValidationError("Upload is being finalized", status=409)
            expires = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
            if expires < datetime.now(UTC).replace(tzinfo=None):
                raise Wan3PrimeValidationError("Upload session expired", status=410)
            total = int(row["total_chunks"] or 0)
            expected_total = (int(row["declared_size"]) + CHUNK_SIZE - 1) // CHUNK_SIZE
            if total != expected_total or int(row["received_chunks"] or 0) != total:
                raise Wan3PrimeValidationError("Upload is incomplete", status=409)
            await db.execute("UPDATE wan3_prime_upload_sessions SET status = 'assembling', updated_at = CURRENT_TIMESTAMP WHERE upload_id = ?", (upload_id,))
            await db.commit()
        session_dir = canonical_child_path(CHUNK_ROOT, upload_id)
        assembled = session_dir / ("assembled" + Path(row["filename"]).suffix.lower())
        try:
            hashes = json.loads(row["chunk_hashes"])
            with open(assembled, "wb") as out:
                for index in range(total):
                    part = canonical_child_path(session_dir, f"{index:06d}.part")
                    if not part.is_file() or _sha256_file(part) != hashes.get(str(index)):
                        raise Wan3PrimeValidationError("Upload chunk is missing or incomplete", status=409)
                    with open(part, "rb") as handle:
                        shutil.copyfileobj(handle, out)
            if assembled.stat().st_size != int(row["declared_size"]):
                raise Wan3PrimeValidationError("Upload size mismatch", status=409)
            saved = await self.save_owned_file(actor, kind=row["kind"], filename=row["filename"], path=assembled,
                content_type=row["content_type"], source="miniapp_wan3_prime_upload")
            async with db_backend.connect(_sqlite_path()) as db:
                await db.execute("UPDATE wan3_prime_upload_sessions SET status = 'completed', completed_result = ?, updated_at = CURRENT_TIMESTAMP WHERE upload_id = ? AND user_id = ?",
                    (json.dumps(saved), upload_id, actor.user_id))
                await db.commit()
            with contextlib.suppress(OSError):
                shutil.rmtree(session_dir)
            return saved
        except Exception:
            async with db_backend.connect(_sqlite_path()) as db:
                await db.execute("UPDATE wan3_prime_upload_sessions SET status = 'open', updated_at = CURRENT_TIMESTAMP WHERE upload_id = ? AND status = 'assembling'", (upload_id,))
                await db.commit()
            raise

    async def save_owned_file(self, actor, *, kind: str, filename: str, path: Path, content_type: str | None = None, source: str = "miniapp_wan3_prime") -> dict[str, Any]:
        await self.init_schema()
        info = await ActualWan3PrimeProbe(storage=self).probe_file(str(path), kind=kind)
        if info.size_bytes is None or info.size_bytes <= 0 or info.size_bytes > _kind_limit(kind):
            raise Wan3PrimeValidationError("Stored media size is not allowed")
        ext = Path(filename).suffix.lower() or (info.extension or "").lower()
        if ext not in _allowed_ext(kind):
            raise Wan3PrimeValidationError("Stored media extension is not allowed")
        info = replace(info, extension=ext)
        media_id = uuid.uuid4().hex
        dest = canonical_child_path(UPLOAD_ROOT, f"{actor.user_id}/{media_id}{ext}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        shutil.copyfile(path, tmp)
        os.replace(tmp, dest)
        public_url = _public_url_for_path(dest)
        digest = _sha256_file(dest)
        async with db_backend.connect(_sqlite_path()) as db:
            await db.execute(
                """
                INSERT INTO wan3_prime_media
                    (user_id, telegram_id, kind, public_url, local_path, filename, content_type, size_bytes, sha256, media_info, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    actor.user_id,
                    actor.telegram_id,
                    kind,
                    public_url,
                    str(dest),
                    filename,
                    content_type or mimetypes.guess_type(filename)[0] or "",
                    int(info.size_bytes),
                    digest,
                    json.dumps(asdict(info), sort_keys=True),
                    source,
                ),
            )
            await db.commit()
            media_id_row = await (
                await db.execute("SELECT id FROM wan3_prime_media WHERE public_url = ?", (public_url,))
            ).fetchone()
        return {
            "ok": True,
            "url": public_url,
            "kind": kind,
            "filename": filename,
            "size": int(info.size_bytes),
            "reference": {"id": media_id_row[0] if media_id_row else None, "created_at": _now(), "source": source},
        }

    async def import_url(self, actor, *, kind: str, url: str) -> dict[str, Any]:
        kind = str(kind or '').strip().lower()
        if kind not in {'image', 'video', 'audio', 'file', 'link'}:
            raise Wan3PrimeValidationError('Unsupported import kind')
        await self.init_schema()
        tmp_dir = canonical_child_path(CHUNK_ROOT, f'import-{uuid.uuid4().hex}')
        tmp_dir.mkdir(parents=True, exist_ok=True)
        temporary = tmp_dir / 'download'
        try:
            fetched = await fetch_public_asset(url, destination=None if kind == 'link' else temporary,
                max_bytes=2 * 1024 * 1024 if kind == 'link' else _kind_limit(kind), webpage=kind == 'link')
            if kind == 'link':
                return {'ok': True, 'url': fetched['url'], 'kind': 'link', 'filename': None, 'size': None}
            filename = _safe_basename(Path(urlparse(fetched['url']).path).name)
            extension = Path(filename).suffix.lower()
            if extension not in _allowed_ext(kind):
                extension = { 'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp',
                    'image/bmp': '.bmp', 'video/mp4': '.mp4', 'video/quicktime': '.mov',
                    'audio/mpeg': '.mp3', 'audio/wav': '.wav', 'audio/x-wav': '.wav',
                    'application/pdf': '.pdf', 'text/plain': '.txt', 'text/markdown': '.md',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
                    'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
                }.get(fetched['content_type'], '')
                filename = 'import' + extension
            if extension not in _allowed_ext(kind):
                raise Wan3PrimeValidationError('Cannot determine a supported file format; upload the file directly')
            typed = temporary.with_suffix(extension)
            os.replace(temporary, typed)
            return await self.save_owned_file(actor, kind=kind, filename=filename, path=typed, source='miniapp_wan3_prime_import')
        finally:
            with contextlib.suppress(OSError):
                shutil.rmtree(tmp_dir)


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
                digest = await asyncio.to_thread(_sha256_file, local)
                if digest != row["sha256"]:
                    raise Wan3PrimeValidationError("Owned media has changed; upload it again", status=409)
                info = await self.probe_file(str(local), kind=kind)
                return replace(info, url=url, sha256=digest)
        if kind == "link":
            await assert_public_url(url, resolve_dns=True)
            return MediaInfo(kind="link", url=url)
        raise Wan3PrimeValidationError("Media URL must be imported or uploaded before launch")

    async def probe_file(self, path: str, *, kind: str) -> MediaInfo:
        file_path = Path(path)
        if not file_path.exists() or not file_path.is_file():
            raise Wan3PrimeValidationError("Media file is missing")
        ext = file_path.suffix.lower()
        size = file_path.stat().st_size
        if kind == "image":
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
        if kind in {"video", "audio"}:
            return await self._ffprobe(file_path, kind=kind, size=size, ext=ext)
        pages = self._document_pages(file_path)
        return MediaInfo(kind=kind, path=str(file_path), size_bytes=size, extension=ext, pages=pages, upstream_page_validation_required=pages is None)

    async def _ffprobe(self, path: Path, *, kind: str, size: int, ext: str) -> MediaInfo:
        def run_probe() -> MediaInfo:
            try:
                completed = subprocess.run(
                    [
                        "ffprobe",
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
            except Exception:
                data = {}
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
            return MediaInfo(kind=kind, path=str(path), size_bytes=size, width=width, height=height, duration_seconds=duration, extension=ext)

        return await asyncio.to_thread(run_probe)

    def _document_pages(self, path: Path) -> int | None:
        if path.suffix.lower() != ".pdf":
            return None
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        return raw.count(b"/Type /Page") or None


wan3_prime_storage = Wan3PrimeStorage()
wan3_prime_probe = ActualWan3PrimeProbe(wan3_prime_storage)
