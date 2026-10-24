import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bot import database
from bot.services.wan3_prime_lifecycle import Wan3PrimeActor
from bot.services.wan3_prime_media import Wan3PrimeValidationError
from bot.services.wan3_prime_storage import CHUNK_ROOT, wan3_prime_storage
from tests.test_wan3_prime_storage import png_bytes


async def assert_upload_admitted_during_protected_media_scan(tmp_path, monkeypatch):
    """Exercise real reservations while an existing recipe lookup is stalled."""
    monkeypatch.chdir(tmp_path)
    user = await database.get_or_create_user(88186)
    actor = Wan3PrimeActor(user.id, user.telegram_id)
    raw = png_bytes()
    session = await wan3_prime_storage.init_upload(actor, kind='image', filename='ref.png', size=len(raw))
    await wan3_prime_storage.save_chunk(actor, upload_id=session['upload_id'], index=0, total=1, chunk=raw)
    saved = await wan3_prime_storage.complete_upload(actor, upload_id=session['upload_id'])
    await database.add_generation_task(user.id, user.telegram_id, 'wan3_slow_pinned_input', 'video', 'wan_3_prime',
        request_data={'reference_image_urls': [saved['url']]})
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE wan3_prime_media SET created_at = '2000-01-01'")
        await db.commit()

    scan_started = asyncio.Event()
    release_scan = asyncio.Event()
    original_connect = database.db_backend.connect

    class ScanConnection:
        def __init__(self, db):
            self.db = db

        @property
        def row_factory(self):
            return self.db.row_factory

        @row_factory.setter
        def row_factory(self, value):
            self.db.row_factory = value

        def __getattr__(self, name):
            return getattr(self.db, name)

        async def execute(self, sql, parameters=()):
            if 'SELECT 1 FROM generation_tasks WHERE request_data LIKE' in sql:
                scan_started.set()
                await release_scan.wait()
            return await self.db.execute(sql, parameters)

    @asynccontextmanager
    async def slow_connect(*args, **kwargs):
        async with original_connect(*args, **kwargs) as db:
            yield ScanConnection(db)

    monkeypatch.setattr(database.db_backend, 'connect', slow_connect)
    cleanup = asyncio.create_task(wan3_prime_storage.cleanup_expired(limit=1))
    upload = None
    try:
        await asyncio.wait_for(scan_started.wait(), timeout=5)
        upload = asyncio.create_task(wan3_prime_storage.init_upload(
            actor, kind='image', filename='new.png', size=len(raw), importing=True))
        done, _ = await asyncio.wait({upload}, timeout=1)
        admitted_before_scan_finished = upload in done
    finally:
        release_scan.set()
        results = await asyncio.gather(cleanup, *([upload] if upload else []), return_exceptions=True)
    assert all(not isinstance(result, BaseException) for result in results), results
    assert admitted_before_scan_finished, 'Reference reservation waited for unrelated retained-media scan'
    async with original_connect(database.DATABASE_PATH) as db:
        remaining = await (await db.execute('SELECT public_url FROM wan3_prime_media')).fetchall()
    assert [row[0] for row in remaining] == [saved['url']]


@pytest.mark.asyncio
async def test_upload_admitted_during_protected_media_scan(tmp_path, monkeypatch):
    await assert_upload_admitted_during_protected_media_scan(tmp_path, monkeypatch)


