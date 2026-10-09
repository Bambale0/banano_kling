"""Ordinary Seedance 2 uses configured provider-quality prices on every surface."""
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import creator_tariff_membership, database, miniapp, trend_api
from bot.config import config
from bot.handlers import generation
from bot.services import task_watchdog
from bot.services.preset_manager import preset_manager
from bot.services.seedance_service import seedance_service
from tests.test_creator_tariff_seedance2 import data, request, telegram
from tests.test_creator_tariff_trends import trend


@pytest.fixture
async def ordinary_actor(monkeypatch):
    prices = deepcopy(preset_manager.get_price_config())
    ordinary = prices['costs_reference']['video_models']['seedance_2']
    ordinary.update(base=20, duration_costs={'5': 20, '10': 40, '15': 60},
                    quality_costs={'480p': 5, '720p': 5})
    prices['creator_tariff'] = {'enabled': True, 'video_models': {
        'seedance_2': {'quality_costs': {'480p': 3, '720p': 3}},
        'seedance_2_5': {'quality_costs': {'480p': 2, '720p': 3}},
    }}
    monkeypatch.setattr(preset_manager, '_price_config', prices)
    role = SimpleNamespace(admin=False, member=False)
    monkeypatch.setattr(config, 'is_admin', lambda _uid: role.admin)
    membership = AsyncMock(side_effect=lambda _uid: role.member)
    monkeypatch.setattr(creator_tariff_membership, 'get_creator_tariff_membership', membership)
    monkeypatch.setattr(task_watchdog, 'DATABASE_PATH', database.DATABASE_PATH)
    await database.get_or_create_user(123)
    await database.add_credits(123, 1000)
    user = await database.get_or_create_user(123)
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(
        123, {'user': user, 'payload': {'user': {'id': 123}}},
    )))
    provider = AsyncMock(return_value={'task_id': 'ordinary-seedance2-test'})
    monkeypatch.setattr(seedance_service, 'generate_video', provider)
    return SimpleNamespace(prices=prices, role=role, membership=membership,
                           provider=provider, user=user, initial=user.credits)


async def launch(surface, body):
    if surface == 'miniapp':
        response = await miniapp.miniapp_generate_video(request(body))
        assert response.status == 200, response.body
        return json.loads(response.body)
    message, state, _ = telegram(body)
    await generation.run_no_preset_video_from_message(message, state, body['prompt'])
    return None


@pytest.mark.parametrize('surface', ['miniapp', 'telegram'])
@pytest.mark.parametrize('duration', [5, 10, 15])
@pytest.mark.parametrize('has_video_reference', [False, True])
@pytest.mark.parametrize('profile,member,admin,rate', [
    ('standard', False, False, 5),
    ('creator', True, False, 3),
    ('admin', True, True, 5),
])
async def test_public_launch_quotes_debits_persists_and_refunds_once(
    ordinary_actor, surface, duration, has_video_reference, profile, member, admin, rate,
):
    actor = ordinary_actor
    actor.role.member, actor.role.admin = member, admin
    display_cost = duration * rate * (2 if has_video_reference else 1)
    charge_cost = 0 if admin else display_cost
    references = ['https://example.test/reference.mp4'] if has_video_reference else []
    body = data(v_duration=duration, v_reference_videos=references,
                tariff='admin', creator_tariff=True,
                billing_quote={'charge_cost': 0, 'profile': 'admin'})
    response = await launch(surface, body)
    if response is not None:
        assert response['cost'] == display_cost
    actor.provider.assert_awaited_once()
    assert actor.provider.await_args.kwargs['resolution'] == '720p'
    task = await database.get_task_by_id('ordinary-seedance2-test')
    assert task is not None
    assert task.cost == charge_cost
    quote = json.loads(task.request_data)['billing_quote']
    assert quote['cost'] == display_cost
    assert quote['charge_cost'] == charge_cost
    assert quote['profile'] == profile
    assert quote['quality'] == '720p'
    assert quote['duration'] == duration
    assert quote['reference_multiplier'] == (2 if has_video_reference else 1)
    assert (await database.get_or_create_user(123)).credits == actor.initial - charge_cost
    if admin:
        actor.membership.assert_not_awaited()

    # Later config/role changes and a stale caller cost must not change refunds.
    actor.prices['costs_reference']['video_models']['seedance_2']['quality_costs']['720p'] = 90
    actor.prices['creator_tariff']['video_models']['seedance_2']['quality_costs']['720p'] = 60
    actor.role.member, actor.role.admin = not member, not admin
    assert await task_watchdog.force_fail_task(task.id, actor.user.id, 999)
    assert (await database.get_or_create_user(123)).credits == actor.initial
    assert not await task_watchdog.force_fail_task(task.id, actor.user.id, 999)
    assert (await database.get_or_create_user(123)).credits == actor.initial
    final_task = await database.get_task_by_id('ordinary-seedance2-test')
    assert final_task.cost == charge_cost
    assert json.loads(final_task.request_data)['billing_quote'] == quote


