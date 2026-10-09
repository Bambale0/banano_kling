"""End-to-end local Seedance 2 pricing through public entry points and stored tasks."""
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import creator_tariff_membership, database, miniapp
from bot.config import config
from bot.handlers import generation
from bot.services import task_watchdog
from bot.services.preset_manager import preset_manager
from bot.services.seedance_service import seedance_service


@pytest.fixture
async def actor(monkeypatch):
    prices = deepcopy(preset_manager.get_price_config())
    prices['creator_tariff'] = {'enabled': True, 'video_models': {
        'seedance_2': {'quality_costs': {'720p': 1}},
        'seedance_2_5': {'quality_costs': {'480p': 1.5, '720p': 2}},
    }}
    monkeypatch.setattr(preset_manager, '_price_config', prices)
    monkeypatch.setattr(config, 'is_admin', lambda _uid: False)
    monkeypatch.setattr(task_watchdog, 'DATABASE_PATH', database.DATABASE_PATH)
    member = AsyncMock(return_value=True)
    monkeypatch.setattr(creator_tariff_membership, 'get_creator_tariff_membership', member)
    user = await database.get_or_create_user(123)
    await database.add_credits(123, 1000)
    user = await database.get_or_create_user(123)
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(123, {'user': user})))
    provider = AsyncMock(return_value={'task_id': 's2-creator-test'})
    monkeypatch.setattr(seedance_service, 'generate_video', provider)
    return SimpleNamespace(prices=prices, member=member, user=user, provider=provider, initial=user.credits)


def data(**updates):
    return {'v_model': 'seedance_2', 'v_type': 'text', 'v_duration': 5,
            'v_ratio': '16:9', 'prompt': 'Camera moves', **updates}


def request(body):
    return SimpleNamespace(app={}, json=AsyncMock(return_value=body))


def telegram(body):
    values = dict(body)
    state = SimpleNamespace(get_data=AsyncMock(side_effect=lambda: dict(values)),
                            clear=AsyncMock(), set_state=AsyncMock())
    async def update(**updates):
        values.update(updates)
    state.update_data = AsyncMock(side_effect=update)
    processing = SimpleNamespace(delete=AsyncMock())
    message = SimpleNamespace(from_user=SimpleNamespace(id=123), answer=AsyncMock(return_value=processing))
    return message, state, processing


@pytest.mark.parametrize('surface', ['miniapp', 'telegram'])
@pytest.mark.parametrize('member,refs,expected', [(True, [], 5), (False, [], 20), (True, ['https://example.test/ref.mp4'], 10)])
async def test_actor_quote_matches_debit_and_immutable_task(actor, surface, member, refs, expected):
    actor.member.return_value = member
    body = data(v_reference_videos=refs, tariff='admin', creator_tariff=False, billing_quote={'charge_cost': 0})
    if surface == 'miniapp':
        response = await miniapp.miniapp_generate_video(request(body))
        assert response.status == 200, response.body
        assert json.loads(response.body)['cost'] == expected
    else:
        message, state, _ = telegram(body)
        await generation.run_no_preset_video_from_message(message, state, body['prompt'])
    task = await database.get_task_by_id('s2-creator-test')
    assert task is not None
    assert task.cost == expected
    stored = json.loads(task.request_data)
    assert stored['billing_quote']['charge_cost'] == expected
    assert stored['billing_quote']['profile'] == ('creator' if member else 'standard')
    assert (await database.get_or_create_user(123)).credits == actor.initial - expected


@pytest.mark.parametrize('surface', ['miniapp', 'telegram'])
async def test_failed_debit_cannot_launch(actor, monkeypatch, surface):
    module = miniapp if surface == 'miniapp' else generation
    monkeypatch.setattr(module, 'deduct_credits', AsyncMock(return_value=False))
    body = data()
    if surface == 'miniapp':
        response = await miniapp.miniapp_generate_video(request(body))
        assert response.status == 400
    else:
        message, state, _ = telegram(body)
        await generation.run_no_preset_video_from_message(message, state, body['prompt'])
    actor.provider.assert_not_awaited()
    assert (await database.get_or_create_user(123)).credits == actor.initial


@pytest.mark.parametrize('surface', ['miniapp', 'telegram'])
async def test_price_change_and_revocation_during_provider_wait_do_not_reprice(actor, surface):
    async def accepted(**_kwargs):
        actor.prices['creator_tariff']['video_models']['seedance_2']['quality_costs']['720p'] = 9
        actor.member.return_value = False
        return {'task_id': 's2-creator-test'}
    actor.provider.side_effect = accepted
    body = data()
    if surface == 'miniapp':
        response = await miniapp.miniapp_generate_video(request(body))
        assert response.status == 200, response.body
    else:
        message, state, _ = telegram(body)
        await generation.run_no_preset_video_from_message(message, state, body['prompt'])
    task = await database.get_task_by_id('s2-creator-test')
    assert task.cost == 5
    assert json.loads(task.request_data)['billing_quote']['charge_cost'] == 5
    assert (await database.get_or_create_user(123)).credits == actor.initial - 5


