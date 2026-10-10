import ast
import inspect
import io
import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycle
from tests.test_wan3_prime_lifecycle import (
    Downloader,
    Prices,
    Probe,
    Provider,
    balance,
    body,
    user_actor,
)


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [500, 502, 503, 504])
async def test_actual_kie_parser_gateway_error_remains_unknown(code):
    from bot.services.wan3_prime_service import Wan3PrimeService
    provider = Provider()
    provider.create_result = Wan3PrimeService(kie_key='test')._parse_kie_create_response(json.dumps({'code': code, 'msg': 'temporary gateway failure'}))
    actor = await user_actor(100)
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    quote = await lifecycle.quote(actor, body())
    result = await lifecycle.launch(actor, body(), quote, 'parsed-gateway')
    assert result['status'] == 'unknown'
    assert await balance(actor.user_id) == 90


@pytest.mark.asyncio
async def test_probe_has_local_protocol_and_demuxer_allowlists(tmp_path, monkeypatch):
    from bot.services import wan3_prime_storage as storage
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'synthetic')
    def run(command, **kwargs):
        assert command[command.index('-protocol_whitelist') + 1] == 'file,pipe'
        assert set(command[command.index('-format_whitelist') + 1].split(',')) <= {'mov', 'wav', 'mp3', 'ogg', 'aac'}
        return SimpleNamespace(returncode=0, stdout=json.dumps({'format': {'duration': '5', 'format_name': 'mov,mp4'},
            'streams': [{'codec_type': 'video', 'width': 640, 'height': 480}]}))
    monkeypatch.setattr(storage.subprocess, 'run', run)
    assert (await storage.ActualWan3PrimeProbe().probe_file(str(source), kind='video')).duration_seconds == 5


def test_voice_decode_has_local_protocol_and_demuxer_allowlists(tmp_path, monkeypatch):
    from bot.services import wan3_prime_audio_worker as worker

    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert command[command.index('-protocol_whitelist') + 1] == 'file,pipe'
        assert 'ogg' in command[command.index('-format_whitelist') + 1].split(',')
        if command[0] == 'ffprobe':
            return SimpleNamespace(returncode=0, stdout=json.dumps({'format': {'duration': 1.2}, 'streams': [{'codec_type': 'audio'}]}))
        assert command.index('-protocol_whitelist') < command.index('-i')
        assert command[command.index('-fs') + 1] == str(15 * 1024**2)
        assert command[command.index('-t') + 1] == '16'
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(worker.subprocess, 'run', run)
    worker.transcode(tmp_path / 'voice.ogg', tmp_path / 'voice.mp3', 15, 15 * 1024**2)
    assert [call[0] for call in calls] == ['ffprobe', 'ffmpeg']


def test_access_log_omits_query_secrets():
    from bot import main
    from bot.safe_access_log import PathOnlyAccessLogger
    logger = logging.getLogger('test-safe-access')
    logger.disabled = False
    logger.setLevel(logging.INFO)
    logger.propagate = False
    output = io.StringIO()
    logger.addHandler(logging.StreamHandler(output))
    access = PathOnlyAccessLogger(logger, '')
    request = SimpleNamespace(remote='127.0.0.1', method='POST', path='/mini-app/api/wan3/callback',
                              path_qs='/mini-app/api/wan3/callback?nonce=DO_NOT_LOG&intent=task')
    access.log(request, SimpleNamespace(status=200, body_length=12), 0.2)
    text = output.getvalue()
    assert 'DO_NOT_LOG' not in text and 'nonce' not in text
    assert '/mini-app/api/wan3/callback' in text
    assert 'access_log_class=PathOnlyAccessLogger' in inspect.getsource(main.main)


@pytest.mark.asyncio
async def test_daily_cleanup_keeps_all_wan_storage(tmp_path, monkeypatch):
    from bot import main
    monkeypatch.chdir(tmp_path)
    tree = ast.parse(inspect.getsource(main._cleanup_loop))
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == '_remove_old_files' and node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == 'static/uploads')
    skip = ast.literal_eval(next(item.value for item in call.keywords if item.arg == 'skip_dirnames'))
    kept = Path('static/uploads/wan3_prime/references/input.mp4')
    removed = Path('static/uploads/old.tmp')
    kept.parent.mkdir(parents=True)
    for path in (kept, removed):
        path.write_bytes(b'synthetic')
        os.utime(path, (1, 1))
    await main._remove_old_files('static/uploads', 1, skip_dirnames=skip)
    assert kept.exists() and not removed.exists()