async def assert_new_pin_survives_retention_prefilter(tmp_path, monkeypatch):
    """A recipe committed after a negative scan still owns its input bytes."""
    monkeypatch.chdir(tmp_path)
    user = await database.get_or_create_user(88187)
    actor = Wan3PrimeActor(user.id, user.telegram_id)
    raw = png_bytes()
    session = await wan3_prime_storage.init_upload(actor, kind='image', filename='ref.png', size=len(raw))
    await wan3_prime_storage.save_chunk(actor, upload_id=session['upload_id'], index=0, total=1, chunk=raw)
    saved = await wan3_prime_storage.complete_upload(actor, upload_id=session['upload_id'])
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE wan3_prime_media SET created_at = '2000-01-01'")
        path = Path((await (await db.execute('SELECT local_path FROM wan3_prime_media')).fetchone())[0])
        await db.commit()

    negative_scan = asyncio.Event()
    release_scan = asyncio.Event()
    original_connect = database.db_backend.connect

    class NegativeCursor:
        async def fetchone(self):
            negative_scan.set()
            await release_scan.wait()

    class ScanConnection:
        def __init__(self, db):
            self.db = db

        @property
        def row_factory(self):
            return self.db.row_factory

        @row_factory.setter
        def row_factory(self, value):
            self.db.row_factory = value

        def __getattr__(self, name):
            return getattr(self.db, name)

        async def execute(self, sql, parameters=()):
            cursor = await self.db.execute(sql, parameters)
            if ('SELECT 1 FROM generation_tasks WHERE request_data LIKE' in sql
                    and not negative_scan.is_set()):
                assert await cursor.fetchone() is None
                return NegativeCursor()
            return cursor

    @asynccontextmanager
    async def slow_connect(*args, **kwargs):
        async with original_connect(*args, **kwargs) as db:
            yield ScanConnection(db)

    monkeypatch.setattr(database.db_backend, 'connect', slow_connect)
    cleanup = asyncio.create_task(wan3_prime_storage.cleanup_expired(limit=1))
    pin = None
    try:
        await asyncio.wait_for(negative_scan.wait(), timeout=5)
        pin = asyncio.create_task(database.add_generation_task(
            user.id, user.telegram_id, 'wan3_newly_pinned_input', 'video', 'wan_3_prime',
            request_data={'reference_image_urls': [saved['url']]}))
        done, _ = await asyncio.wait({pin}, timeout=1)
        pinned_before_recheck = pin in done
    finally:
        release_scan.set()
        results = await asyncio.gather(cleanup, *([pin] if pin else []), return_exceptions=True)
    assert all(not isinstance(result, BaseException) for result in results), results
    assert pinned_before_recheck, 'Recipe writer was blocked by a read-only retention prefilter'
    assert path.read_bytes() == raw
    async with original_connect(database.DATABASE_PATH) as db:
        row = await (await db.execute('SELECT public_url FROM wan3_prime_media')).fetchone()
    assert row and row[0] == saved['url']


@pytest.mark.asyncio
async def test_new_pin_survives_retention_prefilter(tmp_path, monkeypatch):
    await assert_new_pin_survives_retention_prefilter(tmp_path, monkeypatch)


@pytest.mark.asyncio
async def test_expired_chunks_release_quota_only_after_removal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    user = await database.get_or_create_user(88183)
    actor = Wan3PrimeActor(user.id, user.telegram_id)
    raw = png_bytes()
    monkeypatch.setenv('WAN3_UPLOAD_USER_QUOTA_BYTES', str(len(raw)))
    session = await wan3_prime_storage.init_upload(actor, kind='image', filename='one.png', size=len(raw))
    await wan3_prime_storage.save_chunk(actor, upload_id=session['upload_id'], index=0, total=1, chunk=raw)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE wan3_prime_upload_sessions SET expires_at = '2000-01-01', updated_at = '2000-01-01' WHERE upload_id = ?", (session['upload_id'],))
        await db.commit()
    await wan3_prime_storage.cleanup_expired()
    assert not (CHUNK_ROOT/session['upload_id']).exists()
    replacement = await wan3_prime_storage.init_upload(actor, kind='image', filename='two.png', size=len(raw))
    assert replacement['upload_id'] != session['upload_id']


@pytest.mark.asyncio
async def test_concurrent_quota_admission_counts_all_open_reservations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    user = await database.get_or_create_user(88184)
    actor = Wan3PrimeActor(user.id, user.telegram_id)
    raw = png_bytes()
    monkeypatch.setenv('WAN3_UPLOAD_USER_QUOTA_BYTES', str(len(raw)*2))
    results = await asyncio.gather(*(wan3_prime_storage.init_upload(actor, kind='image', filename='image.png', size=len(raw)) for _ in range(5)), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 2
    assert all(isinstance(result, (dict, Wan3PrimeValidationError)) for result in results)


@pytest.mark.asyncio
async def test_pinned_old_media_does_not_starve_unused_media_cleanup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    user = await database.get_or_create_user(88185)
    actor = Wan3PrimeActor(user.id, user.telegram_id)
    raw = png_bytes()
    saved = []
    for _ in range(2):
        session = await wan3_prime_storage.init_upload(actor, kind='image', filename='ref.png', size=len(raw))
        await wan3_prime_storage.save_chunk(actor, upload_id=session['upload_id'], index=0, total=1, chunk=raw)
        saved.append(await wan3_prime_storage.complete_upload(actor, upload_id=session['upload_id']))
    await database.add_generation_task(user.id, user.telegram_id, 'wan3_pinned_input', 'video', 'wan_3_prime',
        request_data={'reference_image_urls': [saved[0]['url']]})
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE wan3_prime_media SET created_at = '2000-01-01'")
        await db.commit()
    await wan3_prime_storage.cleanup_expired(limit=1)
    await wan3_prime_storage.cleanup_expired(limit=1)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        remaining = await (await db.execute('SELECT public_url FROM wan3_prime_media')).fetchall()
    assert [row[0] for row in remaining] == [saved[0]['url']]
