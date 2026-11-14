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


async def _evict_owned_media_into_fake_s3(actor, saved, monkeypatch):
    """Simulate a valid Wan upload already migrated out of the local cache."""
    from bot import db as db_backend
    from tests.test_media_storage import FakeS3Client, configure_s3

    async with db_backend.connect(database.DATABASE_PATH) as db:
        row = await (await db.execute(
            "SELECT local_path FROM wan3_prime_media WHERE public_url = ?",
            (saved['url'],),
        )).fetchone()
    local = Path(row[0])
    relative = local.resolve().relative_to(Path('static/uploads').resolve()).as_posix()
    original_bytes = local.read_bytes()
    fake = FakeS3Client()
    fake.objects[('neuromix-media', f'uploads/{relative}')] = original_bytes
    configure_s3(monkeypatch, fake)
    local.unlink()
    assert not local.exists()
    return local, original_bytes, fake


@pytest.mark.asyncio
async def test_migrated_owned_wan_media_is_restored_from_s3_before_quote(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    actor, saved = await owned_input()
    local, original, _fake = await _evict_owned_media_into_fake_s3(actor, saved, monkeypatch)

    probe = ActualWan3PrimeProbe(wan3_prime_storage, actor)
    info = await probe.probe_url(saved['url'], kind='image')

    assert info.width == 320
    assert info.height == 240
    assert info.size_bytes == len(original)
    assert local.read_bytes() == original
    assert local.with_name(f'.{local.name}.s3-cache').is_file()


@pytest.mark.asyncio
async def test_migrated_wan_media_cannot_be_materialized_by_another_user(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    actor, saved = await owned_input()
    local, _original, fake = await _evict_owned_media_into_fake_s3(actor, saved, monkeypatch)
    download = Mock(wraps=fake.download_file)
    monkeypatch.setattr(fake, 'download_file', download)

    foreign = Wan3PrimeActor(actor.user_id + 1, actor.telegram_id + 1)
    with pytest.raises(Wan3PrimeValidationError, match='another user') as rejected:
        await ActualWan3PrimeProbe(wan3_prime_storage, foreign).probe_url(saved['url'], kind='image')

    assert rejected.value.status == 403
    assert not local.exists()
    download.assert_not_called()


@pytest.mark.asyncio
async def test_migrated_wan_media_with_wrong_s3_digest_fails_closed(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    actor, saved = await owned_input()
    _local, original, fake = await _evict_owned_media_into_fake_s3(actor, saved, monkeypatch)
    key = next(iter(fake.objects))
    fake.objects[key] = original[:-1] + bytes([original[-1] ^ 1])

    with pytest.raises(Wan3PrimeValidationError, match='changed') as rejected:
        await ActualWan3PrimeProbe(wan3_prime_storage, actor).probe_url(saved['url'], kind='image')

    assert rejected.value.status == 409


@pytest.mark.asyncio
async def test_s3_only_wan_reference_can_be_quoted_without_reupload(monkeypatch, tmp_path):
    from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycle
    from tests.test_wan3_prime_lifecycle import Prices, Provider

    monkeypatch.chdir(tmp_path)
    actor, saved = await owned_input()
    local, _original, fake = await _evict_owned_media_into_fake_s3(actor, saved, monkeypatch)
    probe = ActualWan3PrimeProbe(wan3_prime_storage)
    lifecycle = Wan3PrimeLifecycle(probe=probe, preset_manager=Prices(rates={'480p': 2}), transport=Provider())

    quote = await lifecycle.quote(actor, {
        'model': 'wan_3_prime', 'scenario': 'reference',
        'prompt': 'Keep the original scene',
        'reference_image_urls': [saved['url']],
        'resolution': '480P', 'duration': 13, 'audio': True,
    })

    assert quote.billable_seconds_reserved == 13
    assert local.is_file()
    assert len(fake.objects) == 1


@pytest.mark.asyncio
async def test_s3_unavailable_owned_wan_media_preserves_retryable_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    actor, saved = await owned_input()
    local, _original, fake = await _evict_owned_media_into_fake_s3(actor, saved, monkeypatch)
    fake.objects.clear()

    with pytest.raises(Wan3PrimeValidationError, match='temporarily unavailable') as rejected:
        await ActualWan3PrimeProbe(wan3_prime_storage, actor).probe_url(saved['url'], kind='image')

    assert rejected.value.status == 503
    assert not local.exists()
