"""Actual WAN lifecycle: actor-specific reserve, immutable settlement and retries."""
from copy import deepcopy
from pathlib import Path

import pytest

from bot.creator_tariff_membership import set_creator_tariff_membership
from bot.services.preset_manager import preset_manager
from bot.services.wan3_prime_lifecycle import (
    Wan3PrimeLifecycle,
    Wan3PrimeLifecycleError,
)
from tests.test_wan3_prime_lifecycle import (
    Downloader,
    Probe,
    Provider,
    balance,
    body,
    user_actor,
)


@pytest.fixture
def creator_prices(monkeypatch):
    from bot.config import config
    prices = deepcopy(preset_manager.get_price_config())
    prices['creator_tariff'] = {'enabled': True, 'video_models': {
        'seedance_2': {'quality_costs': {'720p': 1}},
        'seedance_2_5': {'quality_costs': {'480p': 2, '720p': 3}},
        'wan_3': {'quality_costs': {'720p': 2}},
        'wan_3_prime': {'quality_costs': {'720p': 3}},
    }}
    monkeypatch.setattr(preset_manager, '_price_config', prices)
    monkeypatch.setattr(config, 'is_admin', lambda uid: uid == 999999999)
    return prices


class OrdinaryRates:
    def get_video_quality_costs(self, model):
        return {'720p': 8 if model == 'wan_3' else 10, '1080p': 12}


@pytest.mark.asyncio
@pytest.mark.parametrize('model,rate', [('wan_3', 2), ('wan_3_prime', 3)])
@pytest.mark.parametrize('duration', [5, -1])
async def test_creator_wan_reserve_and_settlement_use_frozen_personal_rate(creator_prices, model, rate, duration):
    actor = await user_actor(500)
    await set_creator_tariff_membership(999999999, actor.telegram_id, True)
    provider = Provider()
    source = 'https://example.test/source.mp4'
    lifecycle = Wan3PrimeLifecycle(probe=Probe(url_durations={source: 7}, file_duration=4), preset_manager=OrdinaryRates(), transport=provider, downloader=Downloader(Path('static/uploads/wan3_prime/results/creator.mp4')))
    request = body(model=model, scenario='reference', reference_video_urls=[source], duration=duration)
    quote = await lifecycle.quote(actor, request)
    assert quote.rate_per_second == rate
    assert quote.reserve_credits == rate * (30 if duration == -1 else 12)
    result = await lifecycle.launch(actor, request, quote, 'creator-wan')
    assert await balance(actor.user_id) == 500 - quote.reserve_credits
    creator_prices['creator_tariff']['video_models'][model]['quality_costs']['720p'] = 99
    await set_creator_tariff_membership(999999999, actor.telegram_id, False)
    replay = await lifecycle.launch(actor, request, quote, 'creator-wan')
    assert replay['task_id'] == result['task_id'] and provider.creates == 1
    provider.statuses['provider_1'] = {'taskId': 'provider_1', 'model': provider.recipe.provider_model, 'state': 'success', 'resultJson': '{"resultUrls":["https://example.test/result.mp4"]}'}
    await lifecycle.reconcile_once(provider_task_id='provider_1')
    status = await lifecycle.status(actor, result['task_id'])
    expected = rate * (11 if duration == -1 else 12)
    assert status['charged_credits'] == expected
    assert await balance(actor.user_id) == 500 - expected


@pytest.mark.asyncio
async def test_creator_wan_revocation_before_launch_requires_new_quote(creator_prices):
    actor = await user_actor(500)
    await set_creator_tariff_membership(999999999, actor.telegram_id, True)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=OrdinaryRates(), transport=provider)
    request = body(model='wan_3')
    quote = await lifecycle.quote(actor, request)
    await set_creator_tariff_membership(999999999, actor.telegram_id, False)
    with pytest.raises(Wan3PrimeLifecycleError) as caught:
        await lifecycle.launch(actor, request, quote, 'revoked')
    assert caught.value.code == 'stale_quote'
    assert await balance(actor.user_id) == 500 and provider.creates == 0


@pytest.mark.asyncio
async def test_creator_wan_missing_quality_keeps_ordinary_price(creator_prices):
    actor = await user_actor(500)
    await set_creator_tariff_membership(999999999, actor.telegram_id, True)
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=OrdinaryRates(), transport=Provider())
    quote = await lifecycle.quote(actor, body(model='wan_3', resolution='1080P'))
    assert quote.rate_per_second == 12 and quote.reserve_credits == 60
