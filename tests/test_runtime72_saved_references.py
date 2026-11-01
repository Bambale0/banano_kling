"""Saved-reference uploads must survive overlapping retention pruning."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from bot import database


@pytest.fixture(autouse=True)
async def saved_reference_postgres_schema(isolated_database):
    from tests.runtime72_postgres_fixture import runtime_postgres_schema

    async with runtime_postgres_schema():
        yield


async def test_categorized_references_survive_concurrent_uploads_and_both_cleanup_paths(monkeypatch):
    from bot import reference_library

    monkeypatch.setattr(database, 'SAVED_REFERENCES_MAX_PER_KIND', 1)
    folder = await reference_library.create_category(700123, 'Одежда')
    await asyncio.gather(*[
        database.save_user_reference(700123, kind='image', file_url=f'https://example.test/outfit-{index}.png',
                                     file_hash=f'outfit-{index}', category_id=folder['id'])
        for index in range(5)
    ])
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE saved_references SET created_at = '2000-01-01', last_used_at = '2000-01-01' WHERE user_id = ?",
                         ((await database.get_or_create_user(700123)).id,))
        await db.commit()
    await database.cleanup_saved_references(keep_latest=1, max_age_days=1)
    assert len(await reference_library.list_items(700123, folder['id'])) == 5


async def test_personal_categories_bootstrap_natively_on_postgres(monkeypatch):
    if not database.db_backend.is_postgres():
        pytest.skip('requires isolated PostgreSQL runtime CI')
    import os

    import psycopg

    from bot import postgres_aiosqlite, reference_library

    # Empty tables in the dedicated ephemeral database; normal application
    # read/write must recreate them through the native bootstrap, not SQLite DDL.
    async with await psycopg.AsyncConnection.connect(os.environ['DATABASE_URL']) as conn:
        await conn.execute('DROP TABLE reference_category_items')
        await conn.execute('DROP TABLE reference_categories')
        await conn.commit()
    monkeypatch.setattr(postgres_aiosqlite, '_HELPERS_READY', False)
    folder = await reference_library.create_category(700124, 'Наряды')
    assert (await reference_library.list_categories(700124))[0]['id'] == folder['id']


async def test_postgres_cleanup_locks_even_fully_categorized_owners_before_repinning():
    if not database.db_backend.is_postgres():
        pytest.skip('requires isolated PostgreSQL runtime CI')
    import os

    import psycopg

    from bot import reference_library

    user = await database.get_or_create_user(700125)
    folder = await reference_library.create_category(user.telegram_id, 'Одежда')
    refs = [await database.save_user_reference(user.telegram_id, kind='image', file_url=f'https://example.test/pin-{n}.png',
                                               file_hash=f'pin-{n}', category_id=folder['id']) for n in range(3)]
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE saved_references SET created_at = '2000-01-01', last_used_at = '2000-01-01' WHERE user_id = ?", (user.id,))
        await db.commit()
    pending = []
    async with await psycopg.AsyncConnection.connect(os.environ['DATABASE_URL']) as owner_lock:
        await owner_lock.execute('SELECT id FROM users WHERE id = %s FOR UPDATE', (user.id,))
        async with await psycopg.AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as observer:
            async def wait_for_lock(pattern):
                for _ in range(100):
                    row = await (await observer.execute(
                        "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND query LIKE %s", (pattern,),
                    )).fetchone()
                    if row[0]:
                        return
                    await asyncio.sleep(.02)
                raise AssertionError(f'Expected owner serialization: {pattern}')

            try:
                pin = asyncio.create_task(reference_library.save_item(user.telegram_id, folder['id'], refs[0].id))
                pending.append(pin)
                await wait_for_lock('%SELECT id FROM users WHERE id = %FOR UPDATE%')
                cleanup = asyncio.create_task(database.cleanup_saved_references(keep_latest=1, max_age_days=1))
                pending.append(cleanup)
                await wait_for_lock('%SELECT u.id FROM users u WHERE EXISTS%')
                assert not cleanup.done()
                await owner_lock.execute('DELETE FROM reference_category_items WHERE user_id = %s AND reference_id IN (%s, %s)',
                                         (user.id, refs[0].id, refs[1].id))
                await owner_lock.commit()
                await asyncio.wait_for(asyncio.gather(*pending), timeout=10)
            finally:
                await owner_lock.rollback()
                for task in pending:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
    assert str(refs[0].id) in {item['id'] for item in await reference_library.list_items(user.telegram_id, folder['id'])}


@pytest.mark.asyncio
async def test_overlapping_uploads_return_each_reference_when_retention_prunes(monkeypatch):
    user = await database.get_or_create_user(123456)
    monkeypatch.setattr(database, 'get_or_create_user', AsyncMock(return_value=user))
    monkeypatch.setattr(database, '_invalidate_saved_reference_cache', AsyncMock())
    original_prune = database._prune_saved_references_for_user_id

    async def overlapping_prune(*args, **kwargs):
        # Yield where production commits before pruning: other uploads can now
        # insert and prune the oldest row before its caller reads it back.
        await asyncio.sleep(0.05)
        return await original_prune(*args, **kwargs)

    monkeypatch.setattr(database, '_prune_saved_references_for_user_id', overlapping_prune)
    results = await asyncio.gather(*[
        database.save_user_reference(
            123456, kind='image', file_url=f'https://example.test/{index}.png',
            file_hash=f'file-{index}', source='miniapp',
        )
        for index in range(4)
    ])

    assert [reference.file_hash for reference in results] == [f'file-{index}' for index in range(4)]
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        cursor = await db.execute('SELECT COUNT(*) FROM saved_references WHERE user_id = ?', (user.id,))
        assert (await cursor.fetchone())[0] == database.SAVED_REFERENCES_MAX_PER_KIND


@pytest.mark.asyncio
async def test_resaved_reference_is_kept_when_other_timestamps_sort_ahead(monkeypatch):
    user = await database.get_or_create_user(123456)
    monkeypatch.setattr(database, '_invalidate_saved_reference_cache', AsyncMock())
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        # Existing over-limit rows can come from overlapping uploads. A future
        # timestamp also covers the coarse timestamp / older-id tie case.
        for index in range(4):
            await db.execute(
                '''INSERT INTO saved_references
                   (user_id, kind, file_url, file_hash, last_used_at)
                   VALUES (?, 'image', ?, ?, '2099-01-01 00:00:00')''',
                (user.id, f'https://example.test/{index}.png', f'file-{index}'),
            )
        await db.commit()

    reference = await database.save_user_reference(
        123456, kind='image', file_url='https://example.test/0.png',
        file_hash='file-0', source='miniapp',
    )
    stored = await database.get_saved_reference_by_id(123456, reference.id)
    assert stored is not None
    assert stored.file_hash == 'file-0'
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        cursor = await db.execute('SELECT COUNT(*) FROM saved_references WHERE user_id = ?', (user.id,))
        assert (await cursor.fetchone())[0] == database.SAVED_REFERENCES_MAX_PER_KIND


@pytest.mark.asyncio
async def test_postgres_serializes_uploads_before_retention(monkeypatch):
    if not database.db_backend.is_postgres():
        pytest.skip('requires the dedicated ephemeral PostgreSQL test database')
    import os

    import psycopg

    user = await database.get_or_create_user(654321)
    monkeypatch.setattr(database, 'get_or_create_user', AsyncMock(return_value=user))
    monkeypatch.setattr(database, '_invalidate_saved_reference_cache', AsyncMock())
    monkeypatch.setattr(database, 'SAVED_REFERENCES_MAX_PER_KIND', 1)
    original_prune = database._prune_saved_references_for_user_id
    first_at_prune = asyncio.Event()
    release_first = asyncio.Event()
    calls = 0

    async def hold_first_prune(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_at_prune.set()
            await release_first.wait()
        return await original_prune(*args, **kwargs)

    monkeypatch.setattr(database, '_prune_saved_references_for_user_id', hold_first_prune)

    async def upload(index):
        return await database.save_user_reference(
            654321, kind='image', file_url=f'https://example.test/serial-{index}.png',
            file_hash=f'serial-{index}', source='miniapp',
        )

    first = asyncio.create_task(upload(0))
    await asyncio.wait_for(first_at_prune.wait(), timeout=5)
    second = asyncio.create_task(upload(1))
    locked = False
    try:
        async with await psycopg.AsyncConnection.connect(os.environ['DATABASE_URL'], autocommit=True) as observer:
            for _ in range(100):
                cursor = await observer.execute(
                    """SELECT count(*) FROM pg_stat_activity
                       WHERE datname = current_database()
                         AND pid <> pg_backend_pid()
                         AND wait_event_type = 'Lock'
                         AND query LIKE 'SELECT id FROM users WHERE id = %% FOR UPDATE'"""
                )
                locked = (await cursor.fetchone())[0] > 0
                if locked or second.done():
                    break
                await asyncio.sleep(0.01)
        assert locked, 'overlapping upload did not wait for the per-user transaction lock'
    finally:
        release_first.set()
        await asyncio.gather(first, second)

    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        cursor = await db.execute('SELECT COUNT(*) FROM saved_references WHERE user_id = ?', (user.id,))
        assert (await cursor.fetchone())[0] == 1