@pytest.mark.parametrize('surface', ['miniapp', 'telegram'])
async def test_provider_wait_cannot_reprice_accepted_ordinary_launch(ordinary_actor, surface):
    actor = ordinary_actor

    async def accepted(**_kwargs):
        assert (await database.get_or_create_user(123)).credits == actor.initial - 25
        actor.prices['costs_reference']['video_models']['seedance_2']['quality_costs']['720p'] = 90
        actor.role.member = True
        return {'task_id': 'ordinary-seedance2-test'}

    actor.provider.side_effect = accepted
    await launch(surface, data())
    task = await database.get_task_by_id('ordinary-seedance2-test')
    assert task.cost == 25
    quote = json.loads(task.request_data)['billing_quote']
    assert quote['charge_cost'] == 25
    assert quote['profile'] == 'standard'
    assert (await database.get_or_create_user(123)).credits == actor.initial - 25
    assert await task_watchdog.force_fail_task(task.id, actor.user.id, 999)
    assert (await database.get_or_create_user(123)).credits == actor.initial


@pytest.mark.parametrize('surface', ['miniapp', 'telegram'])
async def test_provider_rejection_refunds_original_ordinary_price(ordinary_actor, surface):
    actor = ordinary_actor
    balances_at_provider = []

    async def rejected(**_kwargs):
        balances_at_provider.append((await database.get_or_create_user(123)).credits)
        actor.prices['costs_reference']['video_models']['seedance_2']['quality_costs']['720p'] = 90
        return {'error': 'synthetic provider rejection'}

    actor.provider.side_effect = rejected
    if surface == 'miniapp':
        response = await miniapp.miniapp_generate_video(request(data()))
        assert response.status == 500
    else:
        message, state, _ = telegram(data())
        await generation.run_no_preset_video_from_message(message, state, 'Camera moves')
    actor.provider.assert_awaited_once()
    assert balances_at_provider == [actor.initial - 25]
    assert (await database.get_or_create_user(123)).credits == actor.initial
    assert await database.get_task_by_id('ordinary-seedance2-test') is None


@pytest.mark.parametrize('surface', ['miniapp', 'telegram'])
async def test_rejected_ordinary_debit_cannot_launch_provider(ordinary_actor, monkeypatch, surface):
    module = miniapp if surface == 'miniapp' else generation
    debit = AsyncMock(return_value=False)
    monkeypatch.setattr(module, 'deduct_credits', debit)
    if surface == 'miniapp':
        response = await miniapp.miniapp_generate_video(request(data()))
        assert response.status == 400
    else:
        message, state, _ = telegram(data())
        await generation.run_no_preset_video_from_message(message, state, 'Camera moves')
    debit.assert_awaited_once_with(123, 25)
    ordinary_actor.provider.assert_not_awaited()
    assert (await database.get_or_create_user(123)).credits == ordinary_actor.initial


@pytest.mark.parametrize('entry', ['quick', 'advanced'])
async def test_saved_repeat_requotes_current_ordinary_rate(ordinary_actor, monkeypatch, entry):
    from bot.genjutsu import feed
    from bot.handlers import miniapp_video_continuity_compat as continuity
    from bot.handlers import video_generation_compat as advanced

    actor = ordinary_actor
    await database.add_generation_task(
        actor.user.id, 123, 'source-job', 'video', 'test', model='seedance_2',
        duration=5, aspect_ratio='16:9', prompt='Camera moves', cost=999,
        request_data={'v_model': 'seedance_2', 'v_type': 'text',
                      'billing_quote': {'charge_cost': 999, 'profile': 'creator'}},
    )
    monkeypatch.setattr(feed, 'redirect_legacy_repeat', AsyncMock(return_value=False))
    monkeypatch.setattr(continuity, 'redirect_typed_video_repeat', AsyncMock(return_value=False))
    message, state, _ = telegram(data())
    callback = SimpleNamespace(data='repeat_video_result_source-job',
                               from_user=SimpleNamespace(id=123), message=message,
                               answer=AsyncMock())
    handler = generation.quick_repeat_video_result if entry == 'quick' else advanced.repeat_advanced_video_result
    await handler(callback, state)
    task = await database.get_task_by_id('ordinary-seedance2-test')
    assert task is not None and task.cost == 25
    quote = json.loads(task.request_data)['billing_quote']
    assert quote['profile'] == 'standard'
    assert quote['quality'] == '720p'
    assert quote['charge_cost'] == 25
    assert (await database.get_or_create_user(123)).credits == actor.initial - 25
    assert (await database.get_task_by_id('source-job')).cost == 999
    assert await task_watchdog.force_fail_task(task.id, actor.user.id, 999)
    assert (await database.get_or_create_user(123)).credits == actor.initial