async def test_watchdog_uses_original_charge_even_after_admin_promotion_and_once(actor, monkeypatch):
    response = await miniapp.miniapp_generate_video(request(data()))
    assert response.status == 200
    task = await database.get_task_by_id('s2-creator-test')
    actor.prices['creator_tariff']['video_models']['seedance_2']['quality_costs']['720p'] = 50
    actor.member.return_value = False
    monkeypatch.setattr(config, 'is_admin', lambda _uid: True)
    assert await task_watchdog.force_fail_task(task.id, actor.user.id, 999)
    assert (await database.get_or_create_user(123)).credits == actor.initial
    assert not await task_watchdog.force_fail_task(task.id, actor.user.id, 999)
    assert (await database.get_or_create_user(123)).credits == actor.initial


@pytest.mark.parametrize('surface', ['miniapp', 'telegram'])
async def test_provider_rejection_refunds_only_original_amount(actor, surface):
    async def rejected(**_kwargs):
        actor.prices['creator_tariff']['video_models']['seedance_2']['quality_costs']['720p'] = 9
        return {'error': 'rejected'}
    actor.provider.side_effect = rejected
    if surface == 'miniapp':
        response = await miniapp.miniapp_generate_video(request(data()))
        assert response.status == 500
    else:
        message, state, _ = telegram(data())
        await generation.run_no_preset_video_from_message(message, state, 'Camera moves')
    assert (await database.get_or_create_user(123)).credits == actor.initial


@pytest.mark.parametrize('failure', ['delete', 'success_message'])
async def test_telegram_post_acceptance_notification_failure_cannot_refund(actor, failure):
    message, state, processing = telegram(data())
    if failure == 'delete':
        processing.delete.side_effect = RuntimeError('Telegram transport unavailable')
    else:
        message.answer.side_effect = [processing, RuntimeError('Telegram unavailable'), processing]
    await generation.run_no_preset_video_from_message(message, state, 'Camera moves')
    task = await database.get_task_by_id('s2-creator-test')
    assert task and task.cost == 5
    assert (await database.get_or_create_user(123)).credits == actor.initial - 5
    assert await task_watchdog.force_fail_task(task.id, actor.user.id, task.cost)
    assert (await database.get_or_create_user(123)).credits == actor.initial


@pytest.mark.parametrize('callback_data', ['vid_ref_continue_new', 'ref_skip_new', 'ref_confirm_new'])
async def test_legacy_continue_screen_prices_callback_actor_not_bot_message(actor, monkeypatch, callback_data):
    from bot.handlers import seedance_multimodal_compat as compat
    _, state, _ = telegram(data(generation_type='video', reference_images=['https://example.test/image.png']))
    callback = SimpleNamespace(from_user=SimpleNamespace(id=123),
                               message=SimpleNamespace(from_user=SimpleNamespace(id=999888)),
                               data=callback_data, answer=AsyncMock())
    render = AsyncMock()
    monkeypatch.setattr(compat, '_render_text', render)
    if callback_data == 'vid_ref_continue_new':
        await generation.handle_vid_ref_continue_new(callback, state)
    else:
        await generation.handle_reference_images(callback, state)
    assert render.await_count == 1
    assert all(call.args == (123,) for call in actor.member.await_args_list)
    markup = render.await_args.kwargs['reply_markup']
    prices = [button.text for row in markup.inline_keyboard for button in row if button.text.startswith('Цена:')]
    assert prices == ['Цена: 1.0🍌/с']


@pytest.mark.parametrize('entry', ['quick', 'advanced'])
@pytest.mark.parametrize('failure', ['both_messages', 'clear'])
async def test_composed_repeat_cannot_refund_accepted_job_on_ui_or_state_failure(actor, monkeypatch, entry, failure):
    from bot.genjutsu import feed
    from bot.handlers import miniapp_video_continuity_compat as continuity
    from bot.handlers import video_generation_compat as advanced
    await database.add_generation_task(actor.user.id, 123, 'source-job', 'video', 'test',
                                       model='seedance_2', duration=5, aspect_ratio='16:9',
                                       prompt='Camera moves', cost=999,
                                       request_data={'v_model': 'seedance_2', 'v_type': 'text'})
    monkeypatch.setattr(feed, 'redirect_legacy_repeat', AsyncMock(return_value=False))
    monkeypatch.setattr(continuity, 'redirect_typed_video_repeat', AsyncMock(return_value=False))
    _, state, _ = telegram(data())
    progress = SimpleNamespace(delete=AsyncMock())
    message = SimpleNamespace(answer=AsyncMock(return_value=progress))
    if failure == 'both_messages':
        message.answer.side_effect = [progress, RuntimeError('send failed'), RuntimeError('fallback failed')]
    else:
        state.clear.side_effect = [None, RuntimeError('FSM failed')] if entry == 'advanced' else RuntimeError('FSM failed')
    callback = SimpleNamespace(data='repeat_video_result_source-job', from_user=SimpleNamespace(id=123),
                               message=message, answer=AsyncMock())
    handler = generation.quick_repeat_video_result if entry == 'quick' else advanced.repeat_advanced_video_result
    await handler(callback, state)
    task = await database.get_task_by_id('s2-creator-test')
    assert task and task.cost == 5
    assert (await database.get_or_create_user(123)).credits == actor.initial - 5
    assert await task_watchdog.force_fail_task(task.id, actor.user.id, task.cost)
    assert (await database.get_or_create_user(123)).credits == actor.initial
