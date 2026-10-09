"""Authenticated trend launches share the same frozen Seedance quote/debit."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database, trend_api
from bot.handlers import trend_seedance_25_compat as seedance25
from bot.seedance_trend_recipe import REFERENCE_CONTRACT
from tests import test_creator_tariff_seedance2 as fixtures

actor = fixtures.actor


def trend(model, *, video=False):
    images = ('https://example.test/face.jpg',)
    videos = ('https://example.test/video.mp4',) if video else ()
    return SimpleNamespace(
        model=model, trend_id=1, kind='video', prompt='Camera moves', ratio='16:9',
        settings={'duration': 5, 'scenario': 'imgtxt', 'seedance25_resolution': '720p'},
        reference_urls=images, provider_image_urls=images, provider_video_urls=videos,
        provider_audio_urls=(), reference_contract=REFERENCE_CONTRACT,
        user_reference_inputs=(), template_image_urls=(), template_video_urls=(),
        template_audio_urls=(),
    )


@pytest.mark.parametrize('model,base', [('seedance_2', 5), ('seedance_2_5', 10)])
@pytest.mark.parametrize('video', [False, True])
async def test_trend_prices_same_actor_and_persists_prelaunch_quote(actor, monkeypatch, model, base, video):
    from bot.handlers import seedance_25_public_release as public
    monkeypatch.setattr(public.fullstack, '_validate_seedance_sources', AsyncMock())
    monkeypatch.setattr(public, '_launch_provider', actor.provider)
    monkeypatch.setattr(trend_api, '_record_trend_use', AsyncMock())
    async def provider(**_kwargs):
        actor.prices['creator_tariff']['video_models'][model]['quality_costs']['720p'] = 99
        actor.member.return_value = False
        return {'task_id': 'trend-creator-test'}
    async def dedicated_provider(_payload):
        return await provider()
    actor.provider.side_effect = dedicated_provider if model == 'seedance_2_5' else provider
    runner = seedance25._run_seedance25_trend if model == 'seedance_2_5' else trend_api._run_video_trend
    response = await runner(telegram_id=123, user=actor.user, trend=trend(model, video=video))
    assert response.status == 200, response.body
    expected = base * (2 if video else 1)
    assert json.loads(response.body)['cost'] == expected
    task = await database.get_task_by_id('trend-creator-test')
    assert task.cost == expected
    assert json.loads(task.request_data)['billing_quote']['charge_cost'] == expected
    assert (await database.get_or_create_user(123)).credits == actor.initial - expected


@pytest.mark.parametrize('model,expected', [('seedance_2', 5), ('seedance_2_5', 10)])
async def test_trend_bookkeeping_failure_after_acceptance_cannot_refund(actor, monkeypatch, model, expected):
    from bot.handlers import seedance_25_public_release as public
    monkeypatch.setattr(public.fullstack, '_validate_seedance_sources', AsyncMock())
    monkeypatch.setattr(public, '_launch_provider', actor.provider)
    monkeypatch.setattr(trend_api, '_record_trend_use', AsyncMock(side_effect=RuntimeError('metrics unavailable')))
    runner = seedance25._run_seedance25_trend if model == 'seedance_2_5' else trend_api._run_video_trend
    with pytest.raises(RuntimeError, match='metrics unavailable'):
        await runner(telegram_id=123, user=actor.user, trend=trend(model))
    task = await database.get_task_by_id('s2-creator-test')
    assert task and task.cost == expected
    assert (await database.get_or_create_user(123)).credits == actor.initial - expected
