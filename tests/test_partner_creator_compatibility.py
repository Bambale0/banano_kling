"""Creator and referral policies share accepted tasks without changing locked debits."""
import json
from unittest.mock import AsyncMock

import pytest

from bot import database, miniapp
from bot.handlers import generation
from bot.handlers import seedance_25_public_release as public
from bot.partner_policy import (
    mark_generation_accepted,
    reconcile_pending_invite_bonuses,
)
from bot.services import task_watchdog
from tests import test_creator_tariff_seedance2 as fixtures
from tests import test_seedance2_ordinary_pricing_surfaces as ordinary_fixtures

actor = fixtures.actor
ordinary_actor = ordinary_fixtures.ordinary_actor


@pytest.mark.parametrize('model,expected', [('seedance_2', 5), ('seedance_2_5', 10)])
@pytest.mark.parametrize('surface', ['telegram', 'miniapp'])
async def test_creator_referral_acceptance_and_original_refund_once(actor, monkeypatch, model, expected, surface):
    inviter = await database.get_or_create_user(456)
    assert await database.process_referral(123, inviter.referral_code)
    assert (await database.get_or_create_user(456)).referral_earned == 0
    monkeypatch.setattr(public.fullstack, '_validate_seedance_sources', AsyncMock())

    async def accept(*_args, **_kwargs):
        actor.prices['creator_tariff']['video_models'][model]['quality_costs']['720p'] = 99
        actor.member.return_value = False
        return {'task_id': 'creator-partner-accepted'}

    actor.provider.side_effect = accept
    monkeypatch.setattr(public, '_launch_provider', actor.provider)
    body = fixtures.data(v_model=model, seedance25_scenario='text', seedance25_resolution='720p')
    if surface == 'miniapp':
        response = await miniapp.miniapp_generate_video(fixtures.request(body)) if model == 'seedance_2' else await public._public_miniapp_generate(fixtures.request(body), body)
        assert response.status == 200, response.body
    else:
        message, state, _ = fixtures.telegram(body)
        if model == 'seedance_2':
            await generation.run_no_preset_video_from_message(message, state, body['prompt'])
        else:
            await public._public_message_launch(message, state, body['prompt'])
    task = await database.get_task_by_id('creator-partner-accepted')
    stored = json.loads(task.request_data)
    assert stored['billing_quote']['profile'] == 'creator'
    assert stored['billing_quote']['charge_cost'] == task.cost == expected
    assert stored['partner_generation_accepted'] is True
    assert (await database.get_or_create_user(123)).credits == actor.initial - expected
    assert (await database.get_or_create_user(456)).referral_earned == 3
    assert not await mark_generation_accepted(task.task_id)
    assert await reconcile_pending_invite_bonuses() == 0
    assert await task_watchdog.force_fail_task(task.id, actor.user.id, 999)
    assert not await task_watchdog.force_fail_task(task.id, actor.user.id, 999)
    assert (await database.get_or_create_user(123)).credits == actor.initial
    assert (await database.get_or_create_user(456)).referral_earned == 3


@pytest.mark.parametrize('surface', ['telegram', 'miniapp'])
async def test_ordinary_price_fix_keeps_invite_once_and_original_refund(ordinary_actor, surface):
    actor = ordinary_actor
    inviter = await database.get_or_create_user(456)
    assert await database.process_referral(123, inviter.referral_code)
    assert (await database.get_or_create_user(456)).referral_earned == 0

    async def accepted(**_kwargs):
        assert (await database.get_or_create_user(123)).credits == actor.initial - 25
        actor.prices['costs_reference']['video_models']['seedance_2']['quality_costs']['720p'] = 90
        actor.role.member = True
        return {'task_id': 'ordinary-seedance2-test'}

    actor.provider.side_effect = accepted
    await ordinary_fixtures.launch(surface, fixtures.data())
    task = await database.get_task_by_id('ordinary-seedance2-test')
    quote = json.loads(task.request_data)['billing_quote']
    assert quote['quality'] == '720p'
    assert quote['profile'] == 'standard'
    assert quote['charge_cost'] == task.cost == 25
    assert (await database.get_or_create_user(456)).referral_earned == 3
    assert not await mark_generation_accepted(task.task_id)
    assert await reconcile_pending_invite_bonuses() == 0
    assert await task_watchdog.force_fail_task(task.id, actor.user.id, 999)
    assert not await task_watchdog.force_fail_task(task.id, actor.user.id, 999)
    assert (await database.get_or_create_user(123)).credits == actor.initial
    assert (await database.get_or_create_user(456)).referral_earned == 3


@pytest.mark.parametrize('surface', ['telegram', 'miniapp'])
async def test_rejected_ordinary_launch_does_not_award_inviter(ordinary_actor, surface):
    actor = ordinary_actor
    inviter = await database.get_or_create_user(456)
    assert await database.process_referral(123, inviter.referral_code)
    actor.provider.return_value = {'error': 'synthetic provider rejection'}
    if surface == 'miniapp':
        response = await miniapp.miniapp_generate_video(fixtures.request(fixtures.data()))
        assert response.status == 500
    else:
        message, state, _ = fixtures.telegram(fixtures.data())
        await generation.run_no_preset_video_from_message(message, state, 'Camera moves')
    assert (await database.get_or_create_user(123)).credits == actor.initial
    assert (await database.get_or_create_user(456)).referral_earned == 0
    assert await database.get_task_by_id('ordinary-seedance2-test') is None
    assert await reconcile_pending_invite_bonuses() == 0
