"""Private photos owned by real shared accounts; no legacy Telegram actor."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from PIL import Image

from bot import db as db_backend
from bot.services.image_normalization import ImageNormalizationError, normalize_image
from bot.services.upload_limits import DEFAULT_UPLOAD_MAX_BYTES, UPLOAD_TIMEOUT_SECONDS

from .schema import ensure_schema
from .wallet import WalletConflict, canonical_account

logger = logging.getLogger(__name__)
DEFAULT_ROOT = Path('data/account_references')
REFERENCE_SCHEMA = '''CREATE TABLE IF NOT EXISTS shared_account_references (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES shared_accounts(id),
    storage_key TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    mime TEXT NOT NULL CHECK(mime = 'image/png'),
    width INTEGER NOT NULL CHECK(width > 0), height INTEGER NOT NULL CHECK(height > 0),
    size_bytes BIGINT NOT NULL CHECK(size_bytes > 0),
    created_at_epoch BIGINT NOT NULL,
    removed_at_epoch BIGINT,
    thumbnail_sha256 TEXT NOT NULL)'''
OWNED = '''WITH RECURSIVE owned(id) AS (SELECT ? UNION
    SELECT a.id FROM shared_accounts a JOIN owned o ON a.merged_into = o.id WHERE a.status = 'merged')'''
COLUMNS = 'id, account_id, storage_key, sha256, mime, width, height, size_bytes, created_at_epoch, removed_at_epoch'


class AccountReferenceError(ValueError):
    def __init__(self, code: str, *, status: int = 400):
        self.code, self.status = code, status
        super().__init__(code)


def reference_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{32}', value):
        raise AccountReferenceError('reference_unavailable', status=404)
    return value


def _metadata(row) -> dict:
    return {'id': row[0], 'mime': row[4], 'width': row[5], 'height': row[6],
            'size_bytes': int(row[7]), 'created_at_epoch': int(row[8])}


async def ensure_reference_schema(db) -> None:
    await ensure_schema(db)
    await db.execute('SELECT pg_advisory_xact_lock(?)' if db_backend.is_postgres() else 'BEGIN IMMEDIATE',
                     (80420161110,) if db_backend.is_postgres() else ())
    try:
        execute = getattr(db, 'execute_native_ddl', db.execute)
        await execute(REFERENCE_SCHEMA)
        await execute('CREATE INDEX IF NOT EXISTS shared_account_references_owner ON shared_account_references(account_id, created_at_epoch, id)')
        await db.commit()
    except BaseException:
        await db.rollback()
        raise


class AccountReferenceStore:
    def __init__(self, root: Path | None = None):
        self.root = (root or DEFAULT_ROOT).resolve()
        if self.root.is_relative_to(Path('static/uploads').resolve()):
            raise ValueError('Private photos cannot use public uploads storage')
        self._processing = asyncio.Semaphore(2)

    def _path(self, key: str) -> Path:
        if not re.fullmatch(r'[0-9a-f]{32}\.(?:png|thumbnail\.png|input|staging|thumbnail\.staging)', key):
            raise AccountReferenceError('reference_unavailable', status=404)
        path = self.root / key
        if not path.resolve().is_relative_to(self.root):
            raise AccountReferenceError('reference_unavailable', status=404)
        return path

    def _cleanup(self, paths) -> None:
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning('shared_reference_staging_cleanup_failed')

    def _normalize(self, item_id: str) -> dict:
        source = self._path(item_id + '.input')
        staged = [self._path(item_id + suffix) for suffix in ('.staging', '.thumbnail.staging')]
        finals = [self._path(item_id + suffix) for suffix in ('.png', '.thumbnail.png')]
        created, published = [], []
        try:
            for path in staged:
                with path.open('xb'):
                    pass
                created.append(path)
            metadata = normalize_image(source, staged[0], strip_metadata=True)
            size = staged[0].stat().st_size
            if size > DEFAULT_UPLOAD_MAX_BYTES:
                raise AccountReferenceError('media_too_large', status=413)
            with Image.open(staged[0]) as image:
                image.thumbnail((384, 384))
                image.save(staged[1], format='PNG')
            digests = []
            for path in staged:
                digest = hashlib.sha256()
                with path.open('rb') as handle:
                    for chunk in iter(lambda: handle.read(65536), b''):
                        digest.update(chunk)
                digests.append(digest.hexdigest())
            for stage, final in zip(staged, finals):
                os.chmod(stage, 0o600)
                with stage.open('r+b') as handle:
                    os.fsync(handle.fileno())
                # Publish atomically without replacing an existing private file.
                os.link(stage, final)
                published.append(final)
            if os.name != 'nt':
                descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            return {**metadata, 'size_bytes': size, 'sha256': digests[0], 'thumbnail_sha256': digests[1], 'storage_key': finals[0].name}
        except BaseException:
            self._cleanup(published)
            raise
        finally:
            self._cleanup([source, *created])

    @asynccontextmanager
    async def _transaction(self, requested_account_id: str):
        async with db_backend.connect() as db:
            await ensure_reference_schema(db)
            if not db_backend.is_postgres():
                await db.execute('BEGIN IMMEDIATE')
            try:
                for _ in range(32):
                    owner = await canonical_account(db, requested_account_id)
                    suffix = ' FOR UPDATE' if db_backend.is_postgres() else ''
                    row = await (await db.execute('SELECT status FROM shared_accounts WHERE id = ?' + suffix, (owner,))).fetchone()
                    if row and row[0] == 'active':
                        break
                    await db.rollback()
                    if not db_backend.is_postgres():
                        await db.execute('BEGIN IMMEDIATE')
                else:
                    raise WalletConflict('Account changed; retry operation')
                yield db, owner
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def save(self, account_id: str, chunks, *, reauthorize) -> dict:
        item_id = uuid4().hex
        source = self._path(item_id + '.input')
        worker, database_started, source_created, acknowledged = None, False, False, False

        def clean_unpublished(future):
            if future.cancelled():
                return  # Executor completion is unknown during event-loop shutdown.
            if source_created:
                self._cleanup([source])
            if future.exception() is None:
                self._cleanup([self._path(item_id + suffix) for suffix in ('.png', '.thumbnail.png')])

        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            async with asyncio.timeout(UPLOAD_TIMEOUT_SECONDS):
                size = 0
                with source.open('xb') as handle:
                    source_created = True
                    os.chmod(source, 0o600)
                    async for chunk in chunks:
                        size += len(chunk)
                        if size > DEFAULT_UPLOAD_MAX_BYTES:
                            raise AccountReferenceError('media_too_large', status=413)
                        handle.write(chunk)
                if not size:
                    raise AccountReferenceError('empty_file')
                await self._processing.acquire()
                try:
                    worker = asyncio.create_task(asyncio.to_thread(self._normalize, item_id))
                except BaseException:
                    self._processing.release()
                    raise
                # Request cancellation must not free a permit while its shielded
                # decoder still owns memory and files in the executor.
                worker.add_done_callback(lambda _future: self._processing.release())
                prepared = await asyncio.shield(worker)
                await reauthorize()
                database_started = True
                async with self._transaction(account_id) as (db, owner):
                    created_at = int(time.time())
                    await db.execute('''INSERT INTO shared_account_references
                        (id, account_id, storage_key, sha256, mime, width, height, size_bytes, created_at_epoch, thumbnail_sha256)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (item_id, owner, prepared['storage_key'], prepared['sha256'], prepared['mime'],
                         prepared['width'], prepared['height'], prepared['size_bytes'], created_at, prepared['thumbnail_sha256']))
                logger.info('shared_reference_saved account_id=%s reference_id=%s size_bytes=%s', owner, item_id, prepared['size_bytes'])
                acknowledged = True
                return {'id': item_id, **{key: prepared[key] for key in ('mime', 'width', 'height', 'size_bytes')},
                        'created_at_epoch': created_at}
        except ImageNormalizationError as exc:
            raise AccountReferenceError(exc.code) from exc
        except TimeoutError as exc:
            raise AccountReferenceError('upload_timeout', status=408) from exc
        finally:
            if worker is None:
                if source_created:
                    self._cleanup([source])
            elif not database_started:
                if worker.done():
                    clean_unpublished(worker)
                else:
                    worker.add_done_callback(clean_unpublished)
            # Once metadata work starts, commit may have succeeded even if its
            # acknowledgement was cancelled. Leave final files for reconciliation.
            if database_started and not acknowledged:
                logger.warning('shared_reference_metadata_unconfirmed reference_id=%s', item_id)

    async def list(self, account_id: str, offset: int = 0) -> dict:
        if type(offset) is not int or not 0 <= offset <= 2**31 - 1:
            raise AccountReferenceError('invalid_page')
        async with self._transaction(account_id) as (db, owner):
            rows = await (await db.execute(OWNED + f''' SELECT {COLUMNS} FROM shared_account_references
                WHERE account_id IN (SELECT id FROM owned) AND removed_at_epoch IS NULL
                ORDER BY created_at_epoch DESC, id DESC LIMIT 25 OFFSET ?''', (owner, offset))).fetchall()
        return {'references': [_metadata(row) for row in rows[:24]],
                'next_offset': offset + 24 if len(rows) > 24 else None}

    async def read(self, account_id: str, item_id: str, *, thumbnail: bool = False) -> bytes:
        item_id = reference_id(item_id)
        async with self._transaction(account_id) as (db, owner):
            row = await (await db.execute(OWNED + ''' SELECT storage_key, sha256, thumbnail_sha256 FROM shared_account_references
                WHERE account_id IN (SELECT id FROM owned) AND id = ? AND removed_at_epoch IS NULL''', (owner, item_id))).fetchone()
            if not row:
                raise AccountReferenceError('reference_unavailable', status=404)
            key = row[0]
            if key != item_id + '.png':
                raise AccountReferenceError('reference_unavailable', status=404)
            path = self._path(item_id + '.thumbnail.png' if thumbnail else key)

            def read_file():
                descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
                limit = 1024 * 1024 if thumbnail else DEFAULT_UPLOAD_MAX_BYTES
                with os.fdopen(descriptor, 'rb') as handle:
                    raw = handle.read(limit + 1)
                if len(raw) > limit or hashlib.sha256(raw).hexdigest() != row[2 if thumbnail else 1]:
                    logger.error('shared_reference_integrity_failed reference_id=%s thumbnail=%s', item_id, thumbnail)
                    raise AccountReferenceError('reference_unavailable', status=404)
                return raw

            try:
                return await asyncio.to_thread(read_file)
            except OSError as exc:
                raise AccountReferenceError('reference_unavailable', status=404) from exc

    async def remove(self, account_id: str, item_id: str) -> None:
        item_id = reference_id(item_id)
        async with self._transaction(account_id) as (db, owner):
            row = await (await db.execute(OWNED + ''' SELECT id FROM shared_account_references
                WHERE account_id IN (SELECT id FROM owned) AND id = ?''', (owner, item_id))).fetchone()
            if not row:
                raise AccountReferenceError('reference_unavailable', status=404)
            await db.execute('UPDATE shared_account_references SET removed_at_epoch = COALESCE(removed_at_epoch, ?) WHERE id = ?',
                             (int(time.time()), item_id))
        logger.info('shared_reference_removed account_id=%s reference_id=%s', owner, item_id)
