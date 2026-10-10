from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database, wan3_prime_api
from bot.services.wan3_prime_lifecycle import Wan3PrimeActor
from bot.services.wan3_prime_media import Wan3PrimeValidationError
from bot.services.wan3_prime_probe_cache import probe_slot
from bot.services.wan3_prime_storage import ActualWan3PrimeProbe, wan3_prime_storage


@pytest.mark.asyncio
async def test_voice_admission_precedes_download_and_conversion(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    user = await database.get_or_create_user(995555)
    bot = SimpleNamespace(download=AsyncMock())
    async with probe_slot(user.id):
        with pytest.raises(Wan3PrimeValidationError) as error:
            await wan3_prime_api.store_telegram_wan3_prime_media(telegram_id=user.telegram_id, bot=bot,
                file_id='compressed-voice', filename='voice.ogg', kind='audio', declared_size=1024)
        assert error.value.status == 429
    bot.download.assert_not_awaited()


@pytest.mark.asyncio
async def test_link_import_and_quote_admission_precedes_network(monkeypatch):
    from bot.services import wan3_prime_storage as storage

    user = await database.get_or_create_user(995556)
    actor = Wan3PrimeActor(user.id, user.telegram_id)
    await wan3_prime_storage.init_schema()
    network = AsyncMock(return_value={'url': 'https://example.test/page'})
    monkeypatch.setattr(storage, 'fetch_public_asset', network)
    async with probe_slot(user.id):
        with pytest.raises(Wan3PrimeValidationError) as imported:
            await wan3_prime_storage.import_url(actor, kind='link', url='https://example.test/page')
        with pytest.raises(Wan3PrimeValidationError) as quoted:
            await ActualWan3PrimeProbe(wan3_prime_storage, actor).probe_url('https://example.test/page', kind='link')
        assert imported.value.status == quoted.value.status == 429
    network.assert_not_awaited()


def test_audio_worker_sets_memory_cpu_and_output_limits(monkeypatch):
    import resource
    from unittest.mock import Mock

    from bot.services.wan3_prime_audio_worker import apply_limits

    setter = Mock()
    monkeypatch.setattr(resource, 'setrlimit', setter)
    apply_limits(15 * 1024**2, 512 * 1024**2)
    limits = {call.args[0]: call.args[1] for call in setter.call_args_list}
    assert limits[resource.RLIMIT_FSIZE] == (15 * 1024**2, 15 * 1024**2)
    assert limits[resource.RLIMIT_AS] == (512 * 1024**2, 512 * 1024**2)
    assert limits[resource.RLIMIT_CPU] == (12, 12)


@pytest.mark.parametrize('duration', [0, 16, 3600, float('nan')])
def test_audio_worker_rejects_out_of_range_before_transcoding(tmp_path, monkeypatch, duration):
    import json
    from unittest.mock import Mock

    from bot.services import wan3_prime_audio_worker as worker

    run = Mock(return_value=SimpleNamespace(stdout=json.dumps({'format': {'duration': duration}, 'streams': [{'codec_type': 'audio'}]})))
    monkeypatch.setattr(worker.subprocess, 'run', run)
    with pytest.raises(ValueError, match='duration'):
        worker.transcode(tmp_path / 'source.ogg', tmp_path / 'target.mp3', 15, 15 * 1024**2)
    assert run.call_count == 1
    assert run.call_args.args[0][0] == 'ffprobe'