@pytest.mark.parametrize('has_video_reference', [False, True])
@pytest.mark.parametrize('profile,member,admin,rate', [
    ('standard', False, False, 5),
    ('creator', True, False, 3),
    ('admin', True, True, 5),
])
async def test_trend_display_matches_launch_and_refund(
    ordinary_actor, monkeypatch, has_video_reference, profile, member, admin, rate,
):
    actor = ordinary_actor
    actor.role.member, actor.role.admin = member, admin
    recipe = trend('seedance_2', video=has_video_reference)
    expected = 5 * rate * (2 if has_video_reference else 1)
    charge = 0 if admin else expected
    monkeypatch.setattr(trend_api, '_record_trend_use', AsyncMock())
    assert trend_api.estimate_trend_repeat_cost(recipe, tariff=profile) == expected
    response = await trend_api._run_video_trend(telegram_id=123, user=actor.user, trend=recipe)
    assert response.status == 200, response.body
    assert json.loads(response.body)['cost'] == expected
    task = await database.get_task_by_id('ordinary-seedance2-test')
    assert task.cost == charge
    quote = json.loads(task.request_data)['billing_quote']
    assert quote['cost'] == expected
    assert quote['charge_cost'] == charge
    assert quote['profile'] == profile
    assert quote['quality'] == '720p'
    assert (await database.get_or_create_user(123)).credits == actor.initial - charge
    assert await task_watchdog.force_fail_task(task.id, actor.user.id, 999)
    assert (await database.get_or_create_user(123)).credits == actor.initial


@pytest.mark.parametrize('member,admin,rate', [(False, False, 5), (True, False, 3), (True, True, 5)])
async def test_bootstrap_and_telegram_creation_show_same_configured_price(
    ordinary_actor, monkeypatch, member, admin, rate,
):
    actor = ordinary_actor
    actor.role.member, actor.role.admin = member, admin
    monkeypatch.setattr(miniapp, '_miniapp_payload', AsyncMock(return_value={'init_data': 'signed', 'tariff': 'admin'}))
    monkeypatch.setattr(miniapp, '_cached_bot_me', AsyncMock(return_value=SimpleNamespace(username='synthetic_bot')))
    for name in ('_fetch_recent_tasks', 'list_saved_references', 'get_and_clear_miniapp_notifications'):
        monkeypatch.setattr(miniapp, name, AsyncMock(return_value=[]))
    monkeypatch.setattr(miniapp, 'get_partner_overview', AsyncMock(return_value={}))
    monkeypatch.setattr(miniapp, 'can_attempt_telegram_delivery', AsyncMock(return_value=True))
    monkeypatch.setattr(miniapp, 'needs_telegram_bot_start', AsyncMock(return_value=False))
    before = deepcopy(actor.prices)
    response = await miniapp.miniapp_bootstrap(request({}))
    assert response.status == 200, response.body
    assert 'no-store' in response.headers['Cache-Control']
    models = {item['id']: item for item in json.loads(response.body)['video_models']}
    seedance = models['seedance_2']
    assert seedance['costs']['5'] == 5 * rate
    assert seedance['costs']['10'] == 10 * rate
    assert seedance['costs']['15'] == 15 * rate
    assert seedance['quality_costs']['720p'] == rate
    assert seedance['quality_duration_costs']['720p']['5'] == 5 * rate

    message, state, _ = telegram(data())
    await generation._show_video_creation_screen(message, state, edit=False)
    markup = message.answer.await_args.kwargs['reply_markup']
    labels = [button.text for row in markup.inline_keyboard for button in row if button.text.startswith('Цена:')]
    assert labels == [f'Цена: {float(rate)}🍌/с']
    assert actor.prices == before
