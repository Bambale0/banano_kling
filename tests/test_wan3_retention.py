import asyncio

import pytest

from bot import database
from bot.services.wan3_prime_lifecycle import Wan3PrimeActor
from bot.services.wan3_prime_media import Wan3PrimeValidationError
from bot.services.wan3_prime_storage import CHUNK_ROOT, wan3_prime_storage
from tests.test_wan3_prime_storage import png_bytes


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