@pytest.mark.asyncio
async def test_polling_starts_the_same_wan_worker(monkeypatch):
    from bot import main
    from bot.config import config
    from bot.services import wan3_prime_lifecycle as module
    runtime = SimpleNamespace(startup=AsyncMock(), start_worker=AsyncMock())
    monkeypatch.setattr(module, 'wan3_prime_lifecycle', runtime)
    monkeypatch.setattr(config, 'WEBHOOK_HOST', '')
    bot = SimpleNamespace(id=1)
    await main._start_wan_for_polling(bot)
    assert runtime.telegram_bot is bot
    runtime.startup.assert_awaited_once()
    runtime.start_worker.assert_awaited_once()
    assert '_start_wan_for_polling(bot)' in inspect.getsource(main.on_startup)


@pytest.mark.asyncio
async def test_invalid_result_is_redownloaded_before_settlement(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    actor = await user_actor(100)
    provider = Provider()
    probe = Probe(file_duration=None)
    output = Path('static/uploads/wan3_prime/results/retry.mp4')
    downloader = Downloader(output)
    original = downloader.download
    downloader.download = AsyncMock(wraps=original)
    lifecycle = Wan3PrimeLifecycle(probe=probe, preset_manager=Prices(), transport=provider, downloader=downloader)
    recipe = body(duration=-1)
    quote = await lifecycle.quote(actor, recipe)
    result = await lifecycle.launch(actor, recipe, quote, 'bad-result-retry')
    provider.statuses['provider_1'] = {'taskId': 'provider_1', 'state': 'success', 'resultUrls': ['https://owned.test/result.mp4']}
    await lifecycle.reconcile_once(provider_task_id='provider_1')
    assert not output.exists()
    probe.file_duration = 5
    await lifecycle.reconcile_once(provider_task_id='provider_1')
    assert downloader.download.await_count == 2
    assert (await lifecycle.status(actor, result['task_id']))['status'] == 'completed'
    assert await balance(actor.user_id) == 90


@pytest.mark.asyncio
async def test_repeated_bad_result_has_bounded_operator_resolution(tmp_path, monkeypatch):
    from bot.config import config
    from bot.services.wan3_prime_recovery import unresolved_operations
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('WAN3_RESULT_PROBE_MAX_ATTEMPTS', '2')
    actor = await user_actor(100)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(file_duration=None), preset_manager=Prices(), transport=provider,
        downloader=Downloader(Path('static/uploads/wan3_prime/results/invalid.mp4')))
    quote = await lifecycle.quote(actor, body())
    result = await lifecycle.launch(actor, body(), quote, 'repeated-invalid')
    provider.statuses['provider_1'] = {'taskId': 'provider_1', 'state': 'success', 'resultUrls': ['https://owned.test/result.mp4']}
    for _ in range(2):
        await lifecycle.reconcile_once(provider_task_id='provider_1')
    assert (await lifecycle.status(actor, result['task_id']))['status'] == 'result_attention'
    assert result['task_id'] in [item['internal_task_id'] for item in await unresolved_operations()]
    monkeypatch.setattr(config, 'is_admin', lambda value: value == 999999999)
    await lifecycle.resolve_unknown_refund(result['task_id'], admin_telegram_id=999999999, reason='provider result permanently unavailable')
    assert await balance(actor.user_id) == 100


@pytest.mark.asyncio
async def test_permanent_download_failure_enters_operator_queue_without_resubmission(tmp_path, monkeypatch):
    from bot.services.wan3_prime_recovery import unresolved_operations

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('WAN3_RESULT_PROBE_MAX_ATTEMPTS', '2')
    actor = await user_actor(100)
    provider = Provider()
    failed_download = SimpleNamespace(download=AsyncMock(side_effect=TimeoutError('upstream unavailable')))
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider, downloader=failed_download)
    quote = await lifecycle.quote(actor, body())
    launched = await lifecycle.launch(actor, body(), quote, 'download-outage')
    provider.statuses['provider_1'] = {'taskId': 'provider_1', 'state': 'success', 'resultUrls': ['https://owned.test/expired.mp4']}
    for _ in range(3):
        await lifecycle.reconcile_once(provider_task_id='provider_1')
    assert (await lifecycle.status(actor, launched['task_id']))['status'] == 'result_attention'
    assert failed_download.download.await_count == 2
    assert launched['task_id'] in [row['internal_task_id'] for row in await unresolved_operations()]
    assert provider.creates == 1 and await balance(actor.user_id) == 90
