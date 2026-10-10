import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from bot import database
from bot.services.wan3_prime_lifecycle import Wan3PrimeActor
from bot.services.wan3_prime_media import Wan3PrimeValidationError
from bot.services.wan3_prime_storage import ActualWan3PrimeProbe, wan3_prime_storage
from tests.test_wan3_prime_storage import png_bytes


async def owned_input():
    user = await database.get_or_create_user(942841)
    actor = Wan3PrimeActor(user.id, user.telegram_id)
    image = png_bytes()
    session = await wan3_prime_storage.init_upload(actor, kind='image', filename='probe.png', size=len(image))
    await wan3_prime_storage.save_chunk(actor, upload_id=session['upload_id'], index=0, total=1, chunk=image)
    saved = await wan3_prime_storage.complete_upload(actor, upload_id=session['upload_id'])
    return actor, saved


@pytest.mark.asyncio
async def test_quote_reuses_upload_metadata_and_one_digest_verification(tmp_path, monkeypatch):
    from bot.services import wan3_prime_storage as storage

    monkeypatch.chdir(tmp_path)
    actor, saved = await owned_input()
    original_hash = storage._sha256_file
    hash_file = Mock(wraps=original_hash)
    monkeypatch.setattr(storage, '_sha256_file', hash_file)
    probe = ActualWan3PrimeProbe(wan3_prime_storage, actor)
    decode = AsyncMock(side_effect=AssertionError('verified upload must not be decoded on quote'))
    monkeypatch.setattr(probe, 'probe_file', decode)
    first = await probe.probe_url(saved['url'], kind='image')
    again = await probe.probe_url(saved['url'], kind='image')
    assert first == again and first.width == 320
    assert hash_file.call_count == 1
    decode.assert_not_called()


@pytest.mark.asyncio
async def test_same_size_file_mutation_invalidates_cached_digest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    actor, saved = await owned_input()
    probe = ActualWan3PrimeProbe(wan3_prime_storage, actor)
    await probe.probe_url(saved['url'], kind='image')
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        row = await (await db.execute('SELECT local_path FROM wan3_prime_media WHERE public_url = ?', (saved['url'],))).fetchone()
    local = Path(row[0])
    content = await asyncio.to_thread(local.read_bytes)
    await asyncio.to_thread(local.write_bytes, content[:-1] + bytes([content[-1] ^ 1]))
    with pytest.raises(Wan3PrimeValidationError, match='changed') as error:
        await probe.probe_url(saved['url'], kind='image')
    assert error.value.status == 409


@pytest.mark.asyncio
async def test_expensive_probe_slots_are_bounded_per_user_and_globally(monkeypatch):
    from bot.services.wan3_prime_probe_cache import probe_slot

    monkeypatch.setenv('WAN3_PROBE_GLOBAL_CONCURRENCY', '2')
    monkeypatch.setenv('WAN3_PROBE_USER_CONCURRENCY', '1')
    async with probe_slot(100):
        with pytest.raises(Wan3PrimeValidationError) as user_limit:
            async with probe_slot(100):
                raise AssertionError('second user probe was admitted')
        assert user_limit.value.status == 429
        async with probe_slot(200):
            with pytest.raises(Wan3PrimeValidationError) as global_limit:
                async with probe_slot(300):
                    raise AssertionError('third global probe was admitted')
            assert global_limit.value.status == 429
    # Both admission counters must be released even after exceptions.
    async with probe_slot(100):
        pass
