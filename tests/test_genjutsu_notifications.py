"""Synthetic terminal notifications: no Telegram/provider or production database I/O."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.genjutsu.contract import PipelineError
from bot.genjutsu.delivery import DeliveryFailure
from tests.test_genjutsu_repository import build_repo, make_quote


async def failed_run(repo, *, admin_free=False, code='provider_nsfw'):
    quote = await make_quote(repo)
    run = await repo.start(101, 'notification-case', quote['id'], admin_free=admin_free)
    settings, _ = await repo.settings()
    step = await repo.claim_step(settings)
    await repo.finish_step(step['id'], step['lease_token'], 'failed', error_code=code)
    return run, settings


@pytest.mark.asyncio
async def test_failed_paid_run_enqueues_one_settled_refund_notice(tmp_path):
    repo, _ = await build_repo(tmp_path)
    run, settings = await failed_run(repo)
    assert await repo.balance(101) == 100
    item = await repo.claim_notification(settings)
    assert item['run_id'] == run['id']
    assert item['summary']['reserved_credits'] == 10
    assert item['summary']['refunded_credits'] == 10
    assert item['summary']['charged_credits'] == 0
    assert item['summary']['moderation_count'] == 1
    assert await repo.claim_notification(settings) is None


@pytest.mark.asyncio
async def test_failed_run_sends_plain_refund_notice_once(tmp_path):
    from bot.genjutsu.delivery import TerminalNotifications
    repo, _ = await build_repo(tmp_path)
    run, _ = await failed_run(repo)
    send = AsyncMock(return_value='synthetic-message')
    worker = TerminalNotifications(repo, send)
    assert await worker.tick() is True
    assert await worker.tick() is False
    send.assert_awaited_once()
    owner, text, run_id, _ = send.call_args.args
    assert owner == 101 and run_id == run['id']
    assert 'модерац' in text and '10 🍌' in text and 'на ваш баланс' in text
    assert 'provider_nsfw' not in text and 'http' not in text


async def notification_row(connect, run_id):
    async with connect() as db:
        return await (await db.execute('SELECT * FROM genjutsu_notifications WHERE run_id=?', (run_id,))).fetchone()


@pytest.mark.asyncio
async def test_admin_free_failure_says_no_charge_never_fake_refund(tmp_path):
    from bot.genjutsu.delivery import TerminalNotifications
    repo, _ = await build_repo(tmp_path)
    await failed_run(repo, admin_free=True)
    send = AsyncMock(return_value='free-notice')
    assert await TerminalNotifications(repo, send).tick()
    text = send.call_args.args[1]
    assert 'Списания бананов не было' in text
    assert 'возвращено' not in text.lower()
    assert await repo.balance(101) == 100


@pytest.mark.asyncio
async def test_concurrent_cancellation_enqueues_once_and_refunds_once(tmp_path):
    repo, _ = await build_repo(tmp_path)
    quote = await make_quote(repo)
    run = await repo.start(101, 'cancel-notice', quote['id'])
    await asyncio.gather(repo.cancel(101, run['id']), repo.cancel(101, run['id']))
    settings, _ = await repo.settings()
    claims = await asyncio.gather(repo.claim_notification(settings), repo.claim_notification(settings))
    items = [item for item in claims if item]
    assert len(items) == 1
    assert items[0]['summary']['state'] == 'canceled'
    assert items[0]['summary']['refunded_credits'] == 10
    assert await repo.balance(101) == 100
    item = items[0]
    await repo.finish_notification(run['id'], item['lease_token'], 'delivered', message_id='test-only')
    await repo.cancel(101, run['id'])
    assert await repo.claim_notification(settings) is None


@pytest.mark.asyncio
async def test_partial_run_waits_for_all_variants_and_reports_net_charge(tmp_path):
    from bot.genjutsu.delivery import terminal_notification_text
    repo, _ = await build_repo(tmp_path)
    quote = await make_quote(repo, variants=2)
    run = await repo.start(101, 'partial-notice', quote['id'])
    settings, _ = await repo.settings()
    first = await repo.claim_step(settings)
    await repo.finish_step(first['id'], first['lease_token'], 'failed', error_code='provider_nsfw')
    assert await repo.claim_notification(settings) is None
    second = await repo.claim_step(settings)
    await repo.begin_submission(second['id'], second['lease_token'], 5000)
    output = await repo.add_asset(101, 'video', 'synthetic-partial.mp4', {'duration_ms': 5000})
    await repo.finish_step(second['id'], second['lease_token'], 'completed', output_asset_id=output['id'])
    item = await repo.claim_notification(settings)
    assert item['run_id'] == run['id']
    assert item['summary']['state'] == 'partial'
    assert item['summary']['reserved_credits'] == 20
    assert item['summary']['refunded_credits'] == 10
    assert item['summary']['charged_credits'] == 10
    assert item['summary']['completed_count'] == 1
    assert 'Готовые результаты сохранены' in terminal_notification_text(item['summary'])
    assert await repo.balance(101) == 90


@pytest.mark.asyncio
async def test_failed_chain_notice_includes_released_downstream_reserve(tmp_path):
    repo, _ = await build_repo(tmp_path)
    quote = await make_quote(repo, steps=2)
    run = await repo.start(101, 'chain-notice', quote['id'])
    settings, _ = await repo.settings()
    first = await repo.claim_step(settings)
    await repo.finish_step(first['id'], first['lease_token'], 'failed', error_code='provider_failed')
    item = await repo.claim_notification(settings)
    assert item['run_id'] == run['id']
    assert item['summary']['reserved_credits'] == 70
    assert item['summary']['refunded_credits'] == 70
    assert item['summary']['charged_credits'] == 0
    assert item['summary']['canceled_count'] == 1
    assert await repo.balance(101) == 100


@pytest.mark.asyncio
async def test_success_and_nonterminal_review_do_not_enqueue_failure_notice(tmp_path):
    repo, _ = await build_repo(tmp_path)
    quote = await make_quote(repo)
    run = await repo.start(101, 'review-no-notice', quote['id'])
    settings, _ = await repo.settings()
    first = await repo.claim_step(settings)
    attempt = await repo.begin_submission(first['id'], first['lease_token'], 5000)
    await repo.accept_submission(first['id'], attempt, 'synthetic-provider')
    queued = await repo.claim_step(settings)
    await repo.park_step(queued['id'], queued['lease_token'], 'provider_http_503')
    assert await repo.claim_notification(settings) is None
    assert await repo.balance(101) == 90
    await repo.request_reconciliation(999, run['id'], queued['id'])
    step = await repo.claim_step(settings)
    output = await repo.add_asset(101, 'video', 'synthetic-success.mp4', {'duration_ms': 5000})
    await repo.finish_step(step['id'], step['lease_token'], 'completed', output_asset_id=output['id'])
    assert await repo.claim_notification(settings) is None
    assert (await repo.claim_delivery(settings))['run_id'] == run['id']


@pytest.mark.asyncio
async def test_migration_and_old_terminal_refresh_never_backfill_notices(tmp_path):
    repo, connect = await build_repo(tmp_path)
    run, settings = await failed_run(repo)
    # Emulate a pre-feature terminal row without a notice in this synthetic DB.
    async with connect() as db:
        await db.execute('DELETE FROM genjutsu_notifications WHERE run_id=?', (run['id'],))
        await db.commit()
    await repo.migrate()
    await repo.migrate()
    await repo.cancel(101, run['id'])
    assert await repo.claim_notification(settings) is None


@pytest.mark.asyncio
async def test_outbox_failure_rolls_back_terminal_state_and_refund(tmp_path):
    repo, connect = await build_repo(tmp_path)
    quote = await make_quote(repo)
    run = await repo.start(101, 'atomic-notice', quote['id'])
    settings, _ = await repo.settings()
    step = await repo.claim_step(settings)
    async with connect() as db:
        await db.execute("CREATE TRIGGER fail_notice BEFORE INSERT ON genjutsu_notifications BEGIN SELECT RAISE(ABORT, 'synthetic outbox failure'); END")
        await db.commit()
    with pytest.raises(Exception, match='synthetic outbox failure'):
        await repo.finish_step(step['id'], step['lease_token'], 'failed', error_code='provider_failed')
    assert await repo.balance(101) == 90
    assert (await repo.get_run(101, run['id']))['state'] == 'running'
    async with connect() as db:
        await db.execute('DROP TRIGGER fail_notice')
        await db.commit()
    await repo.finish_step(step['id'], step['lease_token'], 'failed', error_code='provider_failed')
    assert await repo.balance(101) == 100
    assert (await repo.claim_notification(settings))['summary']['refunded_credits'] == 10


@pytest.mark.asyncio
@pytest.mark.parametrize('failure,expected', [
    (DeliveryFailure('chat_unavailable'), 'unavailable'),
    (DeliveryFailure('message_rejected'), 'unavailable'),
    (DeliveryFailure('transport_unknown'), 'delivery_unknown'),
    (TimeoutError('synthetic lost acknowledgement'), 'delivery_unknown'),
])
async def test_unavailable_or_ambiguous_send_is_not_replayed(tmp_path, failure, expected):
    from bot.genjutsu.delivery import TerminalNotifications
    repo, connect = await build_repo(tmp_path)
    run, _ = await failed_run(repo)
    send = AsyncMock(side_effect=failure)
    assert await TerminalNotifications(repo, send).tick()
    assert not await TerminalNotifications(repo, send).tick()
    row = await notification_row(connect, run['id'])
    assert row['status'] == expected and row['attempts'] == 1
    send.assert_awaited_once()
    assert await repo.balance(101) == 100


@pytest.mark.asyncio
async def test_rate_limit_honors_delay_and_eventually_delivers(tmp_path):
    from bot.genjutsu.delivery import TerminalNotifications
    repo, connect = await build_repo(tmp_path)
    now = [1_000_000]
    repo.clock = lambda: now[0]
    run, _ = await failed_run(repo)
    send = AsyncMock(side_effect=[DeliveryFailure('rate_limited', retry_after=12), 'notice-ok'])
    worker = TerminalNotifications(repo, send)
    assert await worker.tick()
    assert not await worker.tick()
    now[0] += 11_999
    assert not await worker.tick()
    now[0] += 1
    assert await worker.tick()
    row = await notification_row(connect, run['id'])
    assert row['status'] == 'delivered' and row['attempts'] == 2
    assert row['message_id'] == 'notice-ok'
    assert not await worker.tick()


@pytest.mark.asyncio
@pytest.mark.parametrize('exhaustion', ['attempts', 'deadline'])
async def test_rate_limit_retry_is_bounded(tmp_path, exhaustion):
    from bot.genjutsu.delivery import TerminalNotifications
    repo, connect = await build_repo(tmp_path)
    now = [1_000_000]
    repo.clock = lambda: now[0]
    settings, version = await repo.settings()
    settings['notification_max_attempts'] = 1 if exhaustion == 'attempts' else 5
    settings['notification_retry_deadline_seconds'] = 60
    await repo.update_settings(999, version, settings)
    run, _ = await failed_run(repo)
    send = AsyncMock(side_effect=DeliveryFailure('rate_limited', retry_after=61 if exhaustion == 'deadline' else 1))
    worker = TerminalNotifications(repo, send)
    assert await worker.tick()
    now[0] += 1_000_000
    assert not await worker.tick()
    row = await notification_row(connect, run['id'])
    assert row['status'] == 'unavailable'
    assert row['error_code'] == 'notification_retry_exhausted'
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_sending_lease_is_unknown_and_old_ack_is_fenced(tmp_path):
    repo, connect = await build_repo(tmp_path)
    now = [1_000_000]
    repo.clock = lambda: now[0]
    run, settings = await failed_run(repo)
    item = await repo.claim_notification(settings)
    now[0] += settings['lease_seconds'] * 1000 + 1
    assert await repo.claim_notification(settings) is None
    row = await notification_row(connect, run['id'])
    assert row['status'] == 'delivery_unknown' and row['attempts'] == 1
    with pytest.raises(PipelineError, match='lease_lost'):
        await repo.finish_notification(run['id'], item['lease_token'], 'delivered', message_id='late-ack')


@pytest.mark.asyncio
async def test_worker_cancellation_during_send_never_resends_after_restart(tmp_path):
    from bot.genjutsu.delivery import TerminalNotifications
    repo, connect = await build_repo(tmp_path)
    now = [1_000_000]
    repo.clock = lambda: now[0]
    run, settings = await failed_run(repo)
    send = AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await TerminalNotifications(repo, send).tick()
    assert (await notification_row(connect, run['id']))['status'] == 'sending'
    now[0] += settings['lease_seconds'] * 1000 + 1
    assert not await TerminalNotifications(repo, send).tick()
    assert (await notification_row(connect, run['id']))['status'] == 'delivery_unknown'
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_sender_is_plaintext_and_uses_private_run_link():
    from bot.genjutsu.runtime import send_terminal_notification
    bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=123)))
    result = await send_terminal_notification(bot, 'https://app.example/studio?existing=1', 101,
                                              'Safe synthetic message', 'run-example', 30)
    assert result == '123'
    kwargs = bot.send_message.call_args.kwargs
    assert kwargs['parse_mode'] is None
    assert kwargs['request_timeout'] == 30
    url = kwargs['reply_markup'].inline_keyboard[0][0].web_app.url
    assert 'genjutsu_run=run-example' in url and 'existing=1' in url


@pytest.mark.asyncio
async def test_runtime_registers_and_stops_notification_worker(tmp_path, monkeypatch):
    from aiohttp import web

    from bot.config import config
    from bot.genjutsu import runtime
    started, stopped = set(), set()
    def worker(name):
        async def run(self, stop):
            started.add(name)
            try:
                await stop.wait()
            finally:
                stopped.add(name)
        return run
    monkeypatch.setattr(runtime.Pipeline, 'worker', worker('generation'))
    monkeypatch.setattr(runtime.Delivery, 'worker', worker('videos'))
    monkeypatch.setattr(runtime.TerminalNotifications, 'worker', worker('notifications'))
    monkeypatch.setattr(config, 'GENJUTSU_MEDIA_ROOT', str(tmp_path / 'private-media'))
    monkeypatch.setattr(config, 'GENJUTSU_PUBLIC_BASE_URL', '')
    monkeypatch.setattr(config, 'GENJUTSU_MEDIA_SIGNING_KEY', '')
    monkeypatch.setattr(config, 'HIGGSFIELD_API_KEY', '')
    app = web.Application()
    runtime.setup_genjutsu(app)
    lifecycle = app.cleanup_ctx[-1](app)
    await anext(lifecycle)
    await asyncio.sleep(0)
    assert started == {'generation', 'videos', 'notifications'}
    await lifecycle.aclose()
    assert stopped == started


@pytest.mark.asyncio
@pytest.mark.parametrize('code,expected', [
    ('provider_failed', 'без подробной причины'),
    ('asset_file_unavailable', 'техническая ошибка'),
    ('unknown:sensitive-provider-detail', 'техническая ошибка'),
])
async def test_reason_text_is_coarse_and_never_echoes_raw_error(tmp_path, code, expected):
    from bot.genjutsu.delivery import TerminalNotifications
    repo, _ = await build_repo(tmp_path)
    await failed_run(repo, code=code)
    send = AsyncMock(return_value='reason-test')
    assert await TerminalNotifications(repo, send).tick()
    assert expected in send.call_args.args[1]
    assert code not in send.call_args.args[1]


@pytest.mark.asyncio
@pytest.mark.parametrize('error_kind,expected', [
    ('rate_limit', 'rate_limited'), ('forbidden', 'chat_unavailable'),
    ('chat_missing', 'chat_unavailable'), ('bad_request', 'message_rejected'),
])
async def test_runtime_sender_classifies_only_known_telegram_outcomes(error_kind, expected):
    from aiogram.exceptions import (
        TelegramBadRequest,
        TelegramForbiddenError,
        TelegramRetryAfter,
    )
    from aiogram.methods import SendMessage

    from bot.genjutsu.runtime import send_terminal_notification
    method = SendMessage(chat_id=101, text='synthetic')
    errors = {
        'rate_limit': TelegramRetryAfter(method=method, message='synthetic', retry_after=7),
        'forbidden': TelegramForbiddenError(method=method, message='synthetic'),
        'chat_missing': TelegramBadRequest(method=method, message='chat not found'),
        'bad_request': TelegramBadRequest(method=method, message='synthetic invalid message'),
    }
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=errors[error_kind]))
    with pytest.raises(DeliveryFailure) as failure:
        await send_terminal_notification(bot, 'https://app.example/studio', 101, 'synthetic', 'run', 30)
    assert failure.value.code == expected
    if error_kind == 'rate_limit':
        assert failure.value.retry_after == 7


def test_notification_policy_defaults_merge_and_invalid_values_fail_closed():
    from bot.genjutsu.contract import default_settings, validate_settings
    old = default_settings()
    old.pop('notification_max_attempts')
    old.pop('notification_retry_deadline_seconds')
    assert validate_settings(old)['notification_max_attempts'] == 5
    assert validate_settings(old)['notification_retry_deadline_seconds'] == 3600
    for key, value in [('notification_max_attempts', 0), ('notification_max_attempts', True),
                       ('notification_retry_deadline_seconds', 59)]:
        with pytest.raises(PipelineError, match='invalid_settings'):
            validate_settings({**old, key: value})


@pytest.mark.asyncio
async def test_custom_notification_templates_use_settled_amounts_and_categories(tmp_path):
    from bot.genjutsu.delivery import TerminalNotifications
    repo, _ = await build_repo(tmp_path)
    settings, version = await repo.settings()
    settings['notification_templates'].update({
        'failed': 'Работу завершить не удалось',
        'moderation': 'Ответ провайдера: модерация',
        'refund': 'Возвращено на баланс: {refunded_credits} бананов',
        'charge': 'Списано всего: {charged_credits} бананов',
        'no_charge': 'Бесплатный запуск',
    })
    await repo.update_settings(999, version, settings)
    await failed_run(repo)
    send = AsyncMock(return_value='custom-copy')
    assert await TerminalNotifications(repo, send).tick()
    text = send.call_args.args[1]
    assert 'Работу завершить не удалось' in text
    assert 'Ответ провайдера: модерация' in text
    assert 'Возвращено на баланс: 5 бананов' in text
    assert 'Списано всего: 0 бананов' in text
    assert 'Бесплатный запуск' not in text
    assert '{' not in text
    assert await repo.balance(101) == 100


@pytest.mark.asyncio
async def test_custom_free_notice_never_uses_refund_or_charge_templates(tmp_path):
    from bot.genjutsu.delivery import TerminalNotifications
    repo, _ = await build_repo(tmp_path)
    settings, version = await repo.settings()
    settings['notification_templates']['no_charge'] = 'Бесплатный запуск, баланс не менялся'
    await repo.update_settings(999, version, settings)
    await failed_run(repo, admin_free=True)
    send = AsyncMock(return_value='custom-free')
    assert await TerminalNotifications(repo, send).tick()
    text = send.call_args.args[1]
    assert 'Бесплатный запуск, баланс не менялся' in text
    assert 'возвращено' not in text.lower()
    assert 'Итоговое списание' not in text


@pytest.mark.parametrize('key,value', [
    ('refund', 'Возврат: {charged_credits}'),
    ('charge', 'Списание: {refunded_credits}'),
    ('refund', 'Возврат без суммы'),
    ('refund', '{refunded_credits} / {refunded_credits}'),
    ('refund', '{refunded_credits.__class__}'),
    ('refund', '{refunded_credits[0]}'),
    ('refund', '{refunded_credits!r}'),
    ('refund', '{refunded_credits:>20}'),
    ('refund', '{{refunded_credits}}'),
    ('refund', '{refunded_credits'),
    ('failed', '{owner}'),
    ('failed', '{prompt}'),
    ('failed', '{refunded_credits}'),
    ('failed', '{'),
    ('failed', ''),
    ('failed', '   '),
    ('failed', None),
    ('failed', 1),
    ('failed', 'x' * 301),
    ('failed', '🍌' * 151),
    ('failed', 'bad\x00text'),
    ('failed', 'bad\rtext'),
    ('failed', 'bad\u202etext'),
    ('failed', 'bad\ud800text'),
])
def test_notification_templates_reject_unsafe_or_unbounded_values(key, value):
    from bot.genjutsu.contract import default_settings, validate_settings
    settings = default_settings()
    settings['notification_templates'][key] = value
    with pytest.raises(PipelineError, match='invalid_notification_templates'):
        validate_settings(settings)


@pytest.mark.parametrize('kind', ['missing', 'extra', 'not_object'])
def test_notification_templates_require_exact_category_keys(kind):
    from bot.genjutsu.contract import default_settings, validate_settings
    settings = default_settings()
    if kind == 'missing':
        settings['notification_templates'].pop('no_charge')
    elif kind == 'extra':
        settings['notification_templates']['provider_raw'] = 'raw'
    else:
        settings['notification_templates'] = []
    with pytest.raises(PipelineError, match='invalid_notification_templates'):
        validate_settings(settings)


def test_old_settings_receive_complete_notification_template_defaults():
    from bot.genjutsu.contract import default_settings, validate_settings
    settings = default_settings()
    templates = settings.pop('notification_templates')
    settings.pop('notification_max_attempts')
    settings.pop('notification_retry_deadline_seconds')
    restored = validate_settings(settings)
    assert restored['notification_templates'] == templates
    restored['notification_templates']['failed'] = 'Changed in memory'
    assert default_settings()['notification_templates'] == templates


def test_notification_renderer_validates_templates_and_keeps_markup_literal():
    from bot.genjutsu.contract import default_settings
    from bot.genjutsu.delivery import terminal_notification_text
    summary = {'state': 'failed', 'moderation_count': 0, 'provider_failure_count': 0,
               'technical_failure_count': 1, 'canceled_count': 0,
               'reserved_credits': 5, 'refunded_credits': 5, 'charged_credits': 0}
    templates = default_settings()['notification_templates']
    templates['failed'] = '<b>Plain text</b> *literal*'
    assert terminal_notification_text(summary, templates).startswith('<b>Plain text</b> *literal*')
    templates['refund'] = '{refunded_credits.__class__}'
    with pytest.raises(PipelineError, match='invalid_notification_templates'):
        terminal_notification_text(summary, templates)
