"""Validate real media structure and the documented boundary, not file names."""
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from bot.services.wan3_prime_media import Wan3PrimeValidationError
from bot.services.wan3_prime_storage import ActualWan3PrimeProbe


def test_pdf_at_fifty_page_boundary_counts_only_real_pages(tmp_path):
    writer = PdfWriter()
    for _ in range(50):
        writer.add_blank_page(width=320, height=240)
    path = tmp_path / 'exactly-fifty.pdf'
    writer.write(path)
    assert ActualWan3PrimeProbe()._document_pages(path) == 50


@pytest.mark.asyncio
async def test_audio_cannot_be_a_renamed_video_without_audio(tmp_path, monkeypatch):
    from bot.services import wan3_prime_storage as storage
    path = tmp_path / 'fake.mp3'
    path.write_bytes(b'not real audio')
    monkeypatch.setattr(storage.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=(
        '{"format":{"duration":"5","format_name":"mov,mp4"},'
        '"streams":[{"codec_type":"video","width":640,"height":360}]}'
    )))
    with pytest.raises(Wan3PrimeValidationError):
        await ActualWan3PrimeProbe().probe_file(str(path), kind='audio')


@pytest.mark.asyncio
async def test_telegram_voice_is_converted_not_rejected(tmp_path, monkeypatch):
    import asyncio
    import subprocess

    from bot import database, wan3_prime_api
    from bot.services.wan3_prime_lifecycle import Wan3PrimeActor
    from bot.services.wan3_prime_storage import wan3_prime_probe

    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'voice.ogg'
    await asyncio.to_thread(subprocess.run, ['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1.2',
                    '-c:a', 'libopus', str(source)], check=True, timeout=15)
    audio = source.read_bytes()
    class Bot:
        async def download(self, file_id, *, destination, timeout, seek):
            destination.write(audio)
    saved = await wan3_prime_api.store_telegram_wan3_prime_media(telegram_id=7155, bot=Bot(), file_id='voice',
        filename='voice.ogg', kind='audio', declared_size=len(audio))
    user = await database.get_or_create_user(7155)
    info = await wan3_prime_probe.for_actor(Wan3PrimeActor(user.id, 7155)).probe_url(saved['url'], kind='audio')
    assert info.extension == '.mp3'
    assert 1.1 < info.duration_seconds < 1.5
